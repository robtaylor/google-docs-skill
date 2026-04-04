#!/usr/bin/env python3
"""Google Docs Manager - Document Operations CLI (Python port of docs_manager.rb)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from google_docs.auth import get_docs_service, get_drive_service
from google_docs.markdown_parser import parse_markdown

# Exit codes
EXIT_SUCCESS = 0
EXIT_OPERATION_FAILED = 1
EXIT_AUTH_ERROR = 2
EXIT_API_ERROR = 3
EXIT_INVALID_ARGS = 4


def output_json(data: dict[str, Any]) -> None:
    """Print JSON to stdout."""
    print(json.dumps(data, indent=2, default=str))


def flatten_tabs(tabs: list[Any]) -> list[Any]:
    """Recursively flatten tabs tree into a flat list."""
    result: list[Any] = []
    for tab in tabs:
        result.append(tab)
        child_tabs = tab.get("childTabs", []) if isinstance(tab, dict) else []
        result.extend(flatten_tabs(child_tabs))
    return result


def _tab_props(tab: Any) -> dict[str, Any]:
    """Get tabProperties dict from a tab."""
    if isinstance(tab, dict):
        return tab.get("tabProperties", {})
    return {}


def _tab_id(tab: Any) -> str | None:
    return _tab_props(tab).get("tabId")


def _tab_title(tab: Any) -> str | None:
    return _tab_props(tab).get("title")


def _tab_index(tab: Any) -> int | None:
    return _tab_props(tab).get("index")


def _get_body_content(tab: Any) -> list[Any]:
    """Get body content from a tab's documentTab."""
    if isinstance(tab, dict):
        return tab.get("documentTab", {}).get("body", {}).get("content", [])
    return []


def _find_tab(tabs: list[Any], tab_id: str) -> Any | None:
    """Find a tab by ID in a flat list of tabs."""
    for tab in tabs:
        if _tab_id(tab) == tab_id:
            return tab
    return None


def _extract_paragraph_text(paragraph: dict[str, Any]) -> str:
    """Extract text from a paragraph element."""
    elements = paragraph.get("elements", [])
    return "".join(
        elem.get("textRun", {}).get("content", "")
        for elem in elements
    )


def _extract_table_text(table: dict[str, Any]) -> str:
    """Extract text from a table element."""
    rows: list[str] = []
    for row in table.get("tableRows", []):
        cells = row.get("tableCells", [])
        cell_texts = [
            _extract_text_content(c.get("content", []))
            for c in cells
        ]
        rows.append(" | ".join(cell_texts))
    return "\n".join(rows)


def _extract_text_content(content_elements: list[Any]) -> str:
    """Extract text content from document body content elements."""
    parts: list[str] = []
    for element in content_elements:
        if element.get("paragraph"):
            parts.append(_extract_paragraph_text(element["paragraph"]))
        elif element.get("table"):
            parts.append(_extract_table_text(element["table"]))
    return "\n".join(parts)


def _batch_update(docs_service: Any, document_id: str, requests: list[dict[str, Any]]) -> Any:
    """Execute a batchUpdate on the docs service."""
    return docs_service.documents().batchUpdate(
        documentId=document_id,
        body={"requests": requests},
    ).execute()


def _read_stdin_json() -> dict[str, Any]:
    """Read and parse JSON from stdin."""
    raw = sys.stdin.read()
    if not raw.strip():
        output_json({
            "status": "error",
            "error_code": "EMPTY_INPUT",
            "message": "No JSON input provided on stdin",
        })
        sys.exit(EXIT_INVALID_ARGS)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        output_json({
            "status": "error",
            "error_code": "INVALID_JSON",
            "message": f"Invalid JSON on stdin: {e}",
        })
        sys.exit(EXIT_INVALID_ARGS)


def _validate_fields(data: dict[str, Any], required: list[str]) -> None:
    """Validate required fields exist in input data."""
    missing = [f for f in required if f not in data or data[f] is None]
    if missing:
        output_json({
            "status": "error",
            "error_code": "MISSING_REQUIRED_FIELDS",
            "message": f"Required fields: {', '.join(required)}",
        })
        sys.exit(EXIT_INVALID_ARGS)


