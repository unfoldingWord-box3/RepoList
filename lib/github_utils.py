"""GitHub API utilities for repository data collection and ODS output.

This module provides utilities for:
- Making authenticated requests to the GitHub REST API and GitHub web pages
- Fetching repository metadata (commits, releases, contributors, dependents, PRs)
- Fetching repository file content (package.json, nx.json, .gitmodules)
- Paginating GitHub API responses
- Writing collected repository data to ODS format

Dependencies:
    - Standard library modules for HTTP requests, JSON, ZIP, base64, and INI parsing
    - lib.utilities: urlopen_with_retry, is_empty

Environment Variables:
    GITHUB_TOKEN: GitHub personal access token for API authentication (optional but
                  recommended to increase rate limits from 60 to 5,000 requests/hour)
"""
import base64
import configparser
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from xml.sax.saxutils import escape

from lib.constants import NODE_LANGUAGES, OFTEN_GITHUB_MISTAKEN_LANGUAGES
from lib.utilities import extract_npmjs_maintainer_names, urlopen_with_retry


def github_request(url, allow_not_found=False, allow_conflict=False, _retry=0):
    """
    Make an authenticated request to the GitHub API with automatic rate limit handling.

    Sends a request to the GitHub API with appropriate headers including authentication
    if GITHUB_TOKEN is available in environment variables. Automatically handles both
    primary (hourly quota) and secondary (burst) rate limits with exponential backoff.
    Optionally suppresses 404 Not Found and 409 Conflict errors for cases where these
    are expected.

    Args:
        url (str): The GitHub API URL to request (must start with https://api.github.com/).
        allow_not_found (bool, optional): If True, return (None, None) for 404 errors
                                          instead of raising. Defaults to False.
        allow_conflict (bool, optional): If True, return (None, None) for 409 errors
                                         (e.g., empty repository) instead of raising.
                                         Defaults to False.
        _retry (int, optional): Internal parameter tracking retry count for rate limiting.
                               Do not set manually.

    Returns:
        tuple[bytes, str | None]: A tuple of (response_data, link_header) where
                                  response_data is the raw response bytes and
                                  link_header is the Link header value for pagination
                                  (or None if not present).

    Raises:
        urllib.error.HTTPError: For HTTP errors that are not suppressed by the
                                allow_not_found or allow_conflict flags. Provides
                                detailed error messages for rate limiting and permission errors.

    Note:
        Rate limit handling:
        - Primary rate limit (403 with X-RateLimit-Remaining: 0): Sleeps until X-RateLimit-Reset
        - Secondary rate limit (429 or 403 with Retry-After): Sleeps for Retry-After seconds
        - Maximum retry attempts: 10
        - Unauthenticated: 60 requests/hour, Authenticated: 5,000 requests/hour
    """
    _rate_limit_max_retry = 10
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

            if _retry >= _rate_limit_max_retry:
                print(f"Exceeded max retries ({_rate_limit_max_retry}) for rate limiting.", file=sys.stderr)
                raise

            if limit_type == "secondary":
                sleep_duration = int(retry_after) + 1 if retry_after else 60
                print(f"GitHub secondary rate limit ({error.code}). Sleeping {sleep_duration}s before retry {_retry + 1}/{_rate_limit_max_retry}...", file=sys.stderr)
            else:
                sleep_duration = max(int(reset_time) - int(time.time()), 0) + 1 if reset_time else 60
                print(f"GitHub primary rate limit. Remaining: {remaining}, Reset in {sleep_duration}s. Retry {_retry + 1}/{_rate_limit_max_retry}...", file=sys.stderr)

            time.sleep(sleep_duration)
            return github_request(url, allow_not_found, allow_conflict, _retry=_retry + 1)

        elif error.code == 404:
            print(f"File not found. (URL: {url})", file=sys.stderr)

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
        print(f"Fetching contributors: {next_url}")

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

    try:
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

    except Exception as e:
        print(f"Error fetching latest commit: {e}")
        return ""


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

    try:
        data, _ = github_request(releases_url, allow_not_found=True)
        if not data:
            return ""

        release = json.loads(data.decode("utf-8"))
        return release.get("published_at") or release.get("created_at", "")

    except Exception as e:
        print(f"Error fetching latest release: {e}")
        return ""


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

    try:
        data, link_header = github_request(pulls_url, allow_not_found=True)
        if not data:
            return ""

        last_page_match = re.search(r'[?&]page=(\d+)>; rel="last"', link_header or "")
        if last_page_match:
            return int(last_page_match.group(1))

        pulls = json.loads(data.decode("utf-8"))
        return len(pulls)

    except Exception as e:
        print(f"Error fetching open PR count: {e}")
        return 0


