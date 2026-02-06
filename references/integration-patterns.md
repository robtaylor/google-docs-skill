# Google Workspace Integration Patterns

Complete workflows combining google-drive, google-sheets, and google-docs skills for powerful automation.

## Pattern 1: Data Report Generation

**Use Case**: Extract spreadsheet data, analyze it, and generate a formatted document report.

**Workflow**:
```bash
# Step 1: Find the source spreadsheet
scripts/drive_manager.rb search \
  --query "Sales Q4 2024" \
  --mime-type "application/vnd.google-apps.spreadsheet"

# Step 2: Read the data
echo '{
  "spreadsheet_id": "SPREADSHEET_ID_FROM_STEP1",
  "range": "Q4 Data!A1:F100"
}' | scripts/sheets_manager.rb read

# Step 3: Process data with Claude (analyze trends, calculate metrics)

# Step 4: Create a new document for the report
echo '{
  "title": "Q4 2024 Sales Analysis Report"
}' | scripts/docs_manager.rb create

# Step 5: Write report sections
echo '{
  "document_id": "DOC_ID_FROM_STEP4",
  "text": "# Q4 2024 Sales Analysis\n\n## Executive Summary\n\n[Claude-generated insights]"
}' | scripts/docs_manager.rb append

# Step 6: Share the report
scripts/drive_manager.rb share \
  --file-id "DOC_ID_FROM_STEP4" \
  --email "stakeholder@company.com" \
  --role "reader"
```

**Expected Output**: Formatted Google Doc with analysis, shared with stakeholders.

---

## Pattern 2: Workspace Organization

**Use Case**: Create organized project workspace with folders, documents, and spreadsheets.

**Workflow**:
```bash
# Step 1: Create project folder
scripts/drive_manager.rb create-folder \
  --name "Project Alpha" \
  --parent-folder-id "root"

# Step 2: Create subfolders
scripts/drive_manager.rb create-folder \
  --name "Documents" \
  --parent-folder-id "PROJECT_FOLDER_ID_FROM_STEP1"

scripts/drive_manager.rb create-folder \
  --name "Spreadsheets" \
  --parent-folder-id "PROJECT_FOLDER_ID_FROM_STEP1"

# Step 3: Create project documents
echo '{
  "title": "Project Alpha - Requirements",
  "parent_folder_id": "DOCUMENTS_FOLDER_ID"
}' | scripts/docs_manager.rb create

# Step 4: Create tracking spreadsheet
# (Use google-sheets create operation with parent_folder_id)

# Step 5: Share entire project folder
scripts/drive_manager.rb share \
  --file-id "PROJECT_FOLDER_ID_FROM_STEP1" \
  --email "team@company.com" \
  --role "writer"
```

**Expected Output**: Organized folder structure with permissions set for team collaboration.

---

## Pattern 3: Bulk Document Updates

**Use Case**: Search for documents matching criteria and update content across multiple files.

**Workflow**:
```bash
# Step 1: Find all matching documents
scripts/drive_manager.rb search \
  --query "Status Report" \
  --mime-type "application/vnd.google-apps.document"

# Step 2: For each document, perform updates
# (Loop through results from Step 1)

for DOC_ID in $(jq -r '.files[].id' search_results.json); do
  # Read current content
  CONTENT=$(scripts/docs_manager.rb read "$DOC_ID")

  # Update with new information
  echo "{
    \"document_id\": \"$DOC_ID\",
    \"find_text\": \"Status: Pending\",
    \"replace_text\": \"Status: Completed\"
  }" | scripts/docs_manager.rb replace
done
```

**Expected Output**: All matching documents updated with new status.

---

## Pattern 4: Spreadsheet Consolidation

**Use Case**: Combine data from multiple spreadsheets into a master sheet.

**Workflow**:
```bash
# Step 1: Find all department spreadsheets
scripts/drive_manager.rb search \
  --query "Department Budget 2024"

# Step 2: Create master consolidation sheet
echo '{
  "title": "Master Budget 2024 - All Departments"
}' | scripts/sheets_manager.rb create

# Step 3: Read data from each department sheet
for SHEET_ID in $(jq -r '.files[].id' search_results.json); do
  echo "{
    \"spreadsheet_id\": \"$SHEET_ID\",
    \"range\": \"Budget!A2:E100\"
  }" | scripts/sheets_manager.rb read >> consolidated_data.json
done

# Step 4: Write consolidated data to master sheet
echo '{
  "spreadsheet_id": "MASTER_SHEET_ID",
  "range": "Consolidated!A2",
  "values": [/* combined data from step 3 */]
}' | scripts/sheets_manager.rb write
```

**Expected Output**: Single master spreadsheet with data from all departments.

---

## Pattern 5: Document Template System

**Use Case**: Create documents from templates with personalized content.

