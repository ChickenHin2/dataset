"""
GitHub GraphQL Repository Search
1. C++ repos
2. No archived, fork, mirror repos
3. created before 2026-01 (not included), and updated after 2026-03 (included)
"""

import csv
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GRAPHQL_URL = "https://api.github.com/graphql"

PAGE_SIZE = 100    # max allowed by GitHub (items per page)
MAX_PAGES_PER_SLICE = 10     # max allowed 1000 results (10 × 100 = 1000 results)

START_DATE = os.environ["START_DATE"]
END_DATE = os.environ["END_DATE"]
OUTPUT_DIR = Path("./filtered1")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# GraphQL query
QUERY = """
query SearchRepos($q: String!, $first: Int!, $after: String) {
  search(query: $q, type: REPOSITORY, first: $first, after: $after) {
    repositoryCount
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      ... on Repository {
        id
        createdAt
        updatedAt
        pushedAt
        diskUsage
        isInOrganization
        name
        nameWithOwner
        sshUrl
        stargazerCount
      }
    }
  }
}
"""

def headers_graphQL() -> dict:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }

def build_graphQL_query(start: datetime, end: datetime, stars: str = "") -> str:
    s = start.strftime("%Y-%m-%d")
    e = end.strftime("%Y-%m-%d")
    q = (
        f"language:C++ "
        f"fork:false "
        f"archived:false "
        f"mirror:false "
        f"pushed:>=2026-03-01 "
        f"created:{s}..{e}"
    )
    if stars:
        q += f" stars:{stars}"
    return q


def run_graphQL_query(variables: dict, retries: int = 5) -> dict:
    for attempt in range(retries):
        resp = requests.post(
            GRAPHQL_URL,
            headers=headers_graphQL(),
            json={"query": QUERY, "variables": variables},
            timeout=30,
        )

        if resp.status_code == 200:
            data = resp.json()
            if "errors" in data:
                raise RuntimeError(f"GraphQL errors: {data['errors']}")
            return data

        if resp.status_code in (403, 429):
            reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
            wait  = max(reset - int(time.time()), 5)
            log.warning("Rate-limited. Sleeping %d s …", wait)
            time.sleep(wait)
            continue

        if resp.status_code >= 500:
            wait = 2 ** attempt
            log.warning("Server error %d. Retrying in %d s …", resp.status_code, wait)
            time.sleep(wait)
            continue

        resp.raise_for_status()

    raise RuntimeError(f"Failed after {retries} attempts.")

# Fetch all pages for a single (start, end) query
def fetch_all_pages(q: str, label: str = "") -> tuple:
    repos = []
    cursor = None

    while True:
        data = run_graphQL_query({"q": q, "first": PAGE_SIZE, "after": cursor})
        search = data["data"]["search"]
        total = search["repositoryCount"]
        if total > 1000:
            return repos, total
        page_info = search["pageInfo"]

        repos.extend(search["nodes"])
        log.info("[%s] page fetched: %d collected / %d total", label, len(repos), total)

        if not page_info["hasNextPage"]:
            return repos, total

        cursor = page_info["endCursor"]
        time.sleep(0.1)

# Fetch one window; split into two halves if >= 1000 results
def fetch_all_repos(start: datetime, end: datetime) -> list:
    log.info("Window %s -> %s", start.strftime("%Y-%m-%dT%H:%M:%S"), end.strftime("%Y-%m-%dT%H:%M:%S"))

    q = build_graphQL_query(start, end)
    repos, total = fetch_all_pages(q, label=f"{start.date()}->{end.date()}")

    if total < 1000:
        return repos

    # Split into two halves and query each separately
    log.warning("Window %s->%s has %d results (>=1000) — splitting into two halves.", start.date(), end.date(), total,)

    mid = start + (end - start) / 2
    left_repos = fetch_all_repos(start, mid)
    right_repos = fetch_all_repos(mid + timedelta(seconds=1), end)

    # Deduplicate by id in case of overlap at the boundary
    seen = set()
    merged = []
    for repo in right_repos + left_repos:
        rid = repo.get("id")
        if rid not in seen:
            seen.add(rid)
            merged.append(repo)

    return merged


def save_repos(repos: list, start: datetime, end: datetime, outdir: Path) -> None:
    if not repos:
        log.info("No repos for %s -> %s, skipping.", start.date(), end.date())
        return

    repos = sorted(repos, key=lambda r: r.get("createdAt", ""), reverse=True)

    prefix = f"repos_{start.strftime('%Y-%m-%d')}_{end.strftime('%Y-%m-%d')}"

    # json_path = outdir / f"{prefix}.json"
    # with open(json_path, "w", encoding="utf-8") as f:
    #     json.dump(repos, f, ensure_ascii=False, indent=2)

    csv_path = outdir / f"{prefix}.csv"

    if repos:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(repos[0].keys()), extrasaction="ignore")
            writer.writeheader()
            writer.writerows(repos)
    else:
        open(csv_path, "w").close()

    log.info("Saved %d repos -> %s", len(repos), csv_path.name)


def main():

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    end_dt = datetime.strptime(END_DATE,   "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
    start_dt = datetime.strptime(START_DATE, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    repos = fetch_all_repos(start_dt, end_dt)
    save_repos(repos, start_dt, end_dt, OUTPUT_DIR)

    log.info("Done. Total repos fetched: %d", len(repos))



if __name__ == "__main__":
    main()