def fetch_repository_commit_count(repo):
    """
    Fetch the total number of commits in a repository's default branch.

    Uses the GitHub API pagination headers with per_page=1 to read the last-page
    number without downloading all commit data.

    Args:
        repo (dict): Repository object containing 'owner', 'name', and
                     'default_branch' fields.

    Returns:
        int | str: Total commit count, or empty string if the repository info is
                   incomplete, the repo is empty, or the request fails.
    """
    owner = repo.get("owner", {}).get("login")
    repo_name = repo.get("name")
    default_branch = repo.get("default_branch")

    if not owner or not repo_name:
        return ""

    params = {"per_page": 1, "sha": default_branch} if default_branch else {"per_page": 1}
    commits_url = (
        f"https://api.github.com/repos/"
        f"{urllib.parse.quote(owner, safe='')}/"
        f"{urllib.parse.quote(repo_name, safe='')}/commits?"
        f"{urllib.parse.urlencode(params)}"
    )

    print(f"Fetching commit count: {owner}/{repo_name}")

    try:
        data, link_header = github_request(commits_url, allow_not_found=True)
        if not data:
            return ""

        last_page_match = re.search(r'[?&]page=(\d+)>; rel="last"', link_header or "")
        if last_page_match:
            return int(last_page_match.group(1))

        commits = json.loads(data.decode("utf-8"))
        return len(commits)

    except Exception as e:
        print(f"Error fetching commit count for {owner}/{repo_name}: {e}")
        return ""


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
    try:
        return fetch_repository_json_file(repo, "package.json")

    except Exception:
        return None


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
    try:
        return fetch_repository_json_file(repo, "nx.json")

    except Exception:
        return None


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


def fetch_repository_submodules(repo):
    """
    Fetch and parse a repository's .gitmodules file.

    Args:
        repo (dict): GitHub repository metadata from the repositories API.

    Returns:
        list[str]: A list of submodule URLs. Returns an empty list when the
                   repository has no .gitmodules file or when the file cannot be parsed.
    """
    owner = repo.get("owner", {}).get("login")
    repo_name = repo.get("name")
    default_branch = repo.get("default_branch")

    if not owner or not repo_name:
        return []

    query_params = urllib.parse.urlencode({
        "ref": default_branch,
    }) if default_branch else ""

    url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/.gitmodules"
    if query_params:
        url = f"{url}?{query_params}"

    try:
        data, _ = github_request(url, allow_not_found=True)

        if not data:
            return []

    except urllib.error.HTTPError as error:
        if error.code == 404:
            return []
        print(f"Could not fetch .gitmodules for {owner}/{repo_name}: {error.code} {error.reason}")
        return []

    try:
        gitmodules_metadata = json.loads(data.decode("utf-8"))
        encoded_content = gitmodules_metadata.get("content", "")

        if not encoded_content:
            return []

        gitmodules_text = base64.b64decode(encoded_content).decode("utf-8")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
        print(f"Could not decode .gitmodules for {owner}/{repo_name}: {error}")
        return []

    parser = configparser.ConfigParser()

    try:
        parser.read_file(io.StringIO(gitmodules_text))
    except configparser.Error as error:
        print(f"Could not parse .gitmodules for {owner}/{repo_name}: {error}")
        return []

    submodules = []

    for section_name in parser.sections():
        if not section_name.startswith("submodule "):
            continue

        submodule_url = parser.get(section_name, "url", fallback="").strip()

        if submodule_url:
            submodules.append(submodule_url)

    return submodules