def _handle_error(exc: Exception, operation: str, error_code: str, message: str) -> None:
    """Handle errors with JSON output matching Ruby format."""
    error_message = str(exc)
    is_api_error = type(exc).__name__ == "HttpError"
    if is_api_error:
        output_json({
            "status": "error",
            "error_code": "API_ERROR",
            "operation": operation,
            "message": f"Google Docs API error: {error_message}",
        })
        sys.exit(EXIT_API_ERROR)
    else:
        output_json({
            "status": "error",
            "error_code": error_code,
            "operation": operation,
            "message": f"{message}: {error_message}",
        })
        sys.exit(EXIT_OPERATION_FAILED)


def _offset_format_request(req: dict[str, Any], offset: int) -> dict[str, Any]:
    """Create a new format request with indices offset by the given amount."""
    new_req: dict[str, Any] = {}
    for key, value in req.items():
        if isinstance(value, dict) and "range" in value:
            new_value = dict(value)
            old_range = value["range"]
            new_value["range"] = {
                **old_range,
                "startIndex": old_range.get("startIndex", 0) + offset,
                "endIndex": old_range.get("endIndex", 0) + offset,
            }
            new_req[key] = new_value
        else:
            new_req[key] = value
    return new_req


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

def cmd_read(docs_service: Any, document_id: str, tab_id: str | None = None) -> None:
    """Read document content."""
    try:
        document = docs_service.documents().get(
            documentId=document_id, includeTabsContent=True
        ).execute()

        tabs = flatten_tabs(document.get("tabs", []))

        if tab_id:
            tab = _find_tab(tabs, tab_id)
            if tab is None:
                available = [{"id": _tab_id(t), "title": _tab_title(t)} for t in tabs]
                output_json({
                    "status": "error",
                    "error_code": "TAB_NOT_FOUND",
                    "operation": "read",
                    "message": f"Tab '{tab_id}' not found. Available tabs: {available}",
                })
                sys.exit(EXIT_OPERATION_FAILED)
            content = _extract_text_content(_get_body_content(tab))
            output_json({
                "status": "success",
                "operation": "read",
                "document_id": document.get("documentId"),
                "title": document.get("title"),
                "tab_id": _tab_id(tab),
                "tab_title": _tab_title(tab),
                "content": content,
                "revision_id": document.get("revisionId"),
            })
        elif len(tabs) > 1:
            tab_contents = [
                {
                    "tab_id": _tab_id(t),
                    "tab_title": _tab_title(t),
                    "content": _extract_text_content(_get_body_content(t)),
                }
                for t in tabs
            ]
            output_json({
                "status": "success",
                "operation": "read",
                "document_id": document.get("documentId"),
                "title": document.get("title"),
                "tab_count": len(tabs),
                "tabs": tab_contents,
                "revision_id": document.get("revisionId"),
            })
        else:
            body_content = (
                _get_body_content(tabs[0]) if tabs
                else document.get("body", {}).get("content", [])
            )
            content = _extract_text_content(body_content)
            output_json({
                "status": "success",
                "operation": "read",
                "document_id": document.get("documentId"),
                "title": document.get("title"),
                "content": content,
                "revision_id": document.get("revisionId"),
            })
    except Exception as e:
        _handle_error(e, "read", "READ_FAILED", "Failed to read document")


def cmd_structure(docs_service: Any, document_id: str, tab_id: str | None = None) -> None:
    """Get document structure (headings)."""
    try:
        document = docs_service.documents().get(
            documentId=document_id, includeTabsContent=True
        ).execute()

        tabs = flatten_tabs(document.get("tabs", []))

        def extract_structure(content_elements: list[Any]) -> list[dict[str, Any]]:
            structure: list[dict[str, Any]] = []
            for element in content_elements:
                para = element.get("paragraph")
                if not para:
                    continue
                para_style = para.get("paragraphStyle", {})
                style_type = para_style.get("namedStyleType", "")
                if style_type.startswith("HEADING_"):
                    level = int(style_type.split("_")[-1])
                    text = _extract_paragraph_text(para)
                    structure.append({
                        "level": level,
                        "text": text,
                        "start_index": element.get("startIndex"),
                        "end_index": element.get("endIndex"),
                    })
            return structure

        if tab_id:
            tab = _find_tab(tabs, tab_id)
            if tab is None:
                available = [{"id": _tab_id(t), "title": _tab_title(t)} for t in tabs]
                output_json({
                    "status": "error",
                    "error_code": "TAB_NOT_FOUND",
                    "operation": "structure",
                    "message": f"Tab '{tab_id}' not found. Available tabs: {available}",
                })
                sys.exit(EXIT_OPERATION_FAILED)
            structure = extract_structure(_get_body_content(tab))
            output_json({
                "status": "success",
                "operation": "structure",
                "document_id": document.get("documentId"),
                "title": document.get("title"),
                "tab_id": _tab_id(tab),
                "tab_title": _tab_title(tab),
                "structure": structure,
            })
        elif len(tabs) > 1:
            tab_structures = [
                {
                    "tab_id": _tab_id(t),
                    "tab_title": _tab_title(t),
                    "structure": extract_structure(_get_body_content(t)),
                }
                for t in tabs
            ]
            output_json({
                "status": "success",
                "operation": "structure",
                "document_id": document.get("documentId"),
                "title": document.get("title"),
                "tab_count": len(tabs),
                "tabs": tab_structures,
            })
        else:
            body_content = (
                _get_body_content(tabs[0]) if tabs
                else document.get("body", {}).get("content", [])
            )
            structure = extract_structure(body_content)
            output_json({
                "status": "success",
                "operation": "structure",
                "document_id": document.get("documentId"),
                "title": document.get("title"),
                "structure": structure,
            })
    except Exception as e:
        _handle_error(e, "structure", "STRUCTURE_FAILED", "Failed to get document structure")


