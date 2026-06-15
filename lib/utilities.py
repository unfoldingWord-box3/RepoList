"""Utility functions for GitHub repository data collection and spreadsheet processing.

This module provides a comprehensive set of utilities for:

- Reading and writing OpenDocument Spreadsheet (ODS) files
- Interacting with GitHub API (repositories, commits, releases, contributors, etc.)
- Interacting with npm registry API (package metadata, downloads, deprecation status)
- Processing repository files (package.json, nx.json, etc.)
- Parsing and manipulating spreadsheet data
- Date parsing and age calculations
- Data validation and type conversions

The module is designed to support automated collection and analysis of GitHub repository
and npm package data for organizational repository management and lifecycle tracking.

Dependencies:
    - pandas: DataFrame operations and Excel/ODS file I/O
    - xml.etree.ElementTree: XML parsing for ODS internal structure
    - Standard library modules for HTTP requests, JSON, CSV, datetime operations

Environment Variables:
    GITHUB_TOKEN: GitHub personal access token for API authentication (optional but recommended
                  to increase rate limits from 60 to 5,000 requests/hour)

Constants:
    NS: Namespace dictionary for ODS XML parsing (office, table, text namespaces)
"""
import base64
import csv
import datetime
import json
import os
import pandas as pd
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}

rate_limit_max_retry = 10

def read_ods_sheets(input_file):
    """
    Read all sheets from an ODS file.

    Returns:
        dict[str, pandas.DataFrame]: Mapping of sheet names to DataFrames.
    """
    return pd.read_excel(
        input_file,
        sheet_name=None,
        engine="odf"
    )


def write_ods_sheets(output_file, sheets):
    """
    Write one or more sheets to an ODS file.

    Args:
        output_file (str): Path to the ODS file to write.
        sheets (dict[str, pandas.DataFrame] | pandas.DataFrame): Sheet data to write.
            If a single DataFrame is provided, it is written to a sheet named "Sheet1".
    """
    if isinstance(sheets, pd.DataFrame):
        sheets = {"Sheet1": sheets}

    with pd.ExcelWriter(output_file, engine="odf") as writer:
        for sheet_name, dataframe in sheets.items():
            dataframe.to_excel(
                writer,
                sheet_name=str(sheet_name)[:31],
                index=False,
            )


def write_rows_to_ods(output_file, sheet_name, rows):
    """
    Write a list of dictionaries to a single-sheet ODS file.

    Args:
        output_file (str): Path to the ODS file to write.
        sheet_name (str): Name of the sheet.
        rows (list[dict]): Rows to write.
    """
    dataframe = pd.DataFrame(rows)
    write_ods_sheets(output_file, {sheet_name: dataframe})


def safe_filename(name):
    """
    Convert a sheet name into a safe filename by replacing invalid characters.

    This function removes or replaces characters that are not allowed in filenames
    on common filesystems (Windows, macOS, Linux). It replaces invalid characters
    with underscores and trims whitespace.

    Args:
        name (str): The original sheet name or string to convert.

    Returns:
        str: A filesystem-safe filename string. Returns "sheet" if the input
             is empty or becomes empty after processing.
    """
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = name.strip()
    return name or "sheet"


def urlopen_with_retry(request, retries=1, retry_delay_seconds=5):
    """
    Open a URL with automatic retry on transient network errors.

    Retries on OSError/URLError (e.g. connection reset, timeout) but raises
    immediately on HTTP errors so callers can inspect the status code and
    headers directly. Rate-limit handling (403/429) is the caller's responsibility.

    Args:
        request (urllib.request.Request): The HTTP request object to execute.
        retries (int, optional): Number of retry attempts for transient errors. Defaults to 1.
        retry_delay_seconds (int, optional): Seconds to wait between retries. Defaults to 5.

    Returns:
        http.client.HTTPResponse: The HTTP response object from a successful request.

    Raises:
        urllib.error.HTTPError: Immediately on any HTTP error — not retried here.
        urllib.error.URLError: If all retry attempts are exhausted for network errors.
    """
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(request)
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError as error:
            if attempt < retries:
                print(
                    f"Network error, retrying in {retry_delay_seconds}s ({attempt + 1}/{retries}): {error.reason}",
                    file=sys.stderr,
                )
                time.sleep(retry_delay_seconds)
                continue
            raise

def load_env_file(env_file):
    """
    Load environment variables from a .env file into os.environ.

    Parses a simple .env file format with KEY=value pairs. Lines starting with #
    are treated as comments. Quoted values (single or double quotes) are unquoted.
    Only sets variables that don't already exist in os.environ.

    Args:
        env_file (str): Path to the .env file to load.

    Returns:
        None
    """
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

