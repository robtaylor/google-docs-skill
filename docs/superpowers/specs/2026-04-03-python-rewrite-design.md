# Google Docs Skill: Full Python Rewrite with uv

## Problem

The existing Ruby-based Google Docs skill (`docs_manager.rb`, `drive_manager.rb`) cannot reliably create large documents (50+ pages) because:

1. All text is sent in a single `insertText` API call — hits the ~10MB `batchUpdate` payload limit
2. All formatting requests sent in a single `batchUpdate` — thousands of requests overflow payload
3. Hand-rolled line-by-line markdown parser cannot handle nested structures reliably
4. No integration between mermaid diagram rendering and markdown content creation
5. Stdin-based JSON input breaks with large or complex content

## Solution

Full rewrite to Python using `uv` for dependency management. Three CLI tools with shared auth and a proper AST-based markdown parser.

## API Constraints (Grounded)

| Constraint | Value | Source |
|---|---|---|
| batchUpdate payload limit | ~10MB | Google API general limit; server returns 400 |
| Write requests/min/user | 60 | developers.google.com/workspace/docs/api/limits |
| Read requests/min/user | 300 | same |
| batchUpdate atomicity | All-or-nothing per call | Official batchUpdate reference |
| Max document characters | ~1.02M | Known practical limit |
| Streaming/chunking | Not supported | Verified in Ruby SDK source |
| Tab support | Full (AddDocumentTab, tabId in Location) | Official tabs docs |
| Best practice | Insert in descending index order | Official best practices |
| SDK | google-api-python-client + google-auth | Google's primary documented language |

## Project Structure

```
scripts/
  pyproject.toml
  google_docs/
    __init__.py
    auth.py                  # Shared OAuth
    docs_manager.py          # Port of docs_manager.rb
    drive_manager.py         # Port of drive_manager.rb
    markdown_to_docs.py      # NEW: large doc pipeline
    markdown_parser.py       # NEW: mistune AST -> Docs API requests
    image_pipeline.py        # NEW: mermaid render + image upload
  docs_manager               # CLI entry point (#!/usr/bin/env uv run)
  drive_manager              # CLI entry point
  markdown_to_docs           # CLI entry point
```

## Module 1: auth.py

Shared OAuth module. Reads existing tokens at:
- `~/.claude/.google/client_secret.json`
- `~/.claude/.google/token.json`

Functions:
- `get_credentials() -> google.oauth2.credentials.Credentials` — loads token, refreshes if expired, prompts for re-auth if refresh fails
- `get_docs_service() -> googleapiclient.discovery.Resource` — builds Docs v1 service
- `get_drive_service() -> googleapiclient.discovery.Resource` — builds Drive v3 service

Must be compatible with the existing Ruby token format (standard Google OAuth2 JSON).

## Module 2: docs_manager.py

1:1 port of `scripts/docs_manager.rb`. All 17 commands with identical CLI interface and JSON output format.

### Commands (all existing)

| Command | Description |
|---|---|
| `read <doc_id> [--tab <tab_id>]` | Read document content |
| `structure <doc_id> [--tab <tab_id>]` | Get headings structure |
| `list-tabs <doc_id>` | List all tabs |
| `insert` | Insert text at index (JSON stdin) |
| `append` | Append text to end (JSON stdin) |
| `replace` | Find and replace (JSON stdin) |
| `format` | Format text range (JSON stdin) |
| `page-break` | Insert page break (JSON stdin) |
| `create` | Create new doc (JSON stdin) |
| `create-from-markdown` | Create doc from markdown (JSON stdin) |
| `create-with-tabs` | Create doc with multiple tabs (JSON stdin) |
| `insert-from-markdown` | Insert markdown into existing doc (JSON stdin) |
| `add-tab` | Add tab to doc (JSON stdin) |
| `delete` | Delete content range (JSON stdin) |
| `insert-image` | Insert inline image (JSON stdin) |
| `insert-table` | Insert table (JSON stdin) |

### Key change in port

Replace the hand-rolled `parse_markdown` method (Ruby line 1364) with `markdown_parser.py` using mistune. This fixes the existing `create-from-markdown` for small-to-medium docs too.

