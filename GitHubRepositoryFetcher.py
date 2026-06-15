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

Output file: unfoldingword_repos.ods
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from xml.sax.saxutils import escape

from lib.utilities import load_env_file, github_request, fetch_repository_dependents, \
    fetch_repository_contributors, \
    fetch_package_json, fetch_npmjs_package_metadata, npm_repo_is_from_uw, fetch_npmjs_last_published, \
    fetch_npmjs_download_count, fetch_nx_json, fetch_package_json_files, get_next_page_url, fetch_repository_json_file, \
    fetch_repository_last_commit_date, fetch_repository_last_release_date, fetch_repository_open_prs_count, \
    fetch_npmjs_is_deprecated, fetch_repository_github_downloads

ORG_NAMES = [
    "unfoldingWord-box3",
    "unfoldingWord",
    "unfoldingWord-dev",
]
OUTPUT_FILE = "unfoldingword_repos.ods"
ENV_FILE = ".env"


def fetch_repositories_for_org(org_name):
    """
    Fetches all repositories for a given GitHub organization.

    This function retrieves all repositories from a specified GitHub organization using
    the GitHub API. It handles pagination to fetch all repositories, and for JavaScript/
    TypeScript repositories, it attempts to fetch and parse their package.json files.

    Args:
        org_name (str): The name of the GitHub organization to fetch repositories from.

    Returns:
        list: A list of repository dictionaries. Each repository contains standard GitHub
              API fields, and for JavaScript/TypeScript repositories, additional fields:
              - 'npmjs_package_name' (str): The npm package name from package.json
              - 'npmjs_used_by' (list): Initially empty, populated later by update_npmjs_dependencies
              - 'npmjs_uses' (list): Initially empty, populated later by update_npmjs_dependencies
              - 'package_json' (dict): The parsed package.json content, or None if not available
    """
    repos = []

    query_params = urllib.parse.urlencode({
        "per_page": 100,
        "type": "all",
        "sort": "updated",
        "direction": "desc",
    })

    github_api_url = f"https://api.github.com/orgs/{org_name}/repos"
    url = f"{github_api_url}?{query_params}"

    while url:
        print(f"Fetching: {url}")

        data, link_header = github_request(url)

        page_repos = json.loads(data.decode("utf-8"))

        for repo in page_repos:
            repo["github_dependents"] = fetch_repository_dependents(repo)
            repo["github_contributors"] = fetch_repository_contributors(repo)
            repo["github_downloads"], repo["github_release_count"] = fetch_repository_github_downloads(repo)
            repo["last_commit_date"] = fetch_repository_last_commit_date(repo)
            repo["last_release_date"] = fetch_repository_last_release_date(repo)
            repo["open_prs_count"] = fetch_repository_open_prs_count(repo)

            language = (repo.get("language") or "").lower()

            if language in ("javascript", "typescript"):
                package_json = fetch_package_json(repo)

                if package_json:
                    npm_package_name = package_json.get("name", "")
                    repo["npmjs_package_name"] = npm_package_name

                    if package_json.get("private") is not True:
                        npm_package_metadata = fetch_npmjs_package_metadata(npm_package_name)

                        if npm_repo_is_from_uw(npm_package_metadata, ORG_NAMES):
                            repo["npmjs_last_published"] = fetch_npmjs_last_published(npm_package_metadata)
                            # repo["npmjs_downloads_last_month"] = fetch_npmjs_download_count(npm_package_name)
                            repo["npmjs_downloads_last_year"] = fetch_npmjs_download_count(
                                npm_package_name,
                                "last-year",
                            )
                            repo["npm_is_deprecated"] = fetch_npmjs_is_deprecated(npm_package_metadata)
                            # repo["npmjs_downloads_total"] = fetch_npmjs_total_download_count(
                            #     npm_package_name,
                            #     npm_package_metadata,
                            # )
                        else:
                            print(
                                f"npm_package_name: {npm_package_name}, Homepage: {npm_package_metadata.get('homepage', 'N/A') if npm_package_metadata else 'N/A'}")


                    workspaces = package_json.get("workspaces", None)
                    if not workspaces:
                        nx_json = fetch_nx_json(repo)
                        if nx_json:
                            workspaces = True

                    if workspaces:
                        repo["package_json_files"] = fetch_package_json_files(repo)

                repo["npmjs_used_by"] = []
                repo["npmjs_uses"] = []
                repo["package_json"] = package_json

        repos.extend(page_repos)

        url = get_next_page_url(link_header)

    return repos


