"""Markdown-to-Google-Docs pipeline for large documents."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from google_docs.auth import get_docs_service
from google_docs.markdown_parser import parse_markdown


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_requests(
    requests: list[dict], max_bytes: int = 4_000_000
) -> list[list[dict]]:
    """Split requests into chunks that fit within max_bytes when JSON-serialized."""
    chunks: list[list[dict]] = []
    current_chunk: list[dict] = []
    current_size = 0

    for req in requests:
        req_size = len(json.dumps(req).encode("utf-8"))
        if current_size + req_size > max_bytes and current_chunk:
            chunks = [*chunks, current_chunk]
            current_chunk = []
            current_size = 0
        current_chunk = [*current_chunk, req]
        current_size += req_size

    if current_chunk:
        chunks = [*chunks, current_chunk]
    return chunks


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Ensures max writes/min stays below the Google API limit."""

    def __init__(self, max_per_minute: int = 55) -> None:
        self._timestamps: list[float] = []
        self._max_per_minute = max_per_minute

    def wait_if_needed(self) -> None:
        now = time.time()
        # Immutable filter: build new list
        self._timestamps = [t for t in self._timestamps if now - t < 60]
        if len(self._timestamps) >= self._max_per_minute:
            sleep_time = 60 - (now - self._timestamps[0]) + 0.1
            time.sleep(sleep_time)
        self._timestamps = [*self._timestamps, time.time()]


# ---------------------------------------------------------------------------
# Batch update with retry
# ---------------------------------------------------------------------------

def _batch_update_with_retry(
    docs_service: object,
    document_id: str,
    requests: list[dict],
    rate_limiter: RateLimiter,
    max_retries: int = 7,
) -> dict:
    """Execute batchUpdate with exponential backoff on 429 errors."""
    rate_limiter.wait_if_needed()

    backoff = 1.0
    for attempt in range(max_retries):
        try:
            result = (
                docs_service.documents()
                .batchUpdate(
                    documentId=document_id,
                    body={"requests": requests},
                )
                .execute()
            )
            return result
        except Exception as exc:  # noqa: BLE001
            error_str = str(exc)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                if attempt < max_retries - 1:
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 64.0)
                    continue
            raise
    raise RuntimeError("Max retries exceeded for batchUpdate")


# ---------------------------------------------------------------------------
# Document creation / lookup
# ---------------------------------------------------------------------------

def _create_document(docs_service: object, title: str) -> dict:
    """Create a new Google Doc and return its metadata."""
    return docs_service.documents().create(body={"title": title}).execute()


def _get_document(
    docs_service: object, document_id: str, tab_id: str | None = None
) -> dict:
    """Fetch document metadata."""
    doc = docs_service.documents().get(documentId=document_id).execute()
    return doc


def _get_end_index(doc: dict, tab_id: str | None = None) -> int:
    """Get the end index of the document body (or specific tab)."""
    if tab_id is not None:
        for tab in doc.get("tabs", []):
            if tab.get("tabProperties", {}).get("tabId") == tab_id:
                body = tab.get("documentTab", {}).get("body", {})
                content = body.get("content", [])
                if content:
                    return content[-1].get("endIndex", 1)
                return 1
        raise ValueError(f"Tab '{tab_id}' not found in document")

    body = doc.get("body", {})
    content = body.get("content", [])
    if content:
        return content[-1].get("endIndex", 1)
    return 1


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------


def _offset_requests(requests: list[dict], offset: int) -> list[dict]:
    """Shift all index/range references in requests by offset (for appending to existing doc)."""
    import copy
    shifted: list[dict] = []
    for req in requests:
        new_req = copy.deepcopy(req)
        for action in new_req.values():
            if isinstance(action, dict):
                loc = action.get("location")
                if loc and "index" in loc:
                    loc["index"] += offset
                rng = action.get("range")
                if rng:
                    if "startIndex" in rng:
                        rng["startIndex"] += offset
                    if "endIndex" in rng:
                        rng["endIndex"] += offset
        shifted.append(new_req)
    return shifted


# ---------------------------------------------------------------------------
# Build requests
# ---------------------------------------------------------------------------

def _build_insert_text_request(
    text: str, index: int, tab_id: str | None = None
) -> dict:
    """Build an InsertText request."""
    location: dict = {"index": index}
    if tab_id is not None:
        location["tabId"] = tab_id
    return {"insertText": {"text": text, "location": location}}


