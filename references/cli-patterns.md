# CLI Interface Patterns - Design Rationale

Understanding the different command-line interface patterns used across google-drive, google-sheets, and google-docs skills.

## Design Philosophy

Each Google skill uses the CLI pattern that best matches its typical use case complexity:

| Skill | Primary Pattern | Rationale |
|-------|----------------|-----------|
| **google-drive** | Command + Flags | Simple file operations benefit from shell-friendly syntax |
| **google-sheets** | JSON via stdin | Complex multi-dimensional data requires structured input |
| **google-docs** | Mixed (args + JSON) | Balance between simple reads and complex formatting |

---

## google-drive: Command + Flags Pattern

### Design Choice

```bash
drive_manager.rb [command] [--flags]
```

**Why This Pattern?**

1. **Shell Integration**: Drive operations commonly used in shell pipelines
2. **Simplicity**: Most Drive operations have few parameters (file ID, query, path)
3. **Composability**: Easy to combine with other Unix tools
4. **Familiarity**: Matches standard CLI tools (ls, grep, find)

### Examples

```bash
# List files - no complex parameters needed
drive_manager.rb list

# Search with simple query
drive_manager.rb search --query "name contains 'Report'"

# Download file - straightforward parameters
drive_manager.rb download --file-id "abc123xyz" --save-path "./download"

# Share file - few clear parameters
drive_manager.rb share --file-id "abc123xyz" --email "user@example.com" --role "reader"
```

### When Flags Work Well

- ✅ **2-5 parameters**: Easy to specify on command line
- ✅ **Flat structure**: No nested objects or arrays
- ✅ **Shell scripting**: Frequently used in loops and pipelines
- ✅ **String values**: Most parameters are simple strings or numbers

### Advanced Usage

For complex operations, google-drive can accept JSON stdin (future enhancement):

```bash
# Current: Simple flag-based
drive_manager.rb share --file-id "ID" --email "user@example.com" --role "writer"

# Future: JSON for batch operations
echo '{
  "file_id": "ID",
  "permissions": [
    {"email": "user1@example.com", "role": "writer"},
    {"email": "user2@example.com", "role": "reader"}
  ]
}' | drive_manager.rb share --json
```

---

## google-sheets: JSON via stdin Pattern

### Design Choice

```bash
echo '{...}' | sheets_manager.rb [command]
```

**Why This Pattern?**

1. **Data Complexity**: Spreadsheet operations involve multi-dimensional arrays
2. **Structured Input**: Cell ranges, formatting, and formulas need clear structure
3. **Batch Operations**: Multiple ranges and operations in single call
4. **Type Preservation**: JSON maintains data types (numbers vs strings)

### Examples

```bash
# Write data - 2D array of values
echo '{
  "spreadsheet_id": "abc123xyz",
  "range": "Sheet1!A1:C3",
  "values": [
    ["Name", "Age", "City"],
    ["Alice", 30, "NYC"],
    ["Bob", 25, "LA"]
  ]
}' | sheets_manager.rb write

# Batch update - complex formatting across multiple ranges
echo '{
  "spreadsheet_id": "abc123xyz",
  "requests": [
    {
      "updateCells": {
        "range": {...},
        "userEnteredFormat": {...}
      }
    },
    {
      "updateCells": {
        "range": {...},
        "userEnteredFormat": {...}
      }
    }
  ]
}' | sheets_manager.rb batch-write
```

### When JSON Works Well

- ✅ **Nested data**: Arrays within objects, complex hierarchies
- ✅ **Multiple values**: Cell ranges, formatting options, batch requests
- ✅ **Type safety**: Preserve numbers, booleans, null values
- ✅ **API alignment**: Google Sheets API uses JSON, direct mapping

### Simple Operation Shortcuts

For common simple operations, flag shortcuts could be added as a future enhancement:

```bash
# Current: JSON for all operations
echo '{"spreadsheet_id":"ID","range":"Sheet1!A1"}' | sheets_manager.rb read

# Possible future: Flag shortcuts for simple reads
sheets_manager.rb read --id "ID" --range "Sheet1!A1"

# Complex operations use JSON (no flag equivalent)
echo '{...}' | sheets_manager.rb batch-write
```