def fetch_repositories():
    repos = []

    for org_name in ORG_NAMES:
        repos.extend(fetch_repositories_for_org(org_name))

    return repos


def update_repo_npmjs_dependency_relationships(repo, repos_by_npmjs_package_name):
    package_json = repo.get("package_json") or []
    current_package_name = repo.get("npmjs_package_name")

    if not package_json:
        return

    if not current_package_name:
        current_package_name = repo.get('name', '') # fall back to repo name

    dependencies = {}

    dependencies.update(package_json.get("dependencies") or {})
    dependencies.update(package_json.get("devDependencies") or {})
    dependencies.update(package_json.get("peerDependencies") or {})

    for dependency_name in dependencies:
        dependency_repo = repos_by_npmjs_package_name.get(dependency_name)

        if dependency_repo is None:
            continue

        npmjs_used_by = dependency_repo.setdefault("npmjs_used_by", [])

        if current_package_name not in npmjs_used_by:
            npmjs_used_by.append(current_package_name)

        npmjs_uses = repo.setdefault("npmjs_uses", [])

        if dependency_name not in npmjs_uses:
            npmjs_uses.append(dependency_name)


def update_npmjs_dependencies(repos):
    """
    Updates npm package dependency relationships within the repositories.

    For each repository with a package.json file, this function analyzes its dependencies
    and peerDependencies to build bidirectional relationships between packages. It populates
    the 'npmjs_used_by' field for packages that are dependencies, and the 'npmjs_uses' field
    for packages that have dependencies.

    Args:
        repos (list): A list of repository dictionaries. Each repository should contain:
            - 'npmjs_package_name' (str, optional): The npm package name
            - 'package_json' (dict): The parsed package.json content, or None if not available
            - 'npmjs_used_by' (list): Will be populated with package names that depend on this package
            - 'npmjs_uses' (list): Will be populated with package names this package depends on

    Returns:
        None. The function modifies the repository dictionaries in place.
    """

    # Create a dictionary mapping npm package names to their corresponding repository objects
    # This allows O(1) lookup of repositories by their npm package name for efficient
    # dependency relationship building. Only repositories with an npm package name are included.
    repos_by_npmjs_package_name = {
        repo.get("npmjs_package_name"): repo
        for repo in repos
        if repo.get("npmjs_package_name")
    }

    sub_modules = []

    # pick up monorepos
    for repo in repos:
        package_json_files = repo.get("package_json_files")
        if package_json_files:
            for package_json_file in package_json_files:
                package_json_path = package_json_file.get("path")
                if not package_json_path or (package_json_path == "package.json"):
                    continue

                package_json = fetch_repository_json_file(repo, package_json_path)
                if package_json:
                    sub_module = repo.copy()
                    new_name = f"{repo.get('name', '')}/{package_json.get('name', '')}"
                    sub_module["name"] = new_name
                    sub_module["npmjs_used_by"] = []
                    sub_module["npmjs_uses"] = []
                    
                    npm_package_name = package_json.get("name", "")
                    sub_module["npmjs_package_name"] = npm_package_name

                    if package_json.get("private") is not True:
                        npm_package_metadata = fetch_npmjs_package_metadata(npm_package_name)

                        if npm_repo_is_from_uw(npm_package_metadata, ORG_NAMES):
                            sub_module["npmjs_last_published"] = fetch_npmjs_last_published(npm_package_metadata)
                            # repo["npmjs_downloads_last_month"] = fetch_npmjs_download_count(npm_package_name)
                            sub_module["npmjs_downloads_last_year"] = fetch_npmjs_download_count(
                                npm_package_name,
                                "last-year",
                            )
                            # repo["npmjs_downloads_total"] = fetch_npmjs_total_download_count(
                            #     npm_package_name,
                            #     npm_package_metadata,
                            # )
                        else:
                            print(
                                f"npm_package_name: {npm_package_name}, Homepage: {npm_package_metadata.get('homepage', 'N/A') if npm_package_metadata else 'N/A'}")

                    sub_module["package_json"] = package_json
                    sub_modules.append(sub_module)

    repos.extend(sub_modules)
    
    for repo in repos:
        update_repo_npmjs_dependency_relationships(repo, repos_by_npmjs_package_name)


