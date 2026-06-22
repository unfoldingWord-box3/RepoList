"""
Repository Lifecycle Classification System

This module provides an automated classification system for GitHub repositories
and their associated npm packages. It evaluates repositories based on activity
metrics, usage patterns, and metadata to categorize them into lifecycle stages
and recommend appropriate actions (keep active, archive, deprecate, or review).

Main Workflow:
    1. Load repository data from an ODS spreadsheet
    2. Apply GitHub classification rules to determine repository status
    3. Apply npm-specific classification rules for published packages
    4. Sort results by classification priority
    5. Export categorized data to CSV and ODS formats

Classification Categories:
    GitHub Repositories:
        - Active: Recent commits within 12 months
        - Keep: Local usage, external dependents, or high downloads
        - Manual review: Core projects, high activity, or edge cases
        - Dead: Archived, deprecated, or long-inactive with no usage
        - Stale: Inactive but with some usage or open issues
        - No longer used: Candidates for archival/cleanup

    npm Packages:
        - Deprecated: Already marked as deprecated
        - Keep: Active usage or significant downloads
        - Deprecate candidate: No usage, archived, or stale
        - Manual review: Security-sensitive, build tools, or edge cases

Configuration Requirements:
    - ODS_FILE: Input spreadsheet filename
    - SHEET_NAME: Name of sheet containing repository data
    - CATEGORIZED_OUTPUT: Base filename for output files
    - SORT_ORDER: List defining classification priority order

Input Data Requirements:
    Repository data should include fields such as:
        - repo name, archived status, fork status
        - commit/release/edit dates
        - npm package information and usage metrics
        - GitHub metrics (downloads, releases, issues, PRs, contributors)
        - language and dependent information

Output Files:
    - categorized_repos.csv: CSV export of all categorized repositories
    - categorized_repos.ods: ODS spreadsheet with categorized repositories

Dependencies:
    - lib.utilities: Helper functions for data loading and export
    - pandas: Data manipulation (via utilities)
    - pyexcel-ods3: ODS file handling (via utilities)

Usage:
    python CatagorizeRepos.py
    - Note: Note that you have first to run `python GitHubRepositoryFetcher.py`
        to collect the repository data before catagorization.

Example:
    The script loads 'unfoldingword_repos.ods', applies classification rules
    to each repository, and exports results to 'categorized_repos.csv' and
    'categorized_repos.ods' with added classification columns.
"""
import sys

from lib.utilities import ( update_ods_sheet_data,
                           is_true, months_old, is_empty, as_int, contains_any, load_repository_data,
                           write_list_to_csv)

ODS_FILE = "unfoldingword_repos.ods"
TAGGED_ODS_FILE = "tagged_repos.ods"
SHEET_NAME = "Repositories"
CATEGORIZED_OUTPUT = "categorized_repos"

TAGGED_COLUMNS = ["Ask","Archive","Keep"]

SORT_ORDER = [
    "No longer used candidate",
    "Manual review",
    "Keep",
    "Dead - archived",
    "Protected private",
]