---

## google-docs: Mixed Pattern

### Design Choice

```bash
# Simple operations: Direct arguments
docs_manager.rb read <document_id>

# Complex operations: JSON via stdin
echo '{...}' | docs_manager.rb insert
```

**Why This Pattern?**

1. **Flexibility**: Optimize for both simple and complex operations
2. **Readability**: Document ID as positional argument is clear
3. **Structured edits**: Text formatting requires nested JSON
4. **Progressive complexity**: Start simple, scale to complex

### Examples

**Simple Operations** (direct arguments):
```bash
# Read document - just needs ID
docs_manager.rb read "abc123xyz"

# Get structure - one parameter
docs_manager.rb structure "abc123xyz"
```

**Complex Operations** (JSON stdin):
```bash
# Insert formatted text at specific position
echo '{
  "document_id": "abc123xyz",
  "index": 1,
  "text": "New paragraph",
  "format": {
    "bold": true,
    "fontSize": 14
  }
}' | docs_manager.rb insert

# Replace with formatting
echo '{
  "document_id": "abc123xyz",
  "find_text": "old text",
  "replace_text": "new text",
  "format": {"bold": true}
}' | docs_manager.rb replace
```

### When Mixed Pattern Works Well

- ✅ **Progressive disclosure**: Simple tasks stay simple
- ✅ **Flexibility**: Complex operations available when needed
- ✅ **Learning curve**: Easy entry point, power user features available
- ✅ **Common case optimization**: Most operations are reads (simple)

---

## Pattern Comparison

### Use Case: Read Operation

**google-drive** (simple flag):
```bash
drive_manager.rb get --file-id "abc123xyz"
```
**Why**: File metadata is flat structure, few parameters.

**google-sheets** (JSON):
```bash
echo '{"spreadsheet_id":"ID","range":"Sheet1!A1:C10"}' | sheets_manager.rb read
```
**Why**: Range specification benefits from structured format, may need multiple ranges.

**google-docs** (direct arg):
```bash
docs_manager.rb read "abc123xyz"
```
**Why**: Only needs document ID, simplest possible interface.

### Use Case: Update Operation

**google-drive** (flags):
```bash
drive_manager.rb update --file-id "ID" --name "New Name" --description "Updated"
```
**Why**: Few flat parameters, clear command-line representation.

**google-sheets** (JSON):
```bash
echo '{
  "spreadsheet_id": "ID",
  "range": "Sheet1!A1:C3",
  "values": [["Data", "More", "Values"], ...]
}' | sheets_manager.rb write
```
**Why**: 2D array of values impossible to represent clearly with flags.

**google-docs** (JSON):
```bash
echo '{
  "document_id": "ID",
  "index": 10,
  "text": "Inserted text",
  "format": {"bold": true, "italic": true}
}' | docs_manager.rb insert
```
**Why**: Multiple nested parameters (position, text, formatting).

---

## Best Practices by Skill

### google-drive Best Practices

✅ **DO**: Use flags for simple operations
```bash
drive_manager.rb search --query "type:document"
drive_manager.rb download --file-id "ID" --save-path "./file"
```

❌ **DON'T**: Try to force JSON when flags are sufficient
```bash
# Unnecessary complexity
echo '{"file_id":"ID"}' | drive_manager.rb get  # No benefit over flags
```

💡 **TIP**: Use shell variables for repeated file IDs
```bash
FILE_ID="abc123xyz"
drive_manager.rb get --file-id "$FILE_ID"
drive_manager.rb download --file-id "$FILE_ID" --save-path "./download"
```

### google-sheets Best Practices

✅ **DO**: Use JSON for all operations
```bash
# Properly structured
echo '{
  "spreadsheet_id": "ID",
  "range": "Sheet1!A1:B10",
  "values": [[1, 2], [3, 4]]
}' | sheets_manager.rb write
```