def _build_image_requests(
    resolved_images: list[dict], tab_id: str | None = None
) -> list[dict]:
    """Build InsertInlineImage requests for resolved images."""
    requests: list[dict] = []
    for img in resolved_images:
        location: dict = {"index": img["index"]}
        if tab_id is not None:
            location["tabId"] = tab_id

        inline_obj: dict = {
            "uri": img["url"],
            "objectSize": {},
        }
        if img.get("width") is not None:
            inline_obj["objectSize"]["width"] = {
                "magnitude": img["width"],
                "unit": "PT",
            }
        if img.get("height") is not None:
            inline_obj["objectSize"]["height"] = {
                "magnitude": img["height"],
                "unit": "PT",
            }

        requests = [*requests, {
            "insertInlineImage": {
                "location": location,
                **inline_obj,
            }
        }]
    return requests


def _build_table_request(
    table: object, tab_id: str | None = None
) -> dict:
    """Build an InsertTable request."""
    location: dict = {"index": table.index}
    if tab_id is not None:
        location["tabId"] = tab_id
    return {
        "insertTable": {
            "rows": table.num_rows,
            "columns": table.num_cols,
            "location": location,
        }
    }


# ---------------------------------------------------------------------------
# Table insertion (post-text)
# ---------------------------------------------------------------------------

def _insert_tables(
    docs_service: object,
    document_id: str,
    tables: list,
    tab_id: str | None,
    rate_limiter: RateLimiter,
) -> int:
    """Insert tables after text, in reverse order, re-reading doc between each."""
    sorted_tables = sorted(tables, key=lambda t: t.index, reverse=True)
    count = 0

    for table in sorted_tables:
        # Insert the table structure
        req = _build_table_request(table, tab_id)
        _batch_update_with_retry(
            docs_service, document_id, [req], rate_limiter
        )

        # Re-read document to find table cell indices
        doc = _get_document(docs_service, document_id)
        _populate_table_cells(
            docs_service, document_id, doc, table, tab_id, rate_limiter
        )
        count += 1

    return count


def _populate_table_cells(
    docs_service: object,
    document_id: str,
    doc: dict,
    table: object,
    tab_id: str | None,
    rate_limiter: RateLimiter,
) -> None:
    """Populate table cells with content after table insertion."""
    # Find the table in the document body
    body = doc.get("body", {})
    if tab_id is not None:
        for tab in doc.get("tabs", []):
            if tab.get("tabProperties", {}).get("tabId") == tab_id:
                body = tab.get("documentTab", {}).get("body", {})
                break

    # Find table elements and populate cells in reverse order
    content = body.get("content", [])
    cell_requests: list[dict] = []

    for element in content:
        tbl = element.get("table")
        if tbl is None:
            continue

        rows_data = tbl.get("tableRows", [])
        if len(rows_data) != table.num_rows:
            continue

        # Build cell insert requests in reverse order
        for row_idx in range(table.num_rows - 1, -1, -1):
            cells = rows_data[row_idx].get("tableCells", [])
            for col_idx in range(table.num_cols - 1, -1, -1):
                if row_idx < len(table.rows) and col_idx < len(table.rows[row_idx]):
                    cell_text = table.rows[row_idx][col_idx]
                    if not cell_text:
                        continue
                    cell_content = cells[col_idx].get("content", [])
                    if cell_content:
                        cell_start = cell_content[0].get("startIndex", 0)
                        location: dict = {"index": cell_start}
                        if tab_id is not None:
                            location["tabId"] = tab_id
                        cell_requests = [*cell_requests, {
                            "insertText": {
                                "text": cell_text,
                                "location": location,
                            }
                        }]
        # Only process the last matching table
        break

    if cell_requests:
        _batch_update_with_retry(
            docs_service, document_id, cell_requests, rate_limiter
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a Markdown file to a Google Doc."
    )
    parser.add_argument(
        "--file", required=True, type=str, help="Path to the markdown file"
    )
    parser.add_argument(
        "--title", type=str, default=None, help="Title for a new document"
    )
    parser.add_argument(
        "--document-id", type=str, default=None,
        help="Existing document ID (appends to end)"
    )
    parser.add_argument(
        "--tab-id", type=str, default=None, help="Specific tab ID"
    )
    parser.add_argument(
        "--drive-folder-id", type=str, default=None,
        help="Drive folder for uploaded images"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse only, no API calls"
    )
    return parser