def cmd_list_tabs(docs_service: Any, document_id: str) -> None:
    """List all tabs in a document."""
    try:
        document = docs_service.documents().get(
            documentId=document_id, includeTabsContent=True
        ).execute()

        tabs = flatten_tabs(document.get("tabs", []))
        tab_info = [
            {"tab_id": _tab_id(t), "title": _tab_title(t), "index": _tab_index(t)}
            for t in tabs
        ]

        output_json({
            "status": "success",
            "operation": "list-tabs",
            "document_id": document.get("documentId"),
            "title": document.get("title"),
            "tab_count": len(tabs),
            "tabs": tab_info,
        })
    except Exception as e:
        _handle_error(e, "list-tabs", "LIST_TABS_FAILED", "Failed to list tabs")


def cmd_insert(docs_service: Any, document_id: str, text: str,
               index: int = 1, tab_id: str | None = None) -> None:
    """Insert text at specific index."""
    try:
        location: dict[str, Any] = {"index": index}
        if tab_id:
            location["tabId"] = tab_id

        requests = [{"insertText": {"location": location, "text": text}}]
        result = _batch_update(docs_service, document_id, requests)

        output_json({
            "status": "success",
            "operation": "insert",
            "document_id": document_id,
            "inserted_at": index,
            "text_length": len(text),
            "revision_id": result.get("writeControl", {}).get("requiredRevisionId"),
        })
    except Exception as e:
        _handle_error(e, "insert", "INSERT_FAILED", "Failed to insert text")


def cmd_append(docs_service: Any, document_id: str, text: str,
               tab_id: str | None = None) -> None:
    """Append text to end of document."""
    try:
        document = docs_service.documents().get(
            documentId=document_id,
            includeTabsContent=bool(tab_id),
        ).execute()

        if tab_id:
            tabs = flatten_tabs(document.get("tabs", []))
            tab = _find_tab(tabs, tab_id)
            body_content = _get_body_content(tab) if tab else []
            end_index = body_content[-1].get("endIndex", 2) - 1 if body_content else 1
        else:
            body_content = document.get("body", {}).get("content", [])
            end_index = body_content[-1].get("endIndex", 2) - 1 if body_content else 1

        location: dict[str, Any] = {"index": end_index}
        if tab_id:
            location["tabId"] = tab_id

        requests = [{"insertText": {"location": location, "text": text}}]
        result = _batch_update(docs_service, document_id, requests)

        output_json({
            "status": "success",
            "operation": "append",
            "document_id": document_id,
            "appended_at": end_index,
            "text_length": len(text),
            "revision_id": result.get("documentId"),
        })
    except Exception as e:
        _handle_error(e, "append", "APPEND_FAILED", "Failed to append text")


