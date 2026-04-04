---
name: google-docs
description: Manage Google Docs and Google Drive with full document operations and file management. Create formatted documents from Markdown files (rendered as native Google Docs formatting, NOT raw markdown). Supports large documents (50+ pages) with automatic chunking, inline mermaid diagrams, and image embedding.
category: productivity
version: 2.0.0
key_capabilities: markdown-to-docs (large doc with chunking), create-from-markdown, insert-from-markdown, tables, mermaid diagrams, images, Drive upload/download/share/search, environment bootstrap
when_to_use: Document content operations, creating formatted Google Docs from Markdown files, large document creation, Drive file management, sharing files
---

# Google Docs & Drive Management Skill

## First Time Setup

Run the setup command to check and bootstrap your environment:
```bash
scripts/setup
```

This checks for: uv, Python 3.11+, dependencies, Google OAuth credentials, and mmdc (for mermaid). It will install missing components automatically where possible.

For JSON output: `scripts/setup --json`

## Purpose

Manage Google Docs documents and Google Drive files. All scripts are Python, managed by `uv`.

**IMPORTANT: Markdown is rendered as formatted Google Docs content** (headings, bold, italic, tables, etc.) — it is NOT inserted as raw markdown text.

**Google Docs:**
- Read document content and structure
- Create documents from Markdown files (with proper formatting)
- Create documents from plain text
- Insert, append, find/replace text
- Text formatting (bold, italic, underline)
- Insert page breaks, images, tables
- Tab support (create, list, add tabs)
- **Large document support** (50+ pages) with automatic API chunking

**Google Drive:**
- Upload, download, search, list files
- Share files with users or publicly
- Create folders, move, copy, delete files

**Mermaid Diagrams:**
- Inline `\`\`\`mermaid` blocks in Markdown are automatically rendered to PNG and inserted as images

## When to Use This Skill

- User wants to create a Google Doc from a local Markdown or text file
- User wants to create a large document (50+ pages)
- User wants Markdown rendered as formatted Google Docs (NOT raw text)
- User wants to read, edit, or format a Google Doc
- User wants to upload/download/share files on Google Drive
- Keywords: "Google Doc", "document", "markdown to doc", "create doc", "upload", "share"

## Core Workflows

### 1. Create Large Document from Markdown File (RECOMMENDED)

**This is the primary workflow for document creation.** Handles 50+ page documents with automatic chunking, mermaid diagrams, and images.

```bash
# Create new doc from a local .md file
scripts/markdown_to_docs --file ./design.md --title "Design Document"

# Append to existing doc
scripts/markdown_to_docs --file ./appendix.md --document-id abc123

# With a Drive folder for uploaded images
scripts/markdown_to_docs --file ./doc.md --title "Report" --drive-folder-id folder123

# Dry run (parse only, no API calls)
scripts/markdown_to_docs --file ./doc.md --title "Test" --dry-run
```

**What it does:**
1. Reads the `.md` file from disk
2. Parses Markdown AST (headings, bold, italic, code, lists, tables, links)
3. Renders `\`\`\`mermaid` blocks to PNG via `mmdc`, uploads to Drive
4. Resolves `![alt](path)` image references, uploads local images to Drive
5. Creates the Google Doc with proper formatting (NOT raw markdown)
6. Chunks API requests into 4MB batches to avoid payload limits
7. Rate-limits to 55 writes/min with exponential backoff

**Supported Markdown features (all rendered as native Google Docs formatting):**
- `#` through `######` → HEADING_1 through HEADING_6
- `**bold**` → Bold text
- `*italic*` → Italic text
- `` `code` `` → Courier New with grey background
- `- item` / `* item` → Bullet lists
- `1. item` → Numbered lists
- `- [ ]` / `- [x]` → Checkboxes
- `---` → Page break
- `| table |` → Google Docs table
- `\`\`\`mermaid` → Rendered diagram image
- `![alt](path)` → Inline image (PNG, JPG, GIF)
- `[text](url)` → Hyperlink

### 2. Read Document

```bash
scripts/docs_manager read <document_id>
scripts/docs_manager structure <document_id>
scripts/docs_manager list-tabs <document_id>
```

### 3. Create Document (Small, via stdin)

**Plain text:**
```bash
echo '{"title": "Notes", "content": "Plain text content"}' | scripts/docs_manager create
```

**From Markdown (small docs only — for large docs use `markdown_to_docs`):**
```bash
echo '{"title": "Report", "markdown": "# Report\n\n**Bold** text"}' | scripts/docs_manager create-from-markdown
```

