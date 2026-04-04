"""Insert images into Google Docs via Apps Script Execution API.

Uses Google Apps Script's DocumentApp.insertImage(blob) to bypass the
Docs REST API's 2KB URL limit and Workspace public-sharing restrictions.

Requires one-time setup:
1. Apps Script API enabled at https://script.google.com/home/usersettings
2. GCP project number set on the script project (stored in SCRIPT_CONFIG_PATH)
3. OAuth scopes: script.projects, script.deployments

Usage:
    from google_docs.image_inserter import insert_images_into_doc

    result = insert_images_into_doc(
        document_id="abc123",
        images=[{"label": "Chart 1", "file_path": "/path/to/chart.png"}],
        drive_folder_id=None,  # auto-creates dated folder
    )
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from google_docs.auth import get_credentials

SCRIPT_CONFIG_PATH = Path.home() / ".claude" / ".google" / "apps_script_config.json"

# Apps Script source code for image insertion
_SCRIPT_CODE = '''
function insertImage(docId, driveFileId) {
  var doc = DocumentApp.openById(docId);
  var body = doc.getBody();
  var blob = DriveApp.getFileById(driveFileId).getBlob();
  body.appendImage(blob);
  doc.saveAndClose();
  return {success: true};
}

function insertImageAtIndex(docId, driveFileId, childIndex) {
  var doc = DocumentApp.openById(docId);
  var body = doc.getBody();
  var blob = DriveApp.getFileById(driveFileId).getBlob();
  if (childIndex >= 0 && childIndex < body.getNumChildren()) {
    body.insertImage(childIndex, blob);
  } else {
    body.appendImage(blob);
  }
  doc.saveAndClose();
  return {success: true, index: childIndex};
}

function insertMultipleImages(docId, driveFileIds) {
  var doc = DocumentApp.openById(docId);
  var body = doc.getBody();
  var results = [];
  for (var i = 0; i < driveFileIds.length; i++) {
    try {
      var blob = DriveApp.getFileById(driveFileIds[i]).getBlob();
      body.appendImage(blob);
      results.push({fileId: driveFileIds[i], success: true});
    } catch(e) {
      results.push({fileId: driveFileIds[i], success: false, error: e.toString()});
    }
  }
  doc.saveAndClose();
  return results;
}
'''

_MANIFEST = json.dumps({
    "timeZone": "UTC",
    "oauthScopes": [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive",
    ],
    "exceptionLogging": "STACKDRIVER",
    "executionApi": {"access": "MYSELF"},
    "runtimeVersion": "V8",
})


def _load_script_config() -> dict | None:
    """Load saved Apps Script project config."""
    if SCRIPT_CONFIG_PATH.exists():
        return json.loads(SCRIPT_CONFIG_PATH.read_text())
    return None


def _find_or_create_folder(drive, name: str, parent_id: str | None = None) -> str:
    """Find a folder by name under parent, or create it. Returns folder ID."""
    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    results = drive.files().list(q=query, fields="files(id)", pageSize=1).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    body: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        body["parents"] = [parent_id]
    created = drive.files().create(body=body, fields="id").execute()
    return created["id"]


def _ensure_drive_folder_path(drive, leaf_name: str) -> str:
    """Create nested Drive folder: skill/image2doc/{leaf_name}/.

    Returns the leaf folder ID.
    """
    skill_id = _find_or_create_folder(drive, "skill")
    image2doc_id = _find_or_create_folder(drive, "image2doc", skill_id)
    leaf_id = _find_or_create_folder(drive, leaf_name, image2doc_id)
    return leaf_id


def _save_script_config(config: dict) -> None:
    """Save Apps Script project config."""
    SCRIPT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCRIPT_CONFIG_PATH.write_text(json.dumps(config, indent=2))
    SCRIPT_CONFIG_PATH.chmod(0o600)


def _get_gcp_project_number() -> str:
    """Extract GCP project number from client_secret.json."""
    client_path = Path.home() / ".claude" / ".google" / "client_secret.json"
    data = json.loads(client_path.read_text())
    installed = data.get("installed", data.get("web", {}))
    client_id = installed.get("client_id", "")
    return client_id.split("-")[0] if "-" in client_id else ""


def ensure_script_project(script_service) -> str:
    """Get or create a reusable Apps Script project for image insertion.

    Returns the script ID. Creates the project on first call,
    reuses it on subsequent calls.
    """
    config = _load_script_config()
    if config and config.get("script_id"):
        # Verify it still exists
        try:
            script_service.projects().get(scriptId=config["script_id"]).execute()
            return config["script_id"]
        except Exception:
            pass  # Recreate

    # Create a standalone script project
    project = script_service.projects().create(body={
        "title": "GoogleDocsSkill_ImageInserter",
    }).execute()
    script_id = project["scriptId"]

    # Push code
    script_service.projects().updateContent(scriptId=script_id, body={
        "files": [
            {"name": "Code", "type": "SERVER_JS", "source": _SCRIPT_CODE},
            {"name": "appsscript", "type": "JSON", "source": _MANIFEST},
        ]
    }).execute()

    # Create version + deployment
    version = script_service.projects().versions().create(
        scriptId=script_id, body={"description": "v1"}
    ).execute()
    script_service.projects().deployments().create(
        scriptId=script_id,
        body={"versionNumber": version["versionNumber"], "description": "api-exec"},
    ).execute()

    gcp_number = _get_gcp_project_number()
    _save_script_config({
        "script_id": script_id,
        "gcp_project_number": gcp_number,
        "created": date.today().isoformat(),
    })

    print(
        f"Apps Script project created: {script_id}\n"
        f"IMPORTANT: Set GCP project number to {gcp_number} at:\n"
        f"  https://script.google.com/home/projects/{script_id}/settings\n"
        f"This is a one-time setup step.",
        file=sys.stderr,
    )

    return script_id


def insert_images_into_doc(
    document_id: str,
    images: list[dict],
    drive_folder_id: str | None = None,
    doc_title: str = "untitled",
    rate_limit_delay: float = 2.5,
    on_progress: callable | None = None,
) -> dict:
    """Insert images into a Google Doc via Apps Script.

    Args:
        document_id: Google Doc ID
        images: List of {label: str, file_path: str} dicts
        drive_folder_id: Drive folder for uploaded images (auto-creates if None)
        doc_title: Used for auto-created folder name
        rate_limit_delay: Seconds between API calls (default 2.5)
        on_progress: Callback(index, total, label, status) for progress tracking

    Returns:
        Dict with inserted/failed counts, folder_id, errors list
    """
    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    script_service = build("script", "v1", credentials=creds)

    script_id = ensure_script_project(script_service)

    # Auto-create Drive folder: skill/image2doc/{date}-{title}/
    if images and not drive_folder_id:
        drive_folder_id = _ensure_drive_folder_path(
            drive, f"{date.today().isoformat()}-{doc_title}"
        )

    inserted = 0
    failed = 0
    errors: list[str] = []
    total = len(images)

    for i, img_info in enumerate(images):
        label = img_info["label"]
        file_path = img_info["file_path"]

        if not os.path.exists(file_path):
            msg = f"File not found: {file_path}"
            errors.append(msg)
            failed += 1
            if on_progress:
                on_progress(i + 1, total, label, "skip")
            continue

        try:
            # Upload image to Drive
            media = MediaFileUpload(file_path, mimetype=_guess_mime(file_path), resumable=True)
            upload_body: dict = {"name": Path(file_path).name}
            if drive_folder_id:
                upload_body["parents"] = [drive_folder_id]

            f = drive.files().create(
                body=upload_body, media_body=media, fields="id"
            ).execute()
            file_id = f["id"]

            # Insert via Apps Script
            result = script_service.scripts().run(
                scriptId=script_id,
                body={
                    "function": "insertImage",
                    "parameters": [document_id, file_id],
                    "devMode": True,
                },
            ).execute()

            if "error" in result:
                detail = result["error"].get("details", [{}])
                err_msg = detail[0].get("errorMessage", "unknown") if detail else "unknown"
                errors.append(f"{label}: {err_msg}")
                failed += 1
                if on_progress:
                    on_progress(i + 1, total, label, "fail")
            else:
                inserted += 1
                if on_progress:
                    on_progress(i + 1, total, label, "ok")

            time.sleep(rate_limit_delay)

        except Exception as e:
            errors.append(f"{label}: {str(e)[:200]}")
            failed += 1
            if on_progress:
                on_progress(i + 1, total, label, "error")

    return {
        "inserted": inserted,
        "failed": failed,
        "total": total,
        "folder_id": drive_folder_id,
        "errors": errors,
    }


def _guess_mime(file_path: str) -> str:
    """Guess MIME type from file extension."""
    ext = Path(file_path).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
    }.get(ext, "application/octet-stream")


def _print_progress(index: int, total: int, label: str, status: str) -> None:
    """Default progress printer."""
    icon = {"ok": "OK", "fail": "FAIL", "skip": "SKIP", "error": "ERR"}.get(status, "?")
    print(f"[{index}/{total}] {icon}: {label}")


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Insert images into Google Doc via Apps Script")
    parser.add_argument("--document-id", required=True, help="Google Doc ID")
    parser.add_argument("--images-json", required=True, help="JSON file: [{label, file_path}, ...]")
    parser.add_argument("--drive-folder-id", help="Drive folder for images (auto-creates if omitted)")
    parser.add_argument("--doc-title", default="untitled", help="Doc title (for auto folder name)")
    parser.add_argument("--delay", type=float, default=2.5, help="Seconds between API calls")
    parser.add_argument("--setup", action="store_true", help="Create/verify Apps Script project only")
    args = parser.parse_args()

    if args.setup:
        creds = get_credentials()
        script_service = build("script", "v1", credentials=creds)
        script_id = ensure_script_project(script_service)
        print(json.dumps({"script_id": script_id, "config_path": str(SCRIPT_CONFIG_PATH)}))
        return

    with open(args.images_json) as f:
        images = json.load(f)

    result = insert_images_into_doc(
        document_id=args.document_id,
        images=images,
        drive_folder_id=args.drive_folder_id,
        doc_title=args.doc_title,
        rate_limit_delay=args.delay,
        on_progress=_print_progress,
    )

    print(f"\nDone: {result['inserted']}/{result['total']} inserted, {result['failed']} failed")
    if result["errors"]:
        print(f"Errors: {result['errors'][:5]}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