**Workflow**:
```bash
# Step 1: Find template document
scripts/drive_manager.rb search \
  --query "Invoice Template"

# Step 2: Copy template for new document
scripts/drive_manager.rb copy \
  --file-id "TEMPLATE_ID" \
  --name "Invoice #1234 - Acme Corp"

# Step 3: Read template content
NEW_DOC_ID=$(jq -r '.id' copy_result.json)
scripts/docs_manager.rb read "$NEW_DOC_ID"

# Step 4: Replace placeholders with actual data
echo "{
  \"document_id\": \"$NEW_DOC_ID\",
  \"find_text\": \"{{CLIENT_NAME}}\",
  \"replace_text\": \"Acme Corporation\"
}" | scripts/docs_manager.rb replace

echo "{
  \"document_id\": \"$NEW_DOC_ID\",
  \"find_text\": \"{{INVOICE_NUMBER}}\",
  \"replace_text\": \"#1234\"
}" | scripts/docs_manager.rb replace

# Step 5: Move to appropriate folder
scripts/drive_manager.rb move \
  --file-id "$NEW_DOC_ID" \
  --destination-folder-id "INVOICES_FOLDER_ID"
```

**Expected Output**: Personalized document created from template in correct location.

---

## Pattern 6: Data Collection Pipeline

**Use Case**: Aggregate data from multiple sources into a tracking spreadsheet.

**Workflow**:
```bash
# Step 1: Create or find tracking spreadsheet
TRACKING_SHEET_ID="your_tracking_sheet_id"

# Step 2: Search for data source documents
scripts/drive_manager.rb search \
  --query "Survey Results 2024"

# Step 3: Extract data from each source
for DOC_ID in $(jq -r '.files[].id' search_results.json); do
  # Read document
  CONTENT=$(scripts/docs_manager.rb read "$DOC_ID")

  # Parse content with Claude to extract structured data
  # (Claude processes CONTENT and formats for spreadsheet)

  # Append to tracking sheet
  echo "{
    \"spreadsheet_id\": \"$TRACKING_SHEET_ID\",
    \"range\": \"Data!A:F\",
    \"values\": [[/* extracted data */]]
  }" | scripts/sheets_manager.rb append
done
```

**Expected Output**: Tracking spreadsheet populated with data from all source documents.

---

## Common Issues & Troubleshooting

### Issue: File ID vs File Path Confusion

**Problem**: Commands fail because wrong identifier type used.

**Solution**:
- **google-drive**: Uses `--file-id` for existing files
- **google-sheets**: Uses `spreadsheet_id` in JSON
- **google-docs**: Uses `document_id` in JSON or as argument

Always use the ID (long alphanumeric string) from search/list results, not the file path.

### Issue: Permission Denied Errors

**Problem**: Operations fail with "Insufficient Permission" error.

**Solution**:
```bash
# Check current permissions
scripts/drive_manager.rb list-permissions \
  --file-id "FILE_ID"

# Add yourself as writer if needed
scripts/drive_manager.rb share \
  --file-id "FILE_ID" \
  --email "your-email@gmail.com" \
  --role "writer"
```

### Issue: Search Returns Too Many Results

**Problem**: Search is too broad and returns unrelated files.

**Solution**: Use more specific query with operators:
```bash
# Combine multiple criteria
scripts/drive_manager.rb search \
  --query "name contains 'Budget' and mimeType='application/vnd.google-apps.spreadsheet'"

# Search in specific folder
scripts/drive_manager.rb search \
  --query "'FOLDER_ID' in parents"
```

---

## Tips for Efficient Workflows

1. **Cache File IDs**: Store frequently-used file IDs in variables or files
2. **Use Batch Operations**: google-sheets batch_update for multiple changes
3. **Error Handling**: Always check JSON response for `"success": true` before proceeding
4. **Permission Planning**: Set folder permissions rather than individual files
5. **Template Reuse**: Create template documents for consistent formatting
6. **Search Optimization**: Use mimeType filters to narrow results quickly

---

## Advanced: Skill Composition Patterns

### Listing Spreadsheets (Without Native List Operation)

Use google-drive with mimeType filter:
```bash
scripts/drive_manager.rb search \
  --query "mimeType='application/vnd.google-apps.spreadsheet'" \
  --max-results 50
```

### Listing Documents (Without Native List Operation)

Use google-drive with mimeType filter:
```bash
scripts/drive_manager.rb search \
  --query "mimeType='application/vnd.google-apps.document'" \
  --max-results 50
```

### Finding Recently Modified Files

```bash
scripts/drive_manager.rb search \
  --query "modifiedTime > '2024-01-01T00:00:00'"
```

---

## Next Steps

- Explore the `references/troubleshooting.md` for detailed error recovery
- See `references/advanced-operations.md` for power user features
- Check skill SKILL.md files for complete operation references
