#!/usr/bin/env python3
"""
Tagged Repos Fetcher

Downloads the unfoldingWord tagged-repos Google Sheet as an ODS file and saves
it to sheets/marked_repos.ods, ready for use by CatagorizeRepos.py.

Setup (one time):
    1. In Google Cloud Console, create a project, enable the Google Drive API,
       and create an OAuth 2.0 credential for a Desktop application.
    2. Download the credential JSON and save it as credentials.json in this directory.
    3. Add GOOGLE_SHEET_ID to your .env file (the long ID from the sheet URL).
    4. Run this script once — a browser tab will open for you to sign in and
       grant read access. The token is then saved to .google_token.json so
       subsequent runs are silent.

Usage: python FetchMarkedReposSheetFromGithub.py
"""

import os
import sys
import urllib.request

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from lib.constants import ENV_FILE, MARKED_ODS_FILE
from lib.utilities import load_env_file

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
TOKEN_FILE = ".google_token.json"
CREDENTIALS_FILE = "credentials.json"
OUTPUT_FILE = MARKED_ODS_FILE


def get_credentials():
    """
    Load cached credentials or run the OAuth browser flow to obtain them.
    Refreshes the access token automatically if it has expired.
    Saves the token to TOKEN_FILE after a successful browser flow.
    """
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired Google access token...")
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                print(
                    f"Error: {CREDENTIALS_FILE} not found.\n"
                    "Download OAuth 2.0 credentials (Desktop app) from Google Cloud Console\n"
                    "and save them as credentials.json in this directory.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print("Opening browser for Google authentication...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token_file:
            token_file.write(creds.to_json())
        print(f"Token saved to {TOKEN_FILE}.")

    return creds


def download_sheet_as_ods(sheet_id, creds):
    """
    Export a Google Sheet as ODS using the Drive export URL.
    Returns the raw bytes of the ODS file.
    """
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=ods"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {creds.token}",
            "User-Agent": "unfoldingword-repo-list-script",
        },
    )
    with urllib.request.urlopen(req) as response:
        return response.read()


def main():
    load_env_file(ENV_FILE)

    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        print("Error: GOOGLE_SHEET_ID not set in .env", file=sys.stderr)
        sys.exit(1)

    creds = get_credentials()

    print(f"Downloading sheet {sheet_id} as ODS...")
    content = download_sheet_as_ods(sheet_id, creds)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "wb") as f:
        f.write(content)

    print(f"Saved to {OUTPUT_FILE} ({len(content):,} bytes).")


if __name__ == "__main__":
    main()