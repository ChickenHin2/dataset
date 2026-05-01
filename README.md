# 📦 Dataset Preparation for Repository using Google Test

## 📊 Dataset Characteristics

The final dataset consists of GitHub repositories that satisfy all of the following:

- Written in **C++**
- **Actively maintained** (updated after 2026-03 inclusive)
- **Sufficient development time for test suites** (created before 2026-01 exclusive)
- **Not archived, forked, or mirrored**
- **Not personal project** (at least 2 contributors)
- Use **CMake** as the build system (`CMakeLists.txt`)
- Include **Google Test** test suites (`#include <gtest/gtest.h>`)

---

## 🧱 Construction

The dataset is constructed in two stages:

1. **Repository-level filtering** using GitHub GraphQL API
2. **Repository filtering (metadata and content inspection)** using GitHub REST API

---

## 🚀 Stage 1: Repository Filtering (GraphQL)

**Script:** `dataset_graphql_filter.py`

This stage retrieves candidate repositories using GitHub GraphQL search.

### 🎯 Filtering Criteria

- **Language:** C++
- **Repository Type:**
  - Not a fork (`fork:false`)
  - Not archived (`archived:false`)
  - Not a mirror (`mirror:false`)
- **Time Constraints:**
  - Created before **2026-01** (exclusive)
  - Updated (pushed) after **2026-03** (inclusive)

### 🔍 Method

Due to GitHub’s **1,000 result limit per search query**, the script:

- Splits the search space using time windows (`created:`)
- Iteratively crawls repositories using pagination
- Applies adaptive window splitting when result count >= 1,000

### 📦 Output

- `*.csv` → name, owner, owner type, created time, updated time, disk usage, star count, clone url

---

## 🔎 Stage 2: Repository Metadata & Content Filtering (REST API)

**Script:** `dataset_restapi_filter.py`

This stage refines candidate repositories using GitHub REST API.

### 🎯 Filtering Criteria

- **Contributors:** ≥ 2
- **Build System:** contains `CMakeLists.txt`
- **Testing Framework:** contains `gtest/gtest.h`

### 🔍 Method

For each repository:

- Retrieve contributor list → count contributors
- Search repository contents for:
  - `CMakeLists.txt`
  - `gtest/gtest.h`

### 📦 Output

- `*.csv` → name, owner, owner type, created time, updated time, disk usage, star count, clone url
