> [!WARNING]
> ## ⚠️ Archived — use [google-workspace](https://github.com/andmarios/google-workspace-skill) instead
>
> This skill is **no longer maintained**. [`andmarios/google-workspace-skill`](https://github.com/andmarios/google-workspace-skill)
> is a strict superset: it covers every Docs and Drive operation here, plus Sheets,
> Slides, Gmail, Calendar, and Contacts (239 operations across 8 services), with
> encrypted token storage, multi-account support, prompt-injection screening, and a
> test suite. It installs as a `uvx gws-cli` tool.
>
> ```bash
> git clone https://github.com/andmarios/google-workspace-skill ~/.claude/skills/google-workspace
> ```
>
> The content below is retained for historical reference only.

---

# Google Docs Skill for Claude Code

A Claude Code skill for managing Google Docs and Google Drive with comprehensive document and file operations.

## Features

### Google Docs Operations
- Read document content and structure
- Create new documents
- Insert and append text
- Find and replace text
- Text formatting (bold, italic, underline)
- Insert page breaks and images
- Delete content ranges

### Google Drive Operations
- Upload and download files
- Search across Drive
- Create and list folders
- Share files and folders
- Move and organize files
- Export files to different formats (PDF, PNG, etc.)

## Installation

Add this skill to your Claude Code configuration:

```bash
# Clone to your skills directory
git clone https://github.com/robtaylor/google-docs-skill.git ~/.claude/skills/google-docs

# Or add as submodule to your claude-config
cd ~/.claude
git submodule add https://github.com/robtaylor/google-docs-skill.git skills/google-docs
```

## Setup

1. **Create Google Cloud Project** and enable the Docs and Drive APIs
2. **Create OAuth 2.0 credentials** (Desktop application type)
3. **Download credentials** and save as `~/.claude/.google/client_secret.json`
4. **Run any command** - the script will prompt for authorization

The OAuth token is shared with other Google skills (Sheets, Calendar, Gmail, etc.).

## Usage

See [SKILL.md](SKILL.md) for complete documentation and examples.

### Quick Examples

```bash
# Read a document
scripts/docs_manager.rb read <document_id>

# Create a document
echo '{"title": "My Doc", "content": "Hello World"}' | scripts/docs_manager.rb create

# Upload a file to Drive
scripts/drive_manager.rb upload --file ./myfile.pdf --name "My PDF"

# Search Drive
scripts/drive_manager.rb search --query "name contains 'Report'"
```

## License

MIT License - see [LICENSE](LICENSE) for details.
