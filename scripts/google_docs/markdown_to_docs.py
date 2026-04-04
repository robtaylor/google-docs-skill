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
    """Entry point for the markdown-to-docs pipeline."""
    parser = _build_parser()
    args = parser.parse_args()

    # Validate arguments
    if args.document_id is None and args.title is None:
        parser.error("Either --title (new doc) or --document-id (existing) is required")

    # 1. Read file
    file_path = Path(args.file).resolve()
    if not file_path.exists():
        print(json.dumps({"status": "error", "error_code": "FILE_NOT_FOUND", "message": f"File not found: {args.file}"}))
        sys.exit(1)

    content = file_path.read_text(encoding="utf-8")
    base_dir = str(file_path.parent)

    # 2. Parse markdown
    parse_result = parse_markdown(content)

    # 3. Dry run: output parse stats and exit
    if args.dry_run:
        output = {
            "status": "dry_run",
            "stats": {
                "characters": len(parse_result.text),
                "format_requests": len(parse_result.format_requests),
                "images": len(parse_result.images),
                "tables": len(parse_result.tables),
            },
        }
        print(json.dumps(output, indent=2))
        return

    # 4. Authenticate
    docs_service = get_docs_service()

    # 5. Pre-process mermaid blocks to PNG (local rendering, no API calls)
    mermaid_count = 0
    image_files: list[dict] = []  # [{label, file_path}] for Apps Script insertion
    if parse_result.images:
        for img in parse_result.images:
            if img.source_type == "mermaid":
                import tempfile
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                tmp.close()
                try:
                    from google_docs.image_pipeline import render_mermaid
                    render_mermaid(img.source, tmp.name)
                    image_files.append({"label": img.alt_text or "Mermaid diagram", "file_path": tmp.name})
                    mermaid_count += 1
                except Exception as e:
                    print(f"Warning: mermaid render failed: {e}", file=sys.stderr)
            elif img.source_type == "file":
                from google_docs.image_pipeline import _resolve_file_path
                try:
                    resolved = _resolve_file_path(img.source, base_dir)
                    # Convert SVG to PNG if needed
                    if resolved.lower().endswith(".svg"):
                        png_path = resolved.rsplit(".", 1)[0] + ".png"
                        if os.path.exists(png_path):
                            resolved = png_path
                        else:
                            from google_docs.image_pipeline import _convert_svg_to_png
                            _convert_svg_to_png(resolved, png_path)
                            resolved = png_path
                    if os.path.exists(resolved):
                        image_files.append({"label": img.alt_text or img.source, "file_path": resolved})
                except (ValueError, FileNotFoundError) as e:
                    print(f"Warning: image skipped: {e}", file=sys.stderr)
            elif img.source_type == "url":
                pass  # URL images can't be inserted via Apps Script; skip

    # 6. Create or get document FIRST (need doc to exist before any requests)
    if args.document_id:
        document_id = args.document_id
        doc = _get_document(docs_service, document_id)
        title = doc.get("title", "Untitled")
    else:
        doc = _create_document(docs_service, args.title)
        document_id = doc["documentId"]
        title = args.title

    rate_limiter = RateLimiter()
    chunks_sent = 0
    total_requests = 0

    # 7. Insert text FIRST (must exist before format requests can reference it)
    insert_index = 1
    if args.document_id:
        insert_index = _get_end_index(doc, args.tab_id) - 1
        if insert_index < 1:
            insert_index = 1

    if parse_result.text:
        text_request = _build_insert_text_request(
            parse_result.text, insert_index, args.tab_id
        )
        _batch_update_with_retry(
            docs_service, document_id, [text_request], rate_limiter
        )
        chunks_sent += 1
        total_requests += 1

    # 8. Apply format + image requests (text now exists in doc)
    offset = insert_index - 1  # Shift parser indices if appending to existing doc

    format_requests = list(parse_result.format_requests)
    if offset > 0:
        format_requests = _offset_requests(format_requests, offset)

    def _get_request_index(req: dict) -> int:
        """Extract the index from any request type for sorting."""
        for action in req.values():
            if isinstance(action, dict):
                loc = action.get("location", {})
                if "index" in loc:
                    return loc["index"]
                rng = action.get("range", {})
                if "startIndex" in rng:
                    return rng["startIndex"]
        return 0

    # Send format requests (these don't depend on external URLs)
    format_requests = sorted(format_requests, key=_get_request_index, reverse=True)

    for chunk in chunk_requests(format_requests):
        _batch_update_with_retry(
            docs_service, document_id, chunk, rate_limiter
        )
        chunks_sent += 1

    total_requests += len(format_requests)

    # Insert images via Apps Script (bypasses Docs API URL/size limits)
    images_inserted = 0
    images_failed = 0
    if image_files:
        from google_docs.image_inserter import insert_images_into_doc, _print_progress
        img_result = insert_images_into_doc(
            document_id=document_id,
            images=image_files,
            drive_folder_id=args.drive_folder_id,
            doc_title=title,
            on_progress=_print_progress,
        )
        images_inserted = img_result["inserted"]
        images_failed = img_result["failed"]

    # 9. Insert tables AFTER text (reverse order, re-read between each)
    tables_inserted = 0
    if parse_result.tables:
        tables_inserted = _insert_tables(
            docs_service, document_id, parse_result.tables,
            args.tab_id, rate_limiter,
        )

    # 10. Output result
    result = {
        "status": "success",
        "document_id": document_id,
        "title": title,
        "web_view_link": f"https://docs.google.com/document/d/{document_id}/edit",
        "stats": {
            "chunks_sent": chunks_sent,
            "total_requests": total_requests,
            "images_uploaded": images_inserted + images_failed,
            "images_inserted": images_inserted,
            "images_failed": images_failed,
            "mermaid_rendered": mermaid_count,
            "tables_inserted": tables_inserted,
            "characters_inserted": len(parse_result.text),
        },
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
