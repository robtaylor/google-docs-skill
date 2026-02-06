#!/usr/bin/env ruby
# frozen_string_literal: true

# Re-exec under a newer Ruby if the current one is too old for Bundler 2+
if RUBY_VERSION < '3.1'
  candidates = Dir.glob(File.join(Dir.home, '.rbenv/versions/*/bin/ruby')) +
               Dir.glob(File.join(Dir.home, '.asdf/installs/ruby/*/bin/ruby')) +
               Dir.glob(File.join(Dir.home, '.local/share/mise/installs/ruby/*/bin/ruby'))
  new_ruby = candidates.sort_by { |p| p.scan(/\d+/).map(&:to_i) }.last
  if new_ruby
    exec(new_ruby, __FILE__, *ARGV)
  else
    warn "Ruby >= 3.1 required (current: #{RUBY_VERSION}). Install via rbenv/asdf/mise."
    exit 1
  end
end

ENV['BUNDLE_GEMFILE'] ||= File.expand_path('../Gemfile', __dir__)
begin
  require 'bundler/setup'
rescue LoadError, Bundler::LockfileError => e
  warn "Bundler setup failed: #{e.message}"
  warn "Run: cd #{File.expand_path('..', __dir__)} && bundle install"
  exit 1
end

require 'google/apis/docs_v1'
require 'google/apis/drive_v3'
require 'google/apis/sheets_v4'
require 'google/apis/calendar_v3'
require 'google/apis/people_v1'
require 'googleauth'
require 'googleauth/stores/file_token_store'
require 'fileutils'
require 'json'