For commands that accept JSON via stdin: keep stdin for backward compatibility since these are small payloads (single operations). The large-doc problem is solved by `markdown_to_docs.py` which uses file paths.

## Module 3: drive_manager.py

1:1 port of `scripts/drive_manager.rb`. All commands with identical CLI interface.

### Commands (all existing)

| Command | Description |
|---|---|
| `upload --file <path> [--folder-id <id>] [--name <name>]` | Upload file |
| `download --file-id <id> --output <path> [--export-as <fmt>]` | Download/export |
| `search --query <query> [--max-results N]` | Search files |
| `list [--max-results N]` | List recent files |
| `share --file-id <id> --email/--type <...> --role <role>` | Share file |
| `create-folder --name <name> [--parent-id <id>]` | Create folder |
| `move --file-id <id> --folder-id <id>` | Move file |
| `copy --file-id <id> --name <name>` | Copy file |
| `update --file-id <id> --file <path>` | Update file content |
| `delete --file-id <id>` | Delete (trash) |
| `get-metadata --file-id <id>` | Get file metadata |

## Module 4: markdown_parser.py

Mistune 3.x based markdown parser that converts AST nodes to Google Docs API Request objects.

### Supported markdown features

- Headings: `#` through `######` -> HEADING_1 through HEADING_6
- Bold: `**text**` -> UpdateTextStyleRequest with bold=true
- Italic: `*text*` -> UpdateTextStyleRequest with italic=true
- Code spans: `` `text` `` -> Courier New font with grey background
- Bullet lists: `- item` / `* item` -> CreateParagraphBulletsRequest (BULLET_DISC_CIRCLE_SQUARE)
- Numbered lists: `1. item` -> CreateParagraphBulletsRequest (NUMBERED_DECIMAL_ALPHA_ROMAN)
- Checkboxes: `- [ ]` / `- [x]` -> CHECKBOX_UNCHECKED / CHECKBOX_CHECKED
- Horizontal rules: `---` -> InsertPageBreakRequest (or horizontal line)
- Tables: `| col | col |` -> InsertTableRequest + cell population
- Fenced code blocks: ` ```lang ``` ` -> Courier New, grey background, full block
- Mermaid blocks: ` ```mermaid ``` ` -> placeholder for image insertion
- Images: `![alt](path)` -> placeholder for image insertion
- Links: `[text](url)` -> UpdateTextStyleRequest with link

### Output format

```python
@dataclass
class ParseResult:
    # Plain text with all markdown stripped (for InsertText)
    text: str
    # Format requests to apply after text insertion
    format_requests: list[dict]  # Google Docs API Request dicts
    # Image placeholders with positions
    images: list[ImagePlaceholder]
    # Table data with positions
    tables: list[TablePlaceholder]

@dataclass
class ImagePlaceholder:
    index: int          # Position in the plain text
    source: str         # File path or mermaid content
    source_type: str    # "file" | "mermaid" | "url"
    alt_text: str
    width: int | None
    height: int | None

@dataclass
class TablePlaceholder:
    index: int
    rows: list[list[str]]
    num_rows: int
    num_cols: int
```

## Module 5: image_pipeline.py

Handles all image processing: mermaid rendering and uploading to Google Drive.

### Functions

- `render_mermaid(content: str, output_path: str, width: int = 800, theme: str = "default") -> str` — calls `mmdc`, returns output path
- `upload_image(file_path: str, drive_service, folder_id: str | None = None) -> str` — uploads to Drive, makes public, returns URL
- `process_images(images: list[ImagePlaceholder], drive_service, base_dir: str, folder_id: str | None = None) -> list[ResolvedImage]` — processes all images, returns URLs

### Image resolution

- `source_type == "file"`: resolve relative to markdown file's directory, upload to Drive
- `source_type == "mermaid"`: render to temp PNG via mmdc, upload to Drive
- `source_type == "url"`: use URL directly (must be publicly accessible)

Supported formats: PNG, JPG, JPEG, GIF. SVG is rendered to PNG first (via mmdc or rsvg-convert).

## Module 6: markdown_to_docs.py (the main new capability)

Orchestrates the full pipeline for large documents.

### CLI Interface