def determine_github_classification(row):
    """
    Classify a GitHub repository based on activity, usage, and metadata.
    
    Evaluates repository data against a prioritized set of classification rules
    to determine its lifecycle status and recommended action. The function checks
    for active development, usage patterns, staleness, and potential for cleanup.
    
    Args:
        row (dict): Repository data containing metadata fields such as:
            - repo name (str): Name of the repository
            - archived (bool/str): Whether repository is archived
            - npm is deprecated (bool/str): Whether npm package is deprecated
            - is fork (bool/str): Whether repository is a fork
            - last commit date (str): Date of last commit
            - last release date (str): Date of last release
            - last edit date (str): Date of last edit
            - npmjs last published (str): Date of last npm publish
            - npmjs used by (str): List of local consumers
            - github dependents (str): List of GitHub dependents
            - npmjs package name (str): Associated npm package name
            - language (str): Primary programming language
            - github downloads (int/str): Count of GitHub downloads
            - github release count (int/str): Number of releases
            - npmjs downloads last year (int/str): npm downloads in last year
            - open issues count (int/str): Number of open issues
            - open prs count (int/str): Number of open pull requests
            - github contributors (int/str): Number of contributors
    
    Returns:
        tuple[str, str]: A tuple containing:
            - classification (str): Category name (e.g., "Active", "Keep - locally used",
              "No longer used candidate", "Manual review", "Stale")
            - reason (str): Human-readable explanation for the classification decision
    
    Classification Priority:
        1. Active: Recent commits (within 12 months)
        2. Keep: Local usage, external dependents, or high downloads
        3. Manual review: Core projects, high activity, or significant history
        4. Dead: Archived, deprecated, or long-inactive with no usage
        5. Stale: Inactive but with some usage or open issues
        6. No longer used: Likely candidates for archival/cleanup
    """
    repo_name = row.get("repo name", "")
    archived = is_true(row.get("archived"))
    npm_deprecated = is_true(row.get("npm is deprecated"))
    is_fork = is_true(row.get("is fork"))

    last_commit_date = row.get("last commit date")
    last_commit_months = months_old(last_commit_date)
    last_commit_date_empty = is_empty(last_commit_date)
    last_release_months = months_old(row.get("last release date"))
    last_edit_months = months_old(row.get("last edit date"))
    npm_last_published_months = months_old(row.get("npmjs last published"))

    npm_used_by_empty = is_empty(row.get("npmjs used by"))
    github_dependents_empty = is_empty(row.get("github dependents"))
    npm_package_empty = is_empty(row.get("npmjs package name"))
    language_empty = is_empty(row.get("language"))

    github_downloads = as_int(row.get("github downloads"))
    github_release_count = as_int(row.get("github release count"))
    npm_downloads_last_year = as_int(row.get("npmjs downloads last year"))
    open_issues_count = as_int(row.get("open issues count"))
    open_prs_count = as_int(row.get("open prs count"))
    github_contributors = as_int(row.get("github contributors"))
    commit_count = as_int(row.get("commit count"))

    cleanup_terms = [
        "poc",
        "proof",
        "demo",
        "test",
        "sample",
        "example",
        "template",
        "old",
        "hackathon",
        "playground",
    ]
    replacement_terms = ["old", "legacy", "deprecated", "obsolete", "archive", "backup"]
    core_terms = [
        "gateway",
        "door43",
        "dcs",
        "translationcore",
        "tc-create",
        "obs-app",
        "bt-servant",
        "tx-job",
        "catalog",
        "content-validation",
        "scripture",
        "resource",
    ]

    has_local_use = not npm_used_by_empty
    has_github_dependents = not github_dependents_empty
    recently_active = last_commit_months is not None and last_commit_months <= 12

    # ClassificationRules.md Rule D1
    if archived:
        return "Dead - archived", "Repository is archived."

    # ClassificationRules.md Rule K0
    if last_commit_date_empty:
        return "Protected private", "Repository has no last commit date — likely a private or protected repository with restricted access."

    # ClassificationRules.md Rule K3 / K4
    if has_github_dependents or npm_downloads_last_year >= 1000:
        return "Keep", f"externally used - Repository has GitHub dependents or at least 1,000 npm downloads in the last year ({npm_downloads_last_year} downloads)."

    # ClassificationRules.md Rule M5
    if not is_empty(row.get("is submodule of")):
        return "Manual review", "Repository is used as a git submodule by another repository."

    # ClassificationRules.md Rule K1
    if recently_active:
        return "Keep", f"Active - Last commit was within the last 12 months ({last_commit_months} months ago)."

    # ClassificationRules.md Rule K2
    if has_local_use:
        return "Keep", "locally used - Repository is listed as used by an npm package."

    # ClassificationRules.md Rule K5
    if contains_any(repo_name, core_terms):
        return "Manual review", "Repository name contains a core project term."

    # ClassificationRules.md Rule D2
    if npm_deprecated and last_commit_months is not None and last_commit_months > 24:
        return "Dead - deprecated", f"Npm package is deprecated and the last commit is older than 24 months ({last_commit_months} months ago)."

    # ClassificationRules.md Rule M1
    if open_issues_count >= 50:
        return "Manual review", f"Repository has at least 50 open issues ({open_issues_count} open issues)."

    # ClassificationRules.md Rule M2
    if github_release_count >= 10 or github_downloads >= 100 or commit_count >= 100:
        return "Manual review", f"Repository has significant release history, GitHub downloads, or commit history ({github_release_count} releases, {github_downloads} downloads, {commit_count} commits)."

    # ClassificationRules.md Rule M3
    if github_contributors >= 5:
        return "Manual review", f"Repository has at least 5 GitHub contributors ({github_contributors} contributors)."

    # ClassificationRules.md Rule M4
    if (
        last_edit_months is not None
        and last_edit_months <= 12
        and last_commit_months is not None
        and last_commit_months > 36
    ):
        return "Manual review", f"Repository was edited recently ({last_edit_months} months ago) but has not had a commit in over 36 months ({last_commit_months} months ago)."

    # ClassificationRules.md Rule D3
    if (
        commit_count is not None
        and commit_count <= 5
        and last_commit_months is not None
        and last_commit_months > 36
        and npm_used_by_empty
        and github_dependents_empty
        and github_downloads == 0
        and github_release_count == 0
    ):
        return "No longer used candidate", f"Repository has very few commits ({commit_count}) and has had no activity in over 36 months ({last_commit_months} months ago) with no usage, downloads, or releases."

    # ClassificationRules.md Rule D4
    if (
        last_commit_months is not None
        and last_commit_months > 60
        and npm_used_by_empty
        and github_dependents_empty
        and github_downloads == 0
        and github_release_count == 0
        and (commit_count is None or commit_count < 50)
    ):
        return "No longer used candidate", f"Repository has had no commits in over 60 months ({last_commit_months} months ago) and has no usage, downloads ({github_downloads}), or releases ({github_release_count})."

    # ClassificationRules.md Rule D5
    if (
        is_fork
        and last_commit_months is not None
        and last_commit_months > 36
        and npm_used_by_empty
        and github_dependents_empty
        and github_downloads == 0
    ):
        return "No longer used candidate", f"Repository is an old fork with no detected usage or downloads ({github_downloads} downloads), and the last commit was over 36 months ago ({last_commit_months} months ago)."

    # ClassificationRules.md Rule D6
    if (
        contains_any(repo_name, cleanup_terms)
        and last_commit_months is not None
        and last_commit_months > 24
        and npm_used_by_empty
        and github_dependents_empty
    ):
        return "No longer used candidate", f"Repository name suggests cleanup/test/demo content, it has no detected usage, and the last commit was over 24 months ago ({last_commit_months} months ago)."

    # ClassificationRules.md Rule D7
    if (
        language_empty
        and github_release_count == 0
        and github_downloads == 0
        and npm_package_empty
        and last_commit_months is not None
        and last_commit_months > 36
    ):
        return "No longer used candidate", f"Repository has no language, releases ({github_release_count}), downloads ({github_downloads}), or npm package, and is older than 36 months ({last_commit_months} months since last commit)."

    # ClassificationRules.md Rule S3
    if (
        last_commit_months is not None
        and last_commit_months > 18
        and (
            not npm_used_by_empty
            or not github_dependents_empty
            or npm_downloads_last_year > 0
        )
    ):
        return "Manual review", f"Stale but used - Repository has had no commits in over 18 months ({last_commit_months} months ago) but still has detected usage ({npm_downloads_last_year} npm downloads in the last year)."

    # ClassificationRules.md Rule S2
    if (
        not npm_package_empty
        and npm_last_published_months is not None
        and npm_last_published_months > 18
        and not npm_deprecated
    ):
        return "Manual review", f"Stale package - Npm package has not been published in over 18 months ({npm_last_published_months} months ago) and is not marked deprecated."

    # ClassificationRules.md Rule S4
    if (
        last_commit_months is not None
        and last_commit_months > 12
        and (open_prs_count >= 5 or open_issues_count >= 20)
    ):
        return "Manual review", f"Stale/neglected - Repository has had no commits in over 12 months ({last_commit_months} months ago) and has many open PRs or issues ({open_prs_count} PRs, {open_issues_count} issues)."

    # ClassificationRules.md Rule S5
    if (
        last_commit_months is not None
        and last_commit_months <= 24
        and last_release_months is not None
        and last_release_months > 24
        and github_release_count > 0
    ):
        return "Manual review", f"Stale release process - Repository has recent commits ({last_commit_months} months ago) but no release in over 24 months ({last_release_months} months ago), with {github_release_count} releases."

    # ClassificationRules.md Rule S1
    if (
        last_commit_months is not None
        and last_commit_months > 18
    ):
        return "Manual review", f"Stale - Repository has had no commits in over 18 months ({last_commit_months} months ago) and is not archived."

    # ClassificationRules.md Rule N1
    if (
        contains_any(repo_name, replacement_terms)
        and last_commit_months is not None
        and last_commit_months > 18
    ):
        return "No longer used candidate", "Repository name suggests it may be old, legacy, deprecated, obsolete, archived, or a backup."

    # ClassificationRules.md Rule N2
    if (
        contains_any(repo_name, cleanup_terms)
        and last_commit_months is not None
        and last_commit_months > 18
    ):
        return "No longer used candidate", f"Repository name suggests cleanup/test/demo content and it has had no commits in over 18 months ({last_commit_months} months ago)."

    # ClassificationRules.md Rule N3
    if (
        is_fork
        and npm_used_by_empty
        and github_dependents_empty
        and (last_commit_months is None or last_commit_months > 18)
    ):
        return "No longer used candidate", "Repository is a fork with no detected npm or GitHub dependent usage."

    # ClassificationRules.md Rule N4
    if (
        not npm_package_empty
        and npm_used_by_empty
        and github_dependents_empty
        and npm_downloads_last_year == 0
        and (last_commit_months is None or last_commit_months > 18)
    ):
        return "No longer used candidate", f"Repository has an npm package but no detected usage or downloads in the last year ({npm_downloads_last_year} npm downloads)."

    return "Manual review", "Repository did not match any automatic classification rule."


