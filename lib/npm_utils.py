"""npm registry utilities for package metadata, download statistics, and dependency tracking.

This module provides utilities for:
- Fetching package metadata from the npm registry
- Checking npm package ownership and deprecation status
- Retrieving download statistics
- Building and updating npm dependency relationships across repositories

Dependencies:
    - Standard library modules for HTTP requests, JSON, datetime operations
    - lib.utilities: urlopen_with_retry, fetch_repository_json_file, is_empty
"""
import datetime
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from lib.utilities import urlopen_with_retry, extract_npmjs_maintainer_names
from lib.github_utils import fetch_repository_json_file


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


def npm_repo_is_from_uw(package_metadata, ORG_NAMES, maintainer_names):
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

    uw_maintainers = ['neutrinog', 'jakobaleksandrovich', 'klappy', 'photo-nomad', 'richmahn', 'mandolyte', 'jag3773', 'mvahowe', 'larsgson', 'abelpz', 'eliaspinero', 'kintsoogii', 'macolon']

    org_names_extended = ORG_NAMES.copy()
    org_names_extended.append("translationCoreApps") # add old organizations

    homepage = package_metadata.get("homepage") or ""
    repository = package_metadata.get("repository") or {}

    if isinstance(repository, dict):
        repository_url = repository.get("url") or ""
    else:
        repository_url = str(repository) if repository else ""

    homepage = homepage.lower()
    repository_url = repository_url.lower()
    if not homepage and not repository_url:
        # check if the maintainers are unfolding word
        maintainer_names = [m.lower() for m in maintainer_names if isinstance(m, str)]
        is_uw_maintainer = any(uw_maintainer.lower() in maintainer_names for uw_maintainer in uw_maintainers)
        return is_uw_maintainer

    in_uw_org = any((org_name.lower() in homepage or org_name.lower() in repository_url) for org_name in org_names_extended)
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


def fetch_npmjs_org_modules(org_name):
    """
    Fetch all package names for an npm organization using the npm search API.

    Uses the npm search API to find all scoped packages (@org_name) with
    offset-based pagination until all results are retrieved.

    Args:
        org_name (str): npm organization name without the @ prefix (e.g., 'unfoldingword').

    Returns:
        dict: Dictionary containing the list of package names.
    """
    PACKAGES_THRESHOLD = 1000

    packages = {}
    size = 250
    threshold = size
    from_idx = 0
    org_name = org_name.strip().lstrip("@")
    package_prefix = f"@{org_name}/"

    while True:
        params = urllib.parse.urlencode({
            "text": package_prefix,
            "size": size,
            "from": from_idx,
        })
        url = f"https://registry.npmjs.org/-/v1/search?{params}"

        print(f"Fetching npm org packages (offset {from_idx}): {url}")

        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "unfoldingword-repo-list-script",
            },
        )

        try:
            with urlopen_with_retry(request) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            print(f"npm search API error: {error.code} {error.reason}", file=sys.stderr)
            break

        objects = data.get("objects", [])
        total = data.get("total", 0)
        threshold = total

        print(
            f"npm search returned {len(objects)} objects out of total {total} "
            f"for query {package_prefix!r}"
        )

        need_to_filter = total > PACKAGES_THRESHOLD
        if need_to_filter:
            threshold = PACKAGES_THRESHOLD
            print(f"This is a large number of results. Turning on filtering and limiting to {threshold}.")

        if not objects:
            break

        for obj in objects:
            pkg_name = obj.get("package", {}).get("name", "").strip()
            if pkg_name:
                if need_to_filter:
                    if not pkg_name.startswith(package_prefix):
                        continue # skip over packages that don't start with the prefix
                packages[pkg_name] = obj

        from_idx += len(objects)
        if from_idx >= threshold or len(objects) < size:
            break

    return packages
    

def get_repos_by_npmjs_package_name(repos):
    """
    Create a dictionary mapping npm package names to their repository data.

    Args:
        repos (list[dict]): List of repository data dictionaries

    Returns:
        dict: Dictionary mapping npm package names to repository objects
    """
    repos_by_npmjs_package_name = {}

    for repo in repos:
        npm_name = repo.get("npmjs_package_name")
        if npm_name:
            if npm_name not in repos_by_npmjs_package_name:
                repos_by_npmjs_package_name[npm_name] = repo
            else:
                previous_repo = repos_by_npmjs_package_name[npm_name]
                replace_repo = False

                if repo.get("owner", {}).get("login", "").lower() == "unfoldingword" \
                        and previous_repo.get("owner", {}).get("login", "").lower() != "unfoldingword":
                    print(f"Replacing {previous_repo['full_name']} with {repo['full_name']} because org ")
                    replace_repo = True

                if not repo.get("archived", False) and previous_repo.get("archived", False):
                    print(f"Replacing {previous_repo['full_name']} with {repo['full_name']} because archive status")
                    replace_repo = True

                print(
                    f"Error: npm package name {npm_name} already exists in the "
                    f"repository data dictionary. Please provide a different npm package name "
                    f"to prevent the overwriting of an existing npm package name."
                )
                print(f"previous repo: {previous_repo}")
                print(f"current repo: {repo}")

                if replace_repo:
                    repos_by_npmjs_package_name[npm_name] = repo
                    print(f"Replaced previous repo with current repo for npm package name: {npm_name}")

    return repos_by_npmjs_package_name


def update_repo_npmjs_dependency_relationships(repo, repos_by_npmjs_package_name):
    package_json = repo.get("package_json") or []
    current_package_name = repo.get("npmjs_package_name")

    if not package_json:
        return

    if not current_package_name:
        current_package_name = repo.get('name', '')

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


def update_npmjs_dependencies(repos, org_names):
    """
    Update npm package dependency relationships within the repositories.

    For each repository with a package.json file, analyzes its dependencies
    and peerDependencies to build bidirectional relationships between packages.
    Also handles monorepo subpackages.

    Args:
        repos (list): List of repository dictionaries.
        org_names (list[str]): Organization names used for npm package ownership checks.

    Returns:
        None. Modifies repository dictionaries in place.
    """
    repos_by_npmjs_package_name = get_repos_by_npmjs_package_name(repos)

    sub_modules = []

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

                        maintainers = extract_npmjs_maintainer_names(npm_package_metadata)
                        if npm_repo_is_from_uw(npm_package_metadata, org_names, maintainers):
                            sub_module["npmjs_last_published"] = fetch_npmjs_last_published(npm_package_metadata)
                            sub_module["npmjs_downloads_last_year"] = fetch_npmjs_download_count(
                                npm_package_name,
                                "last-year",
                            )
                            sub_module["npm_is_deprecated"] = fetch_npmjs_is_deprecated(npm_package_metadata)
                            sub_module["npmjs_maintainers"] = maintainers
                        else:
                            print(
                                f"npm_package_name: {npm_package_name}, Homepage: {npm_package_metadata.get('homepage', 'N/A') if npm_package_metadata else 'N/A'}")

                    sub_module["package_json"] = package_json
                    sub_modules.append(sub_module)

    repos.extend(sub_modules)

    for repo in repos:
        update_repo_npmjs_dependency_relationships(repo, repos_by_npmjs_package_name)