### 4. Insert and Append Text

```bash
# Insert at position
echo '{"document_id": "abc123", "text": "New text", "index": 1}' | scripts/docs_manager insert

# Insert formatted Markdown
echo '{"document_id": "abc123", "markdown": "## Section\n\n- Item 1"}' | scripts/docs_manager insert-from-markdown

# Append to end
echo '{"document_id": "abc123", "text": "Appended text"}' | scripts/docs_manager append
```

### 5. Find and Replace

```bash
echo '{"document_id": "abc123", "find": "old", "replace": "new"}' | scripts/docs_manager replace
```

### 6. Format Text

```bash
echo '{"document_id": "abc123", "start_index": 1, "end_index": 50, "bold": true}' | scripts/docs_manager format
```

### 7. Insert Images and Tables

```bash
# Image
echo '{"document_id": "abc123", "image_url": "https://example.com/img.png"}' | scripts/docs_manager insert-image

# Table
echo '{"document_id": "abc123", "rows": 3, "cols": 2, "data": [["A","B"],["1","2"],["3","4"]]}' | scripts/docs_manager insert-table
```

### 8. Tab Operations

```bash
# List tabs
scripts/docs_manager list-tabs <document_id>

# Add a tab
echo '{"document_id": "abc123", "title": "New Tab"}' | scripts/docs_manager add-tab

# Create doc with multiple tabs
echo '{"title": "Multi-Tab Doc", "tabs": [{"title": "Overview", "markdown": "# Overview"}, {"title": "Details", "content": "Plain text"}]}' | scripts/docs_manager create-with-tabs

# Read specific tab
scripts/docs_manager read <document_id> --tab <tab_id>
```

## Google Drive Operations

```bash
# Upload
scripts/drive_manager upload --file ./doc.pdf
scripts/drive_manager upload --file ./img.png --folder-id abc123

# Download / Export
scripts/drive_manager download --file-id abc123 --output ./local.pdf
scripts/drive_manager download --file-id abc123 --output ./doc.pdf --export-as pdf

# Search
scripts/drive_manager search --query "name contains 'Report'"
scripts/drive_manager list --max-results 20

# Share
scripts/drive_manager share --file-id abc123 --email user@co.com --role writer
scripts/drive_manager share --file-id abc123 --type anyone --role reader

# Folders
scripts/drive_manager create-folder --name "Project Docs"
scripts/drive_manager move --file-id file123 --folder-id folder456

# Other
scripts/drive_manager copy --file-id abc123 --name "Copy"
scripts/drive_manager get-metadata --file-id abc123
scripts/drive_manager delete --file-id abc123
```

## Authentication

**Shared OAuth credentials** at `~/.claude/.google/`:
- `client_secret.json` — OAuth client ID (from Google Cloud Console)
- `token.json` — Auto-managed access/refresh tokens

First run triggers browser OAuth flow. Token auto-refreshes. Shared with email, calendar, contacts, drive, and sheets skills.

Run `scripts/setup` to check credential status.

## Bundled Scripts

| Script | Purpose |
|---|---|
| `scripts/markdown_to_docs` | Large doc creation from .md files with chunking |
| `scripts/docs_manager` | All 17 Google Docs operations |
| `scripts/drive_manager` | All 11 Google Drive operations |
| `scripts/setup` | Environment detection and bootstrap |

## Output Format

All commands return JSON:
```json
{"status": "success", "document_id": "abc123", "operation": "create", ...}
{"status": "error", "error_code": "API_ERROR", "message": "..."}
```

## Dependencies

Python 3.11+ managed by `uv`. Run `cd scripts && uv sync` to install:
- `google-api-python-client` — Google Docs/Drive API
- `google-auth` + `google-auth-oauthlib` — OAuth
- `mistune` — Markdown AST parsing
- `Pillow` — Image dimensions

External (optional): `mmdc` (mermaid CLI) for mermaid diagram rendering.

## Version History

- **2.0.0** (2026-04-03) - Full Python rewrite with uv. Large document support with chunked batchUpdate (4MB batches, 55 writes/min rate limiting). AST-based Markdown parser (mistune). Inline mermaid rendering. Image pipeline. Environment bootstrap. Plain text and Markdown both supported.
- **1.2.0** (2025-12-25) - Markdown support, tables, checkboxes (Ruby).
- **1.1.0** (2025-12-20) - Google Drive operations (Ruby).
- **1.0.0** (2025-11-10) - Initial release (Ruby).