def determine_npmjs_classification(row):
    """
    Classify an npm package's lifecycle status for potential deprecation.
    
    Evaluates published npm packages to determine if they should be kept active,
    deprecated, or require manual review based on usage patterns, publication
    history, and repository status.
    
    Args:
        row (dict): Repository data containing npm and repository metadata:
            - repo name (str): Name of the repository
            - npmjs package name (str): Name of the published npm package
            - npm is deprecated (bool/str): Whether package is marked deprecated
            - archived (bool/str): Whether backing repository is archived
            - npmjs used by (str): List of local package consumers
            - github dependents (str): List of GitHub dependents
            - npmjs downloads last year (int/str): Download count in last year
            - npmjs last published (str): Date of last publish to npm
    
    Returns:
        tuple[str, str]: A tuple containing:
            - classification (str): Category name (e.g., "Deprecated npm package",
              "Keep - npm package in use", "Deprecate npm package candidate",
              "Manual review - npm package")
            - reason (str): Human-readable explanation for the classification decision
    
    Classification Logic:
        - Skips repositories without published npm packages
        - Identifies already-deprecated packages
        - Flags security-sensitive or build-tool packages for manual review
        - Recommends keeping packages with active usage or downloads
        - Suggests deprecation for unused, stale, or archived packages
        - Requires manual review for edge cases and low-usage packages
    """
    repo_name = row.get("repo name", "")
    npm_package_name = row.get("npmjs package name", "")

    npm_package_empty = is_empty(npm_package_name)
    npm_deprecated = is_true(row.get("npm is deprecated"))
    archived = is_true(row.get("archived"))

    npm_used_by_empty = is_empty(row.get("npmjs used by"))
    github_dependents_empty = is_empty(row.get("github dependents"))

    npm_downloads_last_year = as_int(row.get("npmjs downloads last year"))
    npm_last_published_months = months_old(row.get("npmjs last published"))

    replacement_terms = ["old", "legacy", "deprecated", "obsolete", "archive", "backup"]
    sensitive_or_build_terms = [
        "auth",
        "login",
        "token",
        "crypto",
        "security",
        "deploy",
        "build",
        "cli",
        "config",
        "eslint",
        "babel",
        "webpack",
        "rollup",
    ]

    if npm_package_empty:
        return "Manual review", "No npmjs package is published for this repository."

    # ClassificationRules.md Rule P1
    if npm_deprecated:
        return "Deprecated npm package", "Npm package is already explicitly marked as deprecated."

    # ClassificationRules.md Rule P5
    if archived:
        return (
            "Deprecate npm package candidate",
            "Package is backed by an archived repository and is not marked deprecated on npmjs.",
        )

    # ClassificationRules.md Rule P8
    if contains_any(repo_name, sensitive_or_build_terms) or contains_any(npm_package_name, sensitive_or_build_terms):
        return (
            "Manual review - npm package",
            "Package or repository name suggests a security-sensitive, CLI, deployment, configuration, or build-tool package.",
        )

    # ClassificationRules.md Rule P6
    if (
        not npm_used_by_empty
        or not github_dependents_empty
        or npm_downloads_last_year >= 1000
    ):
        return (
            "Keep - npm package in use",
            f"Package has detected local usage, GitHub dependents, or significant npm downloads ({npm_downloads_last_year} downloads in the last year).",
        )

    # ClassificationRules.md Rule P2
    if (
        npm_used_by_empty
        and github_dependents_empty
        and npm_downloads_last_year == 0
    ):
        return (
            "Deprecate npm package candidate",
            "Published package has no detected local consumers, no GitHub dependents, and no npm download activity in the last year.",
        )

    # ClassificationRules.md Rule P3
    if (
        npm_last_published_months is not None
        and npm_last_published_months > 24
        and npm_downloads_last_year < 100
        and npm_used_by_empty
    ):
        return (
            "Deprecate npm package candidate",
            f"Package has not been published in over 24 months ({npm_last_published_months} months ago), has fewer than 100 downloads in the last year ({npm_downloads_last_year}), and has no detected local consumers.",
        )

    # ClassificationRules.md Rule P4
    if contains_any(repo_name, replacement_terms) or contains_any(npm_package_name, replacement_terms):
        return (
            "Deprecate npm package candidate",
            "Package or repository name suggests it may be old, legacy, deprecated, obsolete, archived, or a backup.",
        )

    # ClassificationRules.md Rule P7
    if (
        npm_downloads_last_year >= 1
        and npm_downloads_last_year < 1000
        and npm_used_by_empty
    ):
        return (
            "Manual review - npm package",
            f"Package has low but nonzero npm usage ({npm_downloads_last_year} downloads in the last year) and no detected local consumers.",
        )

    return (
        "Manual review - npm package",
        "Published npm package did not match any automatic npm lifecycle classification rule.",
    )