def write_ods(repos, output_file):
    headers = [
        "repo name",
        "organization name",
        "language",
        "archived",
        "is fork",
        "pushed at",
        "last commit date",
        "last release date",
        "open issues count",
        "open prs count",
        "npmjs package name",
        "npm is deprecated",
        "npmjs downloads last year",
        "npmjs last published",
        "npmjs used by",
        "npmjs uses",
        "github dependents",
        "github contributors",
        "github release count",
        "github downloads",
        "repo url",
        "last edit date",
    ]

    def build_rows(filtered_repos):
        rows = [headers]

        for repo in filtered_repos:
            rows.append([
                repo.get("name", ""),
                repo.get("owner", {}).get("login", ""),
                repo.get("language") or "",
                repo.get("archived", ""),
                repo.get("fork", ""),
                repo.get("pushed_at", ""),
                repo.get("last_commit_date", ""),
                repo.get("last_release_date", ""),
                repo.get("open_issues_count", ""),
                repo.get("open_prs_count", ""),
                repo.get("npmjs_package_name", ""),
                repo.get("npm_is_deprecated", ""),
                repo.get("npmjs_downloads_last_year", ""),
                repo.get("npmjs_last_published", ""),
                ", ".join(repo.get("npmjs_used_by", [])),
                ", ".join(repo.get("npmjs_uses", [])),
                ", ".join(repo.get("github_dependents", [])),
                ", ".join(repo.get("github_contributors", [])),
                repo.get("github_release_count", ""),
                repo.get("github_downloads", ""),
                repo.get("html_url", ""),
                repo.get("updated_at", ""),
            ])

        return rows

    def build_table(table_name, rows):
        table_rows = []

        for row in rows:
            cells = []

            for value in row:
                text = escape(str(value))
                cells.append(
                    '<table:table-cell office:value-type="string">'
                    f"<text:p>{text}</text:p>"
                    "</table:table-cell>"
                )

            table_rows.append(
                "<table:table-row>"
                f"{''.join(cells)}"
                "</table:table-row>"
            )

        return (
            f'<table:table table:name="{escape(table_name)}">'
            f"{''.join(table_rows)}"
            "</table:table>"
        )

    # Filter the repositories to include only those written in JavaScript or TypeScript.
    # This creates a subset of repos by checking if the 'language' field (case-insensitive)
    # matches either 'javascript' or 'typescript'. Handles cases where language is None.
    js_ts_repos = [
        repo
        for repo in repos
        if (repo.get("language") or "").lower() in ("javascript", "typescript")
    ]

    repositories_table = build_table("Repositories", build_rows(repos))
    js_ts_table = build_table("JavaScript TypeScript", build_rows(js_ts_repos))

    content_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    office:version="1.2">
    <office:body>
        <office:spreadsheet>
            {repositories_table}
            {js_ts_table}
        </office:spreadsheet>
    </office:body>
</office:document-content>
'''

    manifest_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest
    xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
    manifest:version="1.2">
    <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>
    <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
</manifest:manifest>
'''

    with zipfile.ZipFile(output_file, mode="w") as ods_file:
        ods_file.writestr(
            "mimetype",
            "application/vnd.oasis.opendocument.spreadsheet",
            compress_type=zipfile.ZIP_STORED,
        )
        ods_file.writestr("content.xml", content_xml)
        ods_file.writestr("META-INF/manifest.xml", manifest_xml)


def main():
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

    repos = fetch_repositories()
    update_npmjs_dependencies(repos) # update repos with npmjs dependency info
    write_ods(repos, OUTPUT_FILE)

    print()
    print(f"Created ODS: {OUTPUT_FILE}")
    print(f"Repositories written: {len(repos)}")


if __name__ == "__main__":
    main()