def github_request(url, allow_not_found=False, allow_conflict=False, _retry=0):
    """
    Make an authenticated request to the GitHub API.

    Sends a request to the GitHub API with appropriate headers including authentication
    if GITHUB_TOKEN is available. Handles common error cases including rate limiting,
    not found, and conflict errors with optional suppression.

    Args:
        url (str): The GitHub API URL to request.
        allow_not_found (bool, optional): If True, return (None, None) for 404 errors
                                          instead of raising. Defaults to False.
        allow_conflict (bool, optional): If True, return (None, None) for 409 errors
                                         instead of raising. Defaults to False.

    Returns:
        tuple[bytes, str | None]: A tuple of (response_data, link_header) where
                                  response_data is the raw response bytes and
                                  link_header is the Link header value for pagination
                                  (or None if not present).

    Raises:
        urllib.error.HTTPError: For HTTP errors that are not suppressed by the
                                allow_not_found or allow_conflict flags. Provides
                                detailed error messages for rate limiting and common errors.
    """
    global rate_limit_max_retry
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
        with urlopen_with_retry(request) as response:
            data = response.read()
            link_header = response.headers.get("Link")
            return data, link_header

    except urllib.error.HTTPError as error:
        if error.code == 404 and allow_not_found:
            return None, None

        if error.code == 409 and allow_conflict:
            return None, None

        if error.code in (403, 429):
            retry_after = error.headers.get("Retry-After")
            reset_time = error.headers.get("X-RateLimit-Reset")
            remaining = error.headers.get("X-RateLimit-Remaining")

            # Determine what kind of limit this is, in priority order:
            # 1. Retry-After header always means secondary rate limit
            # 2. 429 without Retry-After is still a secondary rate limit
            # 3. 403 with X-RateLimit-Remaining == "0" is a primary rate limit
            # 4. 403 with none of the above is a permission/auth error — don't retry
            if retry_after is not None or error.code == 429:
                limit_type = "secondary"
            elif error.code == 403 and remaining == "0":
                limit_type = "primary"
            else:
                print(f"GitHub API returned 403 Forbidden (permission error). (URL: {url})", file=sys.stderr)
                raise

            if _retry >= rate_limit_max_retry:
                print(f"Exceeded max retries ({rate_limit_max_retry}) for rate limiting.", file=sys.stderr)
                raise

            if limit_type == "secondary":
                sleep_duration = int(retry_after) + 1 if retry_after else 60
                print(f"GitHub secondary rate limit ({error.code}). Sleeping {sleep_duration}s before retry {_retry + 1}/{rate_limit_max_retry}...", file=sys.stderr)
            else:
                sleep_duration = max(int(reset_time) - int(time.time()), 0) + 1 if reset_time else 60
                print(f"GitHub primary rate limit. Remaining: {remaining}, Reset in {sleep_duration}s. Retry {_retry + 1}/{rate_limit_max_retry}...", file=sys.stderr)

            time.sleep(sleep_duration)
            return github_request(url, allow_not_found, allow_conflict, _retry=_retry + 1)

        elif error.code == 404:
            print(f"Organization not found. (URL: {url})", file=sys.stderr)

        else:
            print(f"GitHub API error: {error.code} {error.reason} (URL: {url})", file=sys.stderr)

        raise


def github_html_request(url, allow_not_found=False):
    """
    Make an authenticated HTML request to GitHub (non-API endpoint).

    Fetches HTML content from GitHub web pages with authentication. Used for
    scraping data not available through the GitHub API, such as the dependents graph.

    Args:
        url (str): The GitHub web page URL to request.
        allow_not_found (bool, optional): If True, return None for 404 errors
                                          instead of logging an error. Defaults to False.

    Returns:
        str | None: The HTML content as a UTF-8 string, or None if the request fails.
    """
    headers = {
        "Accept": "text/html",
        "User-Agent": "unfoldingword-repo-list-script",
    }

    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    request = urllib.request.Request(url, headers=headers)

    try:
        with urlopen_with_retry(request) as response:
            return response.read().decode("utf-8")

    except urllib.error.HTTPError as error:
        if error.code == 404 and allow_not_found:
            return None

        print(
            f"GitHub HTML request error: {error.code} {error.reason}",
            file=sys.stderr,
        )
        return None

    except urllib.error.URLError as error:
        print(
            f"GitHub HTML request failed: {error.reason} (URL: {url})",
            file=sys.stderr,
        )
        return None
    