def cmd_replace(docs_service: Any, document_id: str, find: str, replace: str,
                match_case: bool = False) -> None:
    """Find and replace text."""
    try:
        requests = [{
            "replaceAllText": {
                "containsText": {"text": find, "matchCase": match_case},
                "replaceText": replace,
            }
        }]
        result = _batch_update(docs_service, document_id, requests)

        replies = result.get("replies", [])
        occurrences = 0
        if replies:
            occurrences = replies[0].get("replaceAllText", {}).get("occurrencesChanged", 0)

        output_json({
            "status": "success",
            "operation": "replace",
            "document_id": document_id,
            "find": find,
            "replace": replace,
            "occurrences": occurrences,
        })
    except Exception as e:
        _handle_error(e, "replace", "REPLACE_FAILED", "Failed to replace text")


def cmd_format(docs_service: Any, document_id: str, start_index: int, end_index: int,
               bold: bool | None = None, italic: bool | None = None,
               underline: bool | None = None, tab_id: str | None = None) -> None:
    """Format text (bold, italic, underline)."""
    try:
        text_style: dict[str, Any] = {}
        if bold is not None:
            text_style["bold"] = bold
        if italic is not None:
            text_style["italic"] = italic
        if underline is not None:
            text_style["underline"] = underline

        range_dict: dict[str, Any] = {"startIndex": start_index, "endIndex": end_index}
        if tab_id:
            range_dict["tabId"] = tab_id

        requests = [{
            "updateTextStyle": {
                "range": range_dict,
                "textStyle": text_style,
                "fields": ",".join(text_style.keys()),
            }
        }]
        _batch_update(docs_service, document_id, requests)

        output_json({
            "status": "success",
            "operation": "format",
            "document_id": document_id,
            "range": {"start": start_index, "end": end_index},
            "formatting": text_style,
        })
    except Exception as e:
        _handle_error(e, "format", "FORMAT_FAILED", "Failed to format text")


def cmd_page_break(docs_service: Any, document_id: str, index: int,
                   tab_id: str | None = None) -> None:
    """Insert page break."""
    try:
        location: dict[str, Any] = {"index": index}
        if tab_id:
            location["tabId"] = tab_id

        requests = [{"insertPageBreak": {"location": location}}]
        _batch_update(docs_service, document_id, requests)

        output_json({
            "status": "success",
            "operation": "page_break",
            "document_id": document_id,
            "inserted_at": index,
        })
    except Exception as e:
        _handle_error(e, "page_break", "PAGE_BREAK_FAILED", "Failed to insert page break")


def cmd_create(docs_service: Any, title: str, content: str | None = None) -> None:
    """Create new document."""
    try:
        result = docs_service.documents().create(body={"title": title}).execute()
        document_id = result.get("documentId")

        if content:
            requests = [{"insertText": {"location": {"index": 1}, "text": content}}]
            _batch_update(docs_service, document_id, requests)

        output_json({
            "status": "success",
            "operation": "create",
            "document_id": document_id,
            "title": result.get("title"),
            "revision_id": result.get("revisionId"),
        })
    except Exception as e:
        _handle_error(e, "create", "CREATE_FAILED", "Failed to create document")


def cmd_create_from_markdown(docs_service: Any, title: str, markdown: str) -> None:
    """Create document from markdown with proper formatting."""
    try:
        result = docs_service.documents().create(body={"title": title}).execute()
        document_id = result.get("documentId")

        parsed = parse_markdown(markdown)

        if parsed.text:
            requests = [{"insertText": {"location": {"index": 1}, "text": parsed.text}}]
            _batch_update(docs_service, document_id, requests)

        format_requests = list(reversed(parsed.format_requests))
        if format_requests:
            _batch_update(docs_service, document_id, format_requests)

        # Insert tables in reverse order, re-read doc between each
        tables = parsed.tables or []
        for table_info in reversed(tables):
            _insert_table_internal(
                docs_service,
                document_id=document_id,
                rows=table_info.num_rows,
                cols=table_info.num_cols,
                index=table_info.index,
                data=[list(row) for row in table_info.rows],
            )

        output_json({
            "status": "success",
            "operation": "create_from_markdown",
            "document_id": document_id,
            "title": title,
            "revision_id": result.get("revisionId"),
            "tables_inserted": len(tables),
        })
    except Exception as e:
        _handle_error(e, "create_from_markdown", "CREATE_FAILED", "Failed to create document")


