#!/usr/bin/env python3
"""Google Drive Manager - CLI for Drive File Operations."""

import argparse
import io
import json
import os
import sys

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from google_docs.auth import get_drive_service

# Exit codes
EXIT_SUCCESS = 0
EXIT_OPERATION_FAILED = 1
EXIT_AUTH_ERROR = 2
EXIT_API_ERROR = 3
EXIT_INVALID_ARGS = 4

MIME_TYPE_MAP = {
    ".excalidraw": "application/json",
    ".json": "application/json",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".zip": "application/zip",
    ".csv": "text/csv",
    ".xml": "application/xml",
    ".yaml": "application/x-yaml",
    ".yml": "application/x-yaml",
}

EXPORT_MIME_MAP = {
    "application/vnd.google-apps.document": "application/pdf",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "application/pdf",
    "application/vnd.google-apps.drawing": "image/png",
}


def output_json(data, exit_code=None):
    """Print JSON output and optionally exit with given code."""
    print(json.dumps(data, indent=2, default=str))
    if exit_code is not None:
        sys.exit(exit_code)


def detect_mime_type(file_path):
    """Detect MIME type from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    return MIME_TYPE_MAP.get(ext, "application/octet-stream")


def _format_file(f):
    """Format a Drive file resource into a JSON-compatible dict."""
    return {
        "id": f.get("id"),
        "name": f.get("name"),
        "mime_type": f.get("mimeType"),
        "web_view_link": f.get("webViewLink"),
        "web_content_link": f.get("webContentLink"),
        "parents": f.get("parents"),
        "created_time": f.get("createdTime"),
        "modified_time": f.get("modifiedTime"),
        "size": f.get("size"),
    }


def cmd_upload(service, args):
    """Upload a file to Google Drive."""
    file_path = args.file
    if not os.path.exists(file_path):
        output_json({
            "status": "error",
            "error_code": "FILE_NOT_FOUND",
            "operation": "upload",
            "message": f"File not found: {file_path}",
        }, EXIT_OPERATION_FAILED)

    file_name = args.name or os.path.basename(file_path)
    mime_type = args.mime_type or detect_mime_type(file_path)

    file_metadata = {"name": file_name}
    if args.folder_id:
        file_metadata["parents"] = [args.folder_id]

    media = MediaFileUpload(file_path, mimetype=mime_type)
    result = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, mimeType, webViewLink, webContentLink, parents, createdTime, modifiedTime, size",
    ).execute()

    output_json({
        "status": "success",
        "operation": "upload",
        "file": _format_file(result),
    })


def cmd_download(service, args):
    """Download a file from Google Drive."""
    file_meta = service.files().get(
        fileId=args.file_id, fields="id, name, mimeType"
    ).execute()

    source_mime = file_meta.get("mimeType", "")
    if source_mime.startswith("application/vnd.google-apps."):
        export_mime = EXPORT_MIME_MAP.get(source_mime, "application/pdf")
        request = service.files().export_media(
            fileId=args.file_id, mimeType=export_mime
        )
        fh = io.FileIO(args.output, "wb")
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.close()
        output_json({
            "status": "success",
            "operation": "export",
            "file_id": args.file_id,
            "output_path": args.output,
            "export_mime_type": export_mime,
        })
        return

    request = service.files().get_media(fileId=args.file_id)
    fh = io.FileIO(args.output, "wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.close()

    output_json({
        "status": "success",
        "operation": "download",
        "file_id": args.file_id,
        "output_path": args.output,
        "name": file_meta.get("name"),
        "mime_type": source_mime,
    })


def cmd_list(service, args):
    """List files in Drive or folder."""
    query_parts = ["trashed = false"]
    if args.folder_id:
        query_parts.append(f"'{args.folder_id}' in parents")

    results = service.files().list(
        q=" and ".join(query_parts),
        pageSize=args.max_results,
        pageToken=args.page_token,
        fields="nextPageToken, files(id, name, mimeType, webViewLink, parents, createdTime, modifiedTime, size)",
    ).execute()

    files = [_format_file(f) for f in results.get("files", [])]
    output_json({
        "status": "success",
        "operation": "list",
        "folder_id": args.folder_id,
        "files": files,
        "next_page_token": results.get("nextPageToken"),
        "count": len(files),
    })


def cmd_search(service, args):
    """Search files with query."""
    query = args.query
    if "trashed" not in query:
        query = f"{query} and trashed = false"

    results = service.files().list(
        q=query,
        pageSize=args.max_results,
        pageToken=args.page_token,
        fields="nextPageToken, files(id, name, mimeType, webViewLink, parents, createdTime, modifiedTime, size)",
    ).execute()

    files = [_format_file(f) for f in results.get("files", [])]
    output_json({
        "status": "success",
        "operation": "search",
        "query": args.query,
        "files": files,
        "next_page_token": results.get("nextPageToken"),
        "count": len(files),
    })


def cmd_get_metadata(service, args):
    """Get file metadata."""
    f = service.files().get(
        fileId=args.file_id,
        fields="id, name, mimeType, webViewLink, webContentLink, parents, createdTime, modifiedTime, size, description, starred, trashed, owners, permissions",
    ).execute()

    owners = [
        {"email": o.get("emailAddress"), "name": o.get("displayName")}
        for o in (f.get("owners") or [])
    ]
    permissions = [
        {"id": p.get("id"), "type": p.get("type"), "role": p.get("role"), "email": p.get("emailAddress")}
        for p in (f.get("permissions") or [])
    ]

    file_data = _format_file(f)
    file_data.update({
        "description": f.get("description"),
        "starred": f.get("starred"),
        "trashed": f.get("trashed"),
        "owners": owners,
        "permissions": permissions,
    })

    output_json({
        "status": "success",
        "operation": "get_metadata",
        "file": file_data,
    })


def cmd_create_folder(service, args):
    """Create a new folder."""
    file_metadata = {
        "name": args.name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    parent_id = getattr(args, "parent_id", None) or args.folder_id
    if parent_id:
        file_metadata["parents"] = [parent_id]

    result = service.files().create(
        body=file_metadata,
        fields="id, name, mimeType, webViewLink, parents, createdTime",
    ).execute()

    output_json({
        "status": "success",
        "operation": "create_folder",
        "folder": {
            "id": result.get("id"),
            "name": result.get("name"),
            "web_view_link": result.get("webViewLink"),
            "parents": result.get("parents"),
            "created_time": result.get("createdTime"),
        },
    })


def cmd_move(service, args):
    """Move file to a different folder."""
    current = service.files().get(
        fileId=args.file_id, fields="parents"
    ).execute()
    previous_parents = ",".join(current.get("parents", []))

    result = service.files().update(
        fileId=args.file_id,
        addParents=args.folder_id,
        removeParents=previous_parents,
        fields="id, name, parents, webViewLink",
    ).execute()

    output_json({
        "status": "success",
        "operation": "move",
        "file": {
            "id": result.get("id"),
            "name": result.get("name"),
            "parents": result.get("parents"),
            "web_view_link": result.get("webViewLink"),
        },
    })


def cmd_share(service, args):
    """Share file with user or make public."""
    perm_type = args.type or ("user" if args.email else "anyone")

    permission = {"type": perm_type, "role": args.role}
    if args.email and perm_type == "user":
        permission["emailAddress"] = args.email

    result = service.permissions().create(
        fileId=args.file_id,
        body=permission,
        fields="id, type, role, emailAddress",
    ).execute()

    file_info = service.files().get(
        fileId=args.file_id, fields="webViewLink, webContentLink"
    ).execute()

    output_json({
        "status": "success",
        "operation": "share",
        "permission": {
            "id": result.get("id"),
            "type": result.get("type"),
            "role": result.get("role"),
            "email": result.get("emailAddress"),
        },
        "web_view_link": file_info.get("webViewLink"),
        "web_content_link": file_info.get("webContentLink"),
    })


def cmd_delete(service, args):
    """Delete file (move to trash or permanent)."""
    if args.permanent:
        service.files().delete(fileId=args.file_id).execute()
    else:
        service.files().update(
            fileId=args.file_id, body={"trashed": True}
        ).execute()

    output_json({
        "status": "success",
        "operation": "delete",
        "file_id": args.file_id,
        "permanent": args.permanent,
    })


def cmd_copy(service, args):
    """Copy a file."""
    file_metadata = {}
    if args.name:
        file_metadata["name"] = args.name
    if args.folder_id:
        file_metadata["parents"] = [args.folder_id]

    result = service.files().copy(
        fileId=args.file_id,
        body=file_metadata,
        fields="id, name, mimeType, webViewLink, parents, createdTime",
    ).execute()

    output_json({
        "status": "success",
        "operation": "copy",
        "file": {
            "id": result.get("id"),
            "name": result.get("name"),
            "mime_type": result.get("mimeType"),
            "web_view_link": result.get("webViewLink"),
            "parents": result.get("parents"),
            "created_time": result.get("createdTime"),
        },
    })


def cmd_update(service, args):
    """Update file content."""
    file_path = args.file
    if not os.path.exists(file_path):
        output_json({
            "status": "error",
            "error_code": "FILE_NOT_FOUND",
            "operation": "update",
            "message": f"File not found: {file_path}",
        }, EXIT_OPERATION_FAILED)

    file_metadata = {}
    if args.name:
        file_metadata["name"] = args.name

    mime_type = detect_mime_type(file_path)
    media = MediaFileUpload(file_path, mimetype=mime_type)

    result = service.files().update(
        fileId=args.file_id,
        body=file_metadata,
        media_body=media,
        fields="id, name, mimeType, webViewLink, modifiedTime, size",
    ).execute()

    output_json({
        "status": "success",
        "operation": "update",
        "file": {
            "id": result.get("id"),
            "name": result.get("name"),
            "mime_type": result.get("mimeType"),
            "web_view_link": result.get("webViewLink"),
            "modified_time": result.get("modifiedTime"),
            "size": result.get("size"),
        },
    })


def _build_parser():
    """Build argparse CLI parser."""
    parser = argparse.ArgumentParser(
        description="Google Drive Manager - File Operations CLI"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # upload
    p = subparsers.add_parser("upload", help="Upload a file to Drive")
    p.add_argument("--file", required=True, help="Local file path")
    p.add_argument("--folder-id", help="Drive folder ID")
    p.add_argument("--name", help="File name override")
    p.add_argument("--mime-type", help="Override MIME type")

    # download
    p = subparsers.add_parser("download", help="Download a file from Drive")
    p.add_argument("--file-id", required=True, help="Drive file ID")
    p.add_argument("--output", required=True, help="Output file path")

    # list
    p = subparsers.add_parser("list", help="List files in Drive or folder")
    p.add_argument("--folder-id", help="Drive folder ID")
    p.add_argument("--max-results", type=int, default=100, help="Max results")
    p.add_argument("--page-token", help="Page token for pagination")

    # search
    p = subparsers.add_parser("search", help="Search files with query")
    p.add_argument("--query", required=True, help="Drive query syntax")
    p.add_argument("--max-results", type=int, default=100, help="Max results")
    p.add_argument("--page-token", help="Page token for pagination")

    # get-metadata
    p = subparsers.add_parser("get-metadata", help="Get file metadata")
    p.add_argument("--file-id", required=True, help="Drive file ID")

    # create-folder
    p = subparsers.add_parser("create-folder", help="Create a new folder")
    p.add_argument("--name", required=True, help="Folder name")
    p.add_argument("--folder-id", help="Parent folder ID")
    p.add_argument("--parent-id", help="Parent folder ID (alias)")

    # move
    p = subparsers.add_parser("move", help="Move file to folder")
    p.add_argument("--file-id", required=True, help="Drive file ID")
    p.add_argument("--folder-id", required=True, help="Destination folder ID")

    # share
    p = subparsers.add_parser("share", help="Share file with user or make public")
    p.add_argument("--file-id", required=True, help="Drive file ID")
    p.add_argument("--email", help="Email address for sharing")
    p.add_argument("--role", default="reader", help="Permission role: reader, writer, commenter")
    p.add_argument("--type", help="Permission type: user, anyone, domain")

    # delete
    p = subparsers.add_parser("delete", help="Delete file (trash or permanent)")
    p.add_argument("--file-id", required=True, help="Drive file ID")
    p.add_argument("--permanent", action="store_true", help="Permanently delete")

    # copy
    p = subparsers.add_parser("copy", help="Copy a file")
    p.add_argument("--file-id", required=True, help="Drive file ID")
    p.add_argument("--name", help="Name for the copy")
    p.add_argument("--folder-id", help="Destination folder ID")

    # update
    p = subparsers.add_parser("update", help="Update file content")
    p.add_argument("--file-id", required=True, help="Drive file ID")
    p.add_argument("--file", required=True, help="Local file path")
    p.add_argument("--name", help="New file name")

    return parser


COMMAND_MAP = {
    "upload": cmd_upload,
    "download": cmd_download,
    "list": cmd_list,
    "search": cmd_search,
    "get-metadata": cmd_get_metadata,
    "create-folder": cmd_create_folder,
    "move": cmd_move,
    "share": cmd_share,
    "delete": cmd_delete,
    "copy": cmd_copy,
    "update": cmd_update,
}


def main():
    """Main entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(EXIT_INVALID_ARGS)

    try:
        service = get_drive_service()
    except Exception as e:
        output_json({
            "status": "error",
            "error_code": "AUTH_ERROR",
            "message": f"Authentication failed: {e}",
        }, EXIT_AUTH_ERROR)

    handler = COMMAND_MAP.get(args.command)
    if not handler:
        output_json({
            "status": "error",
            "error_code": "UNKNOWN_COMMAND",
            "message": f"Unknown command: {args.command}",
            "hint": "Run with --help for usage",
        }, EXIT_INVALID_ARGS)

    try:
        handler(service, args)
    except Exception as e:
        output_json({
            "status": "error",
            "error_code": "API_ERROR",
            "operation": args.command,
            "message": f"Google Drive API error: {e}",
        }, EXIT_API_ERROR)


if __name__ == "__main__":
    main()
