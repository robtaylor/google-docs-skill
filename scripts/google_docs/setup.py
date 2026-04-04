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

    print("\n" + "=" * 40)
    all_ok = env["status"] == "ready"
    if all_ok:
        print("All checks passed. Ready to use!")
    else:
        print("Some items need attention (see above).")


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        env = check_environment()
        print(json.dumps(env, indent=2))
    else:
        bootstrap()


if __name__ == "__main__":
    main()
