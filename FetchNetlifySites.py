#!/usr/bin/env python3
"""
Netlify Sites Fetcher

Queries the Netlify API for all sites in the unfoldingWord Netlify organization
and writes the results to sheets/netlify_sites.csv.

Requires NETLIFY_TOKEN in .env (a Netlify personal access token with read access).

Usage: python FetchNetlifySites.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

from lib.constants import ENV_FILE, NETLIFY_PREFIX_COLUMNS
from lib.utilities import load_env_file, urlopen_with_retry, write_list_to_csv

NETLIFY_API_BASE = "https://api.netlify.com/api/v1"
OUTPUT_CSV = "sheets/netlify_sites.csv"
NETLIFY_ACCOUNT_SLUG = "unfoldingWord"

CSV_FIELDS = [
    "name",
    "id",
    "url",
    "custom_domain",
    "account_name",
    "account_slug",
    "repo_url",
    "repo_branch",
    "framework",
    "build_command",
    "auto_deploy",
    "published_at",
    "created_at",
    "updated_at",
    "state",
]


def netlify_request(path, token):
    url = f"{NETLIFY_API_BASE}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "unfoldingword-repo-list-script",
        },
    )
    response = urlopen_with_retry(req)
    return json.loads(response.read())


def fetch_sites_page(path, token):
    try:
        return netlify_request(path, token)
    except urllib.error.HTTPError as e:
        print(f"HTTP error {e.code}: {e.reason}", file=sys.stderr)
        raise


def fetch_all_sites(token, account_slug=None):
    sites = []
    page = 1
    per_page = 100
    while True:
        if account_slug:
            path = f"/accounts/{account_slug}/sites?page={page}&per_page={per_page}"
        else:
            path = f"/sites?filter=all&page={page}&per_page={per_page}"
        print(f"  Fetching page {page}...")
        try:
            data = fetch_sites_page(path, token)
        except urllib.error.HTTPError as e:
            if e.code == 404 and account_slug:
                print(
                    f"Account slug '{account_slug}' not found — falling back to listing all accessible sites.",
                    file=sys.stderr,
                )
                return fetch_all_sites(token, account_slug=None)
            sys.exit(1)
        if not data:
            break
        sites.extend(data)
        if len(data) < per_page:
            break
        page += 1
    return sites


def site_to_row(site):
    build = site.get("build_settings") or {}
    deploy = site.get("published_deploy") or {}
    return {
        "name": site.get("name", ""),
        "id": site.get("id", ""),
        "url": site.get("ssl_url") or site.get("url", ""),
        "custom_domain": site.get("custom_domain") or "",
        "account_name": site.get("account_name", ""),
        "account_slug": site.get("account_slug", ""),
        "repo_url": build.get("repo_url") or "",
        "repo_branch": build.get("repo_branch") or "",
        "framework": build.get("framework") or "",
        "build_command": build.get("cmd") or "",
        "auto_deploy": "" if not build.get("repo_url") else ("no" if build.get("stop_builds") else "yes"),
        "published_at": deploy.get("published_at") or "",
        "created_at": site.get("created_at", ""),
        "updated_at": site.get("updated_at", ""),
        "state": site.get("state", ""),
    }


def main():
    load_env_file(ENV_FILE)
    token = os.environ.get("NETLIFY_TOKEN")
    if not token:
        print("Error: NETLIFY_TOKEN not set in .env", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching Netlify sites for account '{NETLIFY_ACCOUNT_SLUG}'...")
    sites = fetch_all_sites(token, account_slug=NETLIFY_ACCOUNT_SLUG)
    print(f"Found {len(sites)} site(s).")

    rows = [site_to_row(s) for s in sites]
    rows.sort(key=lambda r: r["name"].lower())

    prefix_columns = NETLIFY_PREFIX_COLUMNS
    # prefix rows with prefix_columns
    for row in rows:
        for col in prefix_columns:
            row[col] = ""

    all_fields = prefix_columns + CSV_FIELDS

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    write_list_to_csv(OUTPUT_CSV, all_fields, rows)

if __name__ == "__main__":
    main()