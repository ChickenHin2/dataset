"""
scan_gtest.py
-------------
Walk a directory of cloned repositories, find C++ test files,
count GoogleTest macros per file, and write results to a CSV.

Usage:
    python scan_gtest.py --repos-dir /path/to/repos --output results.csv

    # Optionally limit to specific repos:
    python scan_gtest.py --repos-dir /path/to/repos --output results.csv \
        --repos repo_a repo_b
"""

import logging
import csv
import re
import sys
from pathlib import Path
from typing import Tuple

REPOS_DIR = Path("./repos")
OUTPUT_DIR = Path("./count")

SKIP_DIRS = {
    ".git", "build", "build_gtest", "cmake-build-debug", "cmake-build-release",
    "third_party", "external", "vendor", "deps", "third-party"
}

CPP_FILE_EXTENSIONS = {".cc", ".cpp", ".cxx", ".h", ".hpp", ".hxx", ".c++"}

GTEST_TEST_RE = re.compile(
    r"^\s*"
    r"(?P<macro>"
    r"TYPED_TEST_P|TYPED_TEST"
    r"|TEST_P|TEST_F|TEST"
    r")"
    r"\s*\(",
    re.MULTILINE,
)

# Detects file that define the TEST macro themselves (likely not GoogleTest)
CUSTOM_TEST_MACRO_RE = re.compile(r"#\s*define\s+TEST\s*\(", re.MULTILINE)

# Detects file that include gtest, if not, likely not GoogleTest
GTEST_INCLUDE_RE = re.compile(r'#\s*include\s*<gtest/gtest\.h>', re.MULTILINE)

GTEST_INCLUDE_RE = re.compile(
    r'^\s*#\s*include\s*'
    r'(?:'
    r'[<"](?:[^<>"]*/)?(?:googletest/)?gtest/gtest\.h[>"]'  # with or without googletest/ prefix, any depth
    r'|[<"]gtest\.h[>"]' # flat: <gtest.h> or "gtest.h"
    r')',
    re.MULTILINE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tests-counter")

def count_tests_in_file(path: Path) -> Tuple[int, bool, bool]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"  [warn] Cannot read {path}: {exc}", file=sys.stderr)
        return 0, False, False
    
    has_custom_macro = bool(CUSTOM_TEST_MACRO_RE.search(text))
    has_gtest_include = bool(GTEST_INCLUDE_RE.search(text))
    text = remove_comments(text)
    count = len(GTEST_TEST_RE.findall(text))

    return count, has_custom_macro, has_gtest_include

def remove_comments(text: str) -> str:
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return text

def should_skip(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)

def scan_repository(repo_dir: Path) -> dict:
    total_tests = 0
    test_files = []
    test_files_has_custom_macro = []
    test_files_without_gtest_include = []
    for file_path in sorted(repo_dir.rglob("*")):
        if not file_path.is_file():
            continue
        if should_skip(file_path):
            continue
        if file_path.suffix.lower() not in CPP_FILE_EXTENSIONS:
            continue

        count, has_custom_macro, has_gtest_include = count_tests_in_file(file_path)
        if count > 0:
            total_tests += count
            test_files.append(file_path.relative_to(repo_dir).as_posix())
            if not has_gtest_include:
                test_files_without_gtest_include.append(file_path.relative_to(repo_dir).as_posix())
        if has_custom_macro:
            test_files_has_custom_macro.append(file_path.relative_to(repo_dir).as_posix())

    if total_tests == 0:
        log.warning("No tests found in %s.", repo_dir.name)
        return {
            "repo": repo_dir.name, 
            "test_files": "", 
            "total_tests": 0, 
            "test_files_custom_test": "", 
            "test_files_without_gtest_include": ""}

    return {
        "repo": repo_dir.name,
        "test_files": ";".join(test_files),
        "total_tests": total_tests,
        "test_files_custom_test": ";".join(test_files_has_custom_macro),
        "test_files_without_gtest_include": ";".join(test_files_without_gtest_include)
    }

def save_csv(repo: dict, output_dir: Path, name: str, fieldnames: list) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / name
    file_exists = csv_path.exists()

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerow(repo)

def main() -> None:
    repos = sorted(REPOS_DIR.iterdir())
    for repo_path in repos:
        save_csv({"repo": repo_path.name}, OUTPUT_DIR, "repos_scanned.csv", ["repo"])

    for i, repo_path in enumerate(repos, 1):
        if not repo_path.is_dir():
            log.warning("Skipping non-directory repo: %s", repo_path.name)
            continue
        log.info("Start to scan repo [%d/%d] - %s.", i, len(repos), repo_path.name)
        result = scan_repository(repo_path)
        log.info(
            "Scan repo %s finished - total tests: %d",
            repo_path.name, result["total_tests"],
        )
        save_csv(result, OUTPUT_DIR, "repos_total_tests.csv", ["repo", "total_tests", "test_files_custom_test", "test_files_without_gtest_include", "test_files"])

if __name__ == "__main__":
    main()