def cmd_create_with_tabs(docs_service: Any, title: str, tabs_def: list[dict[str, Any]]) -> None:
    """Create document with multiple tabs."""
    try:
        result = docs_service.documents().create(body={"title": title}).execute()
        document_id = result.get("documentId")

        doc = docs_service.documents().get(
            documentId=document_id, includeTabsContent=True
        ).execute()
        doc_tabs = doc.get("tabs", [])
        first_tab_id = doc_tabs[0].get("tabProperties", {}).get("tabId") if doc_tabs else None

        tab_results: list[dict[str, Any]] = []

        # Rename first tab if title provided
        if tabs_def:
            first_def = tabs_def[0]
            if first_def.get("title"):
                rename_requests = [{
                    "updateDocumentTab": {
                        "tabProperties": {"tabId": first_tab_id, "title": first_def["title"]},
                        "fields": "title",
                    }
                }]
                _batch_update(docs_service, document_id, rename_requests)
            tab_results.append({
                "tab_id": first_tab_id,
                "title": first_def.get("title", "Tab 1"),
            })

        # Create additional tabs
        for tab_def in tabs_def[1:]:
            tab_props: dict[str, Any] = {}
            if tab_def.get("title"):
                tab_props["title"] = tab_def["title"]
            add_requests = [{"addDocumentTab": {"tabProperties": tab_props}}]
            add_result = _batch_update(docs_service, document_id, add_requests)
            replies = add_result.get("replies", [])
            new_tab_data = (
                replies[0].get("addDocumentTab", {}).get("tab", {}) if replies else {}
            )
            new_tp = new_tab_data.get("tabProperties", {})
            tab_results.append({"tab_id": new_tp.get("tabId"), "title": new_tp.get("title")})

        # Insert content into each tab
        for idx, tab_def in enumerate(tabs_def):
            if idx >= len(tab_results):
                break
            current_tab_id = tab_results[idx].get("tab_id")
            if not current_tab_id:
                continue
            if tab_def.get("markdown"):
                _insert_content_to_tab(docs_service, document_id, current_tab_id, tab_def["markdown"])
            elif tab_def.get("content"):
                _insert_text_to_tab(docs_service, document_id, current_tab_id, tab_def["content"])

        output_json({
            "status": "success",
            "operation": "create_with_tabs",
            "document_id": document_id,
            "title": title,
            "tabs": tab_results,
        })
    except Exception as e:
        _handle_error(e, "create_with_tabs", "CREATE_WITH_TABS_FAILED",
                      "Failed to create document with tabs")


def cmd_insert_from_markdown(docs_service: Any, document_id: str, markdown: str,
                             index: int | None = None, tab_id: str | None = None) -> None:
    """Insert markdown with formatting into existing document."""
    try:
        if index is None:
            document = docs_service.documents().get(
                documentId=document_id,
                includeTabsContent=bool(tab_id),
            ).execute()
            if tab_id:
                tabs = flatten_tabs(document.get("tabs", []))
                tab = _find_tab(tabs, tab_id)
                body_content = _get_body_content(tab) if tab else []
                index = body_content[-1].get("endIndex", 2) - 1 if body_content else 1
            else:
                body_content = document.get("body", {}).get("content", [])
                index = body_content[-1].get("endIndex", 2) - 1 if body_content else 1

        parsed = parse_markdown(markdown)

        location: dict[str, Any] = {"index": index}
        if tab_id:
            location["tabId"] = tab_id

        if parsed.text:
            requests = [{"insertText": {"location": location, "text": parsed.text}}]
            _batch_update(docs_service, document_id, requests)

        # Adjust format indices for insertion point offset
        offset = index - 1
        adjusted_requests = [_offset_format_request(req, offset) for req in parsed.format_requests]

        if adjusted_requests:
            _batch_update(docs_service, document_id, list(reversed(adjusted_requests)))

        # Insert tables in reverse order, re-read between each
        tables = parsed.tables or []
        for table_info in reversed(tables):
            _insert_table_internal(
                docs_service,
                document_id=document_id,
                rows=table_info.num_rows,
                cols=table_info.num_cols,
                index=table_info.index + offset,
                data=[list(row) for row in table_info.rows],
            )

        output_json({
            "status": "success",
            "operation": "insert_from_markdown",
            "document_id": document_id,
            "inserted_at": index,
            "text_length": len(parsed.text),
            "formats_applied": len(parsed.format_requests),
        })
    except Exception as e:
        _handle_error(e, "insert_from_markdown", "INSERT_MARKDOWN_FAILED",
                      "Failed to insert markdown")


