"""Shared OAuth authentication for Google Docs/Drive/Sheets/Calendar/Contacts/Gmail."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

CREDENTIALS_PATH = Path.home() / ".claude" / ".google" / "client_secret.json"
TOKEN_PATH = Path.home() / ".claude" / ".google" / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/script.projects",
    "https://www.googleapis.com/auth/script.deployments",
]

DEFAULT_OAUTH_PORT = 8085


def _load_ruby_token() -> dict | None:
    """Load token from Ruby FileTokenStore format: {"default": "<json-string>"}."""
    if not TOKEN_PATH.exists():
        return None
    try:
        raw = json.loads(TOKEN_PATH.read_text())
        if isinstance(raw, dict) and "default" in raw:
            token_str = raw["default"]
            if isinstance(token_str, str):
                return json.loads(token_str)
            return token_str
        return raw
    except (json.JSONDecodeError, KeyError):
        return None


def _save_credentials(creds: Credentials) -> None:
    """Save credentials in Ruby FileTokenStore compatible format."""
    token_data = {
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "scope": " ".join(SCOPES),
        "token_uri": creds.token_uri or "https://oauth2.googleapis.com/token",
    }
    if creds.expiry:
        token_data["expiry"] = creds.expiry.isoformat() + "Z"

    # Save in Ruby FileTokenStore format
    store_data = {"default": json.dumps(token_data)}
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(store_data))
    TOKEN_PATH.chmod(0o600)


def get_credentials() -> Credentials:
    """Load, refresh, or create OAuth credentials."""
    token_data = _load_ruby_token()

    if token_data:
        creds = Credentials(
            token=token_data.get("access_token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=SCOPES,
        )

        if creds.valid:
            return creds

        if creds.refresh_token:
            try:
                creds.refresh(Request())
                _save_credentials(creds)
                return creds
            except Exception as e:
                print(f"Token refresh failed: {e}", file=sys.stderr)
                # Fall through to re-auth

    # No valid credentials — run auth flow
    if not CREDENTIALS_PATH.exists():
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": "MISSING_CREDENTIALS",
                    "message": f"Client secret not found at {CREDENTIALS_PATH}",
                }
            )
        )
        sys.exit(2)

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=DEFAULT_OAUTH_PORT)
    _save_credentials(creds)
    return creds


def get_docs_service():
    """Build and return Google Docs v1 API service."""
    creds = get_credentials()
    return build("docs", "v1", credentials=creds)


def get_drive_service():
    """Build and return Google Drive v3 API service."""
    creds = get_credentials()
    return build("drive", "v3", credentials=creds)