def fetch_repository_dependents(repo):
    """
    Fetch the list of repository dependents from GitHub's dependency graph.

    Scrapes the GitHub web interface to find repositories that depend on the given
    repository. This data is not available through the GitHub API and must be
    extracted from HTML. Follows pagination to collect all dependents.

    Args:
        repo (dict): Repository object containing 'owner' and 'name' fields.

    Returns:
        list[str]: List of dependent repository names in "owner/repo" format.
                   Returns empty list if the repository info is incomplete or no
                   dependents are found.
    """
    owner = repo.get("owner", {}).get("login")
    repo_name = repo.get("name")

    if not owner or not repo_name:
        return []

    dependents = []
    seen_dependents = set()
    next_url = (
        f"https://github.com/{urllib.parse.quote(owner, safe='')}/"
        f"{urllib.parse.quote(repo_name, safe='')}/network/dependents?"
        f"{urllib.parse.urlencode({'dependent_type': 'REPOSITORY'})}"
    )

    while next_url:
        print(f"Fetching dependents: {owner}/{repo_name}")

        html = github_html_request(next_url, allow_not_found=True)
        if not html:
            break

        repo_links = re.findall(r'href="/([^"/]+/[^"/]+)"', html)

        for dependent in repo_links:
            if dependent == f"{owner}/{repo_name}":
                continue

            if dependent in seen_dependents:
                continue

            seen_dependents.add(dependent)
            dependents.append(dependent)

        next_match = re.search(r'href="([^"]+)"[^>]*>\s*Next\s*</a>', html)
        if not next_match:
            break

        next_url = urllib.parse.urljoin("https://github.com", next_match.group(1))

    return dependents


def fetch_repository_contributors(repo):
    """
    Fetch the list of contributors for a repository from the GitHub API.

    Retrieves all contributors including anonymous contributors. Handles pagination
    to collect complete contributor lists for repositories with many contributors.

    Args:
        repo (dict): Repository object containing 'owner' and 'name' fields.

    Returns:
        list[str]: List of contributor identifiers (login names, names, or emails).
                   Returns empty list if the repository info is incomplete or the
                   request fails.
    """
    owner = repo.get("owner", {}).get("login")
    repo_name = repo.get("name")

    if not owner or not repo_name:
        return []

    contributors = []
    seen_contributors = set()
    next_url = (
        f"https://api.github.com/repos/"
        f"{urllib.parse.quote(owner, safe='')}/"
        f"{urllib.parse.quote(repo_name, safe='')}/contributors?"
        f"{urllib.parse.urlencode({'per_page': 100, 'anon': 'true'})}"
    )

    while next_url:
        print(f"Fetching contributors: {owner}/{repo_name}")

        data, link_header = github_request(next_url, allow_not_found=True)
        if not data:
            break

        decoded_data = data.decode("utf-8").strip()
        if not decoded_data:
            break

        try:
            page_contributors = json.loads(decoded_data)
        except json.JSONDecodeError as error:
            print(
                f"Could not parse contributors response for {owner}/{repo_name}: {error}",
                file=sys.stderr,
            )
            break

        if not isinstance(page_contributors, list):
            message = page_contributors.get("message", "Unexpected contributors response")
            print(
                f"Could not fetch contributors for {owner}/{repo_name}: {message}",
                file=sys.stderr,
            )
            break

        for contributor in page_contributors:
            contributor_name = (
                contributor.get("login")
                or contributor.get("name")
                or contributor.get("email")
            )

            if not contributor_name:
                continue

            if contributor_name in seen_contributors:
                continue

            seen_contributors.add(contributor_name)
            contributors.append(contributor_name)

        next_url = get_next_page_url(link_header)

    return contributors


def fetch_repository_last_commit_date(repo):
    """
    Fetch the date of the most recent commit in a repository.

    Queries the GitHub API for the most recent commit on the default branch
    and extracts the committer date.

    Args:
        repo (dict): Repository object containing 'owner', 'name', and optionally
                     'default_branch' fields.

    Returns:
        str: ISO 8601 formatted date string of the last commit, or empty string
             if the repository info is incomplete or no commits are found.
    """
    owner = repo.get("owner", {}).get("login")
    repo_name = repo.get("name")
    default_branch = repo.get("default_branch")

    if not owner or not repo_name:
        return ""

    query_params = {
        "per_page": 1,
    }

    if default_branch:
        query_params["sha"] = default_branch

    commits_url = (
        f"https://api.github.com/repos/"
        f"{urllib.parse.quote(owner, safe='')}/"
        f"{urllib.parse.quote(repo_name, safe='')}/commits?"
        f"{urllib.parse.urlencode(query_params)}"
    )

    print(f"Fetching latest commit: {owner}/{repo_name}")

    data, _ = github_request(commits_url, allow_not_found=True, allow_conflict=True)
    if not data:
        return ""

    commits = json.loads(data.decode("utf-8"))
    if not commits:
        return ""

    return (
        commits[0]
        .get("commit", {})
        .get("committer", {})
        .get("date", "")
    )


def fetch_repository_last_release_date(repo):
    """
    Fetch the publication date of the most recent release in a repository.

    Queries the GitHub API for the latest release and extracts its publication date.
    Falls back to creation date if publication date is not available.

    Args:
        repo (dict): Repository object containing 'owner' and 'name' fields.

    Returns:
        str: ISO 8601 formatted date string of the last release, or empty string
             if the repository info is incomplete or no releases exist.
    """
    owner = repo.get("owner", {}).get("login")
    repo_name = repo.get("name")

    if not owner or not repo_name:
        return ""

    releases_url = (
        f"https://api.github.com/repos/"
        f"{urllib.parse.quote(owner, safe='')}/"
        f"{urllib.parse.quote(repo_name, safe='')}/releases/latest"
    )

    print(f"Fetching latest release: {owner}/{repo_name}")

    data, _ = github_request(releases_url, allow_not_found=True)
    if not data:
        return ""

    release = json.loads(data.decode("utf-8"))
    return release.get("published_at") or release.get("created_at", "")


