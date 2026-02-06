# Google Skills Troubleshooting Guide

Comprehensive troubleshooting for google-drive, google-sheets, and google-docs skills.

## Exit Codes Reference

All three Google skills use standardized exit codes:

| Code | Meaning | Action Required |
|------|---------|-----------------|
| 0 | Success | None - operation completed successfully |
| 1 | Operation Failed | Check error message for specific issue |
| 2 | Authentication Error | Re-authorize or fix credentials |
| 3 | API Error | Check Google API status, retry later |
| 4 | Invalid Arguments | Review command syntax and parameters |

## Common Authentication Issues

### Error: Missing Credentials File

**Error Message**:
```json
{
  "success": false,
  "error": "client_secret.json not found",
  "error_code": "AUTH_ERROR"
}
```

**Root Cause**: OAuth credentials file not present at expected location.

**Solution Steps**:
1. Verify file exists: `ls ~/.claude/.google/client_secret.json`
2. If missing, download OAuth credentials from Google Cloud Console:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Navigate to APIs & Services > Credentials
   - Create OAuth 2.0 Client ID (Desktop application)
   - Download JSON and save as `~/.claude/.google/client_secret.json`
3. Ensure file has correct permissions: `chmod 600 ~/.claude/.google/client_secret.json`

**Prevention**: Keep backup of `client_secret.json` in secure location.

---

### Error: Invalid Credentials

**Error Message**:
```json
{
  "success": false,
  "error": "Invalid OAuth credentials",
  "error_code": "AUTH_ERROR"
}
```

**Root Cause**: OAuth client configured incorrectly or credentials revoked.

**Solution Steps**:
1. Verify OAuth client is enabled for required APIs:
   - Drive API
   - Sheets API
   - Docs API
   - Calendar API (if using calendar skill)
   - People API (if using contacts skill)
   - Gmail API (if using email skill)
2. Check OAuth consent screen is configured
3. Verify redirect URI is configured: `http://localhost:8080`
4. Download fresh credentials from Google Cloud Console
5. Delete existing token: `rm ~/.claude/.google/token.json`
6. Run any Google skill operation to trigger re-authorization

**Prevention**: Don't manually edit `client_secret.json` file.

---

### Error: Token Expired (Auto-Refresh Failed)

**Error Message**:
```json
{
  "success": false,
  "error": "Token refresh failed",
  "error_code": "AUTH_ERROR"
}
```

**Root Cause**: Refresh token expired or revoked.

**Solution Steps**:
1. Delete expired token: `rm ~/.claude/.google/token.json`
2. Run any Google skill operation to trigger full re-authorization flow
3. Complete OAuth authorization in browser when prompted
4. Verify new token created: `ls -lh ~/.claude/.google/token.json`

