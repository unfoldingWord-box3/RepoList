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
```
bash
python github_repos_csv.py
```
This generates an OpenDocument spreadsheet named:
```
text
unfoldingword_repos.ods
```

## Export Spreadsheet Sheets to CSV

To split the data in [unfoldingword_repos.ods](unfoldingword_repos.ods) into separate CSV files, run:
```
bash
python SheetToCSVConverter.py
```


## Output

- [unfoldingword_repos.ods](unfoldingword_repos.ods) — generated spreadsheet containing repository data
- `*.csv` files — generated from the individual sheets in the spreadsheet by running `SheetToCSVConverter.py`


## Additional Information

[SpreadsheetDocumentation.md](SpreadsheetDocumentation.md) – Documentation for the spreadsheet contents
[CLAUDE.md](CLAUDE.md) – AI Documentation for RepoList
