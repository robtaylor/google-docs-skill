#!/bin/bash
# mermaid_to_docs.sh — Render mermaid diagram and insert into Google Doc
#
# Usage:
#   mermaid_to_docs.sh render <input.mmd> <output.png> [--width 800] [--theme default]
#   mermaid_to_docs.sh insert <document_id> <image_url> [--width 400] [--index N]
#   mermaid_to_docs.sh pipeline <input.mmd> <document_id> [--folder-id <id>] [--width 800]
#
# Commands:
#   render   — Convert .mmd file to PNG using mmdc
#   insert   — Insert an image URL into a Google Doc
#   pipeline — Full flow: render → upload to Drive → insert into Doc

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DOCS_MANAGER="$SCRIPT_DIR/docs_manager.rb"
DRIVE_MANAGER="$SCRIPT_DIR/drive_manager.rb"

render() {
  local input="$1"
  local output="$2"
  shift 2

  local width=800
  local theme="default"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --width) width="$2"; shift 2 ;;
      --theme) theme="$2"; shift 2 ;;
      *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
  done

  if [[ ! -f "$input" ]]; then
    echo '{"success":false,"message":"Input file not found: '"$input"'"}'
    exit 1
  fi

  mmdc -i "$input" -o "$output" -w "$width" -t "$theme" --quiet 2>/dev/null

  if [[ -f "$output" ]]; then
    echo '{"success":true,"output":"'"$output"'"}'
  else
    echo '{"success":false,"message":"Render failed"}'
    exit 1
  fi
}

insert() {
  local doc_id="$1"
  local image_url="$2"
  shift 2

  local width=""
  local index=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --width) width="$2"; shift 2 ;;
      --index) index="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  local json="{\"document_id\":\"$doc_id\",\"image_url\":\"$image_url\""
  [[ -n "$width" ]] && json="$json,\"width\":$width"
  [[ -n "$index" ]] && json="$json,\"index\":$index"
  json="$json}"

  echo "$json" | ruby "$DOCS_MANAGER" insert-image
}

pipeline() {
  local input="$1"
  local doc_id="$2"
  shift 2

  local folder_id=""
  local width=800
  local theme="default"
  local img_width=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --folder-id) folder_id="$2"; shift 2 ;;
      --width) width="$2"; shift 2 ;;
      --theme) theme="$2"; shift 2 ;;
      --img-width) img_width="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  # 1. Render mermaid to PNG
  local tmp_png="/tmp/mermaid_$(date +%s).png"
  mmdc -i "$input" -o "$tmp_png" -w "$width" -t "$theme" --quiet 2>/dev/null

  if [[ ! -f "$tmp_png" ]]; then
    echo '{"success":false,"step":"render","message":"mmdc render failed"}'
    exit 1
  fi

  # 2. Upload to Google Drive
  local upload_args="--file $tmp_png"
  [[ -n "$folder_id" ]] && upload_args="$upload_args --folder-id $folder_id"

  local upload_result
  upload_result=$(ruby "$DRIVE_MANAGER" upload $upload_args 2>&1)

  local file_id
  file_id=$(echo "$upload_result" | ruby -rjson -e 'puts JSON.parse(STDIN.read)["file_id"]' 2>/dev/null)

  if [[ -z "$file_id" ]]; then
    echo '{"success":false,"step":"upload","message":"Drive upload failed","detail":'"$(echo "$upload_result" | head -1 | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))')"'}'
    rm -f "$tmp_png"
    exit 1
  fi

  # 3. Make file publicly readable (needed for Google Docs insert)
  ruby "$DRIVE_MANAGER" share --file-id "$file_id" --role reader --type anyone > /dev/null 2>&1 || true

  # 4. Build image URL
  local image_url="https://drive.google.com/uc?id=$file_id"

  # 5. Insert into Google Doc
  local insert_json="{\"document_id\":\"$doc_id\",\"image_url\":\"$image_url\""
  [[ -n "$img_width" ]] && insert_json="$insert_json,\"width\":$img_width"
  insert_json="$insert_json}"

  local insert_result
  insert_result=$(echo "$insert_json" | ruby "$DOCS_MANAGER" insert-image 2>&1)

  rm -f "$tmp_png"

  echo '{"success":true,"file_id":"'"$file_id"'","image_url":"'"$image_url"'","insert_result":'"$(echo "$insert_result" | head -1)"'}'
}

case "${1:-help}" in
  render)   shift; render "$@" ;;
  insert)   shift; insert "$@" ;;
  pipeline) shift; pipeline "$@" ;;
  *)
    echo "Usage:"
    echo "  $0 render <input.mmd> <output.png> [--width 800] [--theme default]"
    echo "  $0 insert <document_id> <image_url> [--width 400]"
    echo "  $0 pipeline <input.mmd> <document_id> [--folder-id <id>] [--width 800]"
    ;;
esac
