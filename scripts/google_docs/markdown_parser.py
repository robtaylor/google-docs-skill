"""Markdown to Google Docs API request converter using mistune 3.x AST mode.

Parses markdown text into plain text + Google Docs API formatting requests,
image placeholders, and table placeholders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import mistune


@dataclass(frozen=True)
class ImagePlaceholder:
    """Represents an image to be inserted into the document."""

    index: int
    source: str
    source_type: str  # "file" | "mermaid" | "url"
    alt_text: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class TablePlaceholder:
    """Represents a table to be inserted into the document."""

    index: int
    rows: tuple[tuple[str, ...], ...]
    num_rows: int
    num_cols: int


@dataclass(frozen=True)
class ParseResult:
    """Result of parsing markdown into Google Docs API structures."""

    text: str
    format_requests: tuple[dict[str, Any], ...]
    images: tuple[ImagePlaceholder, ...]
    tables: tuple[TablePlaceholder, ...]


# Heading level to Google Docs named style mapping
_HEADING_STYLES: dict[int, str] = {
    1: "HEADING_1",
    2: "HEADING_2",
    3: "HEADING_3",
    4: "HEADING_4",
    5: "HEADING_5",
    6: "HEADING_6",
}

_CODE_BACKGROUND: dict[str, Any] = {
    "color": {"rgbColor": {"red": 0.95, "green": 0.95, "blue": 0.95}}
}
_CODE_FONT_FAMILY = "Courier New"


def _classify_image_source(source: str) -> str:
    """Classify an image source as file, url, or mermaid."""
    if source.startswith(("http://", "https://")):
        return "url"
    return "file"


def _parse_image_dimensions(alt_text: str) -> tuple[str, int | None, int | None]:
    """Extract width/height from alt text like 'diagram =400x300'."""
    match = re.search(r"=(\d+)x(\d+)\s*$", alt_text)
    if match:
        clean_alt = alt_text[: match.start()].strip()
        return clean_alt, int(match.group(1)), int(match.group(2))
    return alt_text, None, None


class _DocBuilder:
    """Accumulates text and format requests while walking the AST.

    Mutable internal state used only during a single parse call.
    No input data is mutated.
    """

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._index: int = 1  # Google Docs 1-based indexing
        self._format_requests: list[dict[str, Any]] = []
        self._images: list[ImagePlaceholder] = []
        self._tables: list[TablePlaceholder] = []
        self._list_stack: list[str] = []

    # --- Text accumulation ---

    def _append(self, text: str) -> tuple[int, int]:
        """Append text, returning (start_index, end_index)."""
        start = self._index
        self._parts.append(text)
        self._index += len(text)
        return start, self._index

    # --- Result building ---

    def build(self) -> ParseResult:
        return ParseResult(
            text="".join(self._parts),
            format_requests=tuple(self._format_requests),
            images=tuple(self._images),
            tables=tuple(self._tables),
        )

    # --- AST walking ---

    def walk(self, tokens: list[dict[str, Any]]) -> None:
        for token in tokens:
            self._visit(token)

    def _visit(self, token: dict[str, Any]) -> None:
        node_type = token.get("type", "")
        handler = getattr(self, f"_visit_{node_type}", None)
        if handler is not None:
            handler(token)
        elif "children" in token:
            children = token["children"]
            if isinstance(children, list):
                self.walk(children)

    # --- Block-level nodes ---

    def _visit_paragraph(self, token: dict[str, Any]) -> None:
        children = token.get("children", [])
        self._walk_inline(children)
        self._append("\n")

    def _visit_heading(self, token: dict[str, Any]) -> None:
        attrs = token.get("attrs", {})
        level: int = attrs.get("level", 1) if attrs else 1
        start = self._index
        children = token.get("children", [])
        self._walk_inline(children)
        self._append("\n")
        end_with_newline = self._index

        style = _HEADING_STYLES.get(level, "HEADING_1")
        self._format_requests.append({
            "updateParagraphStyle": {
                "range": {
                    "startIndex": start,
                    "endIndex": end_with_newline,
                },
                "paragraphStyle": {"namedStyleType": style},
                "fields": "namedStyleType",
            }
        })

    def _visit_block_code(self, token: dict[str, Any]) -> None:
        attrs = token.get("attrs", {})
        info: str = (attrs.get("info", "") or "") if attrs else ""
        raw: str = token.get("raw", "") or token.get("text", "") or ""

        # Mermaid blocks become image placeholders
        if info.strip().lower() == "mermaid":
            self._images.append(ImagePlaceholder(
                index=self._index,
                source=raw,
                source_type="mermaid",
                alt_text="mermaid diagram",
            ))
            self._append("\n")
            return

        # Regular code block
        start, end = self._append(raw)
        self._format_requests.append({
            "updateTextStyle": {
                "range": {"startIndex": start, "endIndex": end},
                "textStyle": {
                    "weightedFontFamily": {"fontFamily": _CODE_FONT_FAMILY},
                    "backgroundColor": _CODE_BACKGROUND,
                },
                "fields": "weightedFontFamily,backgroundColor",
            }
        })
        self._append("\n")

    def _visit_thematic_break(self, _token: dict[str, Any]) -> None:
        start = self._index
        self._append("\n")
        self._format_requests.append({
            "insertPageBreak": {
                "location": {"index": start},
            }
        })

    def _visit_list(self, token: dict[str, Any]) -> None:
        attrs = token.get("attrs", {})
        ordered: bool = (attrs.get("ordered", False)) if attrs else False
        children = token.get("children", [])

        # Detect if any child is a task_list_item
        has_tasks = any(
            c.get("type") == "task_list_item" for c in children
        )

        if has_tasks:
            list_type = "checkbox"
        elif ordered:
            list_type = "ordered"
        else:
            list_type = "bullet"

        self._list_stack.append(list_type)
        for child in children:
            child_type = child.get("type", "")
            if child_type == "task_list_item":
                self._visit_task_list_item(child)
            else:
                self._visit_list_item(child)
        self._list_stack.pop()

    def _visit_list_item(self, token: dict[str, Any]) -> None:
        list_type = self._list_stack[-1] if self._list_stack else "bullet"
        start = self._index

        children = token.get("children", [])
        for child in children:
            child_type = child.get("type", "")
            if child_type in ("paragraph", "block_text"):
                self._walk_inline(child.get("children", []))
            elif child_type == "list":
                self._append("\n")
                self._visit(child)
                return
            else:
                self._visit(child)

        self._append("\n")
        end_with_newline = self._index

        preset = (
            "NUMBERED_DECIMAL_ALPHA_ROMAN"
            if list_type == "ordered"
            else "BULLET_DISC_CIRCLE_SQUARE"
        )

        self._format_requests.append({
            "createParagraphBullets": {
                "range": {
                    "startIndex": start,
                    "endIndex": end_with_newline,
                },
                "bulletPreset": preset,
            }
        })

    def _visit_task_list_item(self, token: dict[str, Any]) -> None:
        start = self._index
        attrs = token.get("attrs", {})
        is_checked: bool = attrs.get("checked", False) if attrs else False

        children = token.get("children", [])
        for child in children:
            child_type = child.get("type", "")
            if child_type in ("paragraph", "block_text"):
                self._walk_inline(child.get("children", []))
            else:
                self._visit(child)

        self._append("\n")
        end_with_newline = self._index

        preset = (
            "CHECKBOX_CHECKED" if is_checked else "CHECKBOX_UNCHECKED"
        )
        self._format_requests.append({
            "createParagraphBullets": {
                "range": {
                    "startIndex": start,
                    "endIndex": end_with_newline,
                },
                "bulletPreset": preset,
            }
        })

    def _visit_table(self, token: dict[str, Any]) -> None:
        children = token.get("children", [])
        rows: list[tuple[str, ...]] = []

        # table_head contains cells directly (one row)
        head = next(
            (c for c in children if c.get("type") == "table_head"), None
        )
        if head:
            cells = tuple(
                self._extract_text(cell)
                for cell in head.get("children", [])
                if cell.get("type") == "table_cell"
            )
            if cells:
                rows.append(cells)

        # table_body contains table_row children
        body = next(
            (c for c in children if c.get("type") == "table_body"), None
        )
        if body:
            for row in body.get("children", []):
                if row.get("type") == "table_row":
                    cells = tuple(
                        self._extract_text(cell)
                        for cell in row.get("children", [])
                        if cell.get("type") == "table_cell"
                    )
                    rows.append(cells)

        if not rows:
            return

        num_cols = max(len(r) for r in rows)
        normalized = tuple(
            r + ("",) * (num_cols - len(r)) for r in rows
        )

        self._tables.append(TablePlaceholder(
            index=self._index,
            rows=normalized,
            num_rows=len(normalized),
            num_cols=num_cols,
        ))
        self._append("\n")

    # --- Inline-level nodes ---

    def _walk_inline(self, tokens: list[dict[str, Any]]) -> None:
        for token in tokens:
            self._visit_inline(token)

    def _visit_inline(self, token: dict[str, Any]) -> None:
        node_type = token.get("type", "")

        if node_type == "text":
            raw = token.get("raw", "") or token.get("children", "")
            if isinstance(raw, str):
                self._append(raw)
            return

        if node_type == "codespan":
            raw = token.get("raw", "") or token.get("children", "")
            if isinstance(raw, str):
                start, end = self._append(raw)
                self._format_requests.append({
                    "updateTextStyle": {
                        "range": {"startIndex": start, "endIndex": end},
                        "textStyle": {
                            "weightedFontFamily": {
                                "fontFamily": _CODE_FONT_FAMILY,
                            },
                            "backgroundColor": _CODE_BACKGROUND,
                        },
                        "fields": "weightedFontFamily,backgroundColor",
                    }
                })
            return

        if node_type == "strong":
            start = self._index
            self._walk_inline(token.get("children", []))
            end = self._index
            self._format_requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            })
            return

        if node_type == "emphasis":
            start = self._index
            self._walk_inline(token.get("children", []))
            end = self._index
            self._format_requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"italic": True},
                    "fields": "italic",
                }
            })
            return

        if node_type == "link":
            attrs = token.get("attrs", {})
            url: str = attrs.get("url", "") if attrs else ""
            start = self._index
            self._walk_inline(token.get("children", []))
            end = self._index
            self._format_requests.append({
                "updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": end},
                    "textStyle": {"link": {"url": url}},
                    "fields": "link",
                }
            })
            return

        if node_type == "image":
            attrs = token.get("attrs", {})
            src: str = (
                attrs.get("src", "") or attrs.get("url", "") or ""
            ) if attrs else ""
            # Alt text is in children for mistune 3.x AST mode
            alt: str = self._extract_text(token)
            alt_clean, width, height = _parse_image_dimensions(alt)
            source_type = _classify_image_source(src)
            self._images.append(ImagePlaceholder(
                index=self._index,
                source=src,
                source_type=source_type,
                alt_text=alt_clean,
                width=width,
                height=height,
            ))
            self._append("\n")
            return

        if node_type == "softbreak":
            return

        if node_type == "linebreak":
            self._append("\n")
            return

        # Fallback: walk children if present
        children = token.get("children", [])
        if isinstance(children, list):
            self._walk_inline(children)
        elif isinstance(children, str):
            self._append(children)

    # --- Helpers ---

    def _extract_text(self, token: dict[str, Any]) -> str:
        """Recursively extract plain text from a token tree."""
        node_type = token.get("type", "")

        if node_type in ("text", "codespan"):
            raw = token.get("raw", "") or token.get("children", "")
            return raw if isinstance(raw, str) else ""

        children = token.get("children", [])
        if isinstance(children, str):
            return children
        if isinstance(children, list):
            return "".join(self._extract_text(c) for c in children)
        return ""


def parse_markdown(markdown_text: str) -> ParseResult:
    """Parse markdown text into Google Docs API structures.

    Args:
        markdown_text: Raw markdown string to parse.

    Returns:
        ParseResult with plain text, format requests, images, and tables.
        The input string is never mutated.

    Raises:
        ValueError: If markdown_text is not a string.
    """
    if not isinstance(markdown_text, str):
        raise ValueError(f"Expected str, got {type(markdown_text).__name__}")

    if not markdown_text.strip():
        return ParseResult(text="", format_requests=(), images=(), tables=())

    md = mistune.create_markdown(
        renderer="ast",
        plugins=["table", "task_lists"],
    )
    tokens: list[dict[str, Any]] = md(markdown_text)  # type: ignore[assignment]

    builder = _DocBuilder()
    builder.walk(tokens)
    return builder.build()
