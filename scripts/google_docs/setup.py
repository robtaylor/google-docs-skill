"""Environment detection and bootstrap for the Google Docs skill."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent.resolve()
GOOGLE_DIR = Path.home() / ".claude" / ".google"
CLIENT_SECRET_PATH = GOOGLE_DIR / "client_secret.json"
TOKEN_PATH = GOOGLE_DIR / "token.json"
SCRIPT_CONFIG_PATH = GOOGLE_DIR / "apps_script_config.json"

REQUIRED_SCRIPT_SCOPES = [
    "https://www.googleapis.com/auth/script.projects",
    "https://www.googleapis.com/auth/script.deployments",
]


def check_environment() -> dict:
    """Check all prerequisites and return status dict."""
    checks = {
        "uv": _check_uv(),
        "python": _check_python(),
        "venv": _check_venv(),
        "dependencies": _check_dependencies(),
        "google_credentials": _check_google_credentials(),
        "google_token": _check_google_token(),
        "mmdc": _check_mmdc(),
        "apps_script_api_gcp": _check_apps_script_api_gcp(),
        "apps_script_api_user": _check_apps_script_api_user(),
        "apps_script_project": _check_apps_script_project(),
        "oauth_scopes": _check_oauth_scopes(),
    }
    all_ok = all(c["ok"] for c in checks.values())
    return {"status": "ready" if all_ok else "setup_needed", "checks": checks}


def check_appscript_only() -> dict:
    """Run only Apps Script related checks (quick diagnostic)."""
    checks = {
        "apps_script_api_gcp": _check_apps_script_api_gcp(),
        "apps_script_api_user": _check_apps_script_api_user(),
        "apps_script_project": _check_apps_script_project(),
        "oauth_scopes": _check_oauth_scopes(),
    }
    all_ok = all(c["ok"] for c in checks.values())
    return {"status": "ready" if all_ok else "setup_needed", "checks": checks}


def _check_uv() -> dict:
    uv = shutil.which("uv")
    if uv:
        return {"ok": True, "path": uv}
    return {"ok": False, "message": "uv not found. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"}


def _check_python() -> dict:
    try:
        result = subprocess.run(
            ["python3", "--version"], capture_output=True, text=True, timeout=5
        )
        version = result.stdout.strip()
        return {"ok": True, "version": version}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"ok": False, "message": "Python 3.11+ required"}


def _check_venv() -> dict:
    venv_path = SCRIPTS_DIR / ".venv"
    if venv_path.exists():
        return {"ok": True, "path": str(venv_path)}
    return {"ok": False, "message": "Virtual environment not created. Run: cd scripts && uv sync"}


def _check_dependencies() -> dict:
    lock_file = SCRIPTS_DIR / "uv.lock"
    if lock_file.exists():
        return {"ok": True}
    return {"ok": False, "message": "Dependencies not installed. Run: cd scripts && uv sync"}


def _check_google_credentials() -> dict:
    if CLIENT_SECRET_PATH.exists():
        return {"ok": True, "path": str(CLIENT_SECRET_PATH)}
    return {
        "ok": False,
        "message": f"Google OAuth client secret not found at {CLIENT_SECRET_PATH}",
        "instructions": [
            "1. Go to https://console.cloud.google.com/apis/credentials",
            "2. Create an OAuth 2.0 Client ID (Desktop application)",
            "3. Download the JSON and save as:",
            f"   {CLIENT_SECRET_PATH}",
        ],
    }


def _check_google_token() -> dict:
    if TOKEN_PATH.exists():
        return {"ok": True, "path": str(TOKEN_PATH)}
    return {
        "ok": False,
        "message": "Not authenticated. Run any docs/drive command to trigger OAuth flow.",
    }


def _check_mmdc() -> dict:
    mmdc = shutil.which("mmdc")
    if mmdc:
        return {"ok": True, "path": mmdc}
    return {
        "ok": False,
        "message": "mmdc not found (optional, needed for mermaid diagrams). Install: npm install -g @mermaid-js/mermaid-cli",
    }


def _build_script_service():
    """Build Apps Script service from stored credentials. Returns service or None."""
    if not TOKEN_PATH.exists():
        return None
    try:
        from google_docs.auth import get_credentials
        from googleapiclient.discovery import build

        creds = get_credentials()
        return build("script", "v1", credentials=creds)
    except Exception:
        return None


def _check_apps_script_api_gcp() -> dict:
    """Check if Apps Script API is enabled in the GCP project."""
    if not TOKEN_PATH.exists():
        return {"ok": False, "message": "Not authenticated yet. Authenticate first, then re-check."}

    try:
        service = _build_script_service()
        if service is None:
            return {"ok": False, "message": "Could not build script service."}
        # Lightweight call: list processes (empty is fine, just tests API access)
        service.processes().list(pageSize=1).execute()
        return {"ok": True}
    except Exception as exc:
        msg = str(exc)
        if "not enabled" in msg.lower() or "403" in msg:
            if "has not been used" in msg.lower() or "it is disabled" in msg.lower():
                return {
                    "ok": False,
                    "message": "Apps Script API is not enabled in your GCP project.",
                    "url": "https://console.cloud.google.com/apis/api/script.googleapis.com",
                    "instructions": [
                        "1. Open the URL above in your browser",
                        "2. Select your GCP project",
                        "3. Click 'Enable' to activate the Apps Script API",
                    ],
                }
        return {"ok": False, "message": f"Apps Script API check failed: {msg}"}


def _check_apps_script_api_user() -> dict:
    """Check if user has enabled the Apps Script API toggle in their account."""
    if not TOKEN_PATH.exists():
        return {"ok": False, "message": "Not authenticated yet. Authenticate first, then re-check."}

    try:
        service = _build_script_service()
        if service is None:
            return {"ok": False, "message": "Could not build script service."}
        service.processes().list(pageSize=1).execute()
        return {"ok": True}
    except Exception as exc:
        msg = str(exc)
        if "user has not enabled" in msg.lower():
            return {
                "ok": False,
                "message": "You need to enable the Apps Script API in your Google account settings.",
                "url": "https://script.google.com/home/usersettings",
                "instructions": [
                    "1. Open https://script.google.com/home/usersettings",
                    "2. Toggle 'Google Apps Script API' to ON",
                ],
            }
        # If we get here without the specific error, assume it passed
        # (the GCP check handles the other 403 cases)
        if "403" not in msg:
            return {"ok": True}
        return {"ok": False, "message": f"Apps Script user API check failed: {msg}"}


def _check_apps_script_project() -> dict:
    """Check if the reusable Apps Script project exists and is configured."""
    if not SCRIPT_CONFIG_PATH.exists():
        return {
            "ok": True,
            "message": "No Apps Script project yet. It will be auto-created on first write operation.",
        }

    try:
        config = json.loads(SCRIPT_CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "message": f"Could not read {SCRIPT_CONFIG_PATH}: {exc}"}

    script_id = config.get("script_id")
    if not script_id:
        return {
            "ok": True,
            "message": "Config exists but no script_id. Will be auto-created on first write.",
        }

    # Verify the script project is still accessible
    try:
        service = _build_script_service()
        if service is None:
            return {"ok": False, "message": "Could not build script service to verify project."}
        service.projects().get(scriptId=script_id).execute()
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Script project {script_id} is not accessible: {exc}",
            "instructions": [
                "The saved script project may have been deleted.",
                f"Delete {SCRIPT_CONFIG_PATH} and re-run to auto-create a new one.",
            ],
        }

    # Check GCP project number
    gcp_number = config.get("gcp_project_number")
    if not gcp_number:
        return {
            "ok": False,
            "message": "GCP project number not set in Apps Script project config.",
            "url": f"https://script.google.com/home/projects/{script_id}/settings",
            "instructions": [
                f"1. Open https://script.google.com/home/projects/{script_id}/settings",
                "2. Under 'Google Cloud Platform (GCP) Project', click 'Change project'",
                "3. Enter your GCP project number and click 'Set project'",
            ],
        }

    return {"ok": True, "script_id": script_id, "gcp_project_number": gcp_number}


def _check_oauth_scopes() -> dict:
    """Check if current token has the required Apps Script scopes."""
    if not TOKEN_PATH.exists():
        return {"ok": False, "message": "Not authenticated yet. Run any command to trigger OAuth."}

    try:
        raw = json.loads(TOKEN_PATH.read_text())
        # Handle Ruby FileTokenStore format
        token_data = raw
        if isinstance(raw, dict) and "default" in raw:
            inner = raw["default"]
            token_data = json.loads(inner) if isinstance(inner, str) else inner

        scope_str = token_data.get("scope", "")
        granted_scopes = set(scope_str.split()) if scope_str else set()

        missing = [s for s in REQUIRED_SCRIPT_SCOPES if s not in granted_scopes]
        if missing:
            return {
                "ok": False,
                "message": "Token is missing required Apps Script scopes.",
                "missing_scopes": missing,
                "instructions": [
                    f"1. Delete the token file: rm {TOKEN_PATH}",
                    "2. Run any docs/drive command to trigger a fresh OAuth flow",
                    "3. The new flow will request all required scopes including Apps Script",
                ],
            }
        return {"ok": True, "scopes_present": list(REQUIRED_SCRIPT_SCOPES)}
    except (json.JSONDecodeError, OSError) as exc:
        return {"ok": False, "message": f"Could not read token: {exc}"}


def bootstrap() -> None:
    """Run interactive bootstrap to set up the environment."""
    print("Google Docs Skill — Environment Setup")
    print("=" * 40)

    env = check_environment()

    # 1. uv
    uv_check = env["checks"]["uv"]
    if not uv_check["ok"]:
        print(f"\n[MISSING] uv: {uv_check['message']}")
        print("Installing uv...")
        try:
            subprocess.run(
                ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"],
                check=True, timeout=60,
            )
            print("[OK] uv installed")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"[FAIL] Could not install uv: {e}")
            print("Please install manually: curl -LsSf https://astral.sh/uv/install.sh | sh")
    else:
        print(f"[OK] uv: {uv_check['path']}")

    # 2. Dependencies
    venv_check = env["checks"]["venv"]
    deps_check = env["checks"]["dependencies"]
    if not venv_check["ok"] or not deps_check["ok"]:
        print("\n[SETUP] Installing Python dependencies...")
        try:
            subprocess.run(
                ["uv", "sync"], cwd=str(SCRIPTS_DIR), check=True, timeout=120,
            )
            print("[OK] Dependencies installed")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            print(f"[FAIL] Dependency install failed: {e}")
    else:
        print("[OK] Dependencies installed")

    # 3. Google credentials
    cred_check = env["checks"]["google_credentials"]
    if not cred_check["ok"]:
        print(f"\n[MISSING] Google OAuth credentials")
        GOOGLE_DIR.mkdir(parents=True, exist_ok=True)
        for line in cred_check["instructions"]:
            print(f"  {line}")
        print(f"\nAfter saving client_secret.json, run any command to trigger OAuth.")
    else:
        print(f"[OK] Google credentials: {cred_check['path']}")

    # 4. Token
    token_check = env["checks"]["google_token"]
    if token_check["ok"]:
        print(f"[OK] Authenticated: {token_check['path']}")
    else:
        print(f"[INFO] {token_check['message']}")

    # 5. mmdc
    mmdc_check = env["checks"]["mmdc"]
    if mmdc_check["ok"]:
        print(f"[OK] mmdc: {mmdc_check['path']}")
    else:
        print(f"[OPTIONAL] {mmdc_check['message']}")

    # 6. Apps Script checks
    print("\n--- Apps Script Setup ---")
    _print_appscript_checks(env["checks"])

    print("\n" + "=" * 40)
    all_ok = env["status"] == "ready"
    if all_ok:
        print("All checks passed. Ready to use!")
    else:
        print("Some items need attention (see above).")


def _print_appscript_checks(checks: dict) -> None:
    """Print Apps Script check results with guidance."""
    appscript_keys = [
        ("apps_script_api_gcp", "Apps Script API (GCP)"),
        ("apps_script_api_user", "Apps Script API (User)"),
        ("apps_script_project", "Apps Script Project"),
        ("oauth_scopes", "OAuth Scopes (Apps Script)"),
    ]

    for key, label in appscript_keys:
        check = checks.get(key, {"ok": False, "message": "Check not run"})
        if check["ok"]:
            detail = check.get("script_id", check.get("message", ""))
            suffix = f": {detail}" if detail else ""
            print(f"[OK] {label}{suffix}")
        else:
            print(f"\n[MISSING] {label}: {check.get('message', 'Failed')}")
            url = check.get("url")
            if url:
                print(f"  URL: {url}")
            for instruction in check.get("instructions", []):
                print(f"  {instruction}")
            missing_scopes = check.get("missing_scopes")
            if missing_scopes:
                for scope in missing_scopes:
                    print(f"    - {scope}")


def _bootstrap_appscript() -> None:
    """Run only the Apps Script diagnostic checks interactively."""
    print("Apps Script — Quick Diagnostic")
    print("=" * 40)

    result = check_appscript_only()
    _print_appscript_checks(result["checks"])

    print("\n" + "=" * 40)
    if result["status"] == "ready":
        print("All Apps Script checks passed.")
    else:
        print("Some Apps Script items need attention (see above).")


def main() -> None:
    """CLI entry point."""
    args = sys.argv[1:]

    if "--check-appscript" in args:
        if "--json" in args:
            result = check_appscript_only()
            print(json.dumps(result, indent=2))
        else:
            _bootstrap_appscript()
    elif "--json" in args:
        env = check_environment()
        print(json.dumps(env, indent=2))
    else:
        bootstrap()


if __name__ == "__main__":
    main()