def is_github_repo(url):
    """
    Check if a URL is a GitHub repository URL.

    Args:
        url (str): URL to check

    Returns:
        bool: True if the URL is a GitHub repository URL, False otherwise
    """
    if is_empty(url):
        return False

    url = str(url).strip().lower()

    # Check for common GitHub URL patterns
    github_patterns = [
        "github.com/",
        "://github.com/",
        "git@github.com:",
    ]

    return any(pattern in url for pattern in github_patterns)


def split_github_repo(url):
    """
    Extract organization and repository name from a GitHub repository URL.

    Parses various GitHub URL formats (HTTPS, SSH, etc.) and extracts the
    organization/owner name and repository name components.

    Args:
        url (str): GitHub repository URL in formats such as:
            - https://github.com/organization/repo
            - https://github.com/organization/repo.git
            - git@github.com:organization/repo.git
            - github.com/organization/repo

    Returns:
        tuple[str, str]: A tuple containing:
            - organization (str): Organization or owner name
            - repo_name (str): Repository name (without .git suffix)
        Returns (None, None) if URL cannot be parsed

    Examples:
        >>> split_github_repo("https://github.com/unfoldingWord/door43-catalog")
        ('unfoldingWord', 'door43-catalog')
        >>> split_github_repo("git@github.com:unfoldingWord/door43-catalog.git")
        ('unfoldingWord', 'door43-catalog')
    """
    if is_empty(url):
        return None, None

    url = str(url).strip()

    # Remove common prefixes
    url = url.replace("https://", "").replace("http://", "").replace("git@", "")

    # Remove github.com/ or github.com:
    if url.startswith("github.com/"):
        url = url[len("github.com/"):]
    elif url.startswith("github.com:"):
        url = url[len("github.com:"):]

    # Remove .git suffix if present
    if url.endswith(".git"):
        url = url[:-4]

    # Split by / to get organization and repo
    parts = url.split("/")

    if len(parts) >= 2:
        organization = parts[0]
        repo_name = parts[1]
        return organization, repo_name

    return None, None


