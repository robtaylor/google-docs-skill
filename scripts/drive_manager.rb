#!/usr/bin/env ruby
# frozen_string_literal: true

require 'google/apis/drive_v3'
require 'googleauth'
require 'googleauth/stores/file_token_store'
require 'fileutils'
require 'json'

# Google Drive Manager - CLI for Drive File Operations
# Version: 1.0.0
# Shares OAuth token with google-docs skill
class DriveManager
  # OAuth scopes - shared with other Google skills
  DRIVE_SCOPE = Google::Apis::DriveV3::AUTH_DRIVE
  DOCS_SCOPE = 'https://www.googleapis.com/auth/documents'
  SHEETS_SCOPE = 'https://www.googleapis.com/auth/spreadsheets'
  CALENDAR_SCOPE = 'https://www.googleapis.com/auth/calendar'
  CONTACTS_SCOPE = 'https://www.googleapis.com/auth/contacts'
  GMAIL_SCOPE = 'https://www.googleapis.com/auth/gmail.modify'

  CREDENTIALS_PATH = File.join(Dir.home, '.claude', '.google', 'client_secret.json')
  TOKEN_PATH = File.join(Dir.home, '.claude', '.google', 'token.json')

  # Exit codes
  EXIT_SUCCESS = 0
  EXIT_OPERATION_FAILED = 1
  EXIT_AUTH_ERROR = 2
  EXIT_API_ERROR = 3
  EXIT_INVALID_ARGS = 4

  def initialize
    @drive_service = Google::Apis::DriveV3::DriveService.new
    @drive_service.client_options.application_name = 'Claude Drive Skill'
    @drive_service.authorization = authorize
  end

  # Authorize using shared OAuth token
  def authorize
    client_id = Google::Auth::ClientId.from_file(CREDENTIALS_PATH)
    token_store = Google::Auth::Stores::FileTokenStore.new(file: TOKEN_PATH)

    authorizer = Google::Auth::UserAuthorizer.new(
      client_id,
      [DRIVE_SCOPE, DOCS_SCOPE, SHEETS_SCOPE, CALENDAR_SCOPE, CONTACTS_SCOPE, GMAIL_SCOPE],
      token_store
    )

    user_id = 'default'
    credentials = authorizer.get_credentials(user_id)

    if credentials.nil?
      url = authorizer.get_authorization_url(base_url: 'http://localhost')
      output_json({
        status: 'error',
        error_code: 'AUTH_REQUIRED',
        message: 'Authorization required. Please use docs_manager.rb auth flow.',
        auth_url: url
      })
      exit EXIT_AUTH_ERROR
    end

    credentials.refresh! if credentials.expired?
    credentials
  end

  # Upload a file to Google Drive
  def upload(file_path:, folder_id: nil, name: nil, mime_type: nil)
    unless File.exist?(file_path)
      output_json({
        status: 'error',
        error_code: 'FILE_NOT_FOUND',
        operation: 'upload',
        message: "File not found: #{file_path}"
      })
      exit EXIT_OPERATION_FAILED
    end

    file_name = name || File.basename(file_path)

    # Auto-detect mime type for common file types
    detected_mime = mime_type || detect_mime_type(file_path)

    file_metadata = Google::Apis::DriveV3::File.new(
      name: file_name
    )
    file_metadata.parents = [folder_id] if folder_id

    result = @drive_service.create_file(
      file_metadata,
      upload_source: file_path,
      content_type: detected_mime,
      fields: 'id, name, mimeType, webViewLink, webContentLink, parents, createdTime, modifiedTime, size'
    )

    output_json({
      status: 'success',
      operation: 'upload',
      file: {
        id: result.id,
        name: result.name,
        mime_type: result.mime_type,
        web_view_link: result.web_view_link,
        web_content_link: result.web_content_link,
        parents: result.parents,
        created_time: result.created_time&.to_s,
        modified_time: result.modified_time&.to_s,
        size: result.size
      }
    })
  rescue Google::Apis::Error => e
    output_json({
      status: 'error',
      error_code: 'API_ERROR',
      operation: 'upload',
      message: "Google Drive API error: #{e.message}"
    })
    exit EXIT_API_ERROR
  end

  # Download a file from Google Drive
  def download(file_id:, output_path:)
    # Get file metadata first
    file = @drive_service.get_file(file_id, fields: 'id, name, mimeType')

    # Handle Google Docs native formats (need export)
    if file.mime_type.start_with?('application/vnd.google-apps.')
      export_google_doc(file_id: file_id, output_path: output_path, source_mime: file.mime_type)
      return
    end

    # Regular file download
    @drive_service.get_file(file_id, download_dest: output_path)

    output_json({
      status: 'success',
      operation: 'download',
      file_id: file_id,
      output_path: output_path,
      name: file.name,
      mime_type: file.mime_type
    })
  rescue Google::Apis::Error => e
    output_json({
      status: 'error',
      error_code: 'API_ERROR',
      operation: 'download',
      message: "Google Drive API error: #{e.message}"
    })
    exit EXIT_API_ERROR
  end

  # Export Google Docs native format to a file
  def export_google_doc(file_id:, output_path:, source_mime:, export_mime: nil)
    # Default export formats
    export_mime ||= case source_mime
                    when 'application/vnd.google-apps.document'
                      'application/pdf'
                    when 'application/vnd.google-apps.spreadsheet'
                      'text/csv'
                    when 'application/vnd.google-apps.presentation'
                      'application/pdf'
                    when 'application/vnd.google-apps.drawing'
                      'image/png'
                    else
                      'application/pdf'
                    end

    @drive_service.export_file(file_id, export_mime, download_dest: output_path)

    output_json({
      status: 'success',
      operation: 'export',
      file_id: file_id,
      output_path: output_path,
      export_mime_type: export_mime
    })
  rescue Google::Apis::Error => e
    output_json({
      status: 'error',
      error_code: 'API_ERROR',
      operation: 'export',
      message: "Google Drive API error: #{e.message}"
    })
    exit EXIT_API_ERROR
  end

  # List files in Drive or folder
  def list(folder_id: nil, max_results: 100, page_token: nil)
    query_parts = ["trashed = false"]
    query_parts << "'#{folder_id}' in parents" if folder_id

    results = @drive_service.list_files(
      q: query_parts.join(' and '),
      page_size: max_results,
      page_token: page_token,
      fields: 'nextPageToken, files(id, name, mimeType, webViewLink, parents, createdTime, modifiedTime, size)'
    )

    files = results.files.map do |f|
      {
        id: f.id,
        name: f.name,
        mime_type: f.mime_type,
        web_view_link: f.web_view_link,
        parents: f.parents,
        created_time: f.created_time&.to_s,
        modified_time: f.modified_time&.to_s,
        size: f.size
      }
    end

    output_json({
      status: 'success',
      operation: 'list',
      folder_id: folder_id,
      files: files,
      next_page_token: results.next_page_token,
      count: files.length
    })
  rescue Google::Apis::Error => e
    output_json({
      status: 'error',
      error_code: 'API_ERROR',
      operation: 'list',
      message: "Google Drive API error: #{e.message}"
    })
    exit EXIT_API_ERROR
  end

  # Search files with query
  def search(query:, max_results: 100, page_token: nil)
    # Add trashed filter if not already in query
    full_query = query.include?('trashed') ? query : "#{query} and trashed = false"

    results = @drive_service.list_files(
      q: full_query,
      page_size: max_results,
      page_token: page_token,
      fields: 'nextPageToken, files(id, name, mimeType, webViewLink, parents, createdTime, modifiedTime, size)'
    )

    files = results.files.map do |f|
      {
        id: f.id,
        name: f.name,
        mime_type: f.mime_type,
        web_view_link: f.web_view_link,
        parents: f.parents,
        created_time: f.created_time&.to_s,
        modified_time: f.modified_time&.to_s,
        size: f.size
      }
    end

    output_json({
      status: 'success',
      operation: 'search',
      query: query,
      files: files,
      next_page_token: results.next_page_token,
      count: files.length
    })
  rescue Google::Apis::Error => e
    output_json({
      status: 'error',
      error_code: 'API_ERROR',
      operation: 'search',
      message: "Google Drive API error: #{e.message}"
    })
    exit EXIT_API_ERROR
  end

  # Get file metadata
  def get_metadata(file_id:)
    file = @drive_service.get_file(
      file_id,
      fields: 'id, name, mimeType, webViewLink, webContentLink, parents, createdTime, modifiedTime, size, description, starred, trashed, owners, permissions'
    )

    output_json({
      status: 'success',
      operation: 'get_metadata',
      file: {
        id: file.id,
        name: file.name,
        mime_type: file.mime_type,
        web_view_link: file.web_view_link,
        web_content_link: file.web_content_link,
        parents: file.parents,
        created_time: file.created_time&.to_s,
        modified_time: file.modified_time&.to_s,
        size: file.size,
        description: file.description,
        starred: file.starred,
        trashed: file.trashed,
        owners: file.owners&.map { |o| { email: o.email_address, name: o.display_name } },
        permissions: file.permissions&.map { |p| { id: p.id, type: p.type, role: p.role, email: p.email_address } }
      }
    })
  rescue Google::Apis::Error => e
    output_json({
      status: 'error',
      error_code: 'API_ERROR',
      operation: 'get_metadata',
      message: "Google Drive API error: #{e.message}"
    })
    exit EXIT_API_ERROR
  end

  # Create a folder
  def create_folder(name:, parent_id: nil)
    file_metadata = Google::Apis::DriveV3::File.new(
      name: name,
      mime_type: 'application/vnd.google-apps.folder'
    )
    file_metadata.parents = [parent_id] if parent_id

    result = @drive_service.create_file(
      file_metadata,
      fields: 'id, name, mimeType, webViewLink, parents, createdTime'
    )

    output_json({
      status: 'success',
      operation: 'create_folder',
      folder: {
        id: result.id,
        name: result.name,
        web_view_link: result.web_view_link,
        parents: result.parents,
        created_time: result.created_time&.to_s
      }
    })
  rescue Google::Apis::Error => e
    output_json({
      status: 'error',
      error_code: 'API_ERROR',
      operation: 'create_folder',
      message: "Google Drive API error: #{e.message}"
    })
    exit EXIT_API_ERROR
  end

  # Move file to a different folder
  def move(file_id:, folder_id:)
    # Get current parents
    file = @drive_service.get_file(file_id, fields: 'parents')
    previous_parents = file.parents&.join(',')

    result = @drive_service.update_file(
      file_id,
      Google::Apis::DriveV3::File.new,
      add_parents: folder_id,
      remove_parents: previous_parents,
      fields: 'id, name, parents, webViewLink'
    )

    output_json({
      status: 'success',
      operation: 'move',
      file: {
        id: result.id,
        name: result.name,
        parents: result.parents,
        web_view_link: result.web_view_link
      }
    })
  rescue Google::Apis::Error => e
    output_json({
      status: 'error',
      error_code: 'API_ERROR',
      operation: 'move',
      message: "Google Drive API error: #{e.message}"
    })
    exit EXIT_API_ERROR
  end

  # Share file with user or make public
  def share(file_id:, email: nil, role: 'reader', type: nil)
    # Determine permission type
    perm_type = type || (email ? 'user' : 'anyone')

    permission = Google::Apis::DriveV3::Permission.new(
      type: perm_type,
      role: role
    )
    permission.email_address = email if email && perm_type == 'user'

    result = @drive_service.create_permission(
      file_id,
      permission,
      fields: 'id, type, role, emailAddress'
    )

    # Get updated file info with sharing link
    file = @drive_service.get_file(file_id, fields: 'webViewLink, webContentLink')

    output_json({
      status: 'success',
      operation: 'share',
      permission: {
        id: result.id,
        type: result.type,
        role: result.role,
        email: result.email_address
      },
      web_view_link: file.web_view_link,
      web_content_link: file.web_content_link
    })
  rescue Google::Apis::Error => e
    output_json({
      status: 'error',
      error_code: 'API_ERROR',
      operation: 'share',
      message: "Google Drive API error: #{e.message}"
    })
    exit EXIT_API_ERROR
  end

  # Delete file (move to trash)
  def delete(file_id:, permanent: false)
    if permanent
      @drive_service.delete_file(file_id)
    else
      @drive_service.update_file(
        file_id,
        Google::Apis::DriveV3::File.new(trashed: true)
      )
    end

    output_json({
      status: 'success',
      operation: 'delete',
      file_id: file_id,
      permanent: permanent
    })
  rescue Google::Apis::Error => e
    output_json({
      status: 'error',
      error_code: 'API_ERROR',
      operation: 'delete',
      message: "Google Drive API error: #{e.message}"
    })
    exit EXIT_API_ERROR
  end

  # Copy file
  def copy(file_id:, name: nil, folder_id: nil)
    file_metadata = Google::Apis::DriveV3::File.new
    file_metadata.name = name if name
    file_metadata.parents = [folder_id] if folder_id

    result = @drive_service.copy_file(
      file_id,
      file_metadata,
      fields: 'id, name, mimeType, webViewLink, parents, createdTime'
    )

    output_json({
      status: 'success',
      operation: 'copy',
      file: {
        id: result.id,
        name: result.name,
        mime_type: result.mime_type,
        web_view_link: result.web_view_link,
        parents: result.parents,
        created_time: result.created_time&.to_s
      }
    })
  rescue Google::Apis::Error => e
    output_json({
      status: 'error',
      error_code: 'API_ERROR',
      operation: 'copy',
      message: "Google Drive API error: #{e.message}"
    })
    exit EXIT_API_ERROR
  end

  # Update file content
  def update(file_id:, file_path:, name: nil)
    unless File.exist?(file_path)
      output_json({
        status: 'error',
        error_code: 'FILE_NOT_FOUND',
        operation: 'update',
        message: "File not found: #{file_path}"
      })
      exit EXIT_OPERATION_FAILED
    end

    file_metadata = Google::Apis::DriveV3::File.new
    file_metadata.name = name if name

    mime_type = detect_mime_type(file_path)

    result = @drive_service.update_file(
      file_id,
      file_metadata,
      upload_source: file_path,
      content_type: mime_type,
      fields: 'id, name, mimeType, webViewLink, modifiedTime, size'
    )

    output_json({
      status: 'success',
      operation: 'update',
      file: {
        id: result.id,
        name: result.name,
        mime_type: result.mime_type,
        web_view_link: result.web_view_link,
        modified_time: result.modified_time&.to_s,
        size: result.size
      }
    })
  rescue Google::Apis::Error => e
    output_json({
      status: 'error',
      error_code: 'API_ERROR',
      operation: 'update',
      message: "Google Drive API error: #{e.message}"
    })
    exit EXIT_API_ERROR
  end

  private

  # Detect MIME type from file extension
  def detect_mime_type(file_path)
    ext = File.extname(file_path).downcase
    case ext
    when '.excalidraw'
      'application/json'
    when '.json'
      'application/json'
    when '.txt'
      'text/plain'
    when '.md'
      'text/markdown'
    when '.html', '.htm'
      'text/html'
    when '.css'
      'text/css'
    when '.js'
      'application/javascript'
    when '.pdf'
      'application/pdf'
    when '.png'
      'image/png'
    when '.jpg', '.jpeg'
      'image/jpeg'
    when '.gif'
      'image/gif'
    when '.svg'
      'image/svg+xml'
    when '.zip'
      'application/zip'
    when '.csv'
      'text/csv'
    when '.xml'
      'application/xml'
    when '.yaml', '.yml'
      'application/x-yaml'
    else
      'application/octet-stream'
    end
  end

  # Output JSON to stdout
  def output_json(data)
    puts JSON.pretty_generate(data)
  end
