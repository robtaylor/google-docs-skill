"""Build Google Docs via Apps Script — handles text, formatting, images, tables in one call.

This replaces the Docs REST API for document content creation. Apps Script's
DocumentApp can insert formatted text AND images from Drive blobs, solving
the REST API's 2KB URL limit and Workspace public-sharing restrictions.

Architecture:
    Python: parse markdown → blocks[] JSON → upload images to Drive
    Apps Script: receive blocks[] → appendParagraph/ListItem/Table/Image sequentially

Usage:
    from google_docs.appscript_builder import build_doc_from_blocks

    result = build_doc_from_blocks(
        document_id="abc123",
        blocks=[
            {"type": "heading", "level": 1, "text": "Title"},
            {"type": "paragraph", "runs": [{"text": "Hello ", "bold": True}]},
            {"type": "image", "driveFileId": "xyz789"},
        ],
    )
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from google_docs.auth import get_credentials

SCRIPT_CONFIG_PATH = Path.home() / ".claude" / ".google" / "apps_script_config.json"

# The Apps Script that builds the entire document from structured blocks
_SCRIPT_CODE = r'''
function buildDocument(docId, blocks) {
  var doc = DocumentApp.openById(docId);
  var body = doc.getBody();

  // Remove the default empty paragraph if doc is new
  if (body.getNumChildren() === 1) {
    var first = body.getChild(0);
    if (first.getType() === DocumentApp.ElementType.PARAGRAPH && first.asParagraph().getText() === '') {
      // Will be replaced by first append
    }
  }

  var stats = {paragraphs: 0, headings: 0, lists: 0, tables: 0, images: 0, codeBlocks: 0, errors: []};

  for (var i = 0; i < blocks.length; i++) {
    var block = blocks[i];
    try {
      switch (block.type) {
        case 'heading':
          _insertHeading(body, block);
          stats.headings++;
          break;
        case 'paragraph':
          _insertParagraph(body, block);
          stats.paragraphs++;
          break;
        case 'list':
          _insertList(body, block);
          stats.lists++;
          break;
        case 'table':
          _insertTable(body, block);
          stats.tables++;
          break;
        case 'image':
          _insertImage(body, block);
          stats.images++;
          break;
        case 'code_block':
          _insertCodeBlock(body, block);
          stats.codeBlocks++;
          break;
        case 'hr':
          body.appendHorizontalRule();
          break;
        default:
          stats.errors.push('Unknown block type: ' + block.type);
      }
    } catch(e) {
      stats.errors.push('Block ' + i + ' (' + block.type + '): ' + e.toString());
    }
  }

  doc.saveAndClose();
  return stats;
}

function _insertHeading(body, block) {
  var para = body.appendParagraph(block.text || '');
  var headingMap = {
    1: DocumentApp.ParagraphHeading.HEADING1,
    2: DocumentApp.ParagraphHeading.HEADING2,
    3: DocumentApp.ParagraphHeading.HEADING3,
    4: DocumentApp.ParagraphHeading.HEADING4,
    5: DocumentApp.ParagraphHeading.HEADING5,
    6: DocumentApp.ParagraphHeading.HEADING6
  };
  para.setHeading(headingMap[block.level] || DocumentApp.ParagraphHeading.HEADING1);

  // Apply inline formatting if runs provided
  if (block.runs && block.runs.length > 0) {
    _applyRuns(para, block.runs);
  }
}

function _insertParagraph(body, block) {
  var para = body.appendParagraph('');
  if (block.runs && block.runs.length > 0) {
    _applyRuns(para, block.runs);
  } else if (block.text) {
    para.appendText(block.text);
  }
}

function _applyRuns(para, runs) {
  var offset = 0;
  for (var i = 0; i < runs.length; i++) {
    var run = runs[i];
    var runText = run.text || '';
    if (runText.length === 0) continue;

    para.appendText(runText);
    var text = para.editAsText();
    var start = offset;
    var end = offset + runText.length - 1;

    if (run.bold) text.setBold(start, end, true);
    if (run.italic) text.setItalic(start, end, true);
    if (run.strikethrough) text.setStrikethrough(start, end, true);
    if (run.underline) text.setUnderline(start, end, true);
    if (run.code) {
      text.setFontFamily(start, end, 'Roboto Mono');
      text.setFontSize(start, end, 9);
      text.setBackgroundColor(start, end, '#f1f3f4');
    }
    if (run.link) {
      text.setLinkUrl(start, end, run.link);
      text.setForegroundColor(start, end, '#1a73e8');
    }

    offset += runText.length;
  }
}

function _insertList(body, block) {
  var items = block.items || [];
  var ordered = block.ordered || false;

  for (var i = 0; i < items.length; i++) {
    var item = items[i];
    var itemText = item.text || '';
    if (itemText.length === 0 && (!item.runs || item.runs.length === 0)) continue;
    var li = body.appendListItem(itemText);
    li.setGlyphType(ordered
      ? DocumentApp.GlyphType.NUMBER
      : DocumentApp.GlyphType.BULLET);
    if (item.level && item.level > 0) {
      li.setNestingLevel(item.level);
    }
    // Apply formatting to list item text
    if (item.runs && item.runs.length > 0) {
      // Clear the plain text and use runs instead
      li.setText('');
      var offset = 0;
      for (var j = 0; j < item.runs.length; j++) {
        var run = item.runs[j];
        if (!run.text) continue;
        li.appendText(run.text);
        var t = li.editAsText();
        var s = offset;
        var e = offset + run.text.length - 1;
        if (run.bold) t.setBold(s, e, true);
        if (run.italic) t.setItalic(s, e, true);
        if (run.code) {
          t.setFontFamily(s, e, 'Roboto Mono');
          t.setFontSize(s, e, 9);
          t.setBackgroundColor(s, e, '#f1f3f4');
        }
        if (run.link) t.setLinkUrl(s, e, run.link);
        offset += run.text.length;
      }
    }
  }
}

function _insertTable(body, block) {
  var rows = block.rows || [];
  if (rows.length === 0) return;

  var table = body.appendTable(rows);
  var numCols = rows[0] ? rows[0].length : 0;

  // Set table to full page width (468pt = 6.5in with 1in margins)
  if (numCols > 0) {
    var pageWidth = 468;
    var colWidth = Math.floor(pageWidth / numCols);
    for (var c = 0; c < numCols; c++) {
      table.setColumnWidth(c, colWidth);
    }
  }

  // Bold the header row
  if (block.boldHeader !== false && table.getNumRows() > 0) {
    var headerRow = table.getRow(0);
    for (var i = 0; i < headerRow.getNumCells(); i++) {
      headerRow.getCell(i).editAsText().setBold(true);
      headerRow.getCell(i).setBackgroundColor('#f1f3f4');
    }
  }
}

function _insertImage(body, block) {
  var blob;
  if (block.driveFileId) {
    blob = DriveApp.getFileById(block.driveFileId).getBlob();
  } else {
    return; // No source
  }

  var img = body.appendImage(blob);
  if (block.width) img.setWidth(block.width);
  if (block.height) img.setHeight(block.height);

  // Add caption as a paragraph below the image
  if (block.caption) {
    var caption = body.appendParagraph(block.caption);
    caption.setAlignment(DocumentApp.HorizontalAlignment.CENTER);
    caption.editAsText().setItalic(true);
    caption.editAsText().setFontSize(9);
    caption.editAsText().setForegroundColor('#666666');
  }
}

function _insertCodeBlock(body, block) {
  var para = body.appendParagraph(block.text || '');
  var text = para.editAsText();
  text.setFontFamily('Roboto Mono');
  text.setFontSize(9);
  text.setBackgroundColor('#f8f9fa');
  para.setIndentStart(36); // 0.5 inch indent
  para.setIndentEnd(36);
  para.setSpacingBefore(6);
  para.setSpacingAfter(6);
  // Light grey left border effect via indent
}
'''

_MANIFEST = json.dumps({
    "timeZone": "UTC",
    "oauthScopes": [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive",
    ],
    "exceptionLogging": "STACKDRIVER",
    "executionApi": {"access": "MYSELF"},
    "runtimeVersion": "V8",
})


def _load_script_config() -> dict | None:
    if SCRIPT_CONFIG_PATH.exists():
        return json.loads(SCRIPT_CONFIG_PATH.read_text())
    return None


def _save_script_config(config: dict) -> None:
    SCRIPT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCRIPT_CONFIG_PATH.write_text(json.dumps(config, indent=2))
    SCRIPT_CONFIG_PATH.chmod(0o600)


def _get_gcp_project_number() -> str:
    client_path = Path.home() / ".claude" / ".google" / "client_secret.json"
    data = json.loads(client_path.read_text())
    installed = data.get("installed", data.get("web", {}))
    client_id = installed.get("client_id", "")
    return client_id.split("-")[0] if "-" in client_id else ""


def _find_or_create_folder(drive, name: str, parent_id: str | None = None) -> str:
    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    results = drive.files().list(q=query, fields="files(id)", pageSize=1).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    body: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        body["parents"] = [parent_id]
    return drive.files().create(body=body, fields="id").execute()["id"]


def _ensure_drive_folder(drive, doc_title: str) -> str:
    """Create Drive folder: skill/image2doc/{date}-{title}/."""
    skill_id = _find_or_create_folder(drive, "skill")
    image2doc_id = _find_or_create_folder(drive, "image2doc", skill_id)
    leaf = f"{date.today().isoformat()}-{doc_title}"
    return _find_or_create_folder(drive, leaf, image2doc_id)


def ensure_script_project(script_service) -> str:
    """Get or create reusable Apps Script project. Returns script ID."""
    config = _load_script_config()
    if config and config.get("script_id"):
        try:
            # Verify it exists and update code
            script_service.projects().get(scriptId=config["script_id"]).execute()
            # Always push latest code
            _push_script_code(script_service, config["script_id"])
            return config["script_id"]
        except Exception:
            pass

    project = script_service.projects().create(body={
        "title": "GoogleDocsSkill_DocBuilder",
    }).execute()
    script_id = project["scriptId"]
    _push_script_code(script_service, script_id)

    version = script_service.projects().versions().create(
        scriptId=script_id, body={"description": "v1"}
    ).execute()
    script_service.projects().deployments().create(
        scriptId=script_id,
        body={"versionNumber": version["versionNumber"], "description": "api-exec"},
    ).execute()

    gcp_number = _get_gcp_project_number()
    _save_script_config({
        "script_id": script_id,
        "gcp_project_number": gcp_number,
        "created": date.today().isoformat(),
    })

    print(
        f"Apps Script project created: {script_id}\n"
        f"IMPORTANT: Set GCP project number to {gcp_number} at:\n"
        f"  https://script.google.com/home/projects/{script_id}/settings",
        file=sys.stderr,
    )
    return script_id


def _push_script_code(script_service, script_id: str) -> None:
    script_service.projects().updateContent(scriptId=script_id, body={
        "files": [
            {"name": "Code", "type": "SERVER_JS", "source": _SCRIPT_CODE},
            {"name": "appsscript", "type": "JSON", "source": _MANIFEST},
        ]
    }).execute()


def _guess_mime(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
    }.get(ext, "application/octet-stream")


def upload_image_to_drive(
    drive, file_path: str, folder_id: str | None = None
) -> str:
    """Upload image to Drive, return file ID."""
    body: dict = {"name": Path(file_path).name}
    if folder_id:
        body["parents"] = [folder_id]
    media = MediaFileUpload(file_path, mimetype=_guess_mime(file_path), resumable=True)
    return drive.files().create(body=body, media_body=media, fields="id").execute()["id"]


def build_doc_from_blocks(
    document_id: str,
    blocks: list[dict],
    on_progress: callable | None = None,
) -> dict:
    """Build document content via Apps Script from structured blocks.

    Args:
        document_id: Google Doc ID (must already exist)
        blocks: List of block dicts (heading, paragraph, list, table, image, code_block, hr)
        on_progress: Optional callback(message: str)

    Returns:
        Stats dict from Apps Script execution
    """
    creds = get_credentials()
    import google_auth_httplib2, httplib2
    http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=300))
    script_service = build("script", "v1", http=http)
    script_id = ensure_script_project(script_service)

    if on_progress:
        on_progress(f"Sending {len(blocks)} blocks to Apps Script...")

    # Apps Script scripts.run has ~50MB payload limit but 6-min execution limit
    # For very large docs, chunk blocks into batches
    BATCH_SIZE = 30  # blocks per call (keep small due to image blob fetch time)
    all_stats: dict = {"paragraphs": 0, "headings": 0, "lists": 0,
                       "tables": 0, "images": 0, "codeBlocks": 0, "errors": []}

    for batch_start in range(0, len(blocks), BATCH_SIZE):
        batch = blocks[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(blocks) + BATCH_SIZE - 1) // BATCH_SIZE

        if on_progress:
            on_progress(f"  Batch {batch_num}/{total_batches} ({len(batch)} blocks)")

        result = script_service.scripts().run(
            scriptId=script_id,
            body={
                "function": "buildDocument",
                "parameters": [document_id, batch],
                "devMode": True,
            },
        ).execute()

        if "error" in result:
            detail = result["error"].get("details", [{}])
            msg = detail[0].get("errorMessage", str(result["error"])) if detail else str(result["error"])
            all_stats["errors"].append(f"Batch {batch_num}: {msg}")
        else:
            stats = result.get("response", {}).get("result", {})
            for key in ("paragraphs", "headings", "lists", "tables", "images", "codeBlocks"):
                all_stats[key] += stats.get(key, 0)
            all_stats["errors"].extend(stats.get("errors", []))

        if batch_start + BATCH_SIZE < len(blocks):
            time.sleep(1)  # Brief pause between batches

    return all_stats
