"""Image pipeline: mermaid rendering and Drive upload for Google Docs."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from googleapiclient.http import MediaFileUpload

_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}


def render_mermaid(
    content: str,
    output_path: str,
    width: int = 800,
    theme: str = "default",
) -> str:
    """Render mermaid diagram content to a PNG file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mmd", delete=False
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        mmdc = shutil.which("mmdc")
        if not mmdc:
            raise RuntimeError(
                "mmdc not found. Install: npm install -g @mermaid-js/mermaid-cli"
            )

        result = subprocess.run(
            [mmdc, "-i", tmp_path, "-o", output_path, "-w", str(width), "-t", theme, "--quiet"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if not Path(output_path).exists():
            raise RuntimeError(
                f"mmdc render failed: {result.stderr or result.stdout or 'no output'}"
            )

        return output_path
    finally:
        os.unlink(tmp_path)


def upload_image(
    file_path: str,
    drive_service: object,
    folder_id: str | None = None,
) -> tuple[str, str]:
    """Upload an image to Google Drive (private) and return (file_id, data_uri).

    Images remain fully private. The data URI embeds the image bytes directly
    in the Docs API request — no public sharing required.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {file_path}")

    suffix = path.suffix.lower()
    if suffix not in _MIME_TYPES:
        raise ValueError(
            f"Unsupported image format: {suffix}. Supported: {list(_MIME_TYPES.keys())}"
        )

    file_metadata: dict = {"name": path.name}
    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaFileUpload(
        str(path), mimetype=_MIME_TYPES[suffix], resumable=True
    )

    created = (
        drive_service.files()
        .create(body=file_metadata, media_body=media, fields="id")
        .execute()
    )
    file_id = created["id"]

    # Build data URI from local file bytes (no public sharing needed)
    data_uri = _file_to_data_uri(str(path), _MIME_TYPES[suffix])

    return file_id, data_uri


def _file_to_data_uri(file_path: str, mime_type: str) -> str:
    """Convert a local file to a base64 data URI."""
    import base64
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return f"data:{mime_type};base64,{b64}"


def process_images(
    images: list,
    drive_service: object,
    base_dir: str,
    folder_id: str | None = None,
) -> list[dict]:
    """Process all image placeholders: render mermaid, upload files, resolve URLs.

    Returns list of {index, url, width, height} dicts.
    """
    resolved: list[dict] = []

    for img in images:
        if img.source_type == "url":
            resolved.append({
                "index": img.index,
                "url": img.source,
                "width": img.width,
                "height": img.height,
            })

        elif img.source_type == "mermaid":
            with tempfile.NamedTemporaryFile(
                suffix=".png", delete=False
            ) as tmp:
                tmp_path = tmp.name

            try:
                render_mermaid(img.source, tmp_path)
                _file_id, data_uri = upload_image(tmp_path, drive_service, folder_id)
                resolved.append({
                    "index": img.index,
                    "url": data_uri,
                    "width": img.width or 468,  # default to page width
                    "height": img.height,
                })
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        elif img.source_type == "file":
            file_path = _resolve_file_path(img.source, base_dir)
            if not os.path.exists(file_path):
                continue  # Skip missing files

            # Convert SVG to PNG if needed
            if file_path.lower().endswith(".svg"):
                png_path = file_path.rsplit(".", 1)[0] + ".png"
                _convert_svg_to_png(file_path, png_path)
                file_path = png_path

            _file_id, data_uri = upload_image(file_path, drive_service, folder_id)
            resolved.append({
                "index": img.index,
                "url": data_uri,
                "width": img.width,
                "height": img.height,
            })

        else:
            raise ValueError(f"Unknown image source_type: {img.source_type}")

    return resolved


def _resolve_file_path(source: str, base_dir: str) -> str:
    """Resolve an image source path relative to base_dir, with traversal guard."""
    if os.path.isabs(source):
        return source
    resolved = Path(os.path.normpath(os.path.join(base_dir, source))).resolve()
    base = Path(base_dir).resolve()
    if not str(resolved).startswith(str(base)):
        raise ValueError(f"Image path escapes base directory: {source}")
    return str(resolved)


def _convert_svg_to_png(svg_path: str, png_path: str) -> None:
    """Convert SVG to PNG using rsvg-convert or mmdc fallback."""
    rsvg = shutil.which("rsvg-convert")
    if rsvg:
        subprocess.run(
            [rsvg, "-o", png_path, svg_path],
            check=True,
            timeout=15,
        )
        return

    mmdc = shutil.which("mmdc")
    if mmdc:
        subprocess.run(
            [mmdc, "-i", svg_path, "-o", png_path, "--quiet"],
            check=True,
            timeout=15,
        )
        return

    raise RuntimeError(
        "Cannot convert SVG to PNG. Install rsvg-convert or mmdc."
    )