end

# CLI Interface
def usage
  puts <<~USAGE
    Google Drive Manager - File Operations CLI
    Version: 1.0.0

    Usage:
      #{File.basename($PROGRAM_NAME)} <command> [options]

    Commands:
      upload          Upload a file to Drive
      download        Download a file from Drive
      list            List files in Drive or folder
      search          Search files with query
      get-metadata    Get file metadata
      create-folder   Create a new folder
      move            Move file to folder
      share           Share file with user or make public
      delete          Delete file (trash or permanent)
      copy            Copy a file
      update          Update file content

    Options:
      --file <path>       Local file path (for upload/update)
      --file-id <id>      Drive file ID
      --folder-id <id>    Drive folder ID
      --output <path>     Output file path (for download)
      --name <name>       File/folder name
      --query <query>     Search query (Drive query syntax)
      --email <email>     Email address (for sharing)
      --role <role>       Permission role: reader, writer, commenter
      --type <type>       Permission type: user, anyone, domain
      --max-results <n>   Max results to return (default: 100)
      --permanent         Permanently delete (not trash)
      --mime-type <type>  Override MIME type for upload

    Examples:
      # Upload a file
      #{File.basename($PROGRAM_NAME)} upload --file ./diagram.excalidraw

      # Upload to specific folder
      #{File.basename($PROGRAM_NAME)} upload --file ./diagram.excalidraw --folder-id 1abc123

      # Download a file
      #{File.basename($PROGRAM_NAME)} download --file-id 1abc123 --output ./downloaded.excalidraw

      # List files in root
      #{File.basename($PROGRAM_NAME)} list

      # List files in folder
      #{File.basename($PROGRAM_NAME)} list --folder-id 1abc123

      # Search for excalidraw files
      #{File.basename($PROGRAM_NAME)} search --query "name contains '.excalidraw'"

      # Get file metadata
      #{File.basename($PROGRAM_NAME)} get-metadata --file-id 1abc123

      # Create a folder
      #{File.basename($PROGRAM_NAME)} create-folder --name "Diagrams"

      # Move file to folder
      #{File.basename($PROGRAM_NAME)} move --file-id 1abc123 --folder-id 1xyz789

      # Share with user
      #{File.basename($PROGRAM_NAME)} share --file-id 1abc123 --email user@example.com --role writer

      # Make file public
      #{File.basename($PROGRAM_NAME)} share --file-id 1abc123 --type anyone --role reader

      # Delete file (to trash)
      #{File.basename($PROGRAM_NAME)} delete --file-id 1abc123

      # Copy file
      #{File.basename($PROGRAM_NAME)} copy --file-id 1abc123 --name "Copy of diagram"

      # Update file content
      #{File.basename($PROGRAM_NAME)} update --file-id 1abc123 --file ./updated.excalidraw

    Exit Codes:
      0 - Success
      1 - Operation failed
      2 - Authentication error
      3 - API error
      4 - Invalid arguments
  USAGE
