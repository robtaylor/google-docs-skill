---
name: google-docs
description: Create formatted Google Docs from Markdown with inline images, mermaid diagrams, and tables. Read docs with tab and comment support. Manage Google Drive files. Uses Python API for reading and Apps Script for writing (bypasses Workspace image restrictions).
category: productivity
version: 2.1.0
key_capabilities: markdown-to-docs (inline images via Apps Script), read with tabs/comments, Drive upload/download/share/search, mermaid diagrams, tables, environment bootstrap
when_to_use: Creating Google Docs from Markdown, reading doc content/tabs/comments, uploading files to Drive, sharing documents
---

# Google Docs & Drive Management Skill

## Architecture

| Operation | Technology | Why |
|---|---|---|
| **Reading** docs, tabs, comments | Python + Docs/Drive REST API | Fast, direct, supports all fields |
| **Writing** docs with images | Python + Google Apps Script | Apps Script can insert private Drive images as blobs — the REST API cannot (2KB URL limit + Workspace blocks public sharing) |
| **Drive** operations | Python + Drive REST API | Standard CRUD |

## First Time Setup

### Step 1: Install dependencies
```bash
scripts/setup
```
This checks uv, Python 3.11+, and installs packages. Follow any prompts.

### Step 2: Google Cloud Project
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Enable these APIs:
   - [Google Docs API](https://console.cloud.google.com/apis/api/docs.googleapis.com)
   - [Google Drive API](https://console.cloud.google.com/apis/api/drive.googleapis.com)
   - [Apps Script API](https://console.cloud.google.com/apis/api/script.googleapis.com)
4. Create OAuth 2.0 credentials (Desktop application)
5. Download the JSON and save as `~/.claude/.google/client_secret.json`

### Step 3: Enable Apps Script (user-level)
Visit [script.google.com/home/usersettings](https://script.google.com/home/usersettings) and toggle **Google Apps Script API** to ON.

### Step 4: Authenticate
Run any command — a browser window opens for Google OAuth. Grant all requested permissions. Token is saved and auto-refreshes.

### Step 5: Set GCP project on Apps Script (first write only)
On the first `markdown_to_docs` run, an Apps Script project is auto-created. You'll see a message like:
```
Apps Script project created: <SCRIPT_ID>
IMPORTANT: Set GCP project number to <NUMBER> at:
  https://script.google.com/home/projects/<SCRIPT_ID>/settings
```
Open that URL, click "Change project", enter the number. This is a **one-time** step.

### Verify setup
```bash
scripts/setup                    # Full check
scripts/setup --check-appscript  # Apps Script only
scripts/setup --json             # Machine-readable
```

## Writing Documents

### Create from Markdown File (PRIMARY WORKFLOW)

```bash
scripts/markdown_to_docs --file ./report.md --title "My Report"
```

**What happens:**
1. Parses Markdown into structured blocks (headings, paragraphs, lists, tables, images, code)
2. Renders mermaid blocks to PNG locally
3. Uploads all images to Google Drive (in `skill/image2doc/{date}-{title}/`)
4. Creates a Google Doc
5. Sends blocks to Apps Script which builds the doc sequentially — **images are inserted inline where they appear in the markdown**
6. Returns JSON with doc URL and stats

**All options:**
```bash
scripts/markdown_to_docs --file PATH --title TITLE        # New doc
scripts/markdown_to_docs --file PATH --document-id ID     # Append to existing
scripts/markdown_to_docs --file PATH --title T --drive-folder-id ID  # Custom image folder
scripts/markdown_to_docs --file PATH --title T --dry-run  # Parse only, no API
```

**Supported Markdown (rendered as native Google Docs formatting):**

| Markdown | Google Docs Result |
|---|---|
| `# Heading` | HEADING_1 through HEADING_6 |
| `**bold**` | Bold text |
| `*italic*` | Italic text |
| `` `code` `` | Roboto Mono, grey background |
| `- item` | Bullet list |
| `1. item` | Numbered list |
| `---` | Horizontal rule |
| `\| table \|` | Full-width table with bold headers |
| `` ```mermaid `` | Rendered diagram image (PNG) |
| `![alt](path)` | Inline image from local file |
| `[text](url)` | Hyperlink |
| `` ```python `` | Code block (Roboto Mono, indented, grey bg) |

**Performance:** A 330-line markdown with 67 images + 4 tables completes in ~3 minutes.

### Small Document Operations (stdin)

For quick edits, use `docs_manager` which reads JSON from stdin:

```bash
# Create plain text doc
echo '{"title": "Notes", "content": "Hello world"}' | scripts/docs_manager create

# Create from markdown (small docs, no images)
echo '{"title": "Doc", "markdown": "# Title\n\n**Bold** text"}' | scripts/docs_manager create-from-markdown

# Insert text at position
echo '{"document_id": "ID", "text": "New text", "index": 1}' | scripts/docs_manager insert

# Append to end
echo '{"document_id": "ID", "text": "More text"}' | scripts/docs_manager append

# Find and replace
echo '{"document_id": "ID", "find": "old", "replace": "new"}' | scripts/docs_manager replace

# Format text range
echo '{"document_id": "ID", "start_index": 1, "end_index": 50, "bold": true}' | scripts/docs_manager format

# Insert page break
echo '{"document_id": "ID", "index": 100}' | scripts/docs_manager page-break

# Delete content range
echo '{"document_id": "ID", "start_index": 10, "end_index": 50}' | scripts/docs_manager delete
```

## Reading Documents

### Read Content
```bash
# Full document
scripts/docs_manager read <document_id>

# Specific tab
scripts/docs_manager read <document_id> --tab <tab_id>

# Include comments
scripts/docs_manager read <document_id> --include-comments
```

### Document Structure (headings outline)
```bash
scripts/docs_manager structure <document_id>
scripts/docs_manager structure <document_id> --tab <tab_id>
```

### Tabs
```bash
# List all tabs
scripts/docs_manager list-tabs <document_id>

# Add a tab
echo '{"document_id": "ID", "title": "New Tab"}' | scripts/docs_manager add-tab

# Create doc with multiple tabs
echo '{"title": "Doc", "tabs": [{"title": "Tab A", "markdown": "# A"}, {"title": "Tab B", "content": "text"}]}' | scripts/docs_manager create-with-tabs
```

### Comments
```bash
# List all comments with replies
scripts/docs_manager list-comments <document_id>

# Add a comment (optionally anchored to quoted text)
echo '{"document_id": "ID", "content": "Fix this", "quotedText": "typo here"}' | scripts/docs_manager add-comment

# Reply to a comment
echo '{"document_id": "ID", "comment_id": "CID", "content": "Done"}' | scripts/docs_manager reply-to-comment

# Resolve a comment
echo '{"document_id": "ID", "comment_id": "CID"}' | scripts/docs_manager resolve-comment

# Delete a comment
echo '{"document_id": "ID", "comment_id": "CID"}' | scripts/docs_manager delete-comment
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

# Folders
scripts/drive_manager create-folder --name "Project Docs"
scripts/drive_manager move --file-id file123 --folder-id folder456

# Other
scripts/drive_manager copy --file-id abc123 --name "Copy"
scripts/drive_manager get-metadata --file-id abc123
scripts/drive_manager delete --file-id abc123
```

## Output Format

All commands return JSON:
```json
{"status": "success", "document_id": "abc123", "operation": "read", ...}
{"status": "error", "error_code": "API_ERROR", "message": "..."}
```

## Scripts Reference

| Script | Commands | Technology |
|---|---|---|
| `scripts/markdown_to_docs` | `--file`, `--title`, `--document-id`, `--dry-run` | Apps Script (write) |
| `scripts/docs_manager` | read, structure, list-tabs, insert, append, replace, format, page-break, create, create-from-markdown, create-with-tabs, insert-from-markdown, add-tab, delete, insert-image, insert-table, list-comments, add-comment, reply-to-comment, resolve-comment, delete-comment | Python API (read+write) |
| `scripts/drive_manager` | upload, download, search, list, share, create-folder, move, copy, update, delete, get-metadata | Python API |
| `scripts/setup` | `--json`, `--check-appscript` | Python |

## Authentication & Credentials

| File | Purpose |
|---|---|
| `~/.claude/.google/client_secret.json` | OAuth client ID (from GCP Console) |
| `~/.claude/.google/token.json` | Access/refresh tokens (auto-managed) |
| `~/.claude/.google/apps_script_config.json` | Apps Script project ID + GCP number |

**OAuth scopes:** documents, drive, spreadsheets, calendar, contacts, gmail.modify, script.projects, script.deployments

**Shared auth:** Token is shared with email, calendar, contacts, drive, and sheets skills.

## Dependencies

Python 3.11+ managed by `uv`:
- `google-api-python-client` — Docs/Drive/Script API
- `google-auth` + `google-auth-oauthlib` — OAuth
- `mistune` — Markdown AST parsing
- `Pillow` — Image handling
- `playwright` — Browser automation (optional)

External: `mmdc` (mermaid CLI, optional — for mermaid diagram rendering)

## Version History

- **2.1.0** (2026-04-06) - Unified Apps Script pipeline: text+formatting+images all in one sequential pass (images inline, not appended). Comment support (list, add, reply, resolve, delete). Full-width tables. Apps Script setup checks in setup.py. Comprehensive SKILL.md rewrite.
- **2.0.0** (2026-04-03) - Full Python rewrite with uv. Large doc support. Mistune AST parser.
- **1.2.0** (2025-12-25) - Markdown support (Ruby).
- **1.0.0** (2025-11-10) - Initial release (Ruby).