def cmd_add_tab(docs_service: Any, document_id: str, title: str | None = None,
                index: int | None = None, parent_tab_id: str | None = None) -> None:
    """Add a tab to an existing document."""
    try:
        tab_properties: dict[str, Any] = {}
        if title is not None:
            tab_properties["title"] = title
        if index is not None:
            tab_properties["index"] = index
        if parent_tab_id is not None:
            tab_properties["parentTabId"] = parent_tab_id

        requests = [{"addDocumentTab": {"tabProperties": tab_properties}}]
        result = _batch_update(docs_service, document_id, requests)

        replies = result.get("replies", [])
        new_tab_data = replies[0].get("addDocumentTab", {}).get("tab", {}) if replies else {}
        new_tp = new_tab_data.get("tabProperties", {})

        output_json({
            "status": "success",
            "operation": "add_tab",
            "document_id": document_id,
            "tab_id": new_tp.get("tabId"),
            "title": new_tp.get("title"),
        })
    except Exception as e:
        _handle_error(e, "add_tab", "ADD_TAB_FAILED", "Failed to add tab")


def cmd_delete(docs_service: Any, document_id: str, start_index: int, end_index: int) -> None:
    """Delete content range."""
    try:
        requests = [{
            "deleteContentRange": {
                "range": {"startIndex": start_index, "endIndex": end_index},
            }
        }]
        _batch_update(docs_service, document_id, requests)

        output_json({
            "status": "success",
            "operation": "delete",
            "document_id": document_id,
            "deleted_range": {"start": start_index, "end": end_index},
        })
    except Exception as e:
        _handle_error(e, "delete", "DELETE_FAILED", "Failed to delete content")


def cmd_insert_image(docs_service: Any, document_id: str, image_url: str,
                     index: int | None = None, width: float | None = None,
                     height: float | None = None, tab_id: str | None = None) -> None:
    """Insert inline image from URL."""
    try:
        if index is None:
            document = docs_service.documents().get(documentId=document_id).execute()
            body_content = document.get("body", {}).get("content", [])
            index = body_content[-1].get("endIndex", 2) - 1 if body_content else 1

        location: dict[str, Any] = {"index": index}
        if tab_id:
            location["tabId"] = tab_id

        insert_req: dict[str, Any] = {
            "insertInlineImage": {"location": location, "uri": image_url}
        }

        object_size: dict[str, Any] = {}
        if width is not None:
            object_size["width"] = {"magnitude": width, "unit": "PT"}
        if height is not None:
            object_size["height"] = {"magnitude": height, "unit": "PT"}
        if object_size:
            insert_req["insertInlineImage"]["objectSize"] = object_size

        result = _batch_update(docs_service, document_id, [insert_req])

        output_json({
            "status": "success",
            "operation": "insert_image",
            "document_id": document_id,
            "inserted_at": index,
            "image_url": image_url,
            "revision_id": result.get("writeControl", {}).get("requiredRevisionId"),
        })
    except Exception as e:
        _handle_error(e, "insert_image", "INSERT_IMAGE_FAILED", "Failed to insert image")


def cmd_insert_table(docs_service: Any, document_id: str, rows: int, cols: int,
                     index: int | None = None,
                     data: list[list[str]] | None = None) -> None:
    """Insert a table into a document."""
    try:
        if index is None:
            document = docs_service.documents().get(documentId=document_id).execute()
            body_content = document.get("body", {}).get("content", [])
            index = body_content[-1].get("endIndex", 2) - 1 if body_content else 1

        requests = [{
            "insertTable": {
                "rows": rows,
                "columns": cols,
                "location": {"index": index},
            }
        }]
        _batch_update(docs_service, document_id, requests)

        if data:
            _populate_table_cells(docs_service, document_id, index, rows, cols, data)

        output_json({
            "status": "success",
            "operation": "insert_table",
            "document_id": document_id,
            "rows": rows,
            "columns": cols,
            "inserted_at": index,
        })
    except Exception as e:
        _handle_error(e, "insert_table", "INSERT_TABLE_FAILED", "Failed to insert table")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _insert_table_internal(docs_service: Any, document_id: str, rows: int, cols: int,
                           index: int, data: list[list[str]] | None = None) -> None:
    """Insert table without JSON output (for use within other methods)."""
    requests = [{
        "insertTable": {
            "rows": rows,
            "columns": cols,
            "location": {"index": index},
        }
    }]
    _batch_update(docs_service, document_id, requests)

    if data:
        _populate_table_cells(docs_service, document_id, index, rows, cols, data)


