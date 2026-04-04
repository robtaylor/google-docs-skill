"""Tests for markdown_parser module."""

import pytest
from google_docs.markdown_parser import (
    ImagePlaceholder,
    ParseResult,
    TablePlaceholder,
    parse_markdown,
)


class TestParseMarkdownBasic:
    def test_empty_input(self):
        result = parse_markdown("")
        assert isinstance(result, ParseResult)
        assert result.text == ""
        assert result.format_requests == ()
        assert result.images == ()
        assert result.tables == ()

    def test_plain_paragraph(self):
        result = parse_markdown("Hello world")
        assert "Hello world" in result.text

    def test_returns_frozen_dataclass(self):
        result = parse_markdown("test")
        with pytest.raises(AttributeError):
            result.text = "mutated"


class TestHeadings:
    def test_h1(self):
        result = parse_markdown("# Title")
        assert "Title" in result.text
        heading_reqs = [r for r in result.format_requests if "updateParagraphStyle" in r]
        assert any(
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_1"
            for r in heading_reqs
        )

    def test_h2(self):
        result = parse_markdown("## Subtitle")
        heading_reqs = [r for r in result.format_requests if "updateParagraphStyle" in r]
        assert any(
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == "HEADING_2"
            for r in heading_reqs
        )

    def test_h3_through_h6(self):
        for level in range(3, 7):
            md = f"{'#' * level} Heading {level}"
            result = parse_markdown(md)
            heading_reqs = [r for r in result.format_requests if "updateParagraphStyle" in r]
            expected = f"HEADING_{level}"
            assert any(
                r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"] == expected
                for r in heading_reqs
            ), f"Missing {expected}"


class TestInlineFormatting:
    def test_bold(self):
        result = parse_markdown("This is **bold** text")
        assert "bold" in result.text
        bold_reqs = [
            r for r in result.format_requests
            if "updateTextStyle" in r and r["updateTextStyle"].get("textStyle", {}).get("bold")
        ]
        assert len(bold_reqs) >= 1

    def test_italic(self):
        result = parse_markdown("This is *italic* text")
        assert "italic" in result.text
        italic_reqs = [
            r for r in result.format_requests
            if "updateTextStyle" in r and r["updateTextStyle"].get("textStyle", {}).get("italic")
        ]
        assert len(italic_reqs) >= 1

    def test_code_span(self):
        result = parse_markdown("Use `code` here")
        assert "code" in result.text
        code_reqs = [
            r for r in result.format_requests
            if "updateTextStyle" in r
            and "weightedFontFamily" in r["updateTextStyle"].get("textStyle", {})
        ]
        assert len(code_reqs) >= 1

    def test_link(self):
        result = parse_markdown("[click here](https://example.com)")
        assert "click here" in result.text
        link_reqs = [
            r for r in result.format_requests
            if "updateTextStyle" in r and "link" in r["updateTextStyle"].get("textStyle", {})
        ]
        assert len(link_reqs) >= 1
        assert link_reqs[0]["updateTextStyle"]["textStyle"]["link"]["url"] == "https://example.com"


class TestLists:
    def test_bullet_list(self):
        result = parse_markdown("- Item 1\n- Item 2")
        assert "Item 1" in result.text
        assert "Item 2" in result.text
        bullet_reqs = [r for r in result.format_requests if "createParagraphBullets" in r]
        assert len(bullet_reqs) >= 1

    def test_numbered_list(self):
        result = parse_markdown("1. First\n2. Second")
        assert "First" in result.text
        numbered_reqs = [
            r for r in result.format_requests
            if "createParagraphBullets" in r
            and r["createParagraphBullets"].get("bulletPreset") == "NUMBERED_DECIMAL_ALPHA_ROMAN"
        ]
        assert len(numbered_reqs) >= 1


class TestImages:
    def test_local_image(self):
        result = parse_markdown("![diagram](./images/flow.png)")
        assert len(result.images) == 1
        img = result.images[0]
        assert isinstance(img, ImagePlaceholder)
        assert img.source == "./images/flow.png"
        assert img.source_type == "file"

    def test_url_image(self):
        result = parse_markdown("![logo](https://example.com/logo.png)")
        assert len(result.images) == 1
        assert result.images[0].source_type == "url"
        assert result.images[0].source == "https://example.com/logo.png"

    def test_mermaid_block(self):
        md = "```mermaid\ngraph LR\n  A-->B\n```"
        result = parse_markdown(md)
        assert len(result.images) == 1
        img = result.images[0]
        assert img.source_type == "mermaid"
        assert "graph LR" in img.source


class TestTables:
    def test_simple_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        result = parse_markdown(md)
        assert len(result.tables) == 1
        table = result.tables[0]
        assert isinstance(table, TablePlaceholder)
        assert table.num_cols == 2

    def test_table_data(self):
        md = "| Name | Value |\n|------|-------|\n| foo | bar |"
        result = parse_markdown(md)
        table = result.tables[0]
        # Table rows should include header
        assert table.num_rows >= 2


class TestCodeBlocks:
    def test_fenced_code_block(self):
        md = "```python\ndef hello():\n    pass\n```"
        result = parse_markdown(md)
        assert "def hello():" in result.text
        code_reqs = [
            r for r in result.format_requests
            if "updateTextStyle" in r
            and "weightedFontFamily" in r["updateTextStyle"].get("textStyle", {})
        ]
        assert len(code_reqs) >= 1


class TestThematicBreak:
    def test_hr_becomes_page_break(self):
        result = parse_markdown("Before\n\n---\n\nAfter")
        page_break_reqs = [r for r in result.format_requests if "insertPageBreak" in r]
        assert len(page_break_reqs) >= 1


class TestIndexTracking:
    def test_indices_start_at_one(self):
        result = parse_markdown("**bold**")
        bold_reqs = [
            r for r in result.format_requests
            if "updateTextStyle" in r and r["updateTextStyle"].get("textStyle", {}).get("bold")
        ]
        assert len(bold_reqs) == 1
        rng = bold_reqs[0]["updateTextStyle"]["range"]
        assert rng["startIndex"] >= 1

    def test_format_ranges_within_text_bounds(self):
        md = "# Title\n\nThis is **bold** and *italic* text.\n\n- item"
        result = parse_markdown(md)
        text_len = len(result.text)
        for req in result.format_requests:
            if "updateTextStyle" in req:
                rng = req["updateTextStyle"]["range"]
                assert rng["startIndex"] >= 1
                assert rng["endIndex"] <= text_len + 1  # 1-based


class TestComplexDocument:
    def test_mixed_content(self):
        md = """# Report

## Overview

This is **bold** and *italic* with `code`.

- Bullet 1
- Bullet 2

```mermaid
graph LR
  A-->B
```

| Col1 | Col2 |
|------|------|
| a    | b    |

![img](./test.png)

---

1. First
2. Second
"""
        result = parse_markdown(md)
        assert len(result.text) > 0
        assert len(result.format_requests) > 0
        assert len(result.images) == 2  # mermaid + file image
        assert len(result.tables) == 1