def fetch_repository_open_prs_count(repo):
    """
    Fetch the count of open pull requests in a repository.

    Uses the GitHub API pagination headers to efficiently determine the total
    count without fetching all pull request data.

    Args:
        repo (dict): Repository object containing 'owner' and 'name' fields.

    Returns:
        int | str: Number of open pull requests, or empty string if the repository
                   info is incomplete or the request fails.
    """
    owner = repo.get("owner", {}).get("login")
    repo_name = repo.get("name")

    if not owner or not repo_name:
        return ""

    pulls_url = (
        f"https://api.github.com/repos/"
        f"{urllib.parse.quote(owner, safe='')}/"
        f"{urllib.parse.quote(repo_name, safe='')}/pulls?"
        f"{urllib.parse.urlencode({'state': 'open', 'per_page': 1})}"
    )

    print(f"Fetching open PR count: {owner}/{repo_name}")

    data, link_header = github_request(pulls_url, allow_not_found=True)
    if not data:
        return ""

    last_page_match = re.search(r'[?&]page=(\d+)>; rel="last"', link_header or "")
    if last_page_match:
        return int(last_page_match.group(1))

    pulls = json.loads(data.decode("utf-8"))
    return len(pulls)


def get_next_page_url(link_header):
    """
    Extract the next page URL from a GitHub API Link header.

    Parses the Link header returned by GitHub API responses to find the URL
    for the next page of paginated results.

    Args:
        link_header (str | None): The Link header value from a GitHub API response.

    Returns:
        str | None: The URL for the next page, or None if there is no next page
                    or the header cannot be parsed.
    """
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


def fetch_repository_file(repo, file_path):
    """
    Fetch a file's base64-encoded content from a repository.

    Attempts to retrieve the file from both 'main' and 'master' branches,
    returning the first successful result.

    Args:
        repo (dict): Repository object containing 'owner' and 'name' fields.
        file_path (str): Path to the file within the repository.

    Returns:
        str | None: Base64-encoded content string, or None if the repository info
                    is incomplete or the file is not found on either branch.
    """
    owner = repo.get("owner", {}).get("login")
    repo_name = repo.get("name")

    if not owner or not repo_name:
        return None

    for branch_name in ("main", "master"):
        file_url = (
            f"https://api.github.com/repos/"
            f"{urllib.parse.quote(owner, safe='')}/"
            f"{urllib.parse.quote(repo_name, safe='')}/"
            f"contents/{urllib.parse.quote(file_path, safe='/')}?"
            f"{urllib.parse.urlencode({'ref': branch_name})}"
        )

        print(f"Fetching {file_path}: {owner}/{repo_name}@{branch_name}")

        data, _ = github_request(file_url, allow_not_found=True)
        if data is None:
            continue

        repository_file = json.loads(data.decode("utf-8"))
        content = repository_file.get("content", "")

        if content:
            return content

    return None


def fetch_repository_json_file(repo, file_path):
    """
    Fetch and parse a JSON file from a repository.

    Retrieves a file using fetch_repository_file(), decodes it from base64,
    and parses it as JSON.

    Args:
        repo (dict): Repository object containing 'owner' and 'name' fields.
        file_path (str): Path to the JSON file within the repository.

    Returns:
        dict | list | None: Parsed JSON content, or None if the file is not found
                            or cannot be parsed.
    """
    encoded_content = fetch_repository_file(repo, file_path)

    if encoded_content:
        decoded_content = base64.b64decode(encoded_content).decode("utf-8")
        return json.loads(decoded_content)

    return None


def fetch_package_json(repo):
    """
    Fetch and parse package.json from a repository.

    Convenience wrapper around fetch_repository_json_file() specifically for
    Node.js package.json files.

    Args:
        repo (dict): Repository object containing 'owner' and 'name' fields.

    Returns:
        dict | None: Parsed package.json content, or None if not found.
    """
    package_json = fetch_repository_json_file(repo, "package.json")
    return package_json


