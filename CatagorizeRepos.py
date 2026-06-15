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
        - Needs review: Default fallback for unmatched cases

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


from lib.utilities import write_rows_to_ods, is_true, months_old, is_empty, as_int, contains_any, load_repository_data, \
    write_list_to_csv

ODS_FILE = "unfoldingword_repos.ods"
SHEET_NAME = "Repositories"
CATEGORIZED_OUTPUT = "categorized_repos"

SORT_ORDER = [
    "No longer used candidate",
    "Keep - externally used",
    "Keep - locally used",
    "Manual review",
    "Needs review",
    "Dead - archived",
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
              "Dead candidate", "Manual review", "Stale", "Needs review")
            - reason (str): Human-readable explanation for the classification decision
    
    Classification Priority:
        1. Active: Recent commits (within 12 months)
        2. Keep: Local usage, external dependents, or high downloads
        3. Manual review: Core projects, high activity, or significant history
        4. Dead: Archived, deprecated, or long-inactive with no usage
        5. Stale: Inactive but with some usage or open issues
        6. No longer used: Likely candidates for archival/cleanup
        7. Needs review: Default fallback for unmatched cases
    """
    repo_name = row.get("repo name", "")
    archived = is_true(row.get("archived"))
    npm_deprecated = is_true(row.get("npm is deprecated"))
    is_fork = is_true(row.get("is fork"))

    last_commit_months = months_old(row.get("last commit date"))
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

    if recently_active:
        return "Active", f"Last commit was within the last 12 months ({last_commit_months} months ago)."

    if has_local_use:
        return "Keep - locally used", "Repository is listed as used by an npm package."

    if has_github_dependents or npm_downloads_last_year >= 1000:
        return "Keep - externally used", f"Repository has GitHub dependents or at least 1,000 npm downloads in the last year ({npm_downloads_last_year} downloads)."

    if contains_any(repo_name, core_terms):
        return "Manual review", "Repository name contains a core project term."

    if archived:
        return "Dead - archived", "Repository is archived."

    if npm_deprecated and last_commit_months is not None and last_commit_months > 24:
        return "Dead - deprecated", f"Npm package is deprecated and the last commit is older than 24 months ({last_commit_months} months ago)."

    if open_issues_count >= 50:
        return "Manual review", f"Repository has at least 50 open issues ({open_issues_count} open issues)."

    if github_release_count >= 10 or github_downloads >= 100:
        return "Manual review", f"Repository has significant release history or GitHub downloads ({github_release_count} releases, {github_downloads} downloads)."

    if github_contributors >= 5:
        return "Manual review", f"Repository has at least 5 GitHub contributors ({github_contributors} contributors)."

    if (
        last_edit_months is not None
        and last_edit_months <= 12
        and last_commit_months is not None
        and last_commit_months > 36
    ):
        return "Manual review", f"Repository was edited recently ({last_edit_months} months ago) but has not had a commit in over 36 months ({last_commit_months} months ago)."

    if (
        last_commit_months is not None
        and last_commit_months > 60
        and not archived
        and npm_used_by_empty
        and github_dependents_empty
        and github_downloads == 0
        and github_release_count == 0
    ):
        return "Dead candidate", f"Repository has had no commits in over 60 months ({last_commit_months} months ago) and has no usage, downloads ({github_downloads}), or releases ({github_release_count})."

    if (
        is_fork
        and last_commit_months is not None
        and last_commit_months > 36
        and npm_used_by_empty
        and github_dependents_empty
        and github_downloads == 0
    ):
        return "Dead candidate", f"Repository is an old fork with no detected usage or downloads ({github_downloads} downloads), and the last commit was over 36 months ago ({last_commit_months} months ago)."

    if (
        contains_any(repo_name, cleanup_terms)
        and last_commit_months is not None
        and last_commit_months > 24
        and npm_used_by_empty
        and github_dependents_empty
    ):
        return "Dead candidate", f"Repository name suggests cleanup/test/demo content, it has no detected usage, and the last commit was over 24 months ago ({last_commit_months} months ago)."

    if (
        language_empty
        and github_release_count == 0
        and github_downloads == 0
        and npm_package_empty
        and last_commit_months is not None
        and last_commit_months > 36
    ):
        return "Dead candidate", f"Repository has no language, releases ({github_release_count}), downloads ({github_downloads}), or npm package, and is older than 36 months ({last_commit_months} months since last commit)."

    if (
        last_commit_months is not None
        and last_commit_months > 18
        and (
            not npm_used_by_empty
            or not github_dependents_empty
            or npm_downloads_last_year > 0
        )
    ):
        return "Stale but used", f"Repository has had no commits in over 18 months ({last_commit_months} months ago) but still has detected usage ({npm_downloads_last_year} npm downloads in the last year)."

    if (
        not npm_package_empty
        and npm_last_published_months is not None
        and npm_last_published_months > 18
        and not npm_deprecated
    ):
        return "Stale package", f"Npm package has not been published in over 18 months ({npm_last_published_months} months ago) and is not marked deprecated."

    if (
        last_commit_months is not None
        and last_commit_months > 12
        and (open_prs_count >= 5 or open_issues_count >= 20)
    ):
        return "Stale / neglected", f"Repository has had no commits in over 12 months ({last_commit_months} months ago) and has many open PRs or issues ({open_prs_count} PRs, {open_issues_count} issues)."

    if (
        last_commit_months is not None
        and last_commit_months <= 24
        and last_release_months is not None
        and last_release_months > 24
        and github_release_count > 0
    ):
        return "Stale release process", f"Repository has recent commits ({last_commit_months} months ago) but no release in over 24 months ({last_release_months} months ago), with {github_release_count} releases."

    if (
        last_commit_months is not None
        and last_commit_months > 18
        and not archived
    ):
        return "Stale", f"Repository has had no commits in over 18 months ({last_commit_months} months ago) and is not archived."

    if contains_any(repo_name, replacement_terms):
        return "No longer used candidate", "Repository name suggests it may be old, legacy, deprecated, obsolete, archived, or a backup."

    if (
        contains_any(repo_name, cleanup_terms)
        and last_commit_months is not None
        and last_commit_months > 12
    ):
        return "No longer used candidate", f"Repository name suggests cleanup/test/demo content and it has had no commits in over 12 months ({last_commit_months} months ago)."

    if is_fork and npm_used_by_empty and github_dependents_empty:
        return "No longer used candidate", "Repository is a fork with no detected npm or GitHub dependent usage."

    if (
        not npm_package_empty
        and npm_used_by_empty
        and github_dependents_empty
        and npm_downloads_last_year == 0
    ):
        return "No longer used candidate", f"Repository has an npm package but no detected usage or downloads in the last year ({npm_downloads_last_year} npm downloads)."

    return "Needs review", "Repository did not match any automatic classification rule."


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
              "Manual review - npm package", "Needs review")
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
        return "Needs review", "No npmjs package is published for this repository."

    if npm_deprecated:
        return "Deprecated npm package", "Npm package is already explicitly marked as deprecated."

    if contains_any(repo_name, sensitive_or_build_terms) or contains_any(npm_package_name, sensitive_or_build_terms):
        return (
            "Manual review - npm package",
            "Package or repository name suggests a security-sensitive, CLI, deployment, configuration, or build-tool package.",
        )

    if (
        not npm_used_by_empty
        or not github_dependents_empty
        or npm_downloads_last_year >= 1000
    ):
        return (
            "Keep - npm package in use",
            f"Package has detected local usage, GitHub dependents, or significant npm downloads ({npm_downloads_last_year} downloads in the last year).",
        )

    if archived:
        return (
            "Deprecate npm package candidate",
            "Package is backed by an archived repository and is not marked deprecated on npmjs.",
        )

    if (
        npm_used_by_empty
        and github_dependents_empty
        and npm_downloads_last_year == 0
    ):
        return (
            "Deprecate npm package candidate",
            "Published package has no detected local consumers, no GitHub dependents, and no npm download activity in the last year.",
        )

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

    if contains_any(repo_name, replacement_terms) or contains_any(npm_package_name, replacement_terms):
        return (
            "Deprecate npm package candidate",
            "Package or repository name suggests it may be old, legacy, deprecated, obsolete, archived, or a backup.",
        )

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

    if "classification" not in headers:
        headers.append("classification")

    if "classification reason" not in headers:
        headers.append("classification reason")

    if "npmjs classification" not in headers:
        headers.append("npmjs classification")

    if "npmjs classification reason" not in headers:
        headers.append("npmjs classification reason")

    for row in data_rows:
        print(row)
        classification, classification_reason = determine_github_classification(row)

        if is_empty(row.get("npmjs package name")):
            npmjs_classification = ""
            npmjs_classification_reason = ""
        else:
            npmjs_classification, npmjs_classification_reason = determine_npmjs_classification(row)

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

    classifications = sorted({row["classification"] for row in data_rows})

    print("Classifications found:")
    for classification in classifications:
        print(f"- {classification}")

    write_list_to_csv(CATEGORIZED_OUTPUT + ".csv", headers, data_rows)
    write_rows_to_ods(CATEGORIZED_OUTPUT + ".ods", "Repositories", data_rows)


if __name__ == "__main__":
    main()