```bash
# Create new doc from markdown file
scripts/markdown_to_docs --file ./design.md --title "Design Doc"

# With Drive folder for uploaded images
scripts/markdown_to_docs --file ./design.md --title "Design Doc" --drive-folder-id abc123

# Into existing document (appends to end)
scripts/markdown_to_docs --file ./design.md --document-id xyz789

# Into specific tab
scripts/markdown_to_docs --file ./design.md --document-id xyz789 --tab-id t.abc

# Dry run
scripts/markdown_to_docs --file ./design.md --dry-run
```

### Pipeline

```
1. Read markdown file from disk
2. Parse with markdown_parser.py -> ParseResult
3. Process images with image_pipeline.py -> resolved URLs
4. Generate full list of Docs API requests:
   a. InsertText for all plain text
   b. UpdateTextStyle / UpdateParagraphStyle for formatting
   c. InsertInlineImage for resolved images
   d. InsertTable + cell population for tables
   All ordered by descending index (per Google best practice)
5. Create document (or get existing doc's end index)
6. Chunk requests into batches of <= 4MB serialized JSON
7. Send each batch via batchUpdate:
   - Track write count, sleep if approaching 60/min
   - On 429: exponential backoff (1s, 2s, 4s, ..., max 64s)
   - On error: report chunk number + resume info
8. Output JSON result
```

### Chunking algorithm

```python
def chunk_requests(requests: list[dict], max_bytes: int = 4_000_000) -> list[list[dict]]:
    """Split requests into chunks that fit within max_bytes when JSON-serialized."""
    chunks = []
    current_chunk = []
    current_size = 0
    
    for req in requests:
        req_size = len(json.dumps(req).encode('utf-8'))
        if current_size + req_size > max_bytes and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        current_chunk.append(req)
        current_size += req_size
    
    if current_chunk:
        chunks.append(current_chunk)
    return chunks
```

### Rate limiter

```python
class RateLimiter:
    """Ensures max 55 writes/min (buffer below 60 limit)."""
    def __init__(self, max_per_minute: int = 55):
        self.timestamps: list[float] = []
        self.max_per_minute = max_per_minute
    
    def wait_if_needed(self):
        now = time.time()
        self.timestamps = [t for t in self.timestamps if now - t < 60]
        if len(self.timestamps) >= self.max_per_minute:
            sleep_time = 60 - (now - self.timestamps[0]) + 0.1
            time.sleep(sleep_time)
        self.timestamps.append(time.time())
```

### Output (JSON)

```json
{
  "status": "success",
  "document_id": "abc123",
  "title": "Design Doc",
  "web_view_link": "https://docs.google.com/document/d/abc123/edit",
  "stats": {
    "chunks_sent": 12,
    "total_requests": 847,
    "images_uploaded": 5,
    "mermaid_rendered": 3,
    "tables_inserted": 8,
    "characters_inserted": 125000
  }
}
```

## CLI Entry Points

Thin wrapper scripts in `scripts/` with `uv run` shebang:

```bash
#!/usr/bin/env -S uv run --project /path/to/scripts
from google_docs.docs_manager import main
main()
```

These ensure `uv` handles dependency resolution automatically on first run.

## Dependencies

```toml
[project]
dependencies = [
    "google-api-python-client>=2.100",
    "google-auth>=2.20",
    "google-auth-oauthlib>=1.0",
    "mistune>=3.0",
    "Pillow>=10.0",
]
```

External tools (must be on PATH):
- `mmdc` (mermaid CLI) — for mermaid block rendering
- `rsvg-convert` (optional) — for SVG to PNG conversion

## SKILL.md Updates

- All examples updated to Python CLI
- New section documenting `markdown_to_docs` command
- Dependencies section updated to Python + uv
- Version bumped to 2.0.0

## What Gets Deleted

- `scripts/docs_manager.rb`
- `scripts/drive_manager.rb`
- `scripts/mermaid_to_docs.sh`

## Testing

- Unit tests for `markdown_parser.py` (AST -> requests conversion)
- Unit tests for chunking algorithm
- Integration tests for `auth.py` (token loading)
- E2E test: create a doc from a sample markdown with mermaid + images + tables