def fetch_package_json_files(repo):
    """
    Find all package.json files in a repository.

    Recursively searches the repository's file tree for all package.json files,
    useful for monorepos with multiple packages.

    Args:
        repo (dict): Repository object containing 'owner', 'name', and 'default_branch' fields.

    Returns:
        list[dict]: List of dictionaries with 'path' and 'url' keys for each
                    package.json file found. Returns empty list if repository
                    info is incomplete or no package.json files are found.
    """
    owner = repo.get("owner", {}).get("login")
    repo_name = repo.get("name")
    default_branch = repo.get("default_branch")

    if not owner or not repo_name or not default_branch:
        return []

    tree_url = (
        f"https://api.github.com/repos/"
        f"{urllib.parse.quote(owner, safe='')}/"
        f"{urllib.parse.quote(repo_name, safe='')}/"
        f"git/trees/"
        f"{urllib.parse.quote(default_branch, safe='')}?"
        f"{urllib.parse.urlencode({'recursive': '1'})}"
    )

    print(f"Fetching recursive file tree: {owner}/{repo_name}@{default_branch}")

    data, _ = github_request(tree_url, allow_not_found=True)
    if data is None:
        return []

    tree_data = json.loads(data.decode("utf-8"))
    package_files = []

    for item in tree_data.get("tree", []):
        if item.get("type") != "blob":
            continue

        path = item.get("path", "")

        if path.endswith("package.json"):
            package_files.append({
                "path": path,
                "url": (
                    f"https://github.com/{owner}/{repo_name}/blob/"
                    f"{urllib.parse.quote(default_branch, safe='')}/{path}"
                ),
            })

    return package_files

def fetch_nx_json(repo):
    """
    Fetch and parse nx.json from a repository.

    Convenience wrapper around fetch_repository_json_file() specifically for
    Nx monorepo configuration files.

    Args:
        repo (dict): Repository object containing 'owner' and 'name' fields.

    Returns:
        dict | None: Parsed nx.json content, or None if not found.
    """
    return fetch_repository_json_file(repo, "nx.json")


def fetch_npmjs_package_metadata(package_name):
    """
    Fetch package metadata from the npm registry.

    Retrieves the complete metadata document for an npm package, including
    version history, dependencies, and publication information.

    Args:
        package_name (str): Name of the npm package (may include scope, e.g., '@scope/package').

    Returns:
        dict | None: Complete npm package metadata, or None if the package is not
                     found or the request fails.
    """
    package_url = (
        "https://registry.npmjs.org/"
        f"{urllib.parse.quote(package_name, safe='@')}"
    )

    print(f"Fetching npm package metadata: {package_name}")

    request = urllib.request.Request(
        package_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "unfoldingword-repo-list-script",
        },
    )

    try:
        with urlopen_with_retry(request) as response:
            return json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None

        print(
            f"npm registry error for {package_name}: {error.code} {error.reason}",
            file=sys.stderr,
        )
        return None


def npm_repo_is_from_uw(package_metadata, ORG_NAMES):
    """
    Check if an npm package belongs to specified organizations.

    Examines the package's homepage and repository URL to determine if it
    belongs to any of the specified organization names.

    Args:
        package_metadata (dict | None): npm package metadata from fetch_npmjs_package_metadata().
        ORG_NAMES (list[str]): List of organization names to check against.

    Returns:
        bool: True if the package's homepage or repository URL contains any of
              the specified organization names (case-insensitive), False otherwise.
    """
    if package_metadata is None:
        return False

    homepage = package_metadata.get("homepage") or ""
    repository = package_metadata.get("repository") or {}

    if isinstance(repository, dict):
        repository_url = repository.get("url") or ""
    else:
        repository_url = str(repository) if repository else ""

    homepage = homepage.lower()
    repository_url = repository_url.lower()

    in_uw_org = any(org_name.lower() in homepage or org_name.lower() in repository_url for org_name in ORG_NAMES)
    return in_uw_org


def fetch_npmjs_last_published(package_metadata):
    """
    Extract the publication date of the latest version from package metadata.

    Determines the most recent publication date by first checking the 'latest'
    dist-tag, then falling back to the most recent date in the time metadata.

    Args:
        package_metadata (dict | None): npm package metadata from fetch_npmjs_package_metadata().

    Returns:
        str: ISO 8601 formatted date string of the last publication, or empty
             string if metadata is None or no publication dates are available.
    """
    if package_metadata is None:
        return ""

    time_metadata = package_metadata.get("time") or {}
    latest_version = package_metadata.get("dist-tags", {}).get("latest")

    if latest_version:
        return time_metadata.get(latest_version, "")

    published_dates = [
        published_at
        for version, published_at in time_metadata.items()
        if version not in ("created", "modified")
    ]

    time.sleep(0.25)

    return max(published_dates, default="")


def fetch_npmjs_is_deprecated(package_metadata):
    """
    Check if an npm package is marked as deprecated.

    Checks both the latest version and the package-level metadata for
    deprecation status.

    Args:
        package_metadata (dict | None): npm package metadata from fetch_npmjs_package_metadata().

    Returns:
        bool | str: True if deprecated, False if not deprecated, or empty string
                    if metadata is None.
    """
    if package_metadata is None:
        return ""

    latest_version = package_metadata.get("dist-tags", {}).get("latest")
    versions = package_metadata.get("versions") or {}

    if latest_version and latest_version in versions:
        return bool(versions[latest_version].get("deprecated"))

    return bool(package_metadata.get("deprecated"))


