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
    - REPOS_SHEET_NAME: Name of sheet containing repository data
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
    - sheets/categorized_repos.csv: CSV export of all categorized repositories
    - sheets/categorized_repos.ods: ODS spreadsheet with categorized repositories

Dependencies:
    - lib.utilities: Helper functions for data loading and export
    - pandas: Data manipulation (via utilities)
    - pyexcel-ods3: ODS file handling (via utilities)

Usage:
    python CatagorizeRepos.py
    - Note: Note that you have first to run `python GitHubRepositoryFetcher.py`
        to collect the repository data before catagorization.

Example:
    The script loads 'sheets/unfoldingword_repos.ods', applies classification rules
    to each repository, and exports results to 'sheets/categorized_repos.csv' and
    'sheets/categorized_repos.ods' with added classification columns.
"""
import csv

from lib.constants import REPO_ODS_FILE, TAGGED_ODS_FILE, CATEGORIZED_OUTPUT, REPOS_SHEET_NAME, NPM_SHEET_NAME, \
    NPM_ORG_NAMES, NETLIFY_SHEET_NAME, NETLIFY_PREFIX_COLUMNS

from lib.utilities import ( update_ods_sheet_data,
                           is_true, months_old, is_empty, as_int, contains_any, load_repository_data,
                           write_list_to_csv)


TAGGED_COLUMNS = ["Ask","Archive","Keep", "Notes"]
TAGGED_NPM_COLUMNS = ["Ask-NPM","Deprecate-NPM","Keep-NPM", "Notes-NPM"]
ALL_TAGGED_COLUMNS = TAGGED_COLUMNS + TAGGED_NPM_COLUMNS

NPM_COLUMN_ORDER = ["Ask-NPM", "Deprecate-NPM", "Keep-NPM", "Notes-NPM", "npmjs package name", "npmjs url", "npm organization", "npmjs maintainers", "npm is deprecated", "npmjs downloads last year", "npmjs last published", "npmjs used by", "npmjs uses", "npmjs classification", "npmjs classification reason", "last edit date", "archived"]

SORT_ORDER = [
    "Archive/Delete candidate",
    "Manual review",
    "Keep",
    "Nothing to do",
    "Protected private",
]
NPM_SORT_ORDER = [
    "Deprecate npm package candidate",
    "Repair npm package",
    "Manual review",
    "Nothing to do",
]

NETLIFY_SORT_ORDER = [
    "Remove Project",
    "Disable Auto Builds",
    "Manual Review",
    "Keep Auto Builds",
]


def determine_github_classification(row):
    """
    Classify a GitHub repository's lifecycle status for archival consideration.
    
    Evaluates repository activity, usage patterns, and metadata to determine if a
    repository should be kept active, archived, or requires manual review based on
    commit history, external dependencies, and usage metrics.
    
    Args:
        row (dict): Repository data containing GitHub and npm metadata:
            - repo name (str): Name of the repository
            - archived (bool/str): Whether repository is archived
            - npm is deprecated (bool/str): Whether npm package is deprecated
            - is fork (bool/str): Whether repository is a fork
            - last commit date (str): Date of last commit
            - last release date (str): Date of last release
            - last edit date (str): Date of last repository edit
            - npmjs last published (str): Date npm package was last published
            - npmjs used by (str): List of npm package consumers
            - github dependents (str): List of GitHub dependents
            - npmjs package name (str): Name of published npm package
            - language (str): Primary programming language
            - github downloads (int/str): Number of GitHub release downloads
            - github release count (int/str): Number of GitHub releases
            - npmjs downloads last year (int/str): npm downloads in last year
            - open issues count (int/str): Number of open issues
            - open prs count (int/str): Number of open pull requests
            - github contributors (int/str): Number of contributors
            - commit count (int/str): Total number of commits
            - is submodule of (str): List of parent repositories using this as submodule
    
    Returns:
        tuple[str, str]: A tuple containing:
            - classification (str): Category name (e.g., "Keep", "Manual review",
              "Archive/Delete candidate", "Nothing to do", "Protected private")
            - reason (str): Human-readable explanation for the classification decision
    
    Classification Logic:
        The function applies a hierarchical set of rules (documented in
        ClassificationRules.md) to determine repository status:
        
        - Nothing to do (N1-N2): Already archived or deprecated
        - Protected private (P1): Private/protected repositories
        - Keep (K1-K3): Active usage, recent commits, or external dependencies
        - Manual review (M1-M13): Edge cases, core projects, or unclear status
        - Archive/Delete candidate (A1-A8): Low activity, no usage, or cleanup targets
    
    Implementation Details:
        1. Extracts and processes repository metadata
        2. Calculates time-based metrics (months since last activity)
        3. Evaluates against keyword lists (cleanup terms, core terms, etc.)
        4. Applies rules in priority order from high-priority keeps to archive candidates
        5. Returns first matching classification with detailed reasoning
    
    Example Classifications:
        - Keep: Repository with 5000 npm downloads in last year
        - Manual review: Core project with no commits in 20 months
        - Archive/Delete candidate: Test repository with no commits in 30 months
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

    # ClassificationRules.md Rule N1
    if archived:
        return "Nothing to do", "Repository is archived."

    # ClassificationRules.md Rule P1
    if last_commit_date_empty:
        return "Protected private", "Repository has no last commit date — likely a private or protected repository with restricted access."

    # ClassificationRules.md Rule K1
    if has_github_dependents or npm_downloads_last_year >= 1000:
        return "Keep", f"externally used - Repository has GitHub dependents or at least 1,000 npm downloads in the last year ({npm_downloads_last_year} downloads)."

    # ClassificationRules.md Rule M1
    if not is_empty(row.get("is submodule of")):
        return "Manual review", "Repository is used as a git submodule by another repository."

    # ClassificationRules.md Rule K2
    if recently_active:
        return "Keep", f"Active - Last commit was within the last 12 months ({last_commit_months} months ago)."

    # ClassificationRules.md Rule K3
    if has_local_use:
        return "Keep", "locally used - Repository is listed as used by an npm package."

    # ClassificationRules.md Rule M2
    if contains_any(repo_name, core_terms):
        return "Manual review", "Repository name contains a core project term."

    # ClassificationRules.md Rule N2
    if npm_deprecated and last_commit_months is not None and last_commit_months > 24:
        return "Nothing to do", f"Npm package is deprecated and the last commit is older than 24 months ({last_commit_months} months ago)."

    # ClassificationRules.md Rule M3
    if open_issues_count >= 50:
        return "Manual review", f"Repository has at least 50 open issues ({open_issues_count} open issues)."

    # ClassificationRules.md Rule M4
    if github_release_count >= 10 or github_downloads >= 100 or commit_count >= 100:
        return "Manual review", f"Repository has significant release history, GitHub downloads, or commit history ({github_release_count} releases, {github_downloads} downloads, {commit_count} commits)."

    # ClassificationRules.md Rule M5
    if github_contributors >= 5:
        return "Manual review", f"Repository has at least 5 GitHub contributors ({github_contributors} contributors)."

    # ClassificationRules.md Rule M6
    if (
        last_edit_months is not None
        and last_edit_months <= 12
        and last_commit_months is not None
        and last_commit_months > 36
    ):
        return "Manual review", f"Repository was edited recently ({last_edit_months} months ago) but has not had a commit in over 36 months ({last_commit_months} months ago)."

    # ClassificationRules.md Rule A1
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
        return "Archive/Delete candidate", f"Repository has very few commits ({commit_count}) and has had no activity in over 36 months ({last_commit_months} months ago) with no usage, downloads, or releases."

    # ClassificationRules.md Rule A2
    if (
        last_commit_months is not None
        and last_commit_months > 60
        and npm_used_by_empty
        and github_dependents_empty
        and github_downloads == 0
        and github_release_count == 0
        and (commit_count is None or commit_count < 50)
    ):
        return "Archive/Delete candidate", f"Repository has had no commits in over 60 months ({last_commit_months} months ago) and has no usage, downloads ({github_downloads}), or releases ({github_release_count})."

    # ClassificationRules.md Rule A3
    if (
        is_fork
        and last_commit_months is not None
        and last_commit_months > 36
        and npm_used_by_empty
        and github_dependents_empty
        and github_downloads == 0
    ):
        return "Archive/Delete candidate", f"Repository is an old fork with no detected usage or downloads ({github_downloads} downloads), and the last commit was over 36 months ago ({last_commit_months} months ago)."

    # ClassificationRules.md Rule A4
    if (
        contains_any(repo_name, cleanup_terms)
        and last_commit_months is not None
        and last_commit_months > 24
        and npm_used_by_empty
        and github_dependents_empty
    ):
        return "Archive/Delete candidate", f"Repository name suggests cleanup/test/demo content, it has no detected usage, and the last commit was over 24 months ago ({last_commit_months} months ago)."

    # ClassificationRules.md Rule A5
    if (
        language_empty
        and github_release_count == 0
        and github_downloads == 0
        and npm_package_empty
        and last_commit_months is not None
        and last_commit_months > 36
    ):
        return "Archive/Delete candidate", f"Repository has no language, releases ({github_release_count}), downloads ({github_downloads}), or npm package, and is older than 36 months ({last_commit_months} months since last commit)."

    # ClassificationRules.md Rule M7
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

    # ClassificationRules.md Rule M8
    if (
        not npm_package_empty
        and npm_last_published_months is not None
        and npm_last_published_months > 18
        and not npm_deprecated
    ):
        return "Manual review", f"Stale package - Npm package has not been published in over 18 months ({npm_last_published_months} months ago) and is not marked deprecated."

    # ClassificationRules.md Rule M9
    if (
        last_commit_months is not None
        and last_commit_months > 12
        and (open_prs_count >= 5 or open_issues_count >= 20)
    ):
        return "Manual review", f"Stale/neglected - Repository has had no commits in over 12 months ({last_commit_months} months ago) and has many open PRs or issues ({open_prs_count} PRs, {open_issues_count} issues)."

    # ClassificationRules.md Rule M10
    if (
        last_commit_months is not None
        and last_commit_months <= 24
        and last_release_months is not None
        and last_release_months > 24
        and github_release_count > 0
    ):
        return "Manual review", f"Stale release process - Repository has recent commits ({last_commit_months} months ago) but no release in over 24 months ({last_release_months} months ago), with {github_release_count} releases."

    # ClassificationRules.md Rule M11
    if (
        last_commit_months is not None
        and last_commit_months > 18
    ):
        return "Manual review", f"Stale - Repository has had no commits in over 18 months ({last_commit_months} months ago) and is not archived."

    # ClassificationRules.md Rule A6
    if (
        contains_any(repo_name, replacement_terms)
        and last_commit_months is not None
        and last_commit_months > 18
    ):
        return "Archive/Delete candidate", "Repository name suggests it may be old, legacy, deprecated, obsolete, archived, or a backup."

    # ClassificationRules.md Rule A7
    if (
        contains_any(repo_name, cleanup_terms)
        and last_commit_months is not None
        and last_commit_months > 18
    ):
        return "Archive/Delete candidate", f"Repository name suggests cleanup/test/demo content and it has had no commits in over 18 months ({last_commit_months} months ago)."

    # ClassificationRules.md Rule A8
    if (
        is_fork
        and npm_used_by_empty
        and github_dependents_empty
        and (last_commit_months is None or last_commit_months > 18)
    ):
        return "Archive/Delete candidate", "Repository is a fork with no detected npm or GitHub dependent usage."

    # ClassificationRules.md Rule M12
    if (
        not npm_package_empty
        and npm_used_by_empty
        and github_dependents_empty
        and npm_downloads_last_year == 0
        and (last_commit_months is None or last_commit_months > 18)
    ):
        return "Archive/Delete candidate", f"Repository has an npm package but no detected usage or downloads in the last year ({npm_downloads_last_year} npm downloads)."

    # ClassificationRules.md Rule M13 - Default Rule
    return "Manual review", "Repository did not match any automatic classification rule."


