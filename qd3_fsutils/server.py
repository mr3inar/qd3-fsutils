"""
qd3_fsutils.server — MCP Server implementation.

Exposes file system utilities as MCP tools:
- read_file: Read file contents
- edit_lines: Replace lines by line numbers
- write_file: Atomic file write
- insert_lines: Insert lines after/before
- delete_lines: Delete lines by range
- validate: Validate file integrity
- get_file_info: Get file metadata
- fetch: Download file from remote host
- sync: Upload file to remote host via rsync
- restore: Restore from backup
- escape: Escape string for SQL or shell
- audit_sql: Audit SQL query for escaping issues
"""

import sys
import json
import traceback
from typing import Any

from mcp.server import Server, NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    ErrorData,
    INTERNAL_ERROR,
    INVALID_PARAMS,
)

from . import core


# ── Tool definitions ──────────────────────────────────────────────

TOOLS = [
    Tool(
        name="read_file",
        description=(
            "Read the contents of a file. Returns full text and line-by-line content. "
            "Useful for examining files before editing them."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "start_line": {"type": "integer", "description": "Start line (1-based, inclusive)", "minimum": 1},
                "end_line": {"type": "integer", "description": "End line (1-based, inclusive)", "minimum": 1},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="edit_lines",
        description=(
            "Replace a range of lines in a file by line numbers (1-based, inclusive). "
            "Uses atomic write with automatic backup and permission preservation. "
            "Validates line count after write and auto-restores on failure."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "from_line": {"type": "integer", "description": "Start line (1-based, inclusive)", "minimum": 1},
                "to_line": {"type": "integer", "description": "End line (1-based, inclusive)", "minimum": 1},
                "content": {"type": "string", "description": "Replacement content (may be multi-line)"},
                "backup": {"type": "boolean", "description": "Create .bak before editing", "default": True},
            },
            "required": ["path", "from_line", "to_line", "content"],
        },
    ),
    Tool(
        name="write_file",
        description=(
            "Atomically write full content to a file. "
            "Uses temp file + atomic rename. Preserves permissions. "
            "Validates checksum after write and auto-restores on failure."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "content": {"type": "string", "description": "Full file content"},
                "backup": {"type": "boolean", "description": "Create .bak before writing", "default": True},
            },
            "required": ["path", "content"],
        },
    ),
    Tool(
        name="insert_lines",
        description=(
            "Insert content after or before a specific line number. "
            "Specify either 'after' or 'before', not both."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "content": {"type": "string", "description": "Content to insert"},
                "after": {"type": "integer", "description": "Insert after this line (1-based). 0 = before first line"},
                "before": {"type": "integer", "description": "Insert before this line (1-based)"},
                "backup": {"type": "boolean", "description": "Create .bak before editing", "default": True},
            },
            "required": ["path", "content"],
        },
    ),
    Tool(
        name="delete_lines",
        description=(
            "Delete a range of lines from a file (1-based, inclusive). "
            "Uses atomic write with automatic backup."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "from_line": {"type": "integer", "description": "Start line (1-based, inclusive)", "minimum": 1},
                "to_line": {"type": "integer", "description": "End line (1-based, inclusive)", "minimum": 1},
                "backup": {"type": "boolean", "description": "Create .bak before editing", "default": True},
            },
            "required": ["path", "from_line", "to_line"],
        },
    ),
    Tool(
        name="validate",
        description=(
            "Validate file integrity: checks existence, non-empty, valid UTF-8. "
            "Optionally checks syntax for JSON/YAML/XML."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "check_syntax": {"type": "boolean", "description": "Check syntax for JSON/YAML/XML", "default": False},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="get_file_info",
        description="Get file metadata: size, line count, permissions, owner.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="fetch",
        description=(
            "Download a file from a remote host via scp. "
            "Useful for bringing remote files locally for editing."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "SSH host (user@hostname)"},
                "remote_path": {"type": "string", "description": "Path on remote host"},
                "local_path": {"type": "string", "description": "Local destination path"},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "key_path": {"type": "string", "description": "Optional SSH key path"},
            },
            "required": ["host", "remote_path", "local_path"],
        },
    ),
    Tool(
        name="sync",
        description=(
            "Upload a local file to a remote host via rsync. "
            "Optionally sets owner and permissions on remote. "
            "Creates remote backup before overwriting."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "local_path": {"type": "string", "description": "Local file path"},
                "host": {"type": "string", "description": "SSH host (user@hostname)"},
                "remote_path": {"type": "string", "description": "Remote destination path"},
                "port": {"type": "integer", "description": "SSH port", "default": 22},
                "key_path": {"type": "string", "description": "Optional SSH key path"},
                "owner": {"type": "string", "description": "Set owner on remote (e.g., www-data)"},
                "perms": {"type": "string", "description": "Set permissions on remote (e.g., 644)"},
                "backup": {"type": "boolean", "description": "Backup on remote before sync", "default": True},
            },
            "required": ["local_path", "host", "remote_path"],
        },
    ),
    Tool(
        name="restore",
        description="Restore a file from its .qd3_fsutils.bak backup.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to restore"},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="escape",
        description=(
            "Escape a string for safe use in SQL queries or shell commands. "
            "For SQL: supports mysql, postgresql, sqlite dialects. "
            "For shell: wraps in single quotes with proper escaping of internal quotes. "
            "For heredoc: wraps multi-line content in a heredoc block for safe shell execution."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "value": {"type": "string", "description": "The string value to escape"},
                "mode": {
                    "type": "string",
                    "description": "Escape mode: 'sql' (default), 'shell', or 'heredoc'",
                    "enum": ["sql", "shell", "heredoc"],
                    "default": "sql",
                },
                "dialect": {
                    "type": "string",
                    "description": "SQL dialect (only for mode='sql'): 'mysql' (default), 'postgresql', 'sqlite'",
                    "enum": ["mysql", "postgresql", "sqlite"],
                    "default": "mysql",
                },
                "delimiter": {
                    "type": "string",
                    "description": "Heredoc delimiter (only for mode='heredoc'). Default: 'SQL'",
                    "default": "SQL",
                },
            },
            "required": ["value"],
        },
    ),
    Tool(
        name="audit_sql",
        description=(
            "Audit a SQL query for escaping issues and potential problems. "
            "Checks for: unmatched quotes, unescaped quotes in strings, "
            "backticks that cause shell command substitution, $ variables that "
            "cause shell expansion, SQL injection via string concatenation, "
            "and other shell-dangerous characters."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "SQL query string to audit"},
            },
            "required": ["query"],
        },
    ),
]