def fetch_npmjs_download_count(package_name, period="last-month"):
    """
    Fetch download count for an npm package over a specified period.

    Queries the npm downloads API to get the total number of downloads for
    a package during the specified time period.

    Args:
        package_name (str): Name of the npm package (may include scope).
        period (str, optional): Time period for download count (e.g., 'last-day',
                                'last-week', 'last-month', 'last-year').
                                Defaults to 'last-month'.

    Returns:
        int | str: Total download count for the period, or empty string if the
                   package name is empty, package is not found, or request fails.
    """
    if not package_name:
        return ""

    downloads_url = (
        "https://api.npmjs.org/downloads/point/"
        f"{urllib.parse.quote(period, safe='')}/"
        f"{urllib.parse.quote(package_name, safe='@')}"
    )

    print(f"Fetching npm download count: {package_name}")

    request = urllib.request.Request(
        downloads_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "unfoldingword-repo-list-script",
        },
    )

    try:
        with urlopen_with_retry(request) as response:
            download_data = json.loads(response.read().decode("utf-8"))
            return download_data.get("downloads", "")

    except urllib.error.HTTPError as error:
        if error.code == 404:
            return ""

        print(
            f"npm downloads API error for {package_name}: {error.code} {error.reason}",
            file=sys.stderr,
        )
        return ""


def fetch_npmjs_download_count(package_name, period="last-month"):
    if not package_name:
        return ""

    downloads_url = (
        "https://api.npmjs.org/downloads/point/"
        f"{urllib.parse.quote(period, safe='')}/"
        f"{urllib.parse.quote(package_name, safe='@')}"
    )

    print(f"Fetching npm download count: {package_name}")

    request = urllib.request.Request(
        downloads_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "unfoldingword-repo-list-script",
        },
    )

    try:
        with urlopen_with_retry(request) as response:
            download_data = json.loads(response.read().decode("utf-8"))
            return download_data.get("downloads", "")

    except urllib.error.HTTPError as error:
        if error.code == 404:
            return ""

        print(
            f"npm downloads API error for {package_name}: {error.code} {error.reason}",
            file=sys.stderr,
        )
        return ""


def fetch_npmjs_total_download_count(package_name, package_metadata):
    """
    Fetch the total lifetime download count for an npm package.

    Calculates total downloads from the package creation date to present by
    making multiple API requests in 365-day increments (npm API limitation).

    Args:
        package_name (str): Name of the npm package (may include scope).
        package_metadata (dict | None): npm package metadata containing creation date.

    Returns:
        int | str: Total lifetime download count, or empty string if package name
                   is empty, metadata is None, creation date is missing/invalid,
                   or request fails.
    """
    if not package_name or package_metadata is None:
        return ""

    created_at = (package_metadata.get("time") or {}).get("created")
    if not created_at:
        return ""

    try:
        start_date = datetime.date.fromisoformat(created_at[:10])
    except ValueError:
        return ""

    end_date = datetime.date.today()
    total_downloads = 0
    current_start = start_date

    print(f"Fetching total npm download count: {package_name}")

    while current_start <= end_date:
        current_end = min(
            current_start + datetime.timedelta(days=364),
            end_date,
            )

        period = f"{current_start.isoformat()}:{current_end.isoformat()}"
        downloads_url = (
            "https://api.npmjs.org/downloads/range/"
            f"{urllib.parse.quote(period, safe=':')}/"
            f"{urllib.parse.quote(package_name, safe='@')}"
        )

        request = urllib.request.Request(
            downloads_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "unfoldingword-repo-list-script",
            },
        )

        try:
            with urlopen_with_retry(request) as response:
                download_data = json.loads(response.read().decode("utf-8"))
                daily_downloads = sum(day.get("downloads", 0) for day in download_data.get("downloads", []))
                total_downloads += daily_downloads

        except urllib.error.HTTPError as error:
            if error.code == 404:
                return ""

            print(
                f"npm downloads API error for {package_name}: {error.code} {error.reason}",
                file=sys.stderr,
            )
            return ""

        current_start = current_end + datetime.timedelta(days=1)

    return total_downloads


def fetch_repository_github_downloads(repo):
    """
    Fetch total GitHub release asset download count and release count for a repository.

    Iterates through all releases in a repository and sums the download counts
    for all assets. Also counts the total number of releases.

    Args:
        repo (dict): Repository object containing 'releases_url' field.

    Returns:
        tuple[int, int]: A tuple of (total_downloads, release_count) where
                         total_downloads is the sum of all asset downloads and
                         release_count is the number of releases. Returns (0, 0)
                         if releases_url is not available.
    """
    downloads = 0
    release_count = 0
    releases_url = repo.get("releases_url", "").replace("{/id}", "")

    if not releases_url:
        return downloads, release_count

    query_params = urllib.parse.urlencode({
        "per_page": 100,
    })
    url = f"{releases_url}?{query_params}"

    while url:
        print(f"Fetching GitHub release downloads: {url}")

        try:
            data, link_header = github_request(url)
            if data is None:
                print(f"No data returned for releases {url}")
                break
                
            releases = json.loads(data.decode("utf-8"))
            release_count += len(releases)
    
            for release in releases:
                for asset in release.get("assets", []):
                    downloads += asset.get("download_count", 0)
    
            url = get_next_page_url(link_header)
            
        except Exception as e:
            print(f"Error fetching GitHub release downloads: {e}")
            break

    return downloads, release_count

