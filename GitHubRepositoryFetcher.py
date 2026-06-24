#!/usr/bin/env python3
"""
GitHub Repository Fetcher

This script fetches repository data from specified GitHub organizations and generates
an OpenDocument Spreadsheet (ODS) file containing detailed information about each repository.

To run do `python GitHubRepositoryFetcher.py`.  This needs to be run before `python CatagorizeRepos.py`

For JavaScript/TypeScript repositories, it also collects npm package metadata including:
- Package names and publication dates
- Download statistics
- Dependency relationships between packages
- Monorepo workspace information

The script produces an ODS file with two sheets:
1. Repositories - All repositories from the specified organizations
2. JavaScript TypeScript - Filtered view of JS/TS repositories only

Output file: sheets/unfoldingword_repos.ods
"""

import os
import sys
import urllib.error
from datetime import datetime

from lib.utilities import load_env_file
from lib.github_utils import github_request, fetch_repositories, write_ods
from lib.npm_utils import update_npmjs_dependencies

ORG_NAMES = [  # highest priority first
    "unfoldingWord",
    "unfoldingWord-dev",
    "unfoldingWord-box3",
]
OUTPUT_FILE = "sheets/unfoldingword_repos.ods"
ENV_FILE = ".env"


def main():
    start_time = datetime.now()

    load_env_file(ENV_FILE)

    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        print(f"Error: GITHUB_TOKEN not found in {ENV_FILE}", file=sys.stderr)
        print("Please ensure your .env file contains a valid GITHUB_TOKEN", file=sys.stderr)
        sys.exit(1)

    try:
        github_request("https://api.github.com/user")
        print("GitHub token verified.")
    except urllib.error.HTTPError as error:
        if error.code == 401:
            print("Error: GITHUB_TOKEN is invalid or expired.", file=sys.stderr)
        else:
            print(f"Error: Could not verify GITHUB_TOKEN: {error.code} {error.reason}", file=sys.stderr)
        sys.exit(1)

    repos = fetch_repositories(ORG_NAMES)
    update_npmjs_dependencies(repos, ORG_NAMES)
    write_ods(repos, OUTPUT_FILE)

    print()
    print(f"Created ODS: {OUTPUT_FILE}")
    print(f"Repositories written: {len(repos)}")

    elapsed_time = datetime.now() - start_time
    hours, remainder = divmod(int(elapsed_time.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    print(f"Elapsed time: {hours}:{minutes:02d}:{seconds:02d}")


if __name__ == "__main__":
    main()