❌ **DON'T**: Try to inline complex JSON on command line
```bash
# Hard to read and maintain
echo '{"spreadsheet_id":"ID","range":"Sheet1!A1:B10","values":[[1,2],[3,4]]}' | sheets_manager.rb write
```

💡 **TIP**: Use heredoc for complex operations
```bash
sheets_manager.rb write <<'EOF'
{
  "spreadsheet_id": "ID",
  "range": "Sheet1!A1:C3",
  "values": [
    ["Header1", "Header2", "Header3"],
    ["Value1", "Value2", "Value3"]
  ]
}
EOF
```

### google-docs Best Practices

✅ **DO**: Use direct arguments for simple reads
```bash
docs_manager.rb read "document_id"
docs_manager.rb structure "document_id"
```

✅ **DO**: Use JSON for complex operations
```bash
echo '{
  "document_id": "ID",
  "text": "New content",
  "format": {"bold": true}
}' | docs_manager.rb append
```

💡 **TIP**: Combine simple and complex operations
```bash
# Get structure first (simple)
STRUCTURE=$(docs_manager.rb structure "ID")

# Then perform complex formatted insertion (JSON)
echo "{
  \"document_id\": \"ID\",
  \"index\": 1,
  \"text\": \"Formatted text\"
}" | docs_manager.rb insert
```

---

## Why Not Standardize Everything?

### Option 1: All Flags (google-drive style)

**Problems**:
- ❌ Can't represent 2D arrays for spreadsheets
- ❌ Complex nested structures impossible (formatting options)
- ❌ Batch operations require multiple command invocations
- ❌ Type ambiguity (is "123" a string or number?)

### Option 2: All JSON (google-sheets style)

**Problems**:
- ❌ Overkill for simple operations (listing files)
- ❌ Poor shell integration and composability
- ❌ More verbose for common simple cases
- ❌ Harder to use interactively

### Option 3: Current Approach (Best of Both)

**Benefits**:
- ✅ Each skill optimized for its primary use case
- ✅ Simple operations stay simple
- ✅ Complex operations have necessary power
- ✅ Consistent within each skill
- ✅ Can evolve independently based on user needs

---

## Future Enhancements

### google-drive: Add Optional JSON Mode

```bash
# Current flag-based for simple sharing
drive_manager.rb share --file-id "ID" --email "user@example.com"

# Future JSON for batch permissions
echo '{
  "file_id": "ID",
  "permissions": [
    {"email": "user1@example.com", "role": "writer"},
    {"email": "user2@example.com", "role": "reader"},
    {"type": "domain", "domain": "company.com", "role": "reader"}
  ]
}' | drive_manager.rb share --json
```

### google-sheets: Add Simple Flag Shortcuts

```bash
# Current: JSON for all operations
echo '{"spreadsheet_id":"ID","range":"A1"}' | sheets_manager.rb read

# Possible future: Flag shortcuts for simple reads
sheets_manager.rb read --id "ID" --range "Sheet1!A1"

# JSON still required for complex operations
echo '{...complex batch operation...}' | sheets_manager.rb batch-write
```

### google-docs: Maintain Mixed Approach

- Keep simple operations with direct arguments
- Keep complex operations with JSON
- Add more format shortcuts for common cases

---

## Key Takeaways

1. **Different problems need different interfaces**: File operations vs spreadsheet data vs document formatting have distinct complexity profiles.

2. **Optimize for the common case**: google-drive optimizes for simple shell operations, google-sheets for structured data manipulation.

3. **Progressive disclosure**: google-docs starts simple (read with ID) and scales to complex (formatted insertions with JSON).

4. **Consistency within skill matters more**: Each skill is internally consistent, reducing cognitive load when using one skill extensively.

5. **Evolution over revolution**: Skills can add complementary patterns (flags to google-sheets, JSON to google-drive) without breaking existing usage.

---

## Related Documentation

- See `integration-patterns.md` for workflow examples using all three patterns
- See `troubleshooting.md` for common CLI syntax errors and solutions
- Check main SKILL.md files for complete operation syntax references