def get_cell_text(cell):
    """
    Extract plain text from an ODS table cell.

    Extracts and concatenates text from all paragraphs within a cell,
    joining multiple paragraphs with newlines.

    Args:
        cell (xml.etree.ElementTree.Element): ODS table cell XML element.

    Returns:
        str: Plain text content of the cell with paragraphs separated by newlines.
    """
    parts = []

    for paragraph in cell.findall(".//text:p", NS):
        text = "".join(paragraph.itertext())
        parts.append(text)

    return "\n".join(parts)


def read_ods_sheet(filename, sheet_name):
    """Read rows from a named sheet in an ODS file.

    This function extracts tabular data from an OpenDocument Spreadsheet (ODS) file
    by parsing its internal XML structure. It handles ODS-specific features like
    repeated rows/columns and normalizes the output to a consistent rectangular grid.

    Args:
        filename (str): Path to the ODS file to read.
        sheet_name (str): Name of the sheet to extract from the ODS file.

    Returns:
        list[list[str]]: A 2D list representing the sheet data, where each inner list
                         is a row of cells. All rows have the same width (determined
                         by the first non-empty row, typically the header).

    Raises:
        ValueError: If the specified sheet_name is not found in the ODS file.

    Processing Details:
        1. Extracts and parses the content.xml file from the ODS ZIP archive
        2. Locates the sheet matching the provided sheet_name
        3. For each row in the sheet:
           - Handles ODS row repetition (number-rows-repeated attribute)
           - For each cell:
             * Extracts text content using get_cell_text()
             * Handles ODS column repetition (number-columns-repeated attribute)
             * Prevents excessive empty column repetition in the header row
             * Constrains cells to the established header width for data rows
           - First row establishes header_width by trimming trailing empty cells
           - Subsequent rows are padded or truncated to match header_width
        4. Returns all rows with consistent column counts

    Note:
        - Empty cells are represented as empty strings ("")
        - The first row determines the number of columns for all subsequent rows
        - ODS files may contain repeated row/column attributes for compression;
          this function expands them to their full representation
    """

    # ODS files are ZIP archives. The spreadsheet data lives in content.xml,
    # so open the archive, read that XML file, and parse it into an ElementTree.
    with zipfile.ZipFile(filename, "r") as ods:
        with ods.open("content.xml") as content:
            tree = ET.parse(content)

    root = tree.getroot()

    # Find every table element in the document. Each table represents one sheet.
    sheets = root.findall(".//table:table", NS)

    for sheet in sheets:
        # ODS stores the sheet name as a namespaced table:name attribute.
        name = sheet.attrib.get(f"{{{NS['table']}}}name")

        # Skip sheets until we find the one the caller requested.
        if name != sheet_name:
            continue

        rows = []

        # The first row is treated as the header. Its width is used to normalize
        # all following rows so CSV output has a consistent number of columns.
        header_width = None

        for row in sheet.findall("table:table-row", NS):
            # ODS may compress identical consecutive rows using
            # table:number-rows-repeated. Default to 1 when it is not present.
            repeated_rows = int(
                row.attrib.get(f"{{{NS['table']}}}number-rows-repeated", "1")
            )

            row_data = []

            for cell in row.findall("table:table-cell", NS):
                # ODS may also compress identical consecutive cells using
                # table:number-columns-repeated.
                repeated_cols = int(
                    cell.attrib.get(f"{{{NS['table']}}}number-columns-repeated", "1")
                )

                # Extract the displayed text from the cell's XML content.
                value = get_cell_text(cell)

                # In the header row, trailing blank cells can be stored as a huge
                # repeated empty range. Keep each empty header cell to one column
                # so the header width does not become artificially large.
                if header_width is None and value == "":
                    repeated_cols = 1

                # After the header width is known, do not read more columns than
                # the header defines. Extra spreadsheet cells are ignored.
                if header_width is not None:
                    remaining_cols = header_width - len(row_data)
                    if remaining_cols <= 0:
                        break
                    repeated_cols = min(repeated_cols, remaining_cols)

                # Expand repeated columns into regular cell values so callers get
                # a normal list of strings instead of ODS compression metadata.
                for _ in range(repeated_cols):
                    row_data.append(value)

            if header_width is None:
                # The first row establishes the number of columns. Remove trailing
                # blanks so accidental empty spreadsheet columns are not included.
                while row_data and row_data[-1] == "":
                    row_data.pop()

                header_width = len(row_data)

            else:
                # Keep data rows rectangular: trim rows that are too wide and pad
                # rows that are too short with empty strings.
                row_data = row_data[:header_width]

                while len(row_data) < header_width:
                    row_data.append("")

            # Expand repeated rows after the row has been normalized. Use copy()
            # so each output row is an independent list.
            for _ in range(repeated_rows):
                rows.append(row_data.copy())

        return rows

    raise ValueError(f"Sheet not found: {sheet_name}")


