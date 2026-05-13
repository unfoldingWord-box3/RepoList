#!/usr/bin/env python3

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from xml.sax.saxutils import escape

ORG_NAME = [
    "unfoldingWord",
    "unfoldingWord-dev",
    "unfoldingWord-box3",
]
OUTPUT_FILE = "unfoldingword_repos.ods"
GITHUB_API_URL = f"https://api.github.com/orgs/{ORG_NAME}/repos"
ENV_FILE = ".env"


def load_env_file(env_file):
    if not os.path.exists(env_file):
        return

    with open(env_file, mode="r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


def github_request(url, allow_not_found=False):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "unfoldingword-repo-list-script",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    request = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(request) as response:
            data = response.read()
            link_header = response.headers.get("Link")
            return data, link_header

    except urllib.error.HTTPError as error:
        if error.code == 404 and allow_not_found:
            return None, None

        if error.code == 403:
            reset_time = error.headers.get("X-RateLimit-Reset")
            if reset_time:
                reset_seconds = int(reset_time) - int(time.time())
                print(
                    f"GitHub rate limit exceeded. Try again in {max(reset_seconds, 0)} seconds.",
                    file=sys.stderr,
                )
            else:
                print("GitHub API returned 403 Forbidden.", file=sys.stderr)

        elif error.code == 404:
            print("Organization not found.", file=sys.stderr)

        else:
            print(f"GitHub API error: {error.code} {error.reason}", file=sys.stderr)

        raise


def get_next_page_url(link_header):
    if not link_header:
        return None

    links = link_header.split(",")

    for link in links:
        parts = link.strip().split(";")
        if len(parts) != 2:
            continue

        url_part = parts[0].strip()
        rel_part = parts[1].strip()

        if rel_part == 'rel="next"':
            return url_part.strip("<>")

    return None


def fetch_package_json(repo):
    owner = repo.get("owner", {}).get("login")
    repo_name = repo.get("name")

    if not owner or not repo_name:
        return None

    for branch_name in ("main", "master"):
        package_url = (
            f"https://api.github.com/repos/"
            f"{urllib.parse.quote(owner, safe='')}/"
            f"{urllib.parse.quote(repo_name, safe='')}/"
            f"contents/package.json?"
            f"{urllib.parse.urlencode({'ref': branch_name})}"
        )

        print(f"Fetching package.json: {owner}/{repo_name}@{branch_name}")

        data, _ = github_request(package_url, allow_not_found=True)
        if data is None:
            continue

        package_file = json.loads(data.decode("utf-8"))
        encoded_content = package_file.get("content", "")

        if not encoded_content:
            return None

        decoded_content = base64.b64decode(encoded_content).decode("utf-8")
        return json.loads(decoded_content)

    return None


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
            language = (repo.get("language") or "").lower()

            if language in ("javascript", "typescript"):
                package_json = fetch_package_json(repo)

                if package_json and package_json.get("private") is not True:
                    repo["npmjs_package_name"] = package_json.get("name", "")

                repo["npmjs_used_by"] = []
                repo["npmjs_uses"] = []
                repo["package_json"] = package_json

        repos.extend(page_repos)

        url = get_next_page_url(link_header)

    return repos

def fetch_repositories():
    repos = []

    for org_name in ORG_NAME:
        repos.extend(fetch_repositories_for_org(org_name))

    return repos


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
            - 'package_json' (dict, optional): Parsed package.json content with 'dependencies'
              and/or 'peerDependencies' fields
            - 'npmjs_used_by' (list): Will be populated with package names that depend on this package
            - 'npmjs_uses' (list): Will be populated with package names this package depends on
    
    Returns:
        None. The function modifies the repository dictionaries in place.
    """
    repos_by_npmjs_package_name = {
        repo.get("npmjs_package_name"): repo
        for repo in repos
        if repo.get("npmjs_package_name")
    }

    for repo in repos:
        package_json = repo.get("package_json")
        current_package_name = repo.get("npmjs_package_name")

        if not package_json or not current_package_name:
            continue

        dependencies = {}
        dependencies.update(package_json.get("dependencies") or {})
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

def write_ods(repos, output_file):
    headers = [
        "repo name",
        "organization name",
        "language",
        "npmjs package name",
        "npmjs used by",
        "npmjs uses",
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
                repo.get("npmjs_package_name", ""),
                ", ".join(repo.get("npmjs_used_by", [])),
                ", ".join(repo.get("npmjs_uses", [])),
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

    repos = fetch_repositories()
    update_npmjs_dependencies(repos)
    write_ods(repos, OUTPUT_FILE)

    print()
    print(f"Created ODS: {OUTPUT_FILE}")
    print(f"Repositories written: {len(repos)}")


if __name__ == "__main__":
    main()
