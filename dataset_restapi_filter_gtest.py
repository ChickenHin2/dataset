"""
GitHub RestAPI Code Search For Each Repository
1. contributors >= 2
2. use CMake (contain CmakeLists.txt)
3. contain Google Test test suites (contain gtest/gtest.h)
"""
import csv
import logging
import os
import time
from pathlib import Path

import requests

# Each token is limited 10 requests in a minute, use more tokens to avoid rate limit
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_TOKEN_1 = os.environ.get("GITHUB_TOKEN_1")
GITHUB_TOKEN_2 = os.environ.get("GITHUB_TOKEN_2")
GITHUB_TOKEN_3 = os.environ.get("GITHUB_TOKEN_3")
GITHUB_TOKEN_4 = os.environ.get("GITHUB_TOKEN_4")
GITHUB_TOKEN_5 = os.environ.get("GITHUB_TOKEN_5")
GITHUB_TOKEN_6 = os.environ.get("GITHUB_TOKEN_6")

GITHUB_TOKENS = [
    GITHUB_TOKEN,
    GITHUB_TOKEN_1,
    GITHUB_TOKEN_2,
    GITHUB_TOKEN_3,
    GITHUB_TOKEN_4,
    GITHUB_TOKEN_5,
    GITHUB_TOKEN_6
]

token_index = 0
token_request_count = 0
REQUESTS_PER_TOKEN = 9

REST_BASE = "https://api.github.com"

INPUT_DIR = Path("./filtered3")

OUTPUT_DIR_2 = Path("./filtered2")
OUTPUT_DIR_3 = Path("./filtered3")
OUTPUT_DIR_4 = Path("./filtered4")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

def current_token() -> str:
    return GITHUB_TOKENS[token_index]

# Change token after 9 requests
def rotate_token() -> None:
    global token_index, token_request_count
    token_index = (token_index + 1) % len(GITHUB_TOKENS)
    token_request_count = 0
    log.info("Rotated to token index %d", token_index)

def headers_restAPI():
    return {
        "Authorization": f"Bearer {current_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def run_restAPI_query(url: str, params: dict = None, retries: int = 5) -> requests.Response:
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers_restAPI(), params=params, timeout=20)
        except requests.RequestException as exc:
            wait = 2 ** attempt
            log.warning("Network error: %s — retrying in %d s", exc, wait)
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            wait = 2 ** attempt
            log.warning("Server error %d on %s — retrying in %d s", resp.status_code, url, wait)
            time.sleep(wait)
            continue

        return resp

    raise RuntimeError(f"REST GET failed after {retries} attempts: {url}")

def run_restAPI_query_retry_403(url: str, params: dict = None, retries: int = 5) -> requests.Response:
    global token_request_count

    if token_request_count >= REQUESTS_PER_TOKEN:
        rotate_token()

    token_request_count += 1

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers_restAPI(), params=params, timeout=20)
        except requests.RequestException as exc:
            wait = 2 ** attempt
            log.warning("Network error: %s — retrying in %d s", exc, wait)
            time.sleep(wait)
            continue

        if resp.status_code in (403, 429):
            # Deal with rate limit by sleeping according to Retry-After or X-RateLimit-Reset
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                wait = int(retry_after) + 1
            else:
                reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                wait  = max(reset - int(time.time()), 5)
            log.warning("Rate-limited. Sleeping %d s …", wait)
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            wait = 2 ** attempt
            log.warning("Server error %d on %s — retrying in %d s", resp.status_code, url, wait)
            time.sleep(wait)
            continue

        return resp

    raise RuntimeError(f"REST GET failed after {retries} attempts: {url}")

#  Returns True if the repo has more than one GitHub-account-linked contributor. (robot contributor is excluded)
def has_multiple_contributors(nameWithOwner: str) -> bool:
    url = f"{REST_BASE}/repos/{nameWithOwner}/contributors"
    resp = run_restAPI_query(url, params={"per_page": 10, "page": 1})

    if resp.status_code == 204:        # empty repo
        log.debug("Empty repo: %s", nameWithOwner)
        return False
    resp = run_restAPI_query(url, params={"per_page": 10, "page": 1})
    if resp.status_code == 404:
        log.debug("Repo not found: %s", nameWithOwner)
        return False
    if resp.status_code != 200:
        log.warning("Unexpected status %d for contributors of %s", resp.status_code, nameWithOwner)
        return False

    contributors = resp.json()
    if not contributors:
        return False
    
    human_count = sum(
            1 for c in contributors
            if c.get("type") != "Bot" and "[bot]" not in c.get("login", "").lower()
        )
    return human_count >= 2

def filter_by_contributor(repos: list, file_name: str) -> list:
    log.info("=== Step 1: Multi-contributor filter (%d repos) ===", len(repos))
    kept = []
    for i, repo in enumerate(repos[1475:], 1476):
        nameWithOwner  = repo.get("nameWithOwner", "")
        ok = has_multiple_contributors(nameWithOwner)
        log.info("[%d/%d] %s — contributors>1: %s", i, len(repos), nameWithOwner, ok)
        if ok:
            kept.append(repo)
            save_repo(repo, OUTPUT_DIR_2, file_name)

    log.info("Step 1 done: %d / %d repos kept.", len(kept), len(repos))
    return kept