def write_list_to_csv(output_csv, headers, data):
    """
    Write row dictionaries to a CSV file, flattening list values.

    Converts list values to comma-separated strings before writing to CSV.
    Useful for exporting spreadsheet data with multi-value cells.

    Args:
        output_csv (str): Path to the output CSV file.
        headers (list[str]): Column headers for the CSV file.
        data (list[dict]): List of row dictionaries to write.

    Returns:
        None
    """
    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        if data:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writeheader()

            for row in data:
                flattened_row = {}
                for key, value in row.items():
                    if isinstance(value, list):
                        flattened_row[key] = ', '.join(value)
                    else:
                        flattened_row[key] = value
                writer.writerow(flattened_row)

            print(f"Data saved to {output_csv}")


def load_repository_data(ODS_FILE, SHEET_NAME):
    """
    Load repository rows from an ODS sheet and normalize comma-separated values.

    Reads a sheet from an ODS file, treats the first row as headers, and
    converts comma-separated cell values into lists.

    Args:
        ODS_FILE (str): Path to the ODS file.
        SHEET_NAME (str): Name of the sheet to read.

    Returns:
        tuple[list[str], list[dict]]: A tuple of (headers, data) where headers
                                      is the list of column names and data is a
                                      list of row dictionaries with comma-separated
                                      values split into lists.
    """
    rows = read_ods_sheet(ODS_FILE, SHEET_NAME)

    headers = rows[0]
    data = [dict(zip(headers, row)) for row in rows[1:]]

    for row in data:
        for key, value in row.items():
            if isinstance(value, str) and ',' in value:
                row[key] = [item.strip() for item in value.split(',')]

    return headers, data


def is_empty(value):
    """
    Return True when a spreadsheet value is empty.

    Handles various empty representations including None, empty strings,
    whitespace-only strings, and lists containing only empty values.

    Args:
        value: Any value from a spreadsheet cell (str, list, None, etc.).

    Returns:
        bool: True if the value is considered empty, False otherwise.
    """
    if value is None:
        return True

    if isinstance(value, list):
        return len([item for item in value if str(item).strip()]) == 0

    return str(value).strip() == ""


def is_true(value):
    """
    Return True for common spreadsheet boolean values.

    Recognizes common textual representations of boolean true values used
    in spreadsheets (case-insensitive).

    Args:
        value: Any value from a spreadsheet cell.

    Returns:
        bool: True if value matches 'true', 'yes', '1', or 'y' (case-insensitive),
              False otherwise.
    """
    return str(value).strip().lower() in {"true", "yes", "1", "y"}


def as_int(value):
    """
    Convert spreadsheet numeric values to int, treating blanks as zero.

    Handles comma-separated thousands, list values (uses first element),
    and converts via float to handle decimal strings.

    Args:
        value: Any value from a spreadsheet cell.

    Returns:
        int: Integer representation of the value, or 0 if the value is empty
             or cannot be converted.
    """
    if is_empty(value):
        return 0

    if isinstance(value, list):
        value = value[0] if value else ""

    try:
        return int(float(str(value).replace(",", "").strip()))
    except ValueError:
        return 0


def parse_date(value):
    """
    Parse common spreadsheet date formats.

    Attempts to parse date strings using multiple common formats including
    ISO 8601, US formats, and datetime with timezone.

    Args:
        value: Any value from a spreadsheet cell that may contain a date.

    Returns:
        datetime.datetime | None: Parsed datetime object, or None if the value
                                  is empty or cannot be parsed by any known format.
    """
    if is_empty(value):
        return None

    if isinstance(value, list):
        value = value[0] if value else ""

    value = str(value).strip()

    for date_format in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.datetime.strptime(value[:19], date_format)
        except ValueError:
            continue

    return None


def months_old(value):
    """
    Return approximate age in months for a date value.

    Calculates the number of complete months between a given date and today.
    Useful for determining repository or package age.

    Args:
        value: Any value that can be parsed as a date.

    Returns:
        int | None: Number of months between the date and today, or None if
                    the value cannot be parsed as a date.
    """
    date_value = parse_date(value)

    if date_value is None:
        return None

    today = datetime.datetime.today()
    return (today.year - date_value.year) * 12 + today.month - date_value.month


def contains_any(value, terms):
    """
    Return True when value contains any term from a list.

    Performs case-insensitive substring matching to check if any of the
    provided terms appear in the value.

    Args:
        value: Any value to search within (converted to lowercase string).
        terms (list[str]): List of terms to search for.

    Returns:
        bool: True if any term is found in the value (case-insensitive),
              False otherwise.
    """
    return any(term in str(value).lower() for term in terms)