def _populate_table_cells(docs_service: Any, document_id: str, insert_index: int,
                          rows: int, cols: int, data: list[list[str]]) -> None:
    """Re-read document and populate table cells in reverse order."""
    document = docs_service.documents().get(documentId=document_id).execute()
    body_content = document.get("body", {}).get("content", [])

    table_element = None
    for element in body_content:
        if element.get("table") and element.get("startIndex", 0) >= insert_index:
            table_element = element
            break

    if table_element is None:
        return

    table = table_element["table"]
    table_rows = table.get("tableRows", [])

    cell_requests: list[dict[str, Any]] = []
    for rev_row_idx, row_data in enumerate(reversed(data)):
        row_idx = len(data) - 1 - rev_row_idx
        if row_idx >= rows or row_idx >= len(table_rows):
            continue

        table_row = table_rows[row_idx]
        table_cells = table_row.get("tableCells", [])

        for rev_col_idx, cell_content in enumerate(reversed(row_data)):
            col_idx = len(row_data) - 1 - rev_col_idx
            if col_idx >= cols or col_idx >= len(table_cells):
                continue

            table_cell = table_cells[col_idx]
            cell_content_elements = table_cell.get("content", [])
            if not cell_content_elements:
                continue

            cell_start = cell_content_elements[0].get("startIndex")
            if cell_start is None:
                continue

            cell_requests.append({
                "insertText": {
                    "location": {"index": cell_start},
                    "text": str(cell_content),
                }
            })

    if cell_requests:
        _batch_update(docs_service, document_id, cell_requests)


def _insert_text_to_tab(docs_service: Any, document_id: str, tab_id: str, text: str) -> None:
    """Insert plain text into a specific tab at index 1."""
    requests = [{"insertText": {"location": {"index": 1, "tabId": tab_id}, "text": text}}]
    _batch_update(docs_service, document_id, requests)


