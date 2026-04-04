"""Convert Markdown AST to structured blocks for Apps Script document builder.

Walks the mistune 3.x AST and produces a list of block dicts that the
Apps Script buildDocument() function can consume directly.

Block types:
    heading: {type, level, text, runs?}
    paragraph: {type, runs}
    list: {type, ordered, items: [{text, level, runs?}]}
    table: {type, rows: [[str]], boldHeader: bool}
    image: {type, driveFileId, caption?, width?, height?}
    code_block: {type, text, language?}
    hr: {type}
"""

from __future__ import annotations

import re

import mistune


def markdown_to_blocks(markdown_text: str) -> list[dict]:
    """Convert markdown text to a list of structured blocks."""
    md = mistune.create_markdown(renderer="ast", plugins=["table"])
    tokens = md(markdown_text)
    walker = _BlockWalker()
    walker.walk(tokens)
    return walker.blocks


class _BlockWalker:
    def __init__(self) -> None:
        self.blocks: list[dict] = []

    def walk(self, tokens: list[dict]) -> None:
        for token in tokens:
            self._visit(token)

    def _visit(self, token: dict) -> None:
        t = token.get("type", "")
        handler = {
            "heading": self._heading,
            "paragraph": self._paragraph,
            "list": self._list,
            "table": self._table,
            "block_code": self._code_block,
            "thematic_break": self._hr,
            "block_quote": self._block_quote,
            "blank_line": lambda _: None,
        }.get(t)
        if handler:
            handler(token)

    def _heading(self, token: dict) -> None:
        level = token.get("attrs", {}).get("level", 1)
        children = token.get("children", [])
        runs = _inline_to_runs(children)
        plain = "".join(r["text"] for r in runs)
        self.blocks.append({
            "type": "heading",
            "level": level,
            "text": plain,
            "runs": runs if _has_formatting(runs) else None,
        })

    def _paragraph(self, token: dict) -> None:
        children = token.get("children", [])

        # Check if this paragraph is a standalone image
        if len(children) == 1 and children[0].get("type") == "image":
            img = children[0]
            attrs = img.get("attrs", {})
            src = attrs.get("url", "") or attrs.get("src", "")
            alt = attrs.get("alt", "") or img.get("alt", "")
            self.blocks.append({
                "type": "image",
                "source": src,
                "source_type": "url" if src.startswith(("http://", "https://")) else "file",
                "caption": alt if isinstance(alt, str) else "",
            })
            return

        runs = _inline_to_runs(children)
        if runs:
            self.blocks.append({"type": "paragraph", "runs": runs})

    def _list(self, token: dict) -> None:
        attrs = token.get("attrs", {})
        ordered = attrs.get("ordered", False)
        items = self._collect_list_items(token.get("children", []), level=0)
        self.blocks.append({
            "type": "list",
            "ordered": ordered,
            "items": items,
        })

    def _collect_list_items(self, children: list[dict], level: int) -> list[dict]:
        items: list[dict] = []
        for child in children:
            if child.get("type") != "list_item":
                continue
            for sub in child.get("children", []):
                if sub.get("type") in ("paragraph", "block_text"):
                    runs = _inline_to_runs(sub.get("children", []))
                    plain = "".join(r["text"] for r in runs)
                    item: dict = {"text": plain, "level": level}
                    if _has_formatting(runs):
                        item["runs"] = runs
                    items.append(item)
                elif sub.get("type") == "list":
                    nested = self._collect_list_items(sub.get("children", []), level + 1)
                    items.extend(nested)
        return items

    def _table(self, token: dict) -> None:
        rows: list[list[str]] = []
        for child in token.get("children", []):
            child_type = child.get("type", "")
            if child_type == "table_head":
                # table_head has table_cell children directly (no table_row wrapper)
                cells = []
                for cell in child.get("children", []):
                    if cell.get("type") == "table_cell":
                        cells.append(_extract_plain_text(cell.get("children", [])))
                if cells:
                    rows.append(cells)
            elif child_type == "table_body":
                for row in child.get("children", []):
                    if row.get("type") == "table_row":
                        cells = []
                        for cell in row.get("children", []):
                            if cell.get("type") == "table_cell":
                                cells.append(_extract_plain_text(cell.get("children", [])))
                        rows.append(cells)
        if rows:
            self.blocks.append({"type": "table", "rows": rows, "boldHeader": True})

    def _code_block(self, token: dict) -> None:
        attrs = token.get("attrs", {})
        info = attrs.get("info", "") or ""
        raw = token.get("raw", "") or token.get("text", "")

        # Mermaid blocks become image placeholders
        if info.strip().lower() == "mermaid":
            self.blocks.append({
                "type": "image",
                "source": raw,
                "source_type": "mermaid",
                "caption": "Mermaid diagram",
            })
            return

        self.blocks.append({
            "type": "code_block",
            "text": raw.rstrip("\n"),
            "language": info.strip() if info else None,
        })

    def _hr(self, _token: dict) -> None:
        self.blocks.append({"type": "hr"})

    def _block_quote(self, token: dict) -> None:
        # Flatten block quote content as indented paragraphs
        for child in token.get("children", []):
            self._visit(child)