def npm_update_nested_used_by_sub(repos, repos_by_npmjs_package_name):
    """
    Perform one iteration of transitive npm dependency propagation.
    
    Scans all repositories and propagates transitive dependencies through the
    dependency graph. When package A is used by package B, and package B uses
    package C, this function adds package C to package A's "npmjs uses" list.
    
    This is a helper function called iteratively by npm_update_nested_used_by()
    until no new dependency relationships are discovered.
    
    Args:
        repos (list[dict]): List of repository data dictionaries containing:
            - npmjs used by (str|list): Comma-separated string or list of packages
              that depend on this package
            - npmjs uses (str|list): Comma-separated string or list of packages
              that this package depends on
        repos_by_npmjs_package_name (dict): Dictionary mapping npm package names
            to their repository data objects for efficient lookup
    
    Returns:
        bool: True if any dependency relationships were added during this iteration,
            False if no changes were made (indicating convergence)
    
    Side Effects:
        Modifies the "npmjs uses" field in repository dictionaries to include
        newly discovered transitive dependencies. Prints diagnostic messages when
        updating dependency lists.
    
    Implementation Details:
        1. Iterates through all repositories
        2. For each repository with consumers (npmjs used by):
           - Gets its own dependencies (npmjs uses)
           - For each consumer package:
             - Looks up the consumer's repository data
             - Adds this repository's dependencies to the consumer's dependencies
             - Marks change if any new dependencies were added
        3. Returns whether any changes occurred
    
    Example:
        If repository A uses [B], and C is used by [A]:
            - C's dependencies will be added to A's "npmjs uses" list
            - If C uses [D], then A's "npmjs uses" becomes [B, D]
    """
    changed = False
    for repo in repos:
        npmjs_used_by = repo.get("npmjs used by")
        if npmjs_used_by:
            npmjs_used_by = [module.strip() for module in npmjs_used_by.split(',')] \
                if isinstance(npmjs_used_by, str) else npmjs_used_by

            npmjs_uses = repo.get("npmjs uses")
            if npmjs_uses:
                npmjs_uses = [module.strip() for module in npmjs_uses.split(',')] \
                    if isinstance(npmjs_uses, str) else npmjs_uses

                for module_name in npmjs_used_by:
                    if module_name in repos_by_npmjs_package_name:
                        module = repos_by_npmjs_package_name[module_name]
                        using_module_npmjs_uses = module.get("npmjs uses")
                        if using_module_npmjs_uses:
                            module_changed = False
                            using_module_npmjs_uses = [module.strip() for module in using_module_npmjs_uses.split(',')] \
                                if isinstance(using_module_npmjs_uses, str) else using_module_npmjs_uses

                            for dependent_module in npmjs_uses:
                                if dependent_module not in using_module_npmjs_uses:
                                    print(
                                        f"updating {module_name} to include {dependent_module}, and used {using_module_npmjs_uses}")
                                    using_module_npmjs_uses.append(dependent_module)
                                    module_changed = True

                            if module_changed:
                                changed = module_changed
                                module["npmjs uses"] = using_module_npmjs_uses

    return changed