def _insert_content_to_tab(docs_service: Any, document_id: str, tab_id: str,
                           markdown: str) -> None:
    """Insert markdown content into a specific tab."""
    parsed = parse_markdown(markdown)

    if parsed.text:
        requests = [{
            "insertText": {
                "location": {"index": 1, "tabId": tab_id},
                "text": parsed.text,
            }
        }]
        _batch_update(docs_service, document_id, requests)

    format_requests = list(reversed(parsed.format_requests))
    if format_requests:
        _batch_update(docs_service, document_id, format_requests)


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build the argparse CLI parser matching the Ruby interface."""
    parser = argparse.ArgumentParser(
        prog="docs_manager",
        description="Google Docs Manager - Document Operations CLI",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # read <document_id> [--tab TAB_ID]
    p_read = subparsers.add_parser("read", help="Read document content")
    p_read.add_argument("document_id")
    p_read.add_argument("--tab", dest="tab_id", default=None)

    # structure <document_id> [--tab TAB_ID]
    p_struct = subparsers.add_parser("structure", help="Get document structure (headings)")
    p_struct.add_argument("document_id")
    p_struct.add_argument("--tab", dest="tab_id", default=None)

    # list-tabs <document_id>
    p_lt = subparsers.add_parser("list-tabs", help="List all tabs in a document")
    p_lt.add_argument("document_id")

    # stdin-based commands
    for name, help_text in [
        ("insert", "Insert text at specific index (JSON via stdin)"),
        ("append", "Append text to end of document (JSON via stdin)"),
        ("replace", "Find and replace text (JSON via stdin)"),
        ("format", "Format text (bold, italic, underline) (JSON via stdin)"),
        ("page-break", "Insert page break (JSON via stdin)"),
        ("create", "Create new document (JSON via stdin)"),
        ("create-from-markdown", "Create new document from markdown (JSON via stdin)"),
        ("create-with-tabs", "Create document with multiple tabs (JSON via stdin)"),
        ("insert-from-markdown", "Insert formatted markdown into existing doc (JSON via stdin)"),
        ("add-tab", "Add a tab to an existing document (JSON via stdin)"),
        ("delete", "Delete content range (JSON via stdin)"),
        ("insert-image", "Insert inline image from URL (JSON via stdin)"),
        ("insert-table", "Insert a table into a document (JSON via stdin)"),
    ]:
        subparsers.add_parser(name, help=help_text)

    return parser


def main() -> None:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(EXIT_INVALID_ARGS)

    docs_service = get_docs_service()
    command = args.command

    if command == "read":
        cmd_read(docs_service, args.document_id, tab_id=args.tab_id)

    elif command == "structure":
        cmd_structure(docs_service, args.document_id, tab_id=args.tab_id)

    elif command == "list-tabs":
        cmd_list_tabs(docs_service, args.document_id)

    elif command == "insert":
        data = _read_stdin_json()
        _validate_fields(data, ["document_id", "text"])
        cmd_insert(docs_service, data["document_id"], data["text"],
                   index=data.get("index", 1), tab_id=data.get("tab_id"))

    elif command == "append":
        data = _read_stdin_json()
        _validate_fields(data, ["document_id", "text"])
        cmd_append(docs_service, data["document_id"], data["text"],
                   tab_id=data.get("tab_id"))

    elif command == "replace":
        data = _read_stdin_json()
        _validate_fields(data, ["document_id", "find", "replace"])
        cmd_replace(docs_service, data["document_id"], data["find"], data["replace"],
                    match_case=data.get("match_case", False))

    elif command == "format":
        data = _read_stdin_json()
        _validate_fields(data, ["document_id", "start_index", "end_index"])
        cmd_format(docs_service, data["document_id"], data["start_index"], data["end_index"],
                   bold=data.get("bold"), italic=data.get("italic"),
                   underline=data.get("underline"), tab_id=data.get("tab_id"))

    elif command == "page-break":
        data = _read_stdin_json()
        _validate_fields(data, ["document_id", "index"])
        cmd_page_break(docs_service, data["document_id"], data["index"],
                       tab_id=data.get("tab_id"))

    elif command == "create":
        data = _read_stdin_json()
        _validate_fields(data, ["title"])
        cmd_create(docs_service, data["title"], content=data.get("content"))

    elif command == "create-from-markdown":
        data = _read_stdin_json()
        _validate_fields(data, ["title", "markdown"])
        cmd_create_from_markdown(docs_service, data["title"], data["markdown"])

    elif command == "create-with-tabs":
        data = _read_stdin_json()
        _validate_fields(data, ["title", "tabs"])
        if not isinstance(data["tabs"], list):
            output_json({
                "status": "error",
                "error_code": "MISSING_REQUIRED_FIELDS",
                "message": "Required fields: title, tabs (array of {title, markdown/content})",
            })
            sys.exit(EXIT_INVALID_ARGS)
        cmd_create_with_tabs(docs_service, data["title"], data["tabs"])

    elif command == "insert-from-markdown":
        data = _read_stdin_json()
        _validate_fields(data, ["document_id", "markdown"])
        cmd_insert_from_markdown(docs_service, data["document_id"], data["markdown"],
                                index=data.get("index"), tab_id=data.get("tab_id"))

    elif command == "add-tab":
        data = _read_stdin_json()
        _validate_fields(data, ["document_id"])
        cmd_add_tab(docs_service, data["document_id"], title=data.get("title"),
                    index=data.get("index"), parent_tab_id=data.get("parent_tab_id"))

    elif command == "delete":
        data = _read_stdin_json()
        _validate_fields(data, ["document_id", "start_index", "end_index"])
        cmd_delete(docs_service, data["document_id"], data["start_index"], data["end_index"])

    elif command == "insert-image":
        data = _read_stdin_json()
        _validate_fields(data, ["document_id", "image_url"])
        cmd_insert_image(docs_service, data["document_id"], data["image_url"],
                         index=data.get("index"), width=data.get("width"),
                         height=data.get("height"), tab_id=data.get("tab_id"))

    elif command == "insert-table":
        data = _read_stdin_json()
        _validate_fields(data, ["document_id", "rows", "cols"])
        cmd_insert_table(docs_service, data["document_id"], data["rows"], data["cols"],
                         index=data.get("index"), data=data.get("data"))

    else:
        output_json({
            "status": "error",
            "error_code": "INVALID_COMMAND",
            "message": f"Unknown command: {command}",
            "valid_commands": [
                "read", "structure", "list-tabs", "insert", "append", "replace",
                "format", "page-break", "create", "create-from-markdown",
                "create-with-tabs", "insert-from-markdown", "add-tab", "delete",
                "insert-image", "insert-table",
            ],
        })
        sys.exit(EXIT_INVALID_ARGS)

    sys.exit(EXIT_SUCCESS)


if __name__ == "__main__":
    main()
