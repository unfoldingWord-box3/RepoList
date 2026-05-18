# GitHub Repository Spreadsheet Tools

Utilities for generating an OpenDocument spreadsheet of GitHub repository data and exporting spreadsheet sheets to CSV files.

## Prerequisites

- Python 3.11+
- A GitHub personal access token
- A Python virtual environment

## Setup

```bash
python -m virtualenv .venv
source .venv/bin/activate
pip install -r requirements.txt   # pandas odfpy
cp env.sample .env                # then add your GITHUB_TOKEN
```

- The token only needs read metadata permission on the target orgs.


## Caution
- `.env` file contains your GitHub token and should not be committed to a public repository. It is ignored by git by adding it to `.gitignore` to help prevent accidental committing of the file.


## Configuration

- In [GitHubRepositoryFetcher.py](GitHubRepositoryFetcher.py):
  - `ORG_NAMES` contains the names of the GitHub organizations to fetch data from.
  - `OUTPUT_FILE` is the name of the output CSV file.

- If file `.env` is not present, Copy the sample environment file:

```
bash
cp env.sample .env
```
  - Then edit `.env` and put in your GitHub token.

## Generate the Repository Spreadsheet

Run:
```bash
python GitHubRepositoryFetcher.py
```
This generates an OpenDocument spreadsheet named:
```
unfoldingword_repos.ods
```

## Export Spreadsheet Sheets to CSV

To split the data in [unfoldingword_repos.ods](unfoldingword_repos.ods) into separate CSV files, run:
```bash
python SheetToCSVConverter.py
```

## Classify Repositories

To classify every repository by activity and usage status and produce a categorized spreadsheet, run:
```bash
python CatagorizeRepos.py
```
This reads the `Repositories` sheet from `unfoldingword_repos.ods`, applies classification rules, and writes `categorized_repos.ods`. See [ClassificationRules.md](ClassificationRules.md) for the full rule set.

## Output

- [unfoldingword_repos.ods](unfoldingword_repos.ods) — generated spreadsheet containing repository data (sheets: `Repositories`, `JavaScript TypeScript`)
- [Repositories.csv](Repositories.csv) — all repositories exported from the spreadsheet
- [JavaScript TypeScript.csv](JavaScript%20TypeScript.csv) — JavaScript/TypeScript repositories exported from the spreadsheet
- [categorized_repos.ods](categorized_repos.ods) — repositories with `classification` and `classification reason` columns added


## Additional Information

[SpreadsheetDocumentation.md](SpreadsheetDocumentation.md) – Documentation for the spreadsheet contents
[ClassificationRules.md](ClassificationRules.md) – Classification rules used by `CatagorizeRepos.py`
[CLAUDE.md](CLAUDE.md) – AI Documentation for RepoList
