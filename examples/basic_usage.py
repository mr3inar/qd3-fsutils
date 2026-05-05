"""
qd3-fsutils — Basic Usage Examples

This file demonstrates how to use qd3-fsutils tools programmatically.
In practice, these tools are called by AI agents via MCP, but you can
also use the core functions directly from Python.
"""

import json
from qd3_fsutils.core import (
    read_file,
    edit_lines,
    write_file,
    insert_lines,
    delete_lines,
    validate_file,
    get_file_info,
    escape_sql,
    escape_shell,
    escape_heredoc,
    audit_sql,
)


def example_read_and_edit():
    """Read a file, edit a range of lines, validate the result."""
    print("=== Example: Read & Edit ===")

    # Create a test file
    write_file("/tmp/example.txt", "line1\nline2\nline3\nline4\nline5\n")

    # Read it
    text, lines = read_file("/tmp/example.txt")
    print(f"Total lines: {len(lines)}")
    for i, line in enumerate(lines, 1):
        print(f"  {i}: {line.rstrip()}")

    # Edit lines 2-3
    result = edit_lines("/tmp/example.txt", 2, 3, "modified_line2\nmodified_line3")
    print(f"\nEdit result: {json.dumps(result, indent=2)}")

    # Read again
    text, lines = read_file("/tmp/example.txt")
    print("\nAfter edit:")
    for i, line in enumerate(lines, 1):
        print(f"  {i}: {line.rstrip()}")

    # Validate
    v = validate_file("/tmp/example.txt")
    print(f"\nValidation: {json.dumps(v, indent=2)}")


def example_atomic_write():
    """Demonstrate atomic write with backup and validation."""
    print("\n=== Example: Atomic Write ===")

    result = write_file(
        "/tmp/example.txt",
        "<?php\nreturn ['debug' => true, 'db' => ['host' => 'localhost']];\n",
    )
    print(f"Write result: checksum={result['checksum']}, backup={result['backup_path']}")

    info = get_file_info("/tmp/example.txt")
    print(f"File info: {json.dumps(info, indent=2)}")


def example_sql_escaping():
    """Demonstrate SQL escaping for different dialects."""
    print("\n=== Example: SQL Escaping ===")

    value = "O'Brien's book"
    print(f"Original: {value}")
    print(f"  MySQL:       {escape_sql(value, 'mysql')}")
    print(f"  PostgreSQL:  {escape_sql(value, 'postgresql')}")
    print(f"  SQLite:      {escape_sql(value, 'sqlite')}")

    # With special characters
    value2 = "line1\nline2\twith\ttabs"
    print(f"\nWith special chars: {repr(value2)}")
    print(f"  MySQL:       {escape_sql(value2, 'mysql')}")


def example_shell_escaping():
    """Demonstrate shell escaping for safe SSH transmission."""
    print("\n=== Example: Shell Escaping ===")

    values = [
        "simple",
        "it's dangerous",
        "$HOME/test",
        "back`tick`command",
        "mixed 'quotes' and $vars and `cmds`",
    ]

    for v in values:
        escaped = escape_shell(v)
        print(f"  {v:40s} → {escaped}")


def example_heredoc():
    """Demonstrate heredoc wrapping for multi-line content."""
    print("\n=== Example: Heredoc ===")

    sql = """UPDATE modx_site_htmlsnippets
SET snippet = '[[!pdoResources?
  &parents=`0`
  &tpl=`utp_tpl`
]]'
WHERE name = 'services-tiles';"""

    heredoc = escape_heredoc(sql, "SQLEOF")
    print(heredoc)


def example_audit_sql():
    """Demonstrate SQL audit for escaping issues."""
    print("\n=== Example: SQL Audit ===")

    queries = [
        # Safe query
        "SELECT * FROM users WHERE id = 1",
        # Unescaped quote
        "UPDATE t SET s = 'it's broken' WHERE id = 1",
        # Backticks (command substitution risk)
        "SELECT * FROM t WHERE name = 'test`id`'",
        # Shell variables
        "INSERT INTO t VALUES ('$USER', '$HOME')",
        # SQL injection pattern
        "SELECT * FROM t WHERE name = '" + "' OR '1'='1" + "'",
    ]

    for q in queries:
        result = audit_sql(q)
        print(f"\nQuery: {q[:60]}...")
        print(f"  Severity: {result['severity']}")
        if result['issues']:
            for issue in result['issues']:
                print(f"  ⚠ Issue [{issue['severity']}]: {issue['description'][:80]}")
        if result['warnings']:
            for warning in result['warnings']:
                print(f"  ⚡ Warning: {warning['description'][:80]}")


def example_remote_workflow():
    """Demonstrate the full remote editing workflow (dry-run)."""
    print("\n=== Example: Remote Workflow (dry-run) ===")

    print("""
    # Step 1: Fetch file from remote
    fetch(
        host="root@myserver.com",
        remote_path="/var/www/site/config.php",
        local_path="./work/config.php"
    )

    # Step 2: Read and edit locally
    read_file(path="./work/config.php")
    edit_lines(path="./work/config.php", from_line=10, to_line=20, content="...")

    # Step 3: Validate
    validate(path="./work/config.php")

    # Step 4: Sync back with permissions
    sync(
        local_path="./work/config.php",
        host="root@myserver.com",
        remote_path="/var/www/site/config.php",
        owner="www-data",
        perms="644"
    )
    """)


if __name__ == "__main__":
    example_read_and_edit()
    example_atomic_write()
    example_sql_escaping()
    example_shell_escaping()
    example_heredoc()
    example_audit_sql()
    example_remote_workflow()
