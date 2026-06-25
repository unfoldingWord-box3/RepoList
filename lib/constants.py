# lib/constants.py

NODE_LANGUAGES = ("javascript", "typescript", "svelte") # lowercase
OFTEN_GITHUB_MISTAKEN_LANGUAGES = ("", "html") # lowercase

REPO_ODS_FILE = "sheets/unfoldingword_repos.ods"
TAGGED_ODS_FILE = "sheets/tagged_repos.ods"
CATEGORIZED_OUTPUT = "sheets/categorized_repos"
ENV_FILE = ".env"
UW_MAINTAINERS = ['neutrinog', 'jakobaleksandrovich', 'klappy', 'photo-nomad', 'richmahn', 'mandolyte', 'jag3773', 'mvahowe', 'larsgson', 'abelpz', 'eliaspinero', 'kintsoogii', 'macolon']
MIN_UW_MAINTAINERS = ['jakobaleksandrovich', 'klappy', 'photo-nomad', 'richmahn', 'jag3773']

REPOS_SHEET_NAME = "Repositories"
JS_TS_SHEET_NAME = "JavaScript TypeScript"
NPM_SHEET_NAME = "NPM Modules"

NPM_ORG_NAMES = [ # npm organizations (lowercase, without @)
    "unfoldingword",
    "oce-editor-tools",
]
ORG_NAMES = [  # highest priority first
    "unfoldingWord",
    "unfoldingWord-dev",
    "unfoldingWord-box3",
]