def main() -> None:
    """Entry point for the markdown-to-docs pipeline.

    Uses Apps Script for ALL content insertion (text + formatting + images + tables)
    in a single sequential pass. Images are inserted inline where they appear
    in the markdown, not appended to the end.
    """
    from google_docs.markdown_to_blocks import markdown_to_blocks
    from google_docs.appscript_builder import (
        build_doc_from_blocks,
        upload_image_to_drive,
        _ensure_drive_folder,
        _find_or_create_folder,
    )
    from google_docs.image_pipeline import render_mermaid, _resolve_file_path

    parser = _build_parser()
    args = parser.parse_args()

    if args.document_id is None and args.title is None:
        parser.error("Either --title (new doc) or --document-id (existing) is required")

    # 1. Read file
    file_path = Path(args.file).resolve()
    if not file_path.exists():
        print(json.dumps({"status": "error", "error_code": "FILE_NOT_FOUND",
                          "message": f"File not found: {args.file}"}))
        sys.exit(1)

    content = file_path.read_text(encoding="utf-8")
    base_dir = str(file_path.parent)
    doc_title = args.title or "untitled"

    # 2. Parse markdown into blocks
    blocks = markdown_to_blocks(content)

    # 3. Dry run
    if args.dry_run:
        block_counts: dict[str, int] = {}
        for b in blocks:
            block_counts[b["type"]] = block_counts.get(b["type"], 0) + 1
        print(json.dumps({"status": "dry_run", "blocks": len(blocks), "by_type": block_counts}, indent=2))
        return

    # 4. Authenticate + create doc
    from google_docs.auth import get_credentials, get_docs_service
    from googleapiclient.discovery import build as api_build

    creds = get_credentials()
    docs_service = get_docs_service()
    drive = api_build("drive", "v3", credentials=creds)

    if args.document_id:
        document_id = args.document_id
        doc = docs_service.documents().get(documentId=document_id).execute()
        doc_title = doc.get("title", doc_title)
    else:
        doc = docs_service.documents().create(body={"title": doc_title}).execute()
        document_id = doc["documentId"]

    print(f"Doc: https://docs.google.com/document/d/{document_id}/edit")

    # 5. Process images: render mermaid, resolve file paths, upload to Drive
    image_blocks = [b for b in blocks if b["type"] == "image"]
    drive_folder_id = args.drive_folder_id

    if image_blocks:
        if not drive_folder_id:
            drive_folder_id = _ensure_drive_folder(drive, doc_title)
        print(f"Uploading {len(image_blocks)} images to Drive...")

        for i, block in enumerate(image_blocks):
            src_type = block.get("source_type", "")
            source = block.get("source", "")

            try:
                if src_type == "mermaid":
                    import tempfile
                    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                    tmp.close()
                    render_mermaid(source, tmp.name)
                    file_id = upload_image_to_drive(drive, tmp.name, drive_folder_id)
                    os.unlink(tmp.name)
                    block["driveFileId"] = file_id
                    print(f"  [{i+1}/{len(image_blocks)}] Mermaid → {file_id}")

                elif src_type == "file":
                    resolved = _resolve_file_path(source, base_dir)
                    if resolved.lower().endswith(".svg"):
                        png = resolved.rsplit(".", 1)[0] + ".png"
                        resolved = png if os.path.exists(png) else resolved
                    if os.path.exists(resolved):
                        file_id = upload_image_to_drive(drive, resolved, drive_folder_id)
                        block["driveFileId"] = file_id
                        print(f"  [{i+1}/{len(image_blocks)}] {Path(resolved).name} → {file_id}")
                    else:
                        print(f"  [{i+1}/{len(image_blocks)}] SKIP (missing): {source}", file=sys.stderr)

                elif src_type == "url":
                    print(f"  [{i+1}/{len(image_blocks)}] SKIP (URL): {source}", file=sys.stderr)

            except Exception as e:
                print(f"  [{i+1}/{len(image_blocks)}] ERROR: {e}", file=sys.stderr)

    # 6. Build document via Apps Script (text + formatting + images, all in order)
    def _progress(msg: str) -> None:
        print(msg)

    stats = build_doc_from_blocks(
        document_id=document_id,
        blocks=blocks,
        on_progress=_progress,
    )

    # 7. Output result
    result = {
        "status": "success",
        "document_id": document_id,
        "title": doc_title,
        "web_view_link": f"https://docs.google.com/document/d/{document_id}/edit",
        "stats": stats,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