def get_repos_by_npmjs_package_name(data_rows):
    """
    Create a dictionary mapping npm package names to their repository data.

    Args:
        data_rows (list[dict]): List of repository data dictionaries
    
    Returns:
        dict: Dictionary mapping npm package names to repository objects
    """
    repos_by_npmjs_package_name = {}

    for repo in data_rows:
        npm_name = repo.get("repo name")
        if npm_name:
            if npm_name not in repos_by_npmjs_package_name:
                repos_by_npmjs_package_name[npm_name] = repo
            else:
                previous_repo = repos_by_npmjs_package_name[npm_name]
                replace_repo = False

                repo_org = repo.get("organization name", "")
                previous_repo_org = previous_repo.get("organization name", "")
                if repo_org.lower() == "unfoldingword" \
                        and previous_repo_org.lower() != "unfoldingword":
                    print(f"Replacing {previous_repo['full_name']} with {repo['full_name']} because org is {repo_org} is unfoldingword")
                    replace_repo = True

                if not is_true(repo.get("archived")) and is_true(previous_repo.get("archived")):
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


def npm_update_nested_used_by(data_rows):
    """
    Propagate nested npm dependency relationships through the repository graph.
    
    Iteratively updates npm package dependency information to include transitive
    dependencies. When package A is used by package B, and package B uses package C,
    this function ensures that package A's "npmjs uses" field also includes package C.
    
    This is an iterative process that continues until no new dependency relationships
    are discovered (fixed-point iteration).
    
    Args:
        data_rows (list[dict]): List of repository data dictionaries containing:
            - npmjs package name (str): Name of the npm package
            - npmjs used by (str|list): Comma-separated string or list of packages
              that depend on this package
            - npmjs uses (str|list): Comma-separated string or list of packages
              that this package depends on
    
    Side Effects:
        Modifies the "npmjs uses" field in repository dictionaries to include
        transitive dependencies discovered through the dependency graph.
    
    Implementation Details:
        1. Creates a lookup dictionary mapping npm package names to repositories
        2. Iteratively scans all packages for new transitive dependencies
        3. For each package that is used by others, propagates its dependencies
           to those dependent packages
        4. Continues iteration until convergence (no new relationships found)
        5. Prints diagnostic information when updating dependency lists
    
    Example:
        If the dependency graph is:
            - Package A uses Package B
            - Package C is used by Package A
            - Package C uses Package D
        
        After running this function:
            - Package A's "npmjs uses" will include both B and D
            - This reflects that A transitively depends on D through C
    """
    changed = True

    repos_by_npmjs_package_name = get_repos_by_npmjs_package_name(data_rows)

    while changed:
        changed = npm_update_nested_used_by_sub(data_rows, repos_by_npmjs_package_name)

        