def _inline_to_runs(tokens: list[dict]) -> list[dict]:
    """Convert inline AST tokens to a flat list of text runs with formatting."""
    runs: list[dict] = []
    for token in tokens:
        _collect_runs(token, runs, bold=False, italic=False, code=False, link=None)
    return runs


def _collect_runs(
    token: dict,
    runs: list[dict],
    bold: bool,
    italic: bool,
    code: bool,
    link: str | None,
) -> None:
    t = token.get("type", "")

    if t == "text":
        text = token.get("raw", "") or token.get("text", "") or token.get("children", "")
        if isinstance(text, str) and text:
            run: dict = {"text": text}
            if bold:
                run["bold"] = True
            if italic:
                run["italic"] = True
            if code:
                run["code"] = True
            if link:
                run["link"] = link
            runs.append(run)

    elif t == "strong":
        for child in token.get("children", []):
            _collect_runs(child, runs, bold=True, italic=italic, code=code, link=link)

    elif t == "emphasis":
        for child in token.get("children", []):
            _collect_runs(child, runs, bold=bold, italic=True, code=code, link=link)

    elif t == "codespan":
        text = token.get("raw", "") or token.get("text", "") or token.get("children", "")
        if isinstance(text, str) and text:
            run = {"text": text, "code": True}
            if bold:
                run["bold"] = True
            if italic:
                run["italic"] = True
            runs.append(run)

    elif t == "link":
        attrs = token.get("attrs", {})
        url = attrs.get("url", "") or attrs.get("href", "")
        for child in token.get("children", []):
            _collect_runs(child, runs, bold=bold, italic=italic, code=code, link=url)

    elif t == "image":
        # Inline image in a paragraph — add alt text as placeholder
        attrs = token.get("attrs", {})
        alt = attrs.get("alt", "") or token.get("alt", "")
        if isinstance(alt, str) and alt:
            runs.append({"text": f"[{alt}]", "italic": True})

    elif t in ("softbreak", "linebreak"):
        runs.append({"text": "\n"})


def _has_formatting(runs: list[dict]) -> bool:
    """Check if any run has non-default formatting."""
    return any(
        r.get("bold") or r.get("italic") or r.get("code") or r.get("link")
        for r in runs
    )


def _extract_plain_text(tokens: list[dict]) -> str:
    """Extract plain text from inline tokens."""
    parts: list[str] = []
    for token in tokens:
        t = token.get("type", "")
        if t == "text":
            raw = token.get("raw", "") or token.get("text", "") or token.get("children", "")
            if isinstance(raw, str):
                parts.append(raw)
        elif t in ("strong", "emphasis", "link"):
            parts.append(_extract_plain_text(token.get("children", [])))
        elif t == "codespan":
            raw = token.get("raw", "") or token.get("text", "") or token.get("children", "")
            if isinstance(raw, str):
                parts.append(raw)
    return "".join(parts)