def fetch_repositories_for_org(org_name, org_names, start_count=0):
    """
    Fetch all repositories for a given GitHub organization.

    Args:
        org_name (str): The name of the GitHub organization to fetch repositories from.
        org_names (list[str]): All organization names, used for npm package ownership checks.
        start_count (int): Starting repository count for progress display. Defaults to 0.

    Returns:
        tuple[list, int]: A tuple of (repos, count) where repos is a list of repository
                          dictionaries and count is the total number fetched including start_count.
    """
    from lib.npm_utils import (
        fetch_npmjs_package_metadata,
        fetch_npmjs_is_deprecated,
        fetch_npmjs_last_published,
        fetch_npmjs_download_count,
        npm_repo_is_from_uw,
    )

    count = start_count
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
            count += 1
            time.sleep(1)

            repo_name = repo.get("name")
            print(f"{count} - Fetching repository: {repo_name}")

            repo["github_dependents"] = fetch_repository_dependents(repo)
            repo["github_contributors"] = fetch_repository_contributors(repo)
            repo["github_downloads"], repo["github_release_count"] = fetch_repository_github_downloads(repo)
            repo["last_commit_date"] = fetch_repository_last_commit_date(repo)
            repo["last_release_date"] = fetch_repository_last_release_date(repo)
            repo["open_prs_count"] = fetch_repository_open_prs_count(repo)
            repo["commit_count"] = fetch_repository_commit_count(repo)
            repo["git_submodules"] = fetch_repository_submodules(repo)
            package_json = None

            language = (repo.get("language") or "").lower()
            if not language in NODE_LANGUAGES:
                # check if github made a mistake on the language field
                if language in OFTEN_GITHUB_MISTAKEN_LANGUAGES:
                    package_json = fetch_package_json(repo)
                    if package_json: # if it has a package.json, it's probably a node repo'
                        print(f"For {repo_name} Language field is '{language}', but it's probably a node repo. Using package.json")
                        new_language = "Javascript"
                        language = new_language.lower()
                        repo["language"] = new_language

            if language in NODE_LANGUAGES:
                if not package_json:
                    package_json = fetch_package_json(repo)

                if package_json:
                    npm_package_name = package_json.get("name", "")
                    repo["npmjs_package_name"] = npm_package_name

                    if package_json.get("private") is not True:
                        npm_package_metadata = fetch_npmjs_package_metadata(npm_package_name)

                        maintainers = extract_npmjs_maintainer_names(npm_package_metadata)
                        if npm_repo_is_from_uw(npm_package_metadata, org_names, maintainers):
                            repo["npmjs_last_published"] = fetch_npmjs_last_published(npm_package_metadata)
                            repo["npmjs_downloads_last_year"] = fetch_npmjs_download_count(
                                npm_package_name,
                                "last-year",
                            )
                            repo["npm_is_deprecated"] = fetch_npmjs_is_deprecated(npm_package_metadata)
                            repo["npmjs_maintainers"] = maintainers

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

    return repos, count


def fetch_repositories(org_names):
    """
    Fetch all repositories across multiple GitHub organizations.

    Args:
        org_names (list[str]): Organization names to fetch, highest priority first.

    Returns:
        list: Combined list of repository dictionaries from all organizations.
    """
    repos = []
    count = 0
    for org_name in org_names:
        org_repos, count = fetch_repositories_for_org(org_name, org_names, count)
        repos.extend(org_repos)
    return repos


def write_ods(repos, output_file):
    """
    Write repository data to an ODS file with two sheets.

    Produces a Repositories sheet with all repos and a JavaScript TypeScript
    sheet filtered to JS/TS repos only.

    Args:
        repos (list): List of repository dictionaries.
        output_file (str): Path to the output ODS file.
    """
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
        "commit count",
        "git submodules",
        "npmjs package name",
        "npm is deprecated",
        "npmjs downloads last year",
        "npmjs last published",
        "npmjs maintainers",
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
                repo.get("commit_count", ""),
                ", ".join(repo.get("git_submodules", [])),
                repo.get("npmjs_package_name", ""),
                repo.get("npm_is_deprecated", ""),
                repo.get("npmjs_downloads_last_year", ""),
                repo.get("npmjs_last_published", ""),
                ", ".join(repo.get("npmjs_maintainers", [])),
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

    js_ts_repos = [
        repo
        for repo in repos
        if (repo.get("language") or "").lower() in NODE_LANGUAGES
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