# Google Sheets Manager - Google CLI Integration for Spreadsheet Operations
# Version: 1.0.0
# Scopes: Docs, Drive, Calendar, Contacts, Gmail, Sheets (shared)
class SheetsManager
  # OAuth scopes - ALL Google skills share these
  DOCS_SCOPE = Google::Apis::DocsV1::AUTH_DOCUMENTS
  DRIVE_SCOPE = Google::Apis::DriveV3::AUTH_DRIVE
  SHEETS_SCOPE = Google::Apis::SheetsV4::AUTH_SPREADSHEETS
  CALENDAR_SCOPE = Google::Apis::CalendarV3::AUTH_CALENDAR
  CONTACTS_SCOPE = Google::Apis::PeopleV1::AUTH_CONTACTS
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
    @sheets_service = Google::Apis::SheetsV4::SheetsService.new
    @sheets_service.client_options.application_name = 'Claude Sheets Skill'
    @sheets_service.authorization = authorize
  end

  def authorize
    client_id = Google::Auth::ClientId.from_file(CREDENTIALS_PATH)
    token_store = Google::Auth::Stores::FileTokenStore.new(file: TOKEN_PATH)

    authorizer = Google::Auth::UserAuthorizer.new(
      client_id,
      [DRIVE_SCOPE, SHEETS_SCOPE, DOCS_SCOPE, CALENDAR_SCOPE, CONTACTS_SCOPE, GMAIL_SCOPE],
      token_store
    )

    user_id = 'default'
    credentials = authorizer.get_credentials(user_id)

    if credentials.nil?
      url = authorizer.get_authorization_url(base_url: 'urn:ietf:wg:oauth:2.0:oob')
      output_json({
        status: 'error',
        error_code: 'AUTH_REQUIRED',
        message: 'Authorization required. Please visit the URL and enter the code.',
        auth_url: url,
        instructions: [
          '1. Visit the authorization URL',
          '2. Grant access to Google Docs, Drive, Sheets, Calendar, Contacts, and Gmail',
          '3. Copy the authorization code',
          "4. Run: ruby #{__FILE__} auth <code>"
        ]
      })
      exit EXIT_AUTH_ERROR
    end

    credentials.refresh! if credentials.expired?
    credentials
  end

  def complete_auth(code)
    client_id = Google::Auth::ClientId.from_file(CREDENTIALS_PATH)
    token_store = Google::Auth::Stores::FileTokenStore.new(file: TOKEN_PATH)

    authorizer = Google::Auth::UserAuthorizer.new(
      client_id,
      [DRIVE_SCOPE, SHEETS_SCOPE, DOCS_SCOPE, CALENDAR_SCOPE, CONTACTS_SCOPE, GMAIL_SCOPE],
      token_store
    )

    user_id = 'default'
    authorizer.get_and_store_credentials_from_code(
      user_id: user_id,
      code: code,
      base_url: 'urn:ietf:wg:oauth:2.0:oob'
    )

    output_json({
      status: 'success',
      message: 'Authorization complete. Token stored successfully.',
      token_path: TOKEN_PATH,
      scopes: [DOCS_SCOPE, DRIVE_SCOPE, SHEETS_SCOPE, CALENDAR_SCOPE, CONTACTS_SCOPE, GMAIL_SCOPE]
    })
  rescue StandardError => e
    output_json({
      status: 'error',
      error_code: 'AUTH_FAILED',
      message: "Authorization failed: #{e.message}"
    })
    exit EXIT_AUTH_ERROR
  end

  # Create a new spreadsheet
  def create_spreadsheet(title:, sheets: nil, data: nil)
    spreadsheet = Google::Apis::SheetsV4::Spreadsheet.new(
      properties: Google::Apis::SheetsV4::SpreadsheetProperties.new(title: title)
    )

    if sheets && sheets.length > 0
      spreadsheet.sheets = sheets.each_with_index.map do |name, i|
        Google::Apis::SheetsV4::Sheet.new(
          properties: Google::Apis::SheetsV4::SheetProperties.new(
            title: name,
            index: i
          )
        )
      end
    end

    result = @sheets_service.create_spreadsheet(spreadsheet)

    if data && data.length > 0
      first_sheet = result.sheets.first.properties.title
      range = "#{first_sheet}!A1"
      value_range = Google::Apis::SheetsV4::ValueRange.new(
        range: range,
        values: data
      )
      @sheets_service.update_spreadsheet_value(
        result.spreadsheet_id, range, value_range,
        value_input_option: 'USER_ENTERED'
      )
    end

    output_json({
      status: 'success',
      operation: 'create',
      spreadsheet_id: result.spreadsheet_id,
      title: result.properties.title,
      spreadsheet_url: result.spreadsheet_url,
      sheets: result.sheets.map { |s| { title: s.properties.title, sheet_id: s.properties.sheet_id } }
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'create', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'CREATE_FAILED', operation: 'create', message: "Failed to create spreadsheet: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Read values from a range
  def read_range(spreadsheet_id:, range:)
    result = @sheets_service.get_spreadsheet_values(spreadsheet_id, range)

    output_json({
      status: 'success',
      operation: 'read',
      spreadsheet_id: spreadsheet_id,
      range: result.range,
      values: result.values || [],
      rows: (result.values || []).length,
      columns: (result.values&.first || []).length
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'read', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'READ_FAILED', operation: 'read', message: "Failed to read range: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Write values to a range
  def write_range(spreadsheet_id:, range:, values:)
    value_range = Google::Apis::SheetsV4::ValueRange.new(
      range: range,
      values: values
    )

    result = @sheets_service.update_spreadsheet_value(
      spreadsheet_id, range, value_range,
      value_input_option: 'USER_ENTERED'
    )

    output_json({
      status: 'success',
      operation: 'write',
      spreadsheet_id: spreadsheet_id,
      updated_range: result.updated_range,
      updated_rows: result.updated_rows,
      updated_columns: result.updated_columns,
      updated_cells: result.updated_cells
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'write', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'WRITE_FAILED', operation: 'write', message: "Failed to write range: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Append rows after existing data
  def append_rows(spreadsheet_id:, range:, values:)
    value_range = Google::Apis::SheetsV4::ValueRange.new(
      range: range,
      values: values
    )

    result = @sheets_service.append_spreadsheet_value(
      spreadsheet_id, range, value_range,
      value_input_option: 'USER_ENTERED',
      insert_data_option: 'INSERT_ROWS'
    )

    output_json({
      status: 'success',
      operation: 'append',
      spreadsheet_id: spreadsheet_id,
      updated_range: result.updates&.updated_range,
      updated_rows: result.updates&.updated_rows,
      updated_columns: result.updates&.updated_columns,
      updated_cells: result.updates&.updated_cells
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'append', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'APPEND_FAILED', operation: 'append', message: "Failed to append rows: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Clear a cell range
  def clear_range(spreadsheet_id:, range:)
    @sheets_service.clear_values(spreadsheet_id, range)

    output_json({
      status: 'success',
      operation: 'clear',
      spreadsheet_id: spreadsheet_id,
      cleared_range: range
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'clear', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'CLEAR_FAILED', operation: 'clear', message: "Failed to clear range: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Read multiple ranges at once
  def batch_read(spreadsheet_id:, ranges:)
    result = @sheets_service.batch_get_spreadsheet_values(spreadsheet_id, ranges: ranges)

    range_data = (result.value_ranges || []).map do |vr|
      {
        range: vr.range,
        values: vr.values || [],
        rows: (vr.values || []).length,
        columns: (vr.values&.first || []).length
      }
    end

    output_json({
      status: 'success',
      operation: 'batch-read',
      spreadsheet_id: spreadsheet_id,
      ranges: range_data
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'batch-read', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'BATCH_READ_FAILED', operation: 'batch-read', message: "Failed to batch read: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Write to multiple ranges at once
  def batch_write(spreadsheet_id:, data:)
    value_ranges = data.map do |d|
      Google::Apis::SheetsV4::ValueRange.new(
        range: d['range'] || d[:range],
        values: d['values'] || d[:values]
      )
    end

    body = Google::Apis::SheetsV4::BatchUpdateValuesRequest.new(
      value_input_option: 'USER_ENTERED',
      data: value_ranges
    )

    result = @sheets_service.batch_update_values(spreadsheet_id, body)

    output_json({
      status: 'success',
      operation: 'batch-write',
      spreadsheet_id: spreadsheet_id,
      total_updated_rows: result.total_updated_rows,
      total_updated_columns: result.total_updated_columns,
      total_updated_cells: result.total_updated_cells,
      total_updated_sheets: result.total_updated_sheets
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'batch-write', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'BATCH_WRITE_FAILED', operation: 'batch-write', message: "Failed to batch write: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Get spreadsheet metadata
  def get_metadata(spreadsheet_id:)
    result = @sheets_service.get_spreadsheet(spreadsheet_id)

    sheets_info = result.sheets.map do |s|
      props = s.properties
      {
        title: props.title,
        sheet_id: props.sheet_id,
        index: props.index,
        sheet_type: props.sheet_type,
        row_count: props.grid_properties&.row_count,
        column_count: props.grid_properties&.column_count,
        frozen_row_count: props.grid_properties&.frozen_row_count,
        frozen_column_count: props.grid_properties&.frozen_column_count
      }
    end

    output_json({
      status: 'success',
      operation: 'get-metadata',
      spreadsheet_id: result.spreadsheet_id,
      title: result.properties.title,
      locale: result.properties.locale,
      time_zone: result.properties.time_zone,
      spreadsheet_url: result.spreadsheet_url,
      sheets: sheets_info
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'get-metadata', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'METADATA_FAILED', operation: 'get-metadata', message: "Failed to get metadata: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Add a new sheet/tab
  def add_sheet(spreadsheet_id:, title:)
    requests = [{
      add_sheet: {
        properties: { title: title }
      }
    }]

    result = batch_update_spreadsheet(spreadsheet_id, requests)
    new_sheet = result.replies.first.add_sheet

    output_json({
      status: 'success',
      operation: 'add-sheet',
      spreadsheet_id: spreadsheet_id,
      sheet_id: new_sheet.properties.sheet_id,
      title: new_sheet.properties.title,
      index: new_sheet.properties.index
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'add-sheet', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'ADD_SHEET_FAILED', operation: 'add-sheet', message: "Failed to add sheet: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Delete a sheet/tab
  def delete_sheet(spreadsheet_id:, sheet_id:)
    requests = [{
      delete_sheet: { sheet_id: sheet_id }
    }]

    batch_update_spreadsheet(spreadsheet_id, requests)

    output_json({
      status: 'success',
      operation: 'delete-sheet',
      spreadsheet_id: spreadsheet_id,
      deleted_sheet_id: sheet_id
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'delete-sheet', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'DELETE_SHEET_FAILED', operation: 'delete-sheet', message: "Failed to delete sheet: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Rename a sheet/tab
  def rename_sheet(spreadsheet_id:, sheet_id:, title:)
    requests = [{
      update_sheet_properties: {
        properties: { sheet_id: sheet_id, title: title },
        fields: 'title'
      }
    }]

    batch_update_spreadsheet(spreadsheet_id, requests)

    output_json({
      status: 'success',
      operation: 'rename-sheet',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      new_title: title
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'rename-sheet', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'RENAME_SHEET_FAILED', operation: 'rename-sheet', message: "Failed to rename sheet: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Copy a sheet to same or different spreadsheet
  def copy_sheet(spreadsheet_id:, sheet_id:, destination_spreadsheet_id: nil)
    destination = destination_spreadsheet_id || spreadsheet_id

    request = Google::Apis::SheetsV4::CopySheetToAnotherSpreadsheetRequest.new(
      destination_spreadsheet_id: destination
    )

    result = @sheets_service.copy_spreadsheet(spreadsheet_id, sheet_id, request)

    output_json({
      status: 'success',
      operation: 'copy-sheet',
      spreadsheet_id: spreadsheet_id,
      source_sheet_id: sheet_id,
      destination_spreadsheet_id: destination,
      new_sheet_id: result.sheet_id,
      new_title: result.title
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'copy-sheet', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'COPY_SHEET_FAILED', operation: 'copy-sheet', message: "Failed to copy sheet: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Format cells
  def format_cells(spreadsheet_id:, sheet_id:, range:, **format_options)
    grid_range = parse_a1_to_grid_range(range, sheet_id)
    cell_format = build_cell_format(format_options)
    fields = build_format_fields(format_options)

    requests = [{
      repeat_cell: {
        range: grid_range,
        cell: { user_entered_format: cell_format },
        fields: "userEnteredFormat(#{fields})"
      }
    }]

    batch_update_spreadsheet(spreadsheet_id, requests)

    output_json({
      status: 'success',
      operation: 'format',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      range: range,
      format_applied: format_options.reject { |_, v| v.nil? }
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'format', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'FORMAT_FAILED', operation: 'format', message: "Failed to format cells: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Merge cells
  def merge_cells(spreadsheet_id:, sheet_id:, range:, merge_type: 'MERGE_ALL')
    grid_range = parse_a1_to_grid_range(range, sheet_id)

    requests = [{
      merge_cells: {
        range: grid_range,
        merge_type: merge_type
      }
    }]

    batch_update_spreadsheet(spreadsheet_id, requests)

    output_json({
      status: 'success',
      operation: 'merge-cells',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      range: range,
      merge_type: merge_type
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'merge-cells', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'MERGE_FAILED', operation: 'merge-cells', message: "Failed to merge cells: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Unmerge cells
  def unmerge_cells(spreadsheet_id:, sheet_id:, range:)
    grid_range = parse_a1_to_grid_range(range, sheet_id)

    requests = [{
      unmerge_cells: { range: grid_range }
    }]

    batch_update_spreadsheet(spreadsheet_id, requests)

    output_json({
      status: 'success',
      operation: 'unmerge-cells',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      range: range
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'unmerge-cells', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'UNMERGE_FAILED', operation: 'unmerge-cells', message: "Failed to unmerge cells: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Freeze rows and/or columns
  def freeze(spreadsheet_id:, sheet_id:, rows: nil, cols: nil)
    grid_properties = {}
    fields = []

    unless rows.nil?
      grid_properties[:frozen_row_count] = rows
      fields << 'gridProperties.frozenRowCount'
    end

    unless cols.nil?
      grid_properties[:frozen_column_count] = cols
      fields << 'gridProperties.frozenColumnCount'
    end

    requests = [{
      update_sheet_properties: {
        properties: {
          sheet_id: sheet_id,
          grid_properties: grid_properties
        },
        fields: fields.join(',')
      }
    }]

    batch_update_spreadsheet(spreadsheet_id, requests)

    output_json({
      status: 'success',
      operation: 'freeze',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      frozen_rows: rows,
      frozen_cols: cols
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'freeze', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'FREEZE_FAILED', operation: 'freeze', message: "Failed to freeze: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Auto-resize columns to fit content
  def auto_resize(spreadsheet_id:, sheet_id:, start_col:, end_col:)
    requests = [{
      auto_resize_dimensions: {
        dimensions: {
          sheet_id: sheet_id,
          dimension: 'COLUMNS',
          start_index: start_col,
          end_index: end_col
        }
      }
    }]

    batch_update_spreadsheet(spreadsheet_id, requests)

    output_json({
      status: 'success',
      operation: 'auto-resize',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      start_col: start_col,
      end_col: end_col
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'auto-resize', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'RESIZE_FAILED', operation: 'auto-resize', message: "Failed to auto-resize: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Sort a range by column
  def sort_range(spreadsheet_id:, sheet_id:, range:, sort_column:, ascending: true)
    grid_range = parse_a1_to_grid_range(range, sheet_id)

    requests = [{
      sort_range: {
        range: grid_range,
        sort_specs: [{
          dimension_index: sort_column,
          sort_order: ascending ? 'ASCENDING' : 'DESCENDING'
        }]
      }
    }]

    batch_update_spreadsheet(spreadsheet_id, requests)

    output_json({
      status: 'success',
      operation: 'sort',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      range: range,
      sort_column: sort_column,
      ascending: ascending
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'sort', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'SORT_FAILED', operation: 'sort', message: "Failed to sort range: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Find and replace across spreadsheet
  def find_replace(spreadsheet_id:, find:, replace:, sheet_id: nil, match_case: false, match_entire_cell: false)
    request = {
      find: find,
      replacement: replace,
      match_case: match_case,
      match_entire_cell: match_entire_cell,
      search_by_regex: false,
      include_formulas: false
    }
    request[:sheet_id] = sheet_id unless sheet_id.nil?

    requests = [{
      find_replace: request
    }]

    result = batch_update_spreadsheet(spreadsheet_id, requests)
    fr_result = result.replies.first.find_replace

    output_json({
      status: 'success',
      operation: 'find-replace',
      spreadsheet_id: spreadsheet_id,
      find: find,
      replace: replace,
      occurrences_changed: fr_result.occurrences_changed || 0,
      values_changed: fr_result.values_changed || 0,
      sheets_changed: fr_result.sheets_changed || 0,
      formulas_changed: fr_result.formulas_changed || 0
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'find-replace', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'FIND_REPLACE_FAILED', operation: 'find-replace', message: "Failed to find/replace: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Set column width
  def set_column_width(spreadsheet_id:, sheet_id:, start_col:, end_col:, width:)
    requests = [{
      update_dimension_properties: {
        range: {
          sheet_id: sheet_id,
          dimension: 'COLUMNS',
          start_index: start_col,
          end_index: end_col
        },
        properties: { pixel_size: width },
        fields: 'pixelSize'
      }
    }]

    batch_update_spreadsheet(spreadsheet_id, requests)

    output_json({
      status: 'success',
      operation: 'set-column-width',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      start_col: start_col,
      end_col: end_col,
      width: width
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'set-column-width', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'SET_WIDTH_FAILED', operation: 'set-column-width', message: "Failed to set column width: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Set row height
  def set_row_height(spreadsheet_id:, sheet_id:, start_row:, end_row:, height:)
    requests = [{
      update_dimension_properties: {
        range: {
          sheet_id: sheet_id,
          dimension: 'ROWS',
          start_index: start_row,
          end_index: end_row
        },
        properties: { pixel_size: height },
        fields: 'pixelSize'
      }
    }]

    batch_update_spreadsheet(spreadsheet_id, requests)

    output_json({
      status: 'success',
      operation: 'set-row-height',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      start_row: start_row,
      end_row: end_row,
      height: height
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'set-row-height', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'SET_HEIGHT_FAILED', operation: 'set-row-height', message: "Failed to set row height: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Add basic filter to a range
  def add_filter(spreadsheet_id:, sheet_id:, range:)
    grid_range = parse_a1_to_grid_range(range, sheet_id)

    requests = [{
      set_basic_filter: {
        filter: { range: grid_range }
      }
    }]

    batch_update_spreadsheet(spreadsheet_id, requests)

    output_json({
      status: 'success',
      operation: 'add-filter',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      range: range
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'add-filter', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'FILTER_FAILED', operation: 'add-filter', message: "Failed to add filter: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Add a chart
  def add_chart(spreadsheet_id:, sheet_id:, range:, chart_type:, title:)
    grid_range = parse_a1_to_grid_range(range, sheet_id)

    chart_spec = build_chart_spec(chart_type, title, grid_range)

    requests = [{
      add_chart: {
        chart: {
          spec: chart_spec,
          position: {
            overlay_position: {
              anchor_cell: {
                sheet_id: sheet_id,
                row_index: 0,
                column_index: (grid_range[:end_column_index] || 0) + 1
              }
            }
          }
        }
      }
    }]

    result = batch_update_spreadsheet(spreadsheet_id, requests)
    chart_reply = result.replies.first.add_chart

    output_json({
      status: 'success',
      operation: 'add-chart',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      chart_id: chart_reply.chart.chart_id,
      title: title,
      chart_type: chart_type
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'add-chart', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'CHART_FAILED', operation: 'add-chart', message: "Failed to add chart: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Protect a range
  def protect_range(spreadsheet_id:, sheet_id:, range:, description: nil, editors: nil)
    grid_range = parse_a1_to_grid_range(range, sheet_id)

    protected_range = { range: grid_range }
    protected_range[:description] = description if description
    protected_range[:warning_only] = false

    if editors && editors.length > 0
      protected_range[:editors] = { users: editors }
    end

    requests = [{
      add_protected_range: { protected_range: protected_range }
    }]

    result = batch_update_spreadsheet(spreadsheet_id, requests)
    pr_result = result.replies.first.add_protected_range

    output_json({
      status: 'success',
      operation: 'protect-range',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      range: range,
      protected_range_id: pr_result.protected_range.protected_range_id,
      description: description
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'protect-range', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'PROTECT_FAILED', operation: 'protect-range', message: "Failed to protect range: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  # Add conditional formatting
  def add_conditional_format(spreadsheet_id:, sheet_id:, range:, rule_type:, **rule_params)
    grid_range = parse_a1_to_grid_range(range, sheet_id)
    rule = build_conditional_format_rule(rule_type, grid_range, rule_params)

    requests = [{
      add_conditional_format_rule: {
        rule: rule,
        index: 0
      }
    }]

    batch_update_spreadsheet(spreadsheet_id, requests)

    output_json({
      status: 'success',
      operation: 'add-conditional-format',
      spreadsheet_id: spreadsheet_id,
      sheet_id: sheet_id,
      range: range,
      rule_type: rule_type
    })
  rescue Google::Apis::Error => e
    output_json({ status: 'error', error_code: 'API_ERROR', operation: 'add-conditional-format', message: "Google Sheets API error: #{e.message}", details: e.body })
    exit EXIT_API_ERROR
  rescue StandardError => e
    output_json({ status: 'error', error_code: 'CONDITIONAL_FORMAT_FAILED', operation: 'add-conditional-format', message: "Failed to add conditional format: #{e.message}" })
    exit EXIT_OPERATION_FAILED
  end

  private

  def output_json(data)
    puts JSON.pretty_generate(data)
  end

  def batch_update_spreadsheet(spreadsheet_id, requests)
    body = Google::Apis::SheetsV4::BatchUpdateSpreadsheetRequest.new(requests: requests)
    @sheets_service.batch_update_spreadsheet(spreadsheet_id, body)
  end

  # Convert A1 notation to GridRange hash
  # Examples: "A1:C5" -> {start_row: 0, end_row: 5, start_col: 0, end_col: 3}
  # Supports: "A1:C5", "A:C", "1:5", "A1", "Sheet1!A1:C5"
  def parse_a1_to_grid_range(range, sheet_id)
    # Strip sheet name prefix if present
    cell_range = range.include?('!') ? range.split('!', 2).last : range

    grid = { sheet_id: sheet_id }

    if cell_range.include?(':')
      start_ref, end_ref = cell_range.split(':')
      start_col, start_row = parse_cell_ref(start_ref)
      end_col, end_row = parse_cell_ref(end_ref)

      grid[:start_column_index] = start_col unless start_col.nil?
      grid[:start_row_index] = start_row unless start_row.nil?
      grid[:end_column_index] = end_col.nil? ? nil : end_col + 1
      grid[:end_row_index] = end_row.nil? ? nil : end_row + 1
    else
      col, row = parse_cell_ref(cell_range)
      grid[:start_column_index] = col unless col.nil?
      grid[:start_row_index] = row unless row.nil?
      grid[:end_column_index] = col + 1 unless col.nil?
      grid[:end_row_index] = row + 1 unless row.nil?
    end

    grid.compact
  end

  # Parse a single cell reference like "A1", "B", "3"
  # Returns [column_index, row_index] where either can be nil
  def parse_cell_ref(ref)
    col_str = ref.match(/^([A-Z]+)/i)&.captures&.first
    row_str = ref.match(/(\d+)$/i)&.captures&.first

    col = col_str ? col_letters_to_index(col_str.upcase) : nil
    row = row_str ? row_str.to_i - 1 : nil

    [col, row]
  end

  # Convert column letters to 0-based index: A->0, B->1, Z->25, AA->26
  def col_letters_to_index(letters)
    result = 0
    letters.each_char do |c|
      result = result * 26 + (c.ord - 'A'.ord + 1)
    end
    result - 1
  end

  def build_cell_format(options)
    format = {}
    fields_list = []

    # Text format
    text_format = {}
    text_format[:bold] = options[:bold] unless options[:bold].nil?
    text_format[:italic] = options[:italic] unless options[:italic].nil?
    text_format[:underline] = options[:underline] unless options[:underline].nil?
    text_format[:font_size] = options[:font_size] if options[:font_size]
    text_format[:font_family] = options[:font_family] if options[:font_family]

    if options[:foreground_color]
      text_format[:foreground_color_style] = {
        rgb_color: options[:foreground_color]
      }
    end

    format[:text_format] = text_format unless text_format.empty?

    # Background color
    if options[:background_color]
      format[:background_color_style] = {
        rgb_color: options[:background_color]
      }
    end

    # Alignment
    format[:horizontal_alignment] = options[:horizontal_alignment] if options[:horizontal_alignment]
    format[:vertical_alignment] = options[:vertical_alignment] if options[:vertical_alignment]

    # Number format
    if options[:number_format]
      format[:number_format] = {
        type: options[:number_format]['type'] || options[:number_format][:type],
        pattern: options[:number_format]['pattern'] || options[:number_format][:pattern]
      }
    end

    # Wrap strategy
    format[:wrap_strategy] = options[:wrap_strategy] if options[:wrap_strategy]

    # Text rotation
    if options[:text_rotation]
      format[:text_rotation] = { angle: options[:text_rotation] }
    end

    # Borders
    if options[:borders]
      format[:borders] = build_borders(options[:borders])
    end

    format
  end

  def build_format_fields(options)
    fields = []
    fields << 'textFormat.bold' unless options[:bold].nil?
    fields << 'textFormat.italic' unless options[:italic].nil?
    fields << 'textFormat.underline' unless options[:underline].nil?
    fields << 'textFormat.fontSize' if options[:font_size]
    fields << 'textFormat.fontFamily' if options[:font_family]
    fields << 'textFormat.foregroundColorStyle' if options[:foreground_color]
    fields << 'backgroundColorStyle' if options[:background_color]
    fields << 'horizontalAlignment' if options[:horizontal_alignment]
    fields << 'verticalAlignment' if options[:vertical_alignment]
    fields << 'numberFormat' if options[:number_format]
    fields << 'wrapStrategy' if options[:wrap_strategy]
    fields << 'textRotation' if options[:text_rotation]
    fields << 'borders' if options[:borders]
    fields.join(',')
  end

  def build_borders(border_config)
    borders = {}
    %w[top bottom left right].each do |side|
      side_config = border_config[side] || border_config[side.to_sym]
      next unless side_config

      border = {
        style: side_config['style'] || side_config[:style] || 'SOLID'
      }
      color = side_config['color'] || side_config[:color]
      border[:color_style] = { rgb_color: color } if color
      borders[side.to_sym] = border
    end
    borders
  end

  def build_chart_spec(chart_type, title, grid_range)
    spec = {
      title: title,
      basic_chart: {
        chart_type: chart_type.upcase,
        legend_position: 'BOTTOM_LEGEND',
        domains: [{
          domain: {
            source_range: { sources: [grid_range] }
          }
        }],
        series: [{
          series: {
            source_range: { sources: [grid_range] }
          },
          target_axis: 'LEFT_AXIS'
        }],
        header_count: 1
      }
    }
    spec
  end

  def build_conditional_format_rule(rule_type, grid_range, params)
    rule = { ranges: [grid_range] }

    case rule_type
    when 'BOOLEAN', 'boolean'
      condition = { type: params[:condition_type] || 'NUMBER_GREATER' }

      if params[:condition_values]
        condition[:values] = Array(params[:condition_values]).map do |v|
          { user_entered_value: v.to_s }
        end
      end

      format = {}
      format[:background_color_style] = { rgb_color: params[:format_background_color] } if params[:format_background_color]
      format[:text_format] = {} if params[:format_bold] || params[:format_foreground_color]
      format[:text_format][:bold] = params[:format_bold] if params[:format_bold]
      if params[:format_foreground_color]
        format[:text_format][:foreground_color_style] = { rgb_color: params[:format_foreground_color] }
      end

      rule[:boolean_rule] = {
        condition: condition,
        format: format
      }
    when 'GRADIENT', 'gradient'
      rule[:gradient_rule] = {
        minpoint: {
          color_style: { rgb_color: params[:min_color] || { red: 0.8, green: 0.2, blue: 0.2 } },
          type: params[:min_type] || 'MIN'
        },
        maxpoint: {
          color_style: { rgb_color: params[:max_color] || { red: 0.2, green: 0.8, blue: 0.2 } },
          type: params[:max_type] || 'MAX'
        }
      }

      if params[:mid_color]
        rule[:gradient_rule][:midpoint] = {
          color_style: { rgb_color: params[:mid_color] },
          type: params[:mid_type] || 'PERCENTILE',
          value: (params[:mid_value] || '50').to_s
        }
      end
    end

    rule
  end
end

# CLI Interface
def usage
  puts <<~USAGE
    Google Sheets Manager - Spreadsheet Operations CLI
    Version: 1.0.0

    Usage:
      #{File.basename($PROGRAM_NAME)} <command> [options]

    All commands accept JSON via stdin (except auth and get-metadata).

    Commands:
      auth <code>              Complete OAuth authorization with code
      create                   Create new spreadsheet
      read                     Read cell range
      write                    Write values to range
      append                   Append rows after existing data
      clear                    Clear cell range
      batch-read               Read multiple ranges
      batch-write              Write to multiple ranges
      get-metadata             Get spreadsheet info (JSON via stdin)
      add-sheet                Add new sheet/tab
      delete-sheet             Delete sheet/tab
      rename-sheet             Rename sheet/tab
      copy-sheet               Copy sheet to same or other spreadsheet
      format                   Format cells (bold, colors, alignment, etc.)
      merge-cells              Merge cell range
      unmerge-cells            Unmerge cell range
      freeze                   Freeze rows/columns
      auto-resize              Auto-resize columns to fit content
      sort                     Sort range by column
      find-replace             Find and replace text
      set-column-width         Set column width in pixels
      set-row-height           Set row height in pixels
      add-filter               Add basic filter to range
      add-chart                Add chart from data range
      protect-range            Protect cells from editing
      add-conditional-format   Add conditional formatting rule

    JSON Input Formats:

      Create:
        {
          "title": "My Spreadsheet",
          "sheets": ["Sheet1", "Sheet2"],   # Optional sheet names
          "data": [["A", "B"], [1, 2]]      # Optional data for first sheet
        }

      Read:
        {
          "spreadsheet_id": "abc123",
          "range": "Sheet1!A1:C10"
        }

      Write:
        {
          "spreadsheet_id": "abc123",
          "range": "Sheet1!A1:B2",
          "values": [["Name", "Age"], ["Alice", 30]]
        }

      Append:
        {
          "spreadsheet_id": "abc123",
          "range": "Sheet1!A:B",
          "values": [["Alice", 30], ["Bob", 25]]
        }

      Clear:
        {
          "spreadsheet_id": "abc123",
          "range": "Sheet1!A1:C10"
        }

      Batch Read:
        {
          "spreadsheet_id": "abc123",
          "ranges": ["Sheet1!A1:C10", "Sheet2!A1:B5"]
        }

      Batch Write:
        {
          "spreadsheet_id": "abc123",
          "data": [
            {"range": "Sheet1!A1:B2", "values": [["a","b"]]},
            {"range": "Sheet2!A1:B2", "values": [["c","d"]]}
          ]
        }

      Get Metadata:
        {
          "spreadsheet_id": "abc123"
        }

      Add Sheet:
        {
          "spreadsheet_id": "abc123",
          "title": "New Sheet"
        }

      Delete Sheet:
        {
          "spreadsheet_id": "abc123",
          "sheet_id": 123456789
        }

      Rename Sheet:
        {
          "spreadsheet_id": "abc123",
          "sheet_id": 123456789,
          "title": "Renamed Sheet"
        }

      Copy Sheet:
        {
          "spreadsheet_id": "abc123",
          "sheet_id": 0,
          "destination_spreadsheet_id": "xyz789"  # Optional, copies within same if omitted
        }

      Format:
        {
          "spreadsheet_id": "abc123",
          "sheet_id": 0,
          "range": "A1:B1",
          "bold": true,
          "background_color": {"red": 0.9, "green": 0.9, "blue": 0.9}
        }

      Merge Cells:
        {
          "spreadsheet_id": "abc123",
          "sheet_id": 0,
          "range": "A1:C1",
          "merge_type": "MERGE_ALL"       # MERGE_ALL, MERGE_ROWS, MERGE_COLUMNS
        }

      Sort:
        {
          "spreadsheet_id": "abc123",
          "sheet_id": 0,
          "range": "A1:D10",
          "sort_column": 0,               # 0-based column index
          "ascending": true
        }

      Find and Replace:
        {
          "spreadsheet_id": "abc123",
          "find": "old value",
          "replace": "new value",
          "sheet_id": 0,                  # Optional: limit to specific sheet
          "match_case": false,
          "match_entire_cell": false
        }

      Add Chart:
        {
          "spreadsheet_id": "abc123",
          "sheet_id": 0,
          "range": "A1:C10",
          "chart_type": "BAR",            # BAR, LINE, PIE, COLUMN, AREA, SCATTER
          "title": "Sales Chart"
        }

    Examples:
      # Create spreadsheet
      echo '{"title":"Budget 2024"}' | #{File.basename($PROGRAM_NAME)} create

      # Write data
      echo '{"spreadsheet_id":"ID","range":"Sheet1!A1:B2","values":[["Name","Age"],["Alice",30]]}' | #{File.basename($PROGRAM_NAME)} write

      # Read data
      echo '{"spreadsheet_id":"ID","range":"Sheet1!A1:B2"}' | #{File.basename($PROGRAM_NAME)} read

      # Format cells bold with background
      echo '{"spreadsheet_id":"ID","sheet_id":0,"range":"A1:B1","bold":true,"background_color":{"red":0.9,"green":0.9,"blue":0.9}}' | #{File.basename($PROGRAM_NAME)} format

      # Append rows
      echo '{"spreadsheet_id":"ID","range":"Sheet1!A:B","values":[["New","Row"]]}' | #{File.basename($PROGRAM_NAME)} append

    Exit Codes:
      0 - Success
      1 - Operation failed
      2 - Authentication error
      3 - API error
      4 - Invalid arguments
  USAGE
end

# Main execution
if __FILE__ == $PROGRAM_NAME
  if ARGV.empty? || ARGV[0] == '--help' || ARGV[0] == '-h'
    usage
    exit(ARGV.empty? ? SheetsManager::EXIT_INVALID_ARGS : SheetsManager::EXIT_SUCCESS)
  end

  command = ARGV[0]

  # Handle auth command separately
  if command == 'auth'
    if ARGV.length < 2
      puts JSON.pretty_generate({
        status: 'error',
        error_code: 'MISSING_CODE',
        message: 'Authorization code required',
        usage: "#{File.basename($PROGRAM_NAME)} auth <code>"
      })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    temp_manager = SheetsManager.allocate
    temp_manager.complete_auth(ARGV[1])
    exit SheetsManager::EXIT_SUCCESS
  end

  manager = SheetsManager.new

  case command

  when 'create'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:title]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required field: title' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.create_spreadsheet(
      title: input[:title],
      sheets: input[:sheets],
      data: input[:data]
    )

  when 'read'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:range]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, range' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.read_range(
      spreadsheet_id: input[:spreadsheet_id],
      range: input[:range]
    )

  when 'write'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:range] && input[:values]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, range, values' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.write_range(
      spreadsheet_id: input[:spreadsheet_id],
      range: input[:range],
      values: input[:values]
    )

  when 'append'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:range] && input[:values]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, range, values' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.append_rows(
      spreadsheet_id: input[:spreadsheet_id],
      range: input[:range],
      values: input[:values]
    )

  when 'clear'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:range]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, range' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.clear_range(
      spreadsheet_id: input[:spreadsheet_id],
      range: input[:range]
    )

  when 'batch-read'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:ranges]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, ranges' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.batch_read(
      spreadsheet_id: input[:spreadsheet_id],
      ranges: input[:ranges]
    )

  when 'batch-write'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:data]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, data' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.batch_write(
      spreadsheet_id: input[:spreadsheet_id],
      data: input[:data]
    )

  when 'get-metadata'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required field: spreadsheet_id' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.get_metadata(spreadsheet_id: input[:spreadsheet_id])

  when 'add-sheet'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:title]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, title' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.add_sheet(
      spreadsheet_id: input[:spreadsheet_id],
      title: input[:title]
    )

  when 'delete-sheet'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.delete_sheet(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id]
    )

  when 'rename-sheet'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id] && input[:title]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id, title' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.rename_sheet(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      title: input[:title]
    )

  when 'copy-sheet'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.copy_sheet(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      destination_spreadsheet_id: input[:destination_spreadsheet_id]
    )

  when 'format'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id] && input[:range]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id, range' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    format_opts = {}
    format_opts[:bold] = input[:bold] unless input[:bold].nil?
    format_opts[:italic] = input[:italic] unless input[:italic].nil?
    format_opts[:underline] = input[:underline] unless input[:underline].nil?
    format_opts[:font_size] = input[:font_size] if input[:font_size]
    format_opts[:font_family] = input[:font_family] if input[:font_family]
    format_opts[:foreground_color] = input[:foreground_color] if input[:foreground_color]
    format_opts[:background_color] = input[:background_color] if input[:background_color]
    format_opts[:horizontal_alignment] = input[:horizontal_alignment] if input[:horizontal_alignment]
    format_opts[:vertical_alignment] = input[:vertical_alignment] if input[:vertical_alignment]
    format_opts[:number_format] = input[:number_format] if input[:number_format]
    format_opts[:wrap_strategy] = input[:wrap_strategy] if input[:wrap_strategy]
    format_opts[:text_rotation] = input[:text_rotation] if input[:text_rotation]
    format_opts[:borders] = input[:borders] if input[:borders]

    manager.format_cells(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      range: input[:range],
      **format_opts
    )

  when 'merge-cells'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id] && input[:range]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id, range' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.merge_cells(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      range: input[:range],
      merge_type: input[:merge_type] || 'MERGE_ALL'
    )

  when 'unmerge-cells'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id] && input[:range]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id, range' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.unmerge_cells(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      range: input[:range]
    )

  when 'freeze'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.freeze(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      rows: input[:rows],
      cols: input[:cols]
    )

  when 'auto-resize'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id] && input[:start_col] && input[:end_col]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id, start_col, end_col' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.auto_resize(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      start_col: input[:start_col],
      end_col: input[:end_col]
    )

  when 'sort'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id] && input[:range] && input[:sort_column]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id, range, sort_column' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.sort_range(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      range: input[:range],
      sort_column: input[:sort_column],
      ascending: input[:ascending].nil? ? true : input[:ascending]
    )

  when 'find-replace'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:find] && input[:replace]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, find, replace' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.find_replace(
      spreadsheet_id: input[:spreadsheet_id],
      find: input[:find],
      replace: input[:replace],
      sheet_id: input[:sheet_id],
      match_case: input[:match_case] || false,
      match_entire_cell: input[:match_entire_cell] || false
    )

  when 'set-column-width'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id] && input[:start_col] && input[:end_col] && input[:width]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id, start_col, end_col, width' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.set_column_width(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      start_col: input[:start_col],
      end_col: input[:end_col],
      width: input[:width]
    )

  when 'set-row-height'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id] && input[:start_row] && input[:end_row] && input[:height]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id, start_row, end_row, height' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.set_row_height(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      start_row: input[:start_row],
      end_row: input[:end_row],
      height: input[:height]
    )

  when 'add-filter'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id] && input[:range]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id, range' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.add_filter(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      range: input[:range]
    )

  when 'add-chart'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id] && input[:range] && input[:chart_type] && input[:title]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id, range, chart_type, title' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.add_chart(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      range: input[:range],
      chart_type: input[:chart_type],
      title: input[:title]
    )

  when 'protect-range'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id] && input[:range]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id, range' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    manager.protect_range(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      range: input[:range],
      description: input[:description],
      editors: input[:editors]
    )

  when 'add-conditional-format'
    input = JSON.parse(STDIN.read, symbolize_names: true)

    unless input[:spreadsheet_id] && input[:sheet_id] && input[:range] && input[:rule_type]
      puts JSON.pretty_generate({ status: 'error', error_code: 'MISSING_REQUIRED_FIELDS', message: 'Required fields: spreadsheet_id, sheet_id, range, rule_type' })
      exit SheetsManager::EXIT_INVALID_ARGS
    end

    rule_params = input.reject { |k, _| [:spreadsheet_id, :sheet_id, :range, :rule_type].include?(k) }

    manager.add_conditional_format(
      spreadsheet_id: input[:spreadsheet_id],
      sheet_id: input[:sheet_id],
      range: input[:range],
      rule_type: input[:rule_type],
      **rule_params
    )

  else
    puts JSON.pretty_generate({
      status: 'error',
      error_code: 'INVALID_COMMAND',
      message: "Unknown command: #{command}",
      valid_commands: %w[auth create read write append clear batch-read batch-write get-metadata add-sheet delete-sheet rename-sheet copy-sheet format merge-cells unmerge-cells freeze auto-resize sort find-replace set-column-width set-row-height add-filter add-chart protect-range add-conditional-format]
    })
    usage
    exit SheetsManager::EXIT_INVALID_ARGS
  end

  exit SheetsManager::EXIT_SUCCESS
end