# Returns True if the repo contains a CMakeLists.txt file anywhere.
def has_cmake(nameWithOwner: str) -> bool:
    url = f"{REST_BASE}/search/code"
    resp = run_restAPI_query(url, params={"q": f"filename:CMakeLists.txt repo:{nameWithOwner}"})

    if resp.status_code == 422:        # repo too large
        log.debug("Code search 422 (unprocessable) for cmake in %s", nameWithOwner)
        return False
    if resp.status_code == 403:        # if hit rate limit in search code, fall back to content API
        log.debug("Incompelete indexing repo: %s, try another url", nameWithOwner)
        url_  = f"{REST_BASE}/repos/{nameWithOwner}/contents/CMakeLists.txt"
        resp_ = run_restAPI_query(url_)
        if resp_.status_code == 404:
            return False
        if resp_.status_code == 200:
            return True
        if resp_.status_code != 200:
            log.warning("Unexpected status %d for cmake check of %s", resp_.status_code, nameWithOwner)
            return False

    if resp.status_code != 200:
        log.warning("Unexpected status %d for cmake check of %s", resp.status_code, nameWithOwner)
        return False

    return resp.json().get("total_count", 0) > 0

def filter_by_cmake(repos: list, file_name: str) -> list:
    log.info("=== Step 2: CMake filter (%d repos) ===", len(repos))
    kept = []
    for i, repo in enumerate(repos, 1):
        nameWithOwner  = repo.get("nameWithOwner", "")
        ok = has_cmake(nameWithOwner)
        log.info("[%d/%d] %s — CMakeLists.txt: %s", i, len(repos), nameWithOwner, ok)
        if ok:
            kept.append(repo)
            save_repo(repo, OUTPUT_DIR_3, file_name)

    log.info("Step 2 done: %d / %d repos kept.", len(kept), len(repos))
    return kept

# Returns True if the repo references gtest
def has_gtest(nameWithOwner: str) -> bool:
    url = f"{REST_BASE}/search/code"

    query = f"<gtest/gtest.h> repo:{nameWithOwner}",

    resp = run_restAPI_query_retry_403(url, params={"q": query})

    if resp.status_code == 422:
        log.debug("Code search 422 (unprocessable) for cmake in %s", nameWithOwner)
        return False
    
    if resp.status_code != 200:
        log.warning("Unexpected status %d for cmake check of %s", resp.status_code, nameWithOwner)
        return False

    if resp.json().get("total_count", 0) > 0:
        return True
    
    return False

def filter_by_gtest(repos: list, file_name: str) -> list:
    log.info("=== Step 3: GTest filter (%d repos) ===", len(repos))
    kept = []
    for i, repo in enumerate(repos, 1):
        nameWithOwner  = repo.get("nameWithOwner", "")
        ok = has_gtest(nameWithOwner)
        log.info("[%d/%d] %s — gtest.h: %s", i, len(repos), nameWithOwner, ok)
        if ok:
            kept.append(repo)
            save_repo(repo, OUTPUT_DIR_4, file_name)

    log.info("Step 3 done: %d / %d repos kept.", len(kept), len(repos))
    return kept

# Load repos from last step (graphql filter results)
def load_all_repos(file_name: str) -> list:
    csv_path = INPUT_DIR / file_name
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
 
    all_repos = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_repos.append(dict(row))
 
    log.info("Loaded %d repos from %s.", len(all_repos), csv_path)
    return all_repos

def save_repo(repo: dict, dir: Path, name: str) -> None:
    dir.mkdir(parents=True, exist_ok=True)

    csv_path = dir / f"{name}"
    file_exists = csv_path.exists()

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(repo.keys()), extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(repo)

# def save_repos(repos: list, dir: Path, name: str) -> None:
#     dir.mkdir(parents=True, exist_ok=True)
 
#     # Sort by createdAt descending (same convention as search output)
#     repos = sorted(repos, key=lambda r: r.get("createdAt", ""), reverse=True)

#     csv_path = dir / f"{name}"
#     if repos:
#         with open(csv_path, "w", newline="", encoding="utf-8") as f:
#             writer = csv.DictWriter(f, fieldnames=list(repos[0].keys()), extrasaction="ignore")
#             writer.writeheader()
#             writer.writerows(repos)
#     else:
#         open(csv_path, "w").close()
    
#     log.info("Saved %d repos -> %s", len(repos), csv_path.name)

def main():
    file_name = "repos_2014_and_before.csv"
    repos = load_all_repos(file_name)
 
    # repos = filter_by_contributor(repos, file_name)
    # repos = filter_by_cmake(repos, file_name)
    repos = filter_by_gtest(repos, file_name)
 
 
if __name__ == "__main__":
    main()