def add_submodule_relationships(data_rows):
    """
    Populate each repository row's 'is submodule of' field based on git submodule URLs.
    """
    for row in data_rows:
        git_submodules = row.get("git submodules")
        if not is_empty(git_submodules):
            print(f"found submodules in: {row.get('repo name')}")
            for submodule_url in git_submodules:
                if is_github_repo(submodule_url):
                    organization, repo_name = split_github_repo(submodule_url)

                    for data_row in data_rows:
                        if data_row.get("repo name") == repo_name and data_row.get("organization name") == organization:
                            print(f"found submodule: {submodule_url} in {data_row.get('repo name')}")
                            submodule_name = organization + "/" + repo_name
                            is_submodule_of = data_row.get("is submodule of")
                            if not is_submodule_of:
                                is_submodule_of = submodule_name
                            else:
                                is_submodule_of = is_submodule_of + "," + submodule_name
                            data_row["is submodule of"] = is_submodule_of

                            break

    for row in data_rows:
        if "is submodule of" not in row:
            row["is submodule of"] = ""


def main():
    """
    Main entry point for repository categorization workflow.

    Loads repository data from an ODS spreadsheet, applies GitHub and npm
    classification rules to each repository, sorts results by classification
    priority, and exports the categorized data to both CSV and ODS formats.
    
    Process:
        1. Load repository data from ODS file
        2. Add classification columns if not present
        3. Apply GitHub classification rules to each repository
        4. Apply npm classification rules to repositories with npm packages
        5. Sort results by classification priority and repository name
        6. Print summary of classifications found
        7. Export results to CSV and ODS files
    
    Output Files:
        - categorized_repos.csv: CSV export of all categorized repositories
        - categorized_repos.ods: ODS spreadsheet with categorized repositories
    
    Global Dependencies:
        - ODS_FILE: Input spreadsheet filename
        - SHEET_NAME: Name of sheet containing repository data
        - CATEGORIZED_OUTPUT: Base filename for output files
        - SORT_ORDER: List defining classification priority order
    """
    headers, data_rows = load_repository_data(ODS_FILE, SHEET_NAME)
    tagged_headers, tagged_data_rows = load_repository_data(TAGGED_ODS_FILE, SHEET_NAME)

    headers = TAGGED_COLUMNS + headers
    data_rows = [
        {**{column: "" for column in TAGGED_COLUMNS}, **row}
        for row in data_rows
    ]

    if "is submodule of" not in headers:
        headers.insert(headers.index("git submodules"), "is submodule of")

    if "repo full name" not in headers:
        headers.insert(headers.index("Keep") + 1, "repo full name")

    if "repo url" in headers:
        headers.remove("repo url")
    headers.insert(headers.index("repo full name") + 1, "repo url")

    if "classification" not in headers:
        headers.append("classification")

    if "classification reason" not in headers:
        headers.append("classification reason")

    if "npmjs classification" not in headers:
        headers.append("npmjs classification")

    if "npmjs classification reason" not in headers:
        headers.append("npmjs classification reason")

    for col in ("github contributors", "github dependents"):
        if col in headers:
            headers.remove(col)
        headers.insert(headers.index("last release date") + 1, col)

    for col in ("github downloads", "github release count"):
        if col in headers:
            headers.remove(col)
        headers.insert(headers.index("npmjs package name"), col)

    for col in ("repo name", "organization name"):
        if col in headers:
            headers.remove(col)
        headers.append(col)

    add_submodule_relationships(data_rows)
    npm_update_nested_used_by(data_rows)

    for row in data_rows:
        print(row)
        classification, classification_reason = determine_github_classification(row)
        repo_name = row.get("repo name")
        organization = row.get("organization name")
        repo_full_name = organization + "/" + repo_name

        if is_empty(row.get("npmjs package name")):
            npmjs_classification = ""
            npmjs_classification_reason = ""
        else:
            npmjs_classification, npmjs_classification_reason = determine_npmjs_classification(row)

        row["repo full name"] = repo_full_name
        row["classification"] = classification
        row["classification reason"] = classification_reason
        row["npmjs classification"] = npmjs_classification
        row["npmjs classification reason"] = npmjs_classification_reason

    # data_rows = [
    #     row for row in data_rows
    #     if row["classification"] != "Dead - archived"
    # ]

    sort_rank = {classification: index for index, classification in enumerate(SORT_ORDER)}
    data_rows.sort(
        key=lambda row: (
            sort_rank.get(row["classification"], len(SORT_ORDER)),
            str(row.get("repo name", "")).lower(),
        )
    )

    tagged_rows_by_repo_full_name = {}

    for tagged_row in tagged_data_rows:
        has_tagged_data = any(
            not is_empty(tagged_row.get(column))
            for column in TAGGED_COLUMNS
        )

        if not has_tagged_data:
            continue

        tagged_repo_full_name = tagged_row.get("repo full name")

        if is_empty(tagged_repo_full_name):
            tagged_repo_name = tagged_row.get("repo name")
            tagged_organization = tagged_row.get("organization name")

            if is_empty(tagged_repo_name) or is_empty(tagged_organization):
                continue

            tagged_repo_full_name = f"{tagged_organization}/{tagged_repo_name}"

        tagged_rows_by_repo_full_name[str(tagged_repo_full_name).strip()] = tagged_row

    for row in data_rows:
        tagged_row = tagged_rows_by_repo_full_name.get(
            str(row.get("repo full name", "")).strip()
        )

        if tagged_row is None:
            continue

        for column in TAGGED_COLUMNS:
            row[column] = tagged_row.get(column, "")

    print("Updated tagged columns in data rows")

    for row in data_rows:
        classification = row["classification"]
        if classification in SORT_ORDER:
            sort_rank = SORT_ORDER.index(classification)
            row["classification"] = str(sort_rank) + "-" + classification

    classifications = sorted({row["classification"] for row in data_rows})

    print("Classifications found:")
    for classification in classifications:
        print(f"- {classification}")

    ordered_rows = [{col: row.get(col, "") for col in headers} for row in data_rows]
    write_list_to_csv(CATEGORIZED_OUTPUT + ".csv", headers, data_rows)
    update_ods_sheet_data(CATEGORIZED_OUTPUT + ".ods", "Repositories", ordered_rows)


if __name__ == "__main__":
    main()
