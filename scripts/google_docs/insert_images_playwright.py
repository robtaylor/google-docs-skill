"""Insert images into a Google Doc using Playwright browser automation.

Bypasses the Docs API's 2KB URL / private-Drive limitation by automating
the Google Docs UI's file upload path — the same mechanism as paste or
Insert > Image > Upload from computer.

Usage:
    # First time: save auth state (opens browser for Google login)
    uv run python -m google_docs.insert_images_playwright --save-auth

    # Then insert images:
    uv run python -m google_docs.insert_images_playwright \
        --document-id <DOC_ID> \
        --images-json /tmp/images_manifest.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

AUTH_STATE_PATH = Path.home() / ".claude" / ".google" / "playwright_state.json"


def save_auth_state() -> None:
    """Open browser for Google login and save auth cookies."""
    from playwright.sync_api import sync_playwright

    print("Opening browser for Google login...")
    print("Please log in to your Google account, then close the browser.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chromium")
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://accounts.google.com")

        print("Waiting for login... (close browser tab when done)")
        try:
            # Wait for user to log in (check for myaccount URL or docs)
            page.wait_for_url("**/myaccount.google.com/**", timeout=300_000)
        except Exception:
            pass

        # Save storage state
        AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(AUTH_STATE_PATH))
        print(f"Auth state saved to {AUTH_STATE_PATH}")
        browser.close()


def insert_images(
    document_id: str,
    images: list[dict],
    headless: bool = True,
) -> dict:
    """Insert images into a Google Doc via Playwright browser upload.

    Each image is inserted at the END of the document (appended).
    The text/formatting should already be in place from the API pipeline.

    Args:
        document_id: Google Doc ID
        images: List of {label: str, file_path: str} dicts
        headless: Run headless

    Returns:
        Stats dict
    """
    from playwright.sync_api import sync_playwright

    if not AUTH_STATE_PATH.exists():
        print("No auth state. Run with --save-auth first.", file=sys.stderr)
        return {"inserted": 0, "failed": len(images), "errors": ["No auth state"]}

    doc_url = f"https://docs.google.com/document/d/{document_id}/edit"
    inserted = 0
    failed = 0
    errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, channel="chromium")
        context = browser.new_context(storage_state=str(AUTH_STATE_PATH))
        page = context.new_page()

        print(f"Opening doc: {doc_url}")
        page.goto(doc_url, wait_until="domcontentloaded", timeout=60_000)
        time.sleep(8)  # Google Docs needs extra time to fully initialize

        if "accounts.google.com" in page.url:
            print("Auth expired. Run --save-auth again.", file=sys.stderr)
            browser.close()
            return {"inserted": 0, "failed": len(images), "errors": ["Auth expired"]}

        # Wait for the document editor to be ready
        try:
            page.wait_for_selector(".kix-appview-editor", timeout=30_000)
        except Exception:
            # Fallback: wait for any content area
            page.wait_for_selector('[contenteditable="true"]', timeout=15_000)
        time.sleep(3)

        for i, img_info in enumerate(images):
            label = img_info["label"]
            file_path = img_info["file_path"]

            if not os.path.exists(file_path):
                errors.append(f"File not found: {file_path}")
                failed += 1
                continue

            try:
                # Move cursor to end of document
                page.keyboard.press("Meta+End" if sys.platform == "darwin" else "Control+End")
                time.sleep(0.3)

                # Add a newline before image
                page.keyboard.press("Enter")
                time.sleep(0.2)

                # Use the Insert > Image > Upload from computer flow
                # Trigger via keyboard shortcut or menu
                # Google Docs doesn't have a direct keyboard shortcut for image insert,
                # so we use the menu bar

                # Click Insert menu
                page.click('[id="docs-insert-menu"]', timeout=5_000)
                time.sleep(0.5)

                # Click Image option
                page.click(':text("Image")', timeout=3_000)
                time.sleep(0.5)

                # Click "Upload from computer" — triggers file chooser
                with page.expect_file_chooser(timeout=10_000) as fc_info:
                    page.click(':text("Upload from computer")', timeout=3_000)
                fc_info.value.set_files(file_path)

                # Wait for upload + rendering
                time.sleep(4)

                inserted += 1
                print(f"[{i+1}/{len(images)}] Inserted: {label}")

            except Exception as e:
                err_msg = f"{label}: {str(e)[:100]}"
                errors.append(err_msg)
                failed += 1
                print(f"[{i+1}/{len(images)}] FAILED: {err_msg}", file=sys.stderr)

                # Try to dismiss any open dialogs/menus
                for _ in range(3):
                    page.keyboard.press("Escape")
                    time.sleep(0.3)

        # Save auth state (cookies may have refreshed)
        context.storage_state(path=str(AUTH_STATE_PATH))
        browser.close()

    return {"inserted": inserted, "failed": failed, "errors": errors}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Insert images into Google Doc via browser")
    parser.add_argument("--save-auth", action="store_true", help="Open browser to save Google auth state")
    parser.add_argument("--document-id", help="Google Doc ID")
    parser.add_argument("--images-json", help="JSON file: [{label, file_path}, ...]")
    parser.add_argument("--headless", action="store_true", default=False)
    args = parser.parse_args()

    if args.save_auth:
        save_auth_state()
        return

    if not args.document_id or not args.images_json:
        parser.error("--document-id and --images-json required (or use --save-auth)")

    with open(args.images_json) as f:
        images = json.load(f)

    result = insert_images(
        document_id=args.document_id,
        images=images,
        headless=args.headless,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
