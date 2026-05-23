#!/usr/bin/env python3
"""
GTest Repository Validator
--------------------------
Reads a CSV of repositories (columns: nameWithOwner, sshUrl), clones each one,
builds it, runs its Google Test cases, and writes a new CSV containing only the
repos that successfully built AND ran tests.

Per-repo build/test logs are written under ./logs/ for manual inspection.

Usage:
    python gtest_repo_validator.py input.csv \
        --output successful.csv \
        --workdir ./repos \
        --logdir ./logs \
        --timeout 900 \
        --jobs 4
"""

import csv
import logging
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

INPUT_DIR = Path("./filtered4")
OUTPUT_DIR_5 = Path("./filtered5")
REPOS_DIR = Path("./repos")
LOG_CLONE_DIR = Path("./logs/clone")
LOG_CONF_DIR = Path("./logs/configure")
LOG_BUILD_DIR = Path("./logs/build")
LOG_TEST_DIR = Path("./logs/test")

start_idx = 50
end_idx = 60

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("build-validator")

def run_cmd(cmd: List[str], cwd: Path, log_file, timeout: int, 
            env: Optional[dict] = None) -> Tuple[int, str]:
    header = f"\n$ {' '.join(cmd)}  (cwd={cwd})\n"
    log_file.write(header)
    log_file.flush()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env=env,
            text=True,
            errors="replace",
        )
        log_file.write(proc.stdout or "")
        log_file.flush()
        tail = (proc.stdout or "")[-2000:]
        return proc.returncode, tail
    except subprocess.TimeoutExpired as e:
        msg = f"\n[TIMEOUT after {timeout}s]\n"
        log_file.write(msg)
        if e.stdout:
            log_file.write(e.stdout if isinstance(e.stdout, str) else e.stdout.decode(errors="replace"))
        log_file.flush()
        return 124, msg
    except FileNotFoundError as e:
        msg = f"\n[COMMAND NOT FOUND] {e}\n"
        log_file.write(msg)
        log_file.flush()
        return 127, msg

def build_and_test_cmake(repo_dir: Path, log_conf_file, log_build_file, log_test_file) -> Tuple[bool, bool, bool, str]:
    log.info("================= build_and_test_cmake")
    if not repo_dir.exists():
        return False, False, False, f"repo_dir does not exist: {repo_dir}"
    build_dir = repo_dir / "build"
    build_dir.mkdir(exist_ok=True)

    # Configure
    rc, tail = run_cmd(
        ["cmake", "-S", ".", "-B", "build",
         "-DCMAKE_BUILD_TYPE=Release",
         "-DBUILD_TESTING=ON",
         "-DBUILD_TESTS=ON"],
        cwd=repo_dir, log_file=log_conf_file, timeout=600,
    )
    log.info(tail)
    if rc != 0:
        error = f"cmake configure failed (rc={rc}): {tail.strip()[-300:]}"
        return False, False, False, error

    log.info("============== cinfigure finished")

    # Build
    rc, tail = run_cmd(
        ["cmake", "--build", "build", "-j"],
        cwd=repo_dir, log_file=log_build_file, timeout=1800,
    )
    if rc != 0:
        error = f"cmake build failed (rc={rc}): {tail.strip()[-300:]}"
        return True, False, False, error

    log.info("============== build finished")

    # Test via ctest
    rc, tail = run_cmd(
        ["ctest", "--test-dir", "build", "--output-on-failure", "--no-tests=error"],
        cwd=repo_dir, log_file=log_test_file, timeout=1200,
    )
    if rc != 0:
        error = f"ctest failed (rc={rc}): {tail.strip()[-300:]}"
        return True, True, False, error
    log.info("============== test finished")
    return True, True, True, ""

def clone_repo(ssh_url: str, log_file) -> bool:
    rc, tail = run_cmd(
            ["git", "clone", "--depth", "1", "--recurse-submodules",
             "--shallow-submodules", ssh_url],
            cwd=REPOS_DIR, log_file=log_file, timeout=180,
        )
    log.info("================= clone_repo finish")
    if rc != 0:
        log.error(f"git clone {ssh_url} failed (rc={rc}): {tail.strip()[-300:]}")
        return False
    return True

def process_repos(repos: list, file_name: str) -> list:
    for d in (REPOS_DIR, LOG_CLONE_DIR, LOG_CONF_DIR, LOG_BUILD_DIR, LOG_TEST_DIR):
        d.mkdir(parents=True, exist_ok=True)

    for i, repo in enumerate(repos[start_idx: end_idx], start_idx + 1):
        name = repo.get("name", "")
        log.info("[%d/%d] %s start...", i, len(repos), name)
        ssh_url = repo.get("sshUrl", "")
        if not ssh_url:
            log.warning("[%d/%d] %s has no sshUrl, skipping.", i, len(repos), name)
            continue
        
        # repo_dir is git clone created directory
        repo_dir = REPOS_DIR / name
        if repo_dir.exists():
            shutil.rmtree(repo_dir, ignore_errors=True)

        with (
            open(LOG_CLONE_DIR / f"{name}.log", "w", encoding="utf-8") as log_clone,
            open(LOG_CONF_DIR  / f"{name}.log", "w", encoding="utf-8") as log_conf,
            open(LOG_BUILD_DIR / f"{name}.log", "w", encoding="utf-8") as log_build,
            open(LOG_TEST_DIR  / f"{name}.log", "w", encoding="utf-8") as log_test,
        ):
            ok = clone_repo(ssh_url, log_clone)
            if not ok:
                repo["configure"] = False
                repo["build"] = False
                repo["test"] = False
                repo["error"] = "clone failed"
                save_repo(repo, OUTPUT_DIR_5, file_name)
                continue

            conf, build, test, error = build_and_test_cmake(
                repo_dir, log_conf, log_build, log_test
            )

        log.info(
            "%s — configure: %s, build: %s, test: %s | error: %s",
            name, conf, build, test, error or "none",
        )
        repo["configure"] = conf
        repo["build"] = build
        repo["test"] = test
        repo["error"] = error
        output_file_name = f"repos_{start_idx}_{end_idx}.csv"
        save_repo(repo, OUTPUT_DIR_5, output_file_name)

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

def main():
    file_name = "repos.csv"
    repos = load_all_repos(file_name)
    process_repos(repos, file_name)


if __name__ == "__main__":
    main()