end

# Parse command line arguments
def parse_args(args)
  options = {}
  i = 0
  while i < args.length
    case args[i]
    when '--file'
      options[:file] = args[i + 1]
      i += 2
    when '--file-id'
      options[:file_id] = args[i + 1]
      i += 2
    when '--folder-id'
      options[:folder_id] = args[i + 1]
      i += 2
    when '--output'
      options[:output] = args[i + 1]
      i += 2
    when '--name'
      options[:name] = args[i + 1]
      i += 2
    when '--query'
      options[:query] = args[i + 1]
      i += 2
    when '--email'
      options[:email] = args[i + 1]
      i += 2
    when '--role'
      options[:role] = args[i + 1]
      i += 2
    when '--type'
      options[:type] = args[i + 1]
      i += 2
    when '--max-results'
      options[:max_results] = args[i + 1].to_i
      i += 2
    when '--permanent'
      options[:permanent] = true
      i += 1
    when '--mime-type'
      options[:mime_type] = args[i + 1]
      i += 2
    when '--parent-id'
      options[:parent_id] = args[i + 1]
      i += 2
    else
      i += 1
    end
  end
  options
end

# Main execution
if __FILE__ == $PROGRAM_NAME
  if ARGV.empty?
    usage
    exit DriveManager::EXIT_INVALID_ARGS
  end

  command = ARGV[0]

  if command == '--help' || command == '-h'
    usage
    exit DriveManager::EXIT_SUCCESS
  end

  manager = DriveManager.new
  options = parse_args(ARGV[1..])

  case command

  when 'upload'
    unless options[:file]
      puts JSON.pretty_generate({
        status: 'error',
        error_code: 'MISSING_FILE',
        message: 'File path required: --file <path>'
      })
      exit DriveManager::EXIT_INVALID_ARGS
    end

    manager.upload(
      file_path: options[:file],
      folder_id: options[:folder_id],
      name: options[:name],
      mime_type: options[:mime_type]
    )

  when 'download'
    unless options[:file_id] && options[:output]
      puts JSON.pretty_generate({
        status: 'error',
        error_code: 'MISSING_ARGS',
        message: 'File ID and output path required: --file-id <id> --output <path>'
      })
      exit DriveManager::EXIT_INVALID_ARGS
    end

    manager.download(
      file_id: options[:file_id],
      output_path: options[:output]
    )

  when 'list'
    manager.list(
      folder_id: options[:folder_id],
      max_results: options[:max_results] || 100
    )

  when 'search'
    unless options[:query]
      puts JSON.pretty_generate({
        status: 'error',
        error_code: 'MISSING_QUERY',
        message: 'Search query required: --query <query>'
      })
      exit DriveManager::EXIT_INVALID_ARGS
    end

    manager.search(
      query: options[:query],
      max_results: options[:max_results] || 100
    )

  when 'get-metadata'
    unless options[:file_id]
      puts JSON.pretty_generate({
        status: 'error',
        error_code: 'MISSING_FILE_ID',
        message: 'File ID required: --file-id <id>'
      })
      exit DriveManager::EXIT_INVALID_ARGS
    end

    manager.get_metadata(file_id: options[:file_id])

  when 'create-folder'
    unless options[:name]
      puts JSON.pretty_generate({
        status: 'error',
        error_code: 'MISSING_NAME',
        message: 'Folder name required: --name <name>'
      })
      exit DriveManager::EXIT_INVALID_ARGS
    end

    manager.create_folder(
      name: options[:name],
      parent_id: options[:parent_id] || options[:folder_id]
    )

  when 'move'
    unless options[:file_id] && options[:folder_id]
      puts JSON.pretty_generate({
        status: 'error',
        error_code: 'MISSING_ARGS',
        message: 'File ID and folder ID required: --file-id <id> --folder-id <id>'
      })
      exit DriveManager::EXIT_INVALID_ARGS
    end

    manager.move(
      file_id: options[:file_id],
      folder_id: options[:folder_id]
    )

  when 'share'
    unless options[:file_id]
      puts JSON.pretty_generate({
        status: 'error',
        error_code: 'MISSING_FILE_ID',
        message: 'File ID required: --file-id <id>'
      })
      exit DriveManager::EXIT_INVALID_ARGS
    end

    manager.share(
      file_id: options[:file_id],
      email: options[:email],
      role: options[:role] || 'reader',
      type: options[:type]
    )

  when 'delete'
    unless options[:file_id]
      puts JSON.pretty_generate({
        status: 'error',
        error_code: 'MISSING_FILE_ID',
        message: 'File ID required: --file-id <id>'
      })
      exit DriveManager::EXIT_INVALID_ARGS
    end

    manager.delete(
      file_id: options[:file_id],
      permanent: options[:permanent] || false
    )

  when 'copy'
    unless options[:file_id]
      puts JSON.pretty_generate({
        status: 'error',
        error_code: 'MISSING_FILE_ID',
        message: 'File ID required: --file-id <id>'
      })
      exit DriveManager::EXIT_INVALID_ARGS
    end

    manager.copy(
      file_id: options[:file_id],
      name: options[:name],
      folder_id: options[:folder_id]
    )

  when 'update'
    unless options[:file_id] && options[:file]
      puts JSON.pretty_generate({
        status: 'error',
        error_code: 'MISSING_ARGS',
        message: 'File ID and file path required: --file-id <id> --file <path>'
      })
      exit DriveManager::EXIT_INVALID_ARGS
    end

    manager.update(
      file_id: options[:file_id],
      file_path: options[:file],
      name: options[:name]
    )

  else
    puts JSON.pretty_generate({
      status: 'error',
      error_code: 'UNKNOWN_COMMAND',
      message: "Unknown command: #{command}",
      hint: "Run '#{File.basename($PROGRAM_NAME)} --help' for usage"
    })
    exit DriveManager::EXIT_INVALID_ARGS
  end

  exit DriveManager::EXIT_SUCCESS
end
