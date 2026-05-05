# qd3-fsutils — Safe File Operations MCP Server

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-purple)](https://modelcontextprotocol.io)
[![Test](https://github.com/qd3/qd3-fsutils/actions/workflows/test.yml/badge.svg)](https://github.com/qd3/qd3-fsutils/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/badge/pypi-v1.1.0-blue)](https://pypi.org/project/qd3-fsutils/)

**qd3-fsutils** is an [MCP (Model Context Protocol)](https://modelcontextprotocol.io) server that gives AI agents safe, atomic file operations — no more corrupted files, broken SEARCH/REPLACE diffs, or shell-escaping nightmares.

---

## The Problem

Standard file-editing tools (`replace_in_file`, `write_to_file`, `sed` over SSH) frequently:

- **Truncate files** — writes get cut off mid-way, leaving files in a broken state
- **Corrupt structure** — SEARCH/REPLACE diffs fail due to whitespace/quote mismatches
- **Break on escaping** — SQL queries with quotes, backticks, or `$` explode when passed through SSH
- **Require huge SEARCH blocks** — that never match because of a single space difference

**Result:** One simple edit turns into 6–7 retries, and the file ends up corrupted.

---

## Solution

**qd3-fsutils** provides 12 MCP tools that solve these problems at the infrastructure level:

| Category | Tools |
|----------|-------|
| **📝 Read & Edit** | `read_file`, `edit_lines`, `write_file`, `insert_lines`, `delete_lines` |
| **🔒 Safety** | `validate`, `get_file_info`, `restore` |
| **🌐 Remote** | `fetch` (scp), `sync` (rsync) |
| **🧹 Escaping** | `escape` (SQL/shell/heredoc), `audit_sql` |

### Key Features

- **Atomic writes** — write to temp file → `os.replace()` (rename). The file is never in a half-written state.
- **Automatic backups** — every edit creates a `.qd3_fsutils.bak` before modifying
- **Permission preservation** — `stat()` → `chmod()` + `chown()` after write
- **Post-write validation** — checksum verification, line count checks
- **Auto-restore** — on validation failure, the file is automatically restored from backup
- **Remote sync** — `fetch` via scp, `sync` via rsync with owner/perms setting
- **SQL/shell escaping** — proper escaping for MySQL, PostgreSQL, SQLite, and shell commands
- **SQL audit** — detects unescaped quotes, backtick command substitution, `$` expansion, injection patterns

---

## Installation

### Prerequisites

- Python 3.10+
- `pip` (Python package manager)
- For remote operations: `scp` and `rsync` (pre-installed on macOS and Linux)

### Install from PyPI (once published)

```bash
pip install qd3-fsutils
```

### Install from source

```bash
git clone https://github.com/qd3/qd3-fsutils.git
cd qd3-fsutils
pip install -e .
```

### Manual setup

```bash
pip install mcp
```

---

## Configuration

### Cline (VS Code extension)

Add to your MCP settings file (typically `~/.cline/data/settings/cline_mcp_settings.json`):

```json
{
  "mcpServers": {
    "qd3-fsutils": {
      "command": "python3",
      "args": ["/path/to/qd3_fsutils/run.py"],
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

If installed via pip, you can use the CLI entry point:

```json
{
  "mcpServers": {
    "qd3-fsutils": {
      "command": "qd3-fsutils",
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "qd3-fsutils": {
      "command": "python3",
      "args": ["/path/to/qd3_fsutils/run.py"]
    }
  }
}
```

### Other MCP clients

Any MCP-compatible client can use this server. Point it to `run.py` or the `qd3-fsutils` CLI command.

---

## Tools Reference

### `read_file` — Read file contents

Reads a file and returns its content with line numbers. Supports partial reads via `start_line`/`end_line`.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|:--------:|-------------|
| `path` | string | ✅ | Path to the file |
| `start_line` | integer | ❌ | Start line (1-based, inclusive) |
| `end_line` | integer | ❌ | End line (1-based, inclusive) |

**Example:**

```python
# Read entire file
read_file(path="/var/www/site/app/Http/Controller.php")

# Read lines 10-20
read_file(
    path="/var/www/site/app/Http/Controller.php",
    start_line=10,
    end_line=20
)
```

**Result:**

```json
{
  "path": "/var/www/site/app/Http/Controller.php",
  "total_lines": 420,
  "start_line": 10,
  "end_line": 20,
  "content": "    public function index()\n    {\n        return view('home');\n    }\n",
  "lines": [
    "10 |     public function index()",
    "11 |     {",
    "12 |         return view('home');",
    "13 |     }"
  ]
}
```

---

### `edit_lines` — Replace lines by number

Replaces lines `from_line` through `to_line` (1-based, inclusive) with new content.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|:--------:|-------------|
| `path` | string | ✅ | Path to the file |
| `from_line` | integer | ✅ | Start line (1-based) |
| `to_line` | integer | ✅ | End line (1-based) |
| `content` | string | ✅ | Replacement content (may be multi-line) |
| `backup` | boolean | ❌ | Create .bak before editing (default: true) |

**Example:**

```python
# Replace lines 42-55 with new code
edit_lines(
    path="/var/www/site/app/Http/Controller.php",
    from_line=42,
    to_line=55,
    content="public function newMethod()\n{\n    return 'hello';\n}"
)
```

**Internal flow:**
1. Read the file
2. Create backup (`.qd3_fsutils.bak`)
3. Build new content: lines before `from_line` + new content + lines after `to_line`
4. Write to temp file in the same directory
5. Copy original file permissions to temp file
6. Atomic `os.replace()` — swap happens in microseconds
7. Validate line count after write
8. On failure — auto-restore from backup

---

### `write_file` — Atomic file write

Completely overwrites a file with atomic guarantees.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|:--------:|-------------|
| `path` | string | ✅ | Path to the file |
| `content` | string | ✅ | Full file content |
| `backup` | boolean | ❌ | Create .bak before writing (default: true) |

**Example:**

```python
write_file(
    path="/var/www/site/config/app.php",
    content="<?php\nreturn ['debug' => true];\n"
)
```

---

### `insert_lines` — Insert lines

Inserts content after or before a specific line number.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|:--------:|-------------|
| `path` | string | ✅ | Path to the file |
| `content` | string | ✅ | Content to insert |
| `after` | integer | ❌ | Insert after line N (1-based). 0 = before first line |
| `before` | integer | ❌ | Insert before line N (1-based) |
| `backup` | boolean | ❌ | Create .bak before editing (default: true) |

**Important:** Specify either `after` or `before`, not both.

**Example:**

```python
# Insert import after line 5
insert_lines(
    path="src/app.ts",
    content="import { useState } from 'react';",
    after=5
)

# Insert comment before line 10
insert_lines(
    path="src/app.ts",
    content="// TODO: refactor this",
    before=10
)
```

---

### `delete_lines` — Delete lines

Deletes lines `from_line` through `to_line` (1-based, inclusive).

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|:--------:|-------------|
| `path` | string | ✅ | Path to the file |
| `from_line` | integer | ✅ | Start line (1-based) |
| `to_line` | integer | ✅ | End line (1-based) |
| `backup` | boolean | ❌ | Create .bak before editing (default: true) |

**Example:**

```python
delete_lines(
    path="src/deprecated.ts",
    from_line=10,
    to_line=25
)
```

---

### `validate` — Validate file integrity

Checks that a file exists, is non-empty, and has valid UTF-8 encoding. Optionally validates syntax for JSON/YAML/XML.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|:--------:|-------------|
| `path` | string | ✅ | Path to the file |
| `check_syntax` | boolean | ❌ | Check syntax for JSON/YAML/XML (default: false) |

**Example:**

```python
validate(path="config.json", check_syntax=True)
# → {"valid": true, "error": null, "info": {...}}
```

---

### `get_file_info` — File metadata

Returns file size, line count, permissions, and owner.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|:--------:|-------------|
| `path` | string | ✅ | Path to the file |

**Result:**

```json
{
  "exists": true,
  "size": 15234,
  "lines": 420,
  "mode": 33188,
  "uid": 1000,
  "gid": 1000,
  "path": "/var/www/site/file.php"
}
```

---

### `fetch` — Download file from remote host

Downloads a file from a remote server via scp for local editing.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|:--------:|-------------|
| `host` | string | ✅ | SSH host (user@hostname) |
| `remote_path` | string | ✅ | Path on remote host |
| `local_path` | string | ✅ | Local destination path |
| `port` | integer | ❌ | SSH port (default: 22) |
| `key_path` | string | ❌ | Path to SSH private key |

**Example:**

```python
fetch(
    host="root@myserver.com",
    remote_path="/var/www/site/config.php",
    local_path="./work/config.php"
)
```

---

### `sync` — Upload file to remote host

Uploads a local file to a remote server via rsync. Optionally sets owner and permissions.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|:--------:|-------------|
| `local_path` | string | ✅ | Local file path |
| `host` | string | ✅ | SSH host (user@hostname) |
| `remote_path` | string | ✅ | Remote destination path |
| `port` | integer | ❌ | SSH port (default: 22) |
| `key_path` | string | ❌ | Path to SSH private key |
| `owner` | string | ❌ | Set owner on remote (e.g., www-data) |
| `perms` | string | ❌ | Set permissions on remote (e.g., 644) |
| `backup` | boolean | ❌ | Create backup on remote before sync (default: true) |

**Example:**

```python
sync(
    local_path="./work/config.php",
    host="root@myserver.com",
    remote_path="/var/www/site/config.php",
    owner="www-data",
    perms="644"
)
```

**What sync does:**
1. Creates a backup on the remote host (`file.php.qd3_fsutils.bak`)
2. Runs `rsync -avz` — transfers only changed parts
3. Executes `chown` and `chmod` on the remote host

---

### `restore` — Restore from backup

Restores a file from its automatically created `.qd3_fsutils.bak`.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|:--------:|-------------|
| `path` | string | ✅ | Path to the file to restore |

**Example:**

```python
restore(path="/var/www/site/config.php")
```

---

### `escape` — Escape strings for SQL or shell

Escapes a string for safe use in SQL queries or shell commands.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|:--------:|-------------|
| `value` | string | ✅ | String to escape |
| `mode` | string | ❌ | Mode: `sql` (default), `shell`, `heredoc` |
| `dialect` | string | ❌ | SQL dialect (for mode=sql): `mysql` (default), `postgresql`, `sqlite` |
| `delimiter` | string | ❌ | Heredoc delimiter (for mode=heredoc). Default: `SQL` |

**Modes:**

**`mode=sql`** — escapes a string value for SQL insertion:
- MySQL: escapes `\`, `'`, `"`, `\n`, `\r`, `\0`
- PostgreSQL/SQLite: doubles single quotes (`'` → `''`)

**`mode=shell`** — wraps the string in single quotes with proper escaping of internal quotes. Protects against:
- `$VAR` — not interpreted as variable expansion
- `` `cmd` `` — not executed as command substitution
- `'quotes'` — properly escaped via `'\''`

**`mode=heredoc`** — wraps multi-line content in a heredoc block for safe shell execution.

**Examples:**

```python
# SQL: MySQL escaping
escape(value="O'Brien", mode="sql", dialect="mysql")
# → "O\\'Brien"

# SQL: PostgreSQL escaping
escape(value="O'Brien", mode="sql", dialect="postgresql")
# → "O''Brien"

# Shell: safe SSH transmission
escape(value="it's $HOME/test`id`", mode="shell")
# → "'it'\\''s $HOME/test`id`'"

# Heredoc: multi-line SQL
escape(value="UPDATE users SET name = 'O''Brien' WHERE id = 1", mode="heredoc")
# → "cat << 'SQL'\nUPDATE users SET name = 'O''Brien' WHERE id = 1\nSQL"
```

---

### `audit_sql` — Audit SQL queries

Analyzes a SQL query for escaping issues and potential problems.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|:--------:|-------------|
| `query` | string | ✅ | SQL query to audit |

**Checks performed:**
- **Unmatched quotes** — `'` opened but not closed
- **Unescaped quotes inside strings** — `'it's'` instead of `'it''s'`
- **Backticks** — `` ` `` in shell context executes commands!
- **`$` variables** — `$var` will be expanded by the shell
- **SQL injection** — string concatenation with variables
- **Dangerous characters** — `!@#$%^&*` inside strings
- **Heredoc delimiter collision** — delimiter appears inside content

**Example:**

```python
audit_sql(query="UPDATE t SET s = 'it's fine' WHERE id = 1")
# → severity: "error", issues: [unescaped_quote_in_string]

audit_sql(query="SELECT * FROM t WHERE name = 'test`id`'")
# → severity: "warning", warnings: [backtick_command_substitution]
```

---

## Workflows

### Local file editing

```
1. read_file(path="src/app.ts")
   → get content with line numbers

2. edit_lines(path="src/app.ts", from_line=10, to_line=20, content="...")
   → atomic replacement, backup created, validation passed

3. validate(path="src/app.ts", check_syntax=True)
   → verify file integrity
```

### Remote server editing

```
1. fetch(host="root@server", remote_path="/var/www/site/file.php", local_path="./work/file.php")
   → download file locally

2. read_file(path="./work/file.php")
   → inspect content

3. edit_lines(path="./work/file.php", from_line=42, to_line=55, content="...")
   → edit locally (atomic, with backup)

4. validate(path="./work/file.php")
   → verify file is valid

5. sync(local_path="./work/file.php", host="root@server", remote_path="/var/www/site/file.php", owner="www-data", perms="644")
   → rsync to host, set permissions, backup created
```

### Safe SQL via SSH

```
1. audit_sql(query="UPDATE t SET s = 'value' WHERE id = 1")
   → verify query is safe for shell transmission

2. escape(value="complex value with 'quotes'", mode="shell")
   → escape for SSH transmission

3. ssh root@host "mysql -e \"UPDATE t SET s = 'escaped_value'\""
   → query won't break the shell
```

### Fixing a broken SQL query

```python
# Step 1: Audit the problematic query
audit_sql(query="""
    UPDATE modx_site_htmlsnippets
    SET snippet = '[[!pdoResources? &tvPrefix=`` &processTVs=`1`]]'
    WHERE name = 'services-tiles';
""")
# → Finds 16 backticks (command substitution risk!)
# → Finds unescaped quotes

# Step 2: Use heredoc to safely transmit
escape(
    value="UPDATE modx_site_htmlsnippets SET snippet = '...' WHERE name = 'services-tiles'",
    mode="heredoc",
    delimiter="SQLEOF"
)
# → cat << 'SQLEOF'
#   UPDATE ...
#   SQLEOF

# Step 3: Execute via SSH
# ssh root@host "cat > /tmp/query.sql << 'SQLEOF'
# UPDATE ...
# SQLEOF
# mysql -u user db < /tmp/query.sql"
```

---

## Safety Guarantees

- **Atomicity:** write via temp file + `os.replace()` — the file is never in a half-written state
- **Backup:** every modification creates a `.qd3_fsutils.bak` copy
- **Auto-restore:** on validation failure, the file is automatically restored from backup
- **Permissions:** original file permissions and ownership are preserved after write
- **Temp cleanup:** temporary files are cleaned up on failure
- **Escaping:** SQL/shell escaping prevents query corruption during SSH transmission

---

## Project Structure

```
qd3-fsutils/
├── README.md              ← this file
├── LICENSE                ← MIT license
├── CHANGELOG.md           ← version history
├── pyproject.toml         ← Python package configuration
├── Makefile               ← convenience commands
├── run.py                 ← MCP server entry point
├── qd3_fsutils/
│   ├── __init__.py        ← package init
│   ├── core.py            ← core: atomic ops, backup, validation, escaping
│   └── server.py          ← MCP server: tools, handlers
└── examples/
    └── basic_usage.py     ← usage examples
```

---

## Development

```bash
# Clone and install in dev mode
git clone https://github.com/qd3/qd3-fsutils.git
cd qd3-fsutils
pip install -e .

# Run tests
python -m pytest tests/

# Check tools are registered
python -c "from qd3_fsutils.server import TOOLS; print([t.name for t in TOOLS])"
```

---

## Requirements

- Python 3.10+
- `mcp` package (`pip install mcp`)
- For `fetch`/`sync`: `scp` and `rsync` (pre-installed on macOS and Linux)

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

## Contributing

Contributions are welcome! Please open an issue or submit a pull request on [GitHub](https://github.com/qd3/qd3-fsutils).