# ── Tool handlers ─────────────────────────────────────────────────

def _result(data: Any) -> list:
    """Wrap result as TextContent list."""
    return [TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]


def _error(msg: str) -> list:
    """Wrap error as TextContent list."""
    return [TextContent(type="text", text=json.dumps({"error": msg}, indent=2, ensure_ascii=False))]


def _handle_tool(name: str, args: dict) -> list:
    """Route tool calls to core functions."""
    try:
        if name == "read_file":
            text, lines = core.read_file(args["path"])
            start = args.get("start_line", 1)
            end = args.get("end_line", len(lines))
            start = max(1, min(start, len(lines)))
            end = max(start, min(end, len(lines)))
            selected = lines[start - 1:end]
            result = {
                "path": args["path"],
                "total_lines": len(lines),
                "start_line": start,
                "end_line": end,
                "content": "".join(selected),
                "lines": [f"{i + start} | {line.rstrip()}" for i, line in enumerate(selected)],
            }
            return _result(result)

        elif name == "edit_lines":
            result = core.edit_lines(
                args["path"],
                args["from_line"],
                args["to_line"],
                args["content"],
                backup=args.get("backup", True),
            )
            return _result(result)

        elif name == "write_file":
            result = core.write_file(
                args["path"],
                args["content"],
                backup=args.get("backup", True),
            )
            return _result(result)

        elif name == "insert_lines":
            result = core.insert_lines(
                args["path"],
                args["content"],
                after=args.get("after"),
                before=args.get("before"),
                backup=args.get("backup", True),
            )
            return _result(result)

        elif name == "delete_lines":
            result = core.delete_lines(
                args["path"],
                args["from_line"],
                args["to_line"],
                backup=args.get("backup", True),
            )
            return _result(result)

        elif name == "validate":
            result = core.validate_file(
                args["path"],
                check_syntax=args.get("check_syntax", False),
            )
            return _result(result)

        elif name == "get_file_info":
            result = core.get_file_info(args["path"])
            return _result(result)

        elif name == "fetch":
            result = core.fetch_remote(
                args["host"],
                args["remote_path"],
                args["local_path"],
                port=args.get("port", 22),
                key_path=args.get("key_path"),
            )
            return _result(result)

        elif name == "sync":
            result = core.sync_to_remote(
                args["local_path"],
                args["host"],
                args["remote_path"],
                port=args.get("port", 22),
                key_path=args.get("key_path"),
                owner=args.get("owner"),
                perms=args.get("perms"),
                backup=args.get("backup", True),
            )
            return _result(result)

        elif name == "restore":
            result = core.restore_backup(args["path"])
            return _result(result)

        elif name == "escape":
            mode = args.get("mode", "sql")
            value = args["value"]

            if mode == "sql":
                dialect = args.get("dialect", "mysql")
                escaped = core.escape_sql(value, dialect)
                return _result({
                    "original": value,
                    "escaped": escaped,
                    "mode": "sql",
                    "dialect": dialect,
                })
            elif mode == "shell":
                escaped = core.escape_shell(value)
                return _result({
                    "original": value,
                    "escaped": escaped,
                    "mode": "shell",
                })
            elif mode == "heredoc":
                delimiter = args.get("delimiter", "SQL")
                escaped = core.escape_heredoc(value, delimiter)
                return _result({
                    "original": value,
                    "escaped": escaped,
                    "mode": "heredoc",
                    "delimiter": delimiter,
                })
            else:
                return _error(f"Unknown escape mode: {mode}")

        elif name == "audit_sql":
            result = core.audit_sql(args["query"])
            return _result(result)

        else:
            return _error(f"Unknown tool: {name}")

    except core.FileNotFoundError as e:
        return _error(str(e))
    except core.LineRangeError as e:
        return _error(str(e))
    except core.ValidationError as e:
        return _error(str(e))
    except core.FileEditError as e:
        return _error(str(e))
    except Exception as e:
        return _error(f"Unexpected error: {e}\n{traceback.format_exc()}")


# ── Server setup ──────────────────────────────────────────────────

def create_server() -> Server:
    """Create and configure the MCP server."""
    server = Server("qd3-fsutils")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list:
        return _handle_tool(name, arguments)

    return server


async def main():
    """Entry point: run the MCP server over stdio."""
    server = create_server()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            initialization_options=InitializationOptions(
                server_name="qd3-fsutils",
                server_version="1.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