**Prevention**:
- Don't manually edit `token.json`
- Complete OAuth flow promptly (don't leave browser window open)
- Check token expiration if using skills infrequently

---

### Error: Insufficient Scope

**Error Message**:
```json
{
  "success": false,
  "error": "Token missing required scope",
  "error_code": "AUTH_ERROR"
}
```

**Root Cause**: Token was created with fewer scopes than currently required.

**Solution Steps**:
1. Delete token to force full re-authorization: `rm ~/.claude/.google/token.json`
2. Run operation again - script will request all required scopes
3. Carefully review scope list in OAuth consent screen
4. Authorize all requested scopes

**Prevention**: When adding new Google skills, re-authorize to include new scopes.

---

## Common Operation Issues

### Error: File Not Found

**Error Message**:
```json
{
  "success": false,
  "error": "File not found: abc123xyz",
  "error_code": "API_ERROR"
}
```

**Root Cause**: File ID doesn't exist or user lacks access permissions.

**Solution Steps**:
1. Verify file ID is correct (long alphanumeric string, not file name)
2. Check file exists with search:
   ```bash
   scripts/drive_manager.rb search \
     --query "name='Your File Name'"
   ```
3. Verify you have access to the file:
   ```bash
   scripts/drive_manager.rb list-permissions \
     --file-id "FILE_ID"
   ```
4. If file is shared, ensure it's shared with your authenticated account

**Prevention**: Always use file IDs from search/list results, not hardcoded values.

---

### Error: Permission Denied

**Error Message**:
```json
{
  "success": false,
  "error": "Insufficient permission to access file",
  "error_code": "API_ERROR"
}
```

**Root Cause**: User lacks required permission level for requested operation.

**Solution Steps**:
1. Check current permissions:
   ```bash
   scripts/drive_manager.rb list-permissions \
     --file-id "FILE_ID"
   ```
2. If you're not the owner, request permission from file owner
3. If you are the owner but using different account, share to authenticated account:
   ```bash
   scripts/drive_manager.rb share \
     --file-id "FILE_ID" \
     --email "your-authenticated-email@gmail.com" \
     --role "writer"
   ```

**Prevention**: Check permissions before performing write/modify operations.

---

### Error: Invalid Range (Sheets Only)

**Error Message**:
```json
{
  "success": false,
  "error": "Invalid range: InvalidSheet!A1:B10",
  "error_code": "API_ERROR"
}
```

**Root Cause**: Sheet name doesn't exist or range syntax incorrect.

**Solution Steps**:
1. Get spreadsheet metadata to see available sheets:
   ```bash
   echo '{"spreadsheet_id":"SPREADSHEET_ID"}' | \
     scripts/sheets_manager.rb get-metadata
   ```
2. Use exact sheet name (case-sensitive) from metadata
3. Verify A1 notation syntax: `SheetName!A1:B10`
4. Common mistakes:
   - Missing sheet name: `A1:B10` (should be `Sheet1!A1:B10`)
   - Wrong delimiter: `Sheet1:A1:B10` (should use `!`)
   - Invalid range: `A1:ZZ` (should specify both corners)

**Prevention**: Always query metadata first to confirm sheet names.

---

### Error: Index Out of Bounds (Docs Only)

**Error Message**:
```json
{
  "success": false,
  "error": "Index 5000 exceeds document length",
  "error_code": "API_ERROR"
}
```

**Root Cause**: Attempting to insert/delete at position beyond document end.

**Solution Steps**:
1. Read document to get current structure:
   ```bash
   scripts/docs_manager.rb structure "DOCUMENT_ID"
   ```
2. Use `append` operation instead of `insert` for adding to end
3. Calculate correct indices based on content length
4. Note: Document indices are 1-based (first character is index 1)

**Prevention**: Use `append` for end-of-document operations, `structure` to verify indices.

---

## Network and API Issues

### Error: Rate Limit Exceeded

**Error Message**:
```json
{
  "success": false,
  "error": "Rate limit exceeded, retry after X seconds",
  "error_code": "API_ERROR"
}
```

**Root Cause**: Too many API requests in short time period.

**Solution Steps**:
1. Wait time specified in error message
2. Implement exponential backoff for retry logic
3. Use batch operations instead of individual calls:
   - google-sheets: Use `batch-write` for multiple data operations
   - google-drive: Process files in smaller batches

**Prevention**:
- Use batch operations for bulk changes
- Add delays between operations in loops
- Query metadata once and reuse, don't query per operation

---

### Error: Network Timeout

**Error Message**:
```json
{
  "success": false,
  "error": "Request timeout: Network operation timed out",
  "error_code": "API_ERROR"
}
```

**Root Cause**: Network connectivity issue or Google API temporary outage.

**Solution Steps**:
1. Check internet connectivity: `ping google.com`
2. Verify Google API status: [Google Workspace Status Dashboard](https://www.google.com/appsstatus)
3. Retry operation after brief delay
4. For large files, consider splitting into smaller operations

**Prevention**: Implement retry logic with exponential backoff for production workflows.

---

## CLI Interface Issues

### Issue: Command Not Recognized (google-drive)

**Error**: `Unknown command: --list`

**Root Cause**: google-drive uses command-first syntax, not flag-first.

**Solution**:
```bash
# WRONG ❌
drive_manager.rb --list

# CORRECT ✅
drive_manager.rb list
```

**Pattern**: `drive_manager.rb [command] [--flags]`

---

### Issue: JSON Parse Error (google-sheets, google-docs)

**Error**: `Invalid JSON input`

**Root Cause**: Malformed JSON sent to stdin.

**Solution**:
1. Validate JSON syntax with tool: `echo '{ your json }' | jq .`
2. Ensure proper quoting:
   ```bash
   # WRONG ❌ (shell interprets $)
   echo '{"key": "$value"}' | sheets_manager.rb read

   # CORRECT ✅ (escape or use single quotes)
   echo '{"key": "value"}' | sheets_manager.rb read
   ```
3. Use heredoc for complex JSON:
   ```bash
   sheets_manager.rb read <<'EOF'
   {
     "spreadsheet_id": "abc123xyz",
     "range": "Sheet1!A1:B10"
   }
   EOF
   ```

**Prevention**: Test JSON with `jq` before piping to scripts.

---

## Data Format Issues

### Issue: Formula Not Calculating

**Problem**: Formula appears as text `=SUM(A1:A10)` instead of result.

**Root Cause**: Using `RAW` input option instead of `USER_ENTERED`.

**Solution**:
```bash
echo '{
  "spreadsheet_id": "ID",
  "range": "Sheet1!C1",
  "values": [["=SUM(A1:A10)"]],
  "input_option": "USER_ENTERED"
}' | sheets_manager.rb write
```

**Prevention**: Always use `"input_option": "USER_ENTERED"` for formulas.

---

### Issue: Date/Time Formatting

**Problem**: Dates appear as numbers (e.g., 44927 instead of 2023-01-15).

**Root Cause**: Google Sheets stores dates as serial numbers.

**Solution**:
1. Apply number format via batch_update:
   ```bash
   echo '{
     "spreadsheet_id": "ID",
     "requests": [{
       "repeatCell": {
         "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 10, "startColumnIndex": 0, "endColumnIndex": 1},
         "cell": {
           "userEnteredFormat": {
             "numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}
           }
         },
         "fields": "userEnteredFormat.numberFormat"
       }
     }]
   }' | sheets_manager.rb batch_update
   ```

**Prevention**: Apply formatting after writing date values.

---

## Performance Issues

### Issue: Slow Large File Operations

**Problem**: Operations on large spreadsheets/documents timeout or take excessive time.

**Solution**:
1. **For Sheets**: Use specific ranges instead of entire sheets:
   ```bash
   # SLOW ❌
   echo '{"spreadsheet_id":"ID","range":"Sheet1"}' | sheets_manager.rb read

   # FAST ✅
   echo '{"spreadsheet_id":"ID","range":"Sheet1!A1:Z1000"}' | sheets_manager.rb read
   ```

2. **For Docs**: Read structure first, then specific sections:
   ```bash
   # Get structure to understand document
   docs_manager.rb structure "DOC_ID"

   # Read only needed content range
   ```

3. **For Drive**: Limit search results:
   ```bash
   drive_manager.rb search --query "name contains 'Report'" --max-results 50
   ```

**Prevention**: Query only data you need, use pagination for large result sets.

---

## Debugging Tips

### Enable Verbose Output

Add debug logging to troubleshoot issues:

```bash
# For google-drive
DEBUG=1 drive_manager.rb list

# For google-sheets and google-docs
# Add debug flag to JSON input (if supported)
```

### Inspect API Responses

Save JSON output for inspection:

```bash
drive_manager.rb list > output.json
cat output.json | jq .
```

### Test Authentication Separately

Verify OAuth flow works:

```bash
# Delete token
rm ~/.claude/.google/token.json

# Run simple operation
drive_manager.rb list

# Should prompt for authorization
# Complete OAuth flow in browser
# Verify token created
ls -lh ~/.claude/.google/token.json
```

### Validate File IDs

Test file ID is accessible:

```bash
drive_manager.rb get --file-id "FILE_ID"
```

---

## Getting Help

### Check Logs

Ruby gem errors may provide additional context:
```bash
# Verify Bundler setup (from skill root directory)
bundle check

# If gems are missing, install them
bundle install

# Check installed gem versions
bundle list | grep google-apis
```

### Verify API Enablement

Ensure APIs are enabled in Google Cloud Console:
1. Visit [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to APIs & Services > Library
3. Search and enable:
   - Google Drive API
   - Google Sheets API
   - Google Docs API
   - (Plus Calendar, People, Gmail if using those skills)

### Test with Google API Explorer

Validate operations work outside skill scripts:
- [Drive API Explorer](https://developers.google.com/drive/api/v3/reference)
- [Sheets API Explorer](https://developers.google.com/sheets/api/reference/rest)
- [Docs API Explorer](https://developers.google.com/docs/api/reference/rest)

---

## Additional Resources

- See `integration-patterns.md` for workflow examples
- Check main SKILL.md files for operation syntax
- Review Ruby script source for implementation details
- Consult Google Workspace API documentation for advanced usage
