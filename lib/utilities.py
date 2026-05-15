import base64
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

def safe_filename(name):
    """
    Convert a sheet name into a safe filename.
    """
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = name.strip()
    return name or "sheet"


def urlopen_with_retry(request, retries=1, retry_delay_seconds=5):
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(request)
        except urllib.error.HTTPError as error:
            if error.code == 429 and attempt < retries:
                print(
                    f"Received 429 Too Many Requests. Retrying in {retry_delay_seconds} second...",
                    file=sys.stderr,
                )
                time.sleep(retry_delay_seconds)
                continue

            raise


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
        with urlopen_with_retry(request) as response:
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
                print(f"GitHub API returned 403 Forbidden. (URL: {url})", file=sys.stderr)

        elif error.code == 404:
            print(f"Organization not found. (URL: {url})", file=sys.stderr)

        else:
            print(f"GitHub API error: {error.code} {error.reason} (URL: {url})", file=sys.stderr)

        raise


def github_html_request(url, allow_not_found=False):
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

    data, _ = github_request(commits_url, allow_not_found=True)
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
    encoded_content = fetch_repository_file(repo, file_path)

    if encoded_content:
        decoded_content = base64.b64decode(encoded_content).decode("utf-8")
        return json.loads(decoded_content)

    return None


def fetch_package_json(repo):
    package_json = fetch_repository_json_file(repo, "package.json")
    return package_json


def fetch_package_json_files(repo):
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
    return fetch_repository_json_file(repo, "nx.json")


def fetch_npmjs_package_metadata(package_name):
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


def npm_repo_is_from_uw(package_metadata, ORG_NAME):
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

    in_uw_org = any(org_name.lower() in homepage or org_name.lower() in repository_url for org_name in ORG_NAME)
    return in_uw_org


def fetch_npmjs_last_published(package_metadata):
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

