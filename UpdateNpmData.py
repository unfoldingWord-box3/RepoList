#!/usr/bin/env python3
"""
npm Module Data Updater

Re-fetches npm registry data (downloads, publish date, deprecation status) for every
npm package recorded in unfoldingword_repos.ods, then rewrites both sheets in place.

Run after GitHubRepositoryFetcher.py to refresh npm data without re-fetching all
GitHub repository metadata.

Usage: python UpdateNpmData.py
"""

import sys

from lib.utilities import (
    load_env_file,
    load_repository_data,
    fetch_npmjs_package_metadata,
    fetch_npmjs_last_published,
    fetch_npmjs_download_count,
    fetch_npmjs_is_deprecated,
    npm_repo_is_from_uw,
    is_empty,
    update_ods_sheet_data,
)

ODS_FILE = "unfoldingword_repos.ods"
ENV_FILE = ".env"
SHEET_NAME = "Repositories"
JS_TS_SHEET_NAME = "JavaScript TypeScript"
ORG_NAMES = [  # highest priority first
    "unfoldingWord",
    "unfoldingWord-dev",
    "unfoldingWord-box3",
]


def recompute_used_by(data_rows):
    """
    Recompute 'npmjs used by' by inverting the 'npmjs uses' graph.

    If row A lists package X in its 'npmjs uses', then X's 'npmjs used by'
    should include A's package name. This avoids re-reading package.json files
    since the dependency graph is already encoded in the ODS.
    """
    rows_by_package = {}
    for row in data_rows:
        pkg = row.get("npmjs package name")
        if not is_empty(pkg):
            if isinstance(pkg, list):
                pkg = pkg[0]
            rows_by_package[str(pkg).strip()] = row

    for row in data_rows:
        row["npmjs used by"] = []

    for row in data_rows:
        npmjs_uses = row.get("npmjs uses")
        current_pkg = row.get("npmjs package name")
        if is_empty(current_pkg) or is_empty(npmjs_uses):
            continue

        if isinstance(current_pkg, list):
            current_pkg = current_pkg[0]
        current_pkg = str(current_pkg).strip()

        if isinstance(npmjs_uses, list):
            used_list = npmjs_uses
        else:
            used_list = [p.strip() for p in str(npmjs_uses).split(",") if p.strip()]

        for dep in used_list:
            if dep in rows_by_package:
                dep_row = rows_by_package[dep]
                if current_pkg not in dep_row["npmjs used by"]:
                    dep_row["npmjs used by"].append(current_pkg)


def flatten_lists(data_rows):
    """Convert any list-valued cells back to comma-separated strings for ODS output."""
    for row in data_rows:
        for key, val in row.items():
            if isinstance(val, list):
                row[key] = ", ".join(str(v) for v in val)


def main():
    load_env_file(ENV_FILE)

    print(f"Loading {ODS_FILE}...")
    headers, data_rows = load_repository_data(ODS_FILE, SHEET_NAME)
    print(f"Loaded {len(data_rows)} repositories.")

    total = len(data_rows)
    updated = 0
    skipped = 0

    for i, row in enumerate(data_rows):
        pkg_name = row.get("npmjs package name")
        if is_empty(pkg_name):
            continue

        if isinstance(pkg_name, list):
            pkg_name = pkg_name[0]
        pkg_name = str(pkg_name).strip()

        print(f"[{i + 1}/{total}] {pkg_name}")

        metadata = fetch_npmjs_package_metadata(pkg_name)
        if not metadata:
            print(f"  Skipping — no metadata found")
            skipped += 1
            continue

        if not npm_repo_is_from_uw(metadata, ORG_NAMES):
            print(f"  Skipping — not from a uW org")
            skipped += 1
            continue

        row["npm is deprecated"] = fetch_npmjs_is_deprecated(metadata)
        row["npmjs downloads last year"] = fetch_npmjs_download_count(pkg_name, "last-year")
        row["npmjs last published"] = fetch_npmjs_last_published(metadata)
        updated += 1

    print(f"\nUpdated {updated} packages, skipped {skipped}.")

    print("Recomputing npm dependency relationships...")
    recompute_used_by(data_rows)

    flatten_lists(data_rows)

    ordered_rows = [{col: row.get(col, "") for col in headers} for row in data_rows]

    print(f"Writing {SHEET_NAME} sheet to {ODS_FILE}...")
    update_ods_sheet_data(ODS_FILE, SHEET_NAME, ordered_rows)

    js_ts_rows = [
        row for row in ordered_rows
        if str(row.get("language", "")).lower() in ("javascript", "typescript")
    ]
    print(f"Writing {JS_TS_SHEET_NAME} sheet ({len(js_ts_rows)} repos)...")
    update_ods_sheet_data(ODS_FILE, JS_TS_SHEET_NAME, js_ts_rows)

    print("Done.")


if __name__ == "__main__":
    main()