def determine_npmjs_classification(row):
    """
    Classify an npm package's lifecycle status for deprecation consideration.
    
    Evaluates npm package activity, usage patterns, and metadata to determine if a
    package should be kept active, deprecated, or requires manual review based on
    publication history, download metrics, and organizational ownership.
    
    Args:
        row (dict): Repository data containing npm package metadata:
            - repo name (str): Name of the repository
            - npmjs package name (str): Name of the published npm package
            - npm is deprecated (bool/str): Whether npm package is deprecated
            - archived (bool/str): Whether repository is archived
            - npmjs used by (str): List of npm package consumers
            - github dependents (str): List of GitHub dependents
            - npmjs downloads last year (int/str): npm downloads in last year
            - npmjs last published (str): Date npm package was last published
            - npm organization (str): npm organization that owns the package
            - npmjs broken (str): Description of package issues if broken
    
    Returns:
        tuple[str, str]: A tuple containing:
            - classification (str): Category name (e.g., "Keep - npm package in use",
              "Deprecate npm package candidate", "Manual review - npm package",
              "Nothing to do", "Repair npm package")
            - reason (str): Human-readable explanation for the classification decision
    
    Classification Logic:
        The function applies a hierarchical set of rules (documented in
        ClassificationRules.md) to determine npm package status:
        
        - Manual review (NM1): No npm package published
        - Nothing to do (NN1-NN4): Already deprecated, not published, or not our org
        - Deprecate candidate (ND1-ND4): Archived repo, no usage, stale, or legacy naming
        - Repair npm package (NR1): Package is broken on npmjs
        - Manual review (NM2-NM3): Security-sensitive packages or low usage
        - Keep (NK1): Active usage or significant downloads
    
    Implementation Details:
        1. Extracts and processes npm package metadata
        2. Calculates time-based metrics (months since last publish)
        3. Evaluates against keyword lists (replacement terms, sensitive terms, etc.)
        4. Applies rules in priority order from nothing to do to deprecate candidates
        5. Returns first matching classification with detailed reasoning
    
    Example Classifications:
        - Keep: Package with 5000 npm downloads in last year
        - Deprecate candidate: Published package with no usage and 0 downloads
        - Manual review: Security-sensitive package (contains "auth" in name)
        - Nothing to do: Package already marked deprecated on npmjs
    """
    repo_name = row.get("repo name", "")
    npm_package_name = row.get("npmjs package name", "")

    npm_package_empty = is_empty(npm_package_name)
    npm_deprecated = is_true(row.get("npm is deprecated"))
    archived = is_true(row.get("archived"))

    npm_used_by_empty = is_empty(row.get("npmjs used by"))
    github_dependents_empty = is_empty(row.get("github dependents"))

    npm_downloads_last_year = as_int(row.get("npmjs downloads last year"))
    npm_last_published_date = row.get("npmjs last published")
    npm_last_published_months = months_old(npm_last_published_date)
    npm_organization = row.get("npm organization")
    is_our_org = npm_organization in NPM_ORG_NAMES
    npmjs_broken = row.get("npmjs broken")

    replacement_terms = ["old", "legacy", "deprecated", "obsolete", "archive", "backup"]
    sensitive_or_build_terms = [
        "auth",
        "login",
        "crypto",
        "security",
        "deploy",
        "build",
        "config",
        "eslint",
        "babel",
        "webpack",
        "rollup",
    ]

    # ClassificationRules.md Rule NM1
    if npm_package_empty:
        return "Manual review", "No npmjs package is published for this repository."

    # ClassificationRules.md Rule NN1
    if npm_deprecated:
        return "Nothing to do", "Npm package is already explicitly marked as deprecated."

    # ClassificationRules.md Rule NN2
    if not npm_last_published_date:
        return (
            "Nothing to do",
            f"Not Published so nothing to do.",
        )

    # ClassificationRules.md Rule NN3
    if not is_our_org:
        return (
            "Nothing to do",
            f"Not our org so nothing to do.",
        )

    # ClassificationRules.md Rule ND1
    if (
        archived
        and npm_last_published_date
        and is_our_org
    ):
        return (
            "Deprecate npm package candidate",
            "Package is backed by an archived repository and is not marked deprecated on npmjs.",
        )

    # ClassificationRules.md Rule NR1
    if (
        npmjs_broken
        and is_our_org
    ):
        return (
            "Repair npm package",
            f"Package is broken on npmjs - {npmjs_broken}.",
        )

    # ClassificationRules.md Rule NM2
    repo_name_contains_sensitive_terms = contains_any(repo_name, sensitive_or_build_terms)
    npm_name_contains_sensitive_terms = contains_any(npm_package_name, sensitive_or_build_terms)
    if repo_name_contains_sensitive_terms or npm_name_contains_sensitive_terms:
        return (
            "Manual review",
            "Package or repository name suggests a security-sensitive, CLI, deployment, configuration, or build-tool package.",
        )

    # ClassificationRules.md Rule NN4
    if (
        not npm_used_by_empty
        or not github_dependents_empty
        or npm_downloads_last_year >= 1000
    ):
        return (
            "Nothing to do",
            f"Package in use - detected local usage, GitHub dependents, or significant npm downloads ({npm_downloads_last_year} downloads in the last year).",
        )

    # ClassificationRules.md Rule ND2
    if (
        npm_used_by_empty
        and github_dependents_empty
        and npm_downloads_last_year == 0
        and npm_last_published_date
    ):
        return (
            "Deprecate npm package candidate",
            "Published package has no detected local consumers, no GitHub dependents, and no npm download activity in the last year.",
        )

    # ClassificationRules.md Rule ND3
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

    # ClassificationRules.md Rule ND4
    if (
        contains_any(repo_name, replacement_terms)
        or contains_any(npm_package_name, replacement_terms)
        and npm_last_published_date
    ):
        return (
            "Deprecate npm package candidate",
            "Package or repository name suggests it may be old, legacy, deprecated, obsolete, archived, or a backup.",
        )

    # ClassificationRules.md Rule NM3
    if (
        npm_downloads_last_year >= 1
        and npm_downloads_last_year < 1000
        and npm_used_by_empty
    ):
        return (
            "Manual review",
            f"Package has low but nonzero npm usage ({npm_downloads_last_year} downloads in the last year) and no detected local consumers.",
        )

    # ClassificationRules.md Rule NM4 - Default NPM Rule
    return (
        "Manual review",
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


def prepend_tagged_columns(headers, data_rows, tagged_columns):
    """
    Prepend tagged columns to headers and initialize them in data rows.

    Args:
        headers (list[str]): List of column headers to modify.
        data_rows (list[dict]): List of row dictionaries to modify.
        tagged_columns (list[str]): Columns to prepend.

    Returns:
        tuple[list[str], list[dict]]: Updated headers and data rows.
    """
    headers = tagged_columns + headers
    data_rows = [
        {**{column: "" for column in tagged_columns}, **row}
        for row in data_rows
    ]
    return headers, data_rows


def copy_tagged_data_to_rows(data_rows, tagged_data_rows, copy_columns):
    """
    Copy tagged column values from tagged rows to matching data rows.

    Builds a lookup dictionary from tagged rows by repository full name,
    then copies specified column values to matching rows in data_rows.

    Args:
        data_rows (list[dict]): List of row dictionaries to update.
        tagged_data_rows (list[dict]): List of tagged row dictionaries to copy from.
        copy_columns (list[str]): List of column names to copy.
    """
    # Build a lookup dictionary keyed by normalized repo full name for O(1) matching
    tagged_rows_by_repo_full_name = {}

    if len(tagged_data_rows) == 0:
        return

    for tagged_row in tagged_data_rows:
        # Skip rows that have no tagged data in any of the columns we care about
        has_tagged_data = any(
            not is_empty(tagged_row.get(column))
            for column in copy_columns
        )

        if not has_tagged_data:
            continue

        # Try to get the full name directly first
        tagged_repo_full_name = tagged_row.get("repo full name")

        # If no full name, construct it from organization and repo name
        if is_empty(tagged_repo_full_name):
            tagged_repo_name = tagged_row.get("repo name")
            tagged_organization = tagged_row.get("organization name")

            # Skip if we can't construct a valid identifier
            if is_empty(tagged_repo_name) or is_empty(tagged_organization):
                continue

            tagged_repo_full_name = f"{tagged_organization}/{tagged_repo_name}"

        # Store with normalized (stripped) key for consistent matching
        tagged_rows_by_repo_full_name[str(tagged_repo_full_name).strip()] = tagged_row

    # Apply tagged values to matching data rows
    for row in data_rows:
        # Look up the tagged row using the normalized repo full name
        tagged_row = tagged_rows_by_repo_full_name.get(
            str(row.get("repo full name", "")).strip()
        )

        # Skip if no matching tagged row was found
        if tagged_row is None:
            continue

        # Copy each specified column value from the tagged row to the data row
        for column in copy_columns:
            row[column] = tagged_row.get(column, "")


def copy_netlify_prefix_columns_to_rows(netlify_ordered_rows, previous_netlify_data_rows):
    """
    Copy manually maintained Netlify prefix columns from the previous Netlify sheet
    into the newly generated Netlify rows.

    Rows are matched using stable Netlify identifiers when available.
    """
    if not previous_netlify_data_rows or not netlify_ordered_rows:
        return

    match_columns = [
        "site_id",
        "site id",
        "id",
        "name",
        "site name",
        "url",
        "admin_url",
        "admin url",
    ]

    matching_column = next(
        (
            column
            for column in match_columns
            if any(not is_empty(row.get(column)) for row in previous_netlify_data_rows)
               and any(not is_empty(row.get(column)) for row in netlify_ordered_rows)
        ),
        None,
    )

    if matching_column is None:
        print("Unable to copy previous Netlify prefix column data: no matching key column found.")
        return

    previous_rows_by_key = {
        str(row.get(matching_column, "")).strip(): row
        for row in previous_netlify_data_rows
        if not is_empty(row.get(matching_column))
    }

    for row in netlify_ordered_rows:
        row_key = str(row.get(matching_column, "")).strip()
        previous_row = previous_rows_by_key.get(row_key)

        if previous_row is None:
            continue

        for column in NETLIFY_PREFIX_COLUMNS:
            row[column] = previous_row.get(column, "")


def determine_netlify_classification(row):
    """
    Classify a Netlify site's lifecycle status.

    Applies rules NL1–NL11 from Netlify.md in priority order and returns a
    recommendation label and human-readable reason.

    Args:
        row (dict): Netlify site data. Relevant fields:
            - name (str): Netlify site slug.
            - custom_domain (str): Custom domain, if configured.
            - repo_url (str): Linked GitHub repository URL.
            - account_slug (str): Netlify account slug.
            - published_at (str): ISO timestamp of the most recent publish.
            - repo archived (bool/str): Whether the backing GitHub repo is archived.

    Returns:
        tuple[str, str]: (recommendation, reason) where recommendation is one of
            "Keep Auto Builds", "Disable Auto Builds", "Remove Project", or
            "Manual Review".
    """
    ORG_ACCOUNT_SLUG = "unfoldingword-hvaaits"
    demo_terms = ["poc", "demo", "test", "lab", "playground", "experiment", "template"]
    throwaway_terms = ["trash", "delete"]

    name = row.get("name", "")
    custom_domain = row.get("custom_domain", "")
    repo_url = row.get("repo_url", "") or row.get("repo url", "")
    account_slug = row.get("account_slug", "")
    published_at = row.get("published_at", "")
    repo_archived = is_true(row.get("repo archived"))

    # Netlify.md Rule NL1 — Keep Auto Builds: production site with a custom domain
    if not is_empty(custom_domain):
        return "Keep Auto Builds", "Site has a custom domain — it is serving production traffic."

    # Detect Netlify-autogenerated slugs: three-or-more segments ending with a 5–8 char hex segment
    parts = name.split("-") if name else []
    last_segment = parts[-1] if parts else ""
    is_autogenerated = (
        len(parts) >= 3
        and 5 <= len(last_segment) <= 8
        and all(c in "0123456789abcdef" for c in last_segment.lower())
    )
    is_throwaway = is_autogenerated or bool(contains_any(name, throwaway_terms))

    # Netlify.md Rule NL2 — Remove Project: orphaned + autogenerated/throwaway name
    if is_empty(repo_url) and is_throwaway:
        return "Remove Project", "No repo linked and site name is autogenerated or a throwaway placeholder — nothing to preserve."

    # Netlify.md Rule NL3 — Manual Review: no linked repo (not caught by NL2)
    if is_empty(repo_url):
        return "Manual Review", "No repo linked — confirm whether the site has a purpose before removing."

    # Netlify.md Rule NL4 — Manual Review: backing GitHub repo is archived
    if repo_archived:
        return "Manual Review", "Backing GitHub repo is archived — decide whether to keep as a static artifact, redirect, or remove."

    # Netlify.md Rule NL5 — Manual Review: site is in a non-organization Netlify account
    if not is_empty(account_slug) and account_slug != ORG_ACCOUNT_SLUG:
        return "Manual Review", f"Site is in a non-organization Netlify account ({account_slug}) — transfer to the unfoldingWord account or remove."

    # Netlify.md Rule NL6 — Manual Review: site has never been published
    if is_empty(published_at):
        return "Manual Review", "Site has never been successfully published — investigate the build failure or delete the project."

    published_months = months_old(published_at)

    # Netlify.md Rule NL7 — Keep Auto Builds: published within the last 12 months
    if published_months is not None and published_months <= 12:
        return "Keep Auto Builds", f"Site was published within the last 12 months ({published_months} months ago)."

    # Netlify.md Rule NL8 — Disable Auto Builds: POC/demo/test/lab/playground/experiment/template name
    matched_term = contains_any(name, demo_terms)
    if matched_term:
        return "Disable Auto Builds", f"Site name contains '{matched_term}' — experimental or one-off build; keep for reference but stop auto-deploying."

    # Netlify.md Rule NL9 — Disable Auto Builds: published more than 18 months ago
    if published_months is not None and published_months > 18:
        return "Disable Auto Builds", f"Site has not been published in over 18 months ({published_months} months ago) — disable auto-deploy to stop consuming build minutes."

    # Netlify.md Rule NL10 — Manual Review: published 12–18 months ago (borderline)
    if published_months is not None and 12 < published_months <= 18:
        return "Manual Review", f"Site was last published {published_months} months ago — confirm whether active development is ongoing."

    # Netlify.md Rule NL11 — Manual Review: default
    return "Manual Review", "Site did not match any automatic Netlify classification rule."


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
        - sheets/categorized_repos.csv: CSV export of all categorized repositories
        - sheets/categorized_repos.ods: ODS spreadsheet with categorized repositories
    
    Global Dependencies:
        - REPO_ODS_FILE: Input spreadsheet filename
        - REPOS_SHEET_NAME: Name of sheet containing repository data
        - CATEGORIZED_OUTPUT: Base filename for output files
        - SORT_ORDER: List defining classification priority order
    """
    headers, data_rows = load_repository_data(REPO_ODS_FILE, REPOS_SHEET_NAME)
    tagged_headers, tagged_data_rows = load_repository_data(TAGGED_ODS_FILE, REPOS_SHEET_NAME)

    try:
        npm_tagged_headers, npm_tagged_data_rows = load_repository_data(TAGGED_ODS_FILE, NPM_SHEET_NAME)
    except Exception as e:
        print(f"Error loading NPM tagged data: {e}")
        # fall back to using data from REPOS_SHEET_NAME
        npm_tagged_headers = tagged_headers
        npm_tagged_data_rows = tagged_data_rows

    headers, data_rows = prepend_tagged_columns(headers, data_rows, ALL_TAGGED_COLUMNS)

    #read previous data the sheet NETLIFY_SHEET_NAME on spreadsheet CATEGORIZED_OUTPUT + ".ods"
    try:
        previous_netlify_headers, previous_netlify_data_rows = load_repository_data(
            TAGGED_ODS_FILE,
            NETLIFY_SHEET_NAME,
        )
    except Exception as e:
        print(f"Error loading previous Netlify data: {e}")
        previous_netlify_headers = []
        previous_netlify_data_rows = []


    if "is submodule of" not in headers:
        headers.insert(headers.index("git submodules"), "is submodule of")

    if "repo full name" not in headers:
        headers.insert(headers.index("Notes") + 1, "repo full name")

    if "repo url" in headers:
        headers.remove("repo url")
    headers.insert(headers.index("repo full name") + 1, "repo url")

    for col in ("repo full name2", "repo url2"):
        if col in headers:
            headers.remove(col)

    if "classification" not in headers:
        headers.append("classification")

    headers.insert(headers.index("classification"), "repo full name2")
    headers.insert(headers.index("classification"), "repo url2")

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

    if "npmjs url" in headers:
        headers.remove("npmjs url")
    headers.insert(headers.index("npmjs package name") + 1, "npmjs url")

    # Move TAGGED_NPM_COLUMNS before "npmjs package name"
    for col in TAGGED_NPM_COLUMNS:
        if col in headers:
            headers.remove(col)
        npmjs_package_name_index = headers.index("npmjs package name")
        headers.insert(npmjs_package_name_index, col)
    
    for col in ("repo name", "organization name"):
        if col in headers:
            headers.remove(col)
        headers.append(col)

    add_submodule_relationships(data_rows)
    npm_update_nested_used_by(data_rows)

    for row in data_rows:
        # print(row)
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
        row["repo full name2"] = repo_full_name
        row["repo url2"] = row.get("repo url", "")
        pkg_name = row.get("npmjs package name")
        npmjs_last_published = row.get("npmjs last published")
        if not is_empty(pkg_name) and not is_empty(npmjs_last_published):
            if isinstance(pkg_name, list):
                pkg_name = pkg_name[0]
            row["npmjs url"] = f"https://www.npmjs.com/package/{pkg_name}"
        else:
            row["npmjs url"] = ""
        row["classification"] = classification
        row["classification reason"] = classification_reason
        row["npmjs classification"] = npmjs_classification
        row["npmjs classification reason"] = npmjs_classification_reason


    sort_rank = {classification: index for index, classification in enumerate(SORT_ORDER)}
    data_rows.sort(
        key=lambda row: (
            sort_rank.get(row["classification"], len(SORT_ORDER)),
            str(row.get("repo name", "")).lower(),
        )
    )

    copy_tagged_data_to_rows(data_rows, tagged_data_rows, TAGGED_COLUMNS)
    copy_tagged_data_to_rows(data_rows, npm_tagged_data_rows, TAGGED_NPM_COLUMNS)

    print("Updated tagged columns in data rows")

    for row in data_rows:
        classification = row["classification"]
        if classification in SORT_ORDER:
            sort_rank = SORT_ORDER.index(classification)
            row["classification"] = str(sort_rank) + "-" + classification
        elif classification:
            print(f"Classification {classification} not found in SORT_ORDER")
            
    classifications = sorted({row["classification"] for row in data_rows})

    print("Classifications found:")
    for classification in classifications:
        print(f"- {classification}")

    for row in data_rows:
        classification = row["npmjs classification"]
        if classification in NPM_SORT_ORDER:
            sort_rank = NPM_SORT_ORDER.index(classification)
            row["npmjs classification"] = str(sort_rank) + "-" + classification
        elif classification:
            print(f"No NPM sort rank for {classification}")

    ordered_rows = [{col: row.get(col, "") for col in headers} for row in data_rows]
    write_list_to_csv(CATEGORIZED_OUTPUT + ".csv", headers, data_rows)
    update_ods_sheet_data(CATEGORIZED_OUTPUT + ".ods", "Repositories", ordered_rows)

    # Add new sheet for NPM Modules - filter rows with npm module name and reorder columns
    npm_rows = [row for row in data_rows if not is_empty(row.get("npmjs package name"))]
    
    # Create new column order: NPM_COLUMN_ORDER columns first, then remaining columns
    npm_headers = NPM_COLUMN_ORDER.copy()
    for col in headers:
        if col not in npm_headers:
            npm_headers.append(col)
    
    npm_ordered_rows = [{col: row.get(col, "") for col in npm_headers} for row in npm_rows]

    npm_ordered_rows.sort(
        key=lambda row: (row.get("npmjs classification", ""), row.get("npmjs classification reason", "")))

    update_ods_sheet_data(CATEGORIZED_OUTPUT + ".ods", NPM_SHEET_NAME, npm_ordered_rows)

    try:
        with open("sheets/netlify_sites.csv", newline="", encoding="utf-8") as netlify_csv_file:
            netlify_rows_ = list(csv.DictReader(netlify_csv_file))
    except FileNotFoundError:
        print("Netlify CSV file not found; using previous Netlify sheet data.")
        netlify_rows_ = previous_netlify_data_rows
    
    copy_netlify_prefix_columns_to_rows(netlify_rows_, previous_netlify_data_rows)
    
    if netlify_rows_:
        netlify_headers = list(netlify_rows_[0].keys())

        if "auto_deploy" in netlify_headers and "account_name" in netlify_headers:
            netlify_headers.remove("auto_deploy")
            netlify_headers.insert(netlify_headers.index("account_name"), "auto_deploy")
            netlify_rows_ = [
                {column: row.get(column, "") for column in netlify_headers}
                for row in netlify_rows_
            ]

        # Add column to left indicating if repo has been archived
        # Build a lookup of archived status by repo full name
        archived_by_repo = {}
        for row in data_rows:
            repo_full_name = row.get("repo full name", "")
            if repo_full_name:
                archived_by_repo[repo_full_name.lower()] = is_true(row.get("archived"))

        # Add "repo archived", "Netlify Recommendation", and "Netlify Recommendation Reason"
        # columns to the beginning of headers
        if "repo archived" not in netlify_headers:
            netlify_headers.insert(0, "repo archived")

        for column in ("Netlify Recommendation", "Netlify Recommendation Reason"):
            if column in netlify_headers:
                netlify_headers.remove(column)

        repo_branch_index = netlify_headers.index("repo_branch")
        netlify_headers.insert(repo_branch_index, "Netlify Recommendation")
        netlify_headers.insert(repo_branch_index + 1, "Netlify Recommendation Reason")

        # For each Netlify row, set archived status and apply classification rules
        for netlify_row in netlify_rows_:
            # Try to extract repo info from build_settings or repo_url
            repo_url = netlify_row.get("repo_url", "") or netlify_row.get("repository_url", "")
            archived_value = ""

            if repo_url and is_github_repo(repo_url):
                org, repo_name = split_github_repo(repo_url)
                if org and repo_name:
                    repo_full_name = f"{org}/{repo_name}".lower()
                    if repo_full_name in archived_by_repo:
                        archived_value = archived_by_repo[repo_full_name]

            netlify_row["repo archived"] = archived_value

            recommendation, recommendation_reason = determine_netlify_classification(netlify_row)
            netlify_row["Netlify Recommendation"] = recommendation
            netlify_row["Netlify Recommendation Reason"] = recommendation_reason

        # Reorder columns to match updated headers
        netlify_rows_ = [
            {column: row.get(column, "") for column in netlify_headers}
            for row in netlify_rows_
        ]

        for row in netlify_rows_:
            classification = row["Netlify Recommendation"]
            if classification in NETLIFY_SORT_ORDER:
                sort_rank = NETLIFY_SORT_ORDER.index(classification)
                row["Netlify Recommendation"] = str(sort_rank) + "-" + classification
            elif classification:
                print(f"No Netlify sort rank for {classification}")

        netlify_rows_.sort(
            key=lambda row: (row.get("Netlify Recommendation", ""), row.get("Netlify Recommendation Reason", "")))

    update_ods_sheet_data(CATEGORIZED_OUTPUT + ".ods", NETLIFY_SHEET_NAME, netlify_rows_)

if __name__ == "__main__":
    main()
