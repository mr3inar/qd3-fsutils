"""
qd3_fsutils.core — Atomic file operations core.

Provides safe, atomic file manipulation with:
- Atomic writes via temp file + rename
- Automatic backup (.qd3_fsutils.bak)
- Permission preservation (stat + chmod/chown)
- Line-based editing (by line numbers)
- Content validation hooks
- SQL/shell escaping and audit
"""

import os
import stat as stat_module
import shutil
import tempfile
import hashlib
import re
from pathlib import Path
from typing import Optional, Tuple


class FileEditError(Exception):
    """Base exception for file edit operations."""
    pass


class FileNotFoundError(FileEditError):
    """File does not exist."""
    pass


class LineRangeError(FileEditError):
    """Invalid line range specified."""
    pass


class ValidationError(FileEditError):
    """Post-write validation failed."""
    pass


# ── File operations ───────────────────────────────────────────────

def _get_file_info(path: str) -> dict:
    """Get file metadata: size, lines, permissions, owner."""
    p = Path(path)
    if not p.exists():
        return {"exists": False, "size": 0, "lines": 0, "mode": None, "uid": None, "gid": None}

    st = p.stat()
    return {
        "exists": True,
        "size": st.st_size,
        "lines": len(p.read_text(encoding="utf-8", errors="replace").splitlines()),
        "mode": st.st_mode,
        "uid": st.st_uid,
        "gid": st.st_gid,
        "path": str(p.resolve()),
    }


def _preserve_permissions(src_path: str, dst_path: str):
    """Copy file permissions and ownership from src to dst."""
    try:
        st = os.stat(src_path)
        os.chmod(dst_path, stat_module.S_IMODE(st.st_mode))
        try:
            os.chown(dst_path, st.st_uid, st.st_gid)
        except PermissionError:
            pass  # non-root, ignore
    except FileNotFoundError:
        pass  # source gone, skip


def _atomic_write(dest_path: str, content: str, preserve_perms: bool = True) -> str:
    """
    Write content atomically to dest_path.

    - Writes to a temp file in the same directory (same filesystem → atomic rename)
    - Preserves permissions from original file if it exists
    - Returns the md5 checksum of written content
    """
    dest = Path(dest_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file in same directory (atomic rename requires same filesystem)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(dest.parent),
        prefix=f".{dest.name}.tmp.",
        suffix=".qd3",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(fd)  # ensure data is on disk

        # Preserve permissions from original
        if preserve_perms and dest.exists():
            _preserve_permissions(str(dest), tmp_path)

        # Atomic rename
        os.replace(tmp_path, str(dest))

        # Compute checksum
        checksum = hashlib.md5(content.encode("utf-8")).hexdigest()
        return checksum
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _backup(path: str) -> Optional[str]:
    """Create a .bak copy of the file. Returns backup path or None."""
    p = Path(path)
    if not p.exists():
        return None
    bak_path = p.with_suffix(p.suffix + ".qd3_fsutils.bak")
    shutil.copy2(str(p), str(bak_path))
    return str(bak_path)


def _restore_from_backup(path: str) -> bool:
    """Restore file from .bak. Returns True if restored."""
    p = Path(path)
    bak_path = p.with_suffix(p.suffix + ".qd3_fsutils.bak")
    if bak_path.exists():
        shutil.copy2(str(bak_path), str(p))
        return True
    return False


def read_file(path: str) -> Tuple[str, list]:
    """Read file content and return (full_text, lines_list)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    return text, lines


def edit_lines(
    path: str,
    from_line: int,
    to_line: int,
    new_content: str,
    *,
    backup: bool = True,
    preserve_perms: bool = True,
    validate: bool = True,
) -> dict:
    """
    Replace lines [from_line, to_line] (1-based, inclusive) with new_content.

    Args:
        path: Path to the file
        from_line: Start line (1-based, inclusive)
        to_line: End line (1-based, inclusive)
        new_content: Replacement text (may be multi-line)
        backup: Create .bak before editing
        preserve_perms: Preserve original file permissions
        validate: Validate result after write

    Returns:
        dict with keys: success, checksum, backup_path, lines_before, lines_after, info
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    text, lines = read_file(path)
    total_lines = len(lines)

    if from_line < 1 or from_line > total_lines:
        raise LineRangeError(
            f"from_line={from_line} out of range [1, {total_lines}]"
        )
    if to_line < from_line or to_line > total_lines:
        raise LineRangeError(
            f"to_line={to_line} out of range [{from_line}, {total_lines}]"
        )

    # Backup
    bak = _backup(path) if backup else None

    # Build new content
    before = "".join(lines[: from_line - 1])
    after = "".join(lines[to_line:])
    new_text = before + new_content + ("\n" if new_content and not new_content.endswith("\n") else "") + after

    # Atomic write
    try:
        checksum = _atomic_write(path, new_text, preserve_perms=preserve_perms)
    except Exception as e:
        # Restore from backup on failure
        if bak:
            _restore_from_backup(path)
        raise FileEditError(f"Write failed, restored from backup: {e}") from e

    # Validate
    if validate:
        _, new_lines = read_file(path)
        expected_lines = (from_line - 1) + new_content.count("\n") + 1 + (total_lines - to_line)
        # Adjust: if new_content doesn't end with \n, it's one less newline
        if new_content and not new_content.endswith("\n"):
            expected_lines = (from_line - 1) + new_content.count("\n") + 1 + (total_lines - to_line)
        else:
            expected_lines = (from_line - 1) + new_content.count("\n") + (total_lines - to_line)

        actual_lines = len(new_lines)
        if abs(actual_lines - expected_lines) > 2:  # tolerance for edge cases
            if bak:
                _restore_from_backup(path)
            raise ValidationError(
                f"Line count mismatch: expected ~{expected_lines}, got {actual_lines}. Restored."
            )

    return {
        "success": True,
        "checksum": checksum,
        "backup_path": bak,
        "lines_before": total_lines,
        "lines_after": len(Path(path).read_text(encoding="utf-8").splitlines()),
        "info": _get_file_info(path),
    }


def write_file(
    path: str,
    content: str,
    *,
    backup: bool = True,
    preserve_perms: bool = True,
    validate: bool = True,
) -> dict:
    """
    Atomically write full content to file.

    Args:
        path: Path to the file
        content: Full file content
        backup: Create .bak before writing
        preserve_perms: Preserve original file permissions
        validate: Validate result after write

    Returns:
        dict with keys: success, checksum, backup_path, info
    """
    p = Path(path)
    bak = _backup(path) if backup and p.exists() else None

    try:
        checksum = _atomic_write(path, content, preserve_perms=preserve_perms)
    except Exception as e:
        if bak:
            _restore_from_backup(path)
        raise FileEditError(f"Write failed, restored from backup: {e}") from e

    if validate:
        written = Path(path).read_text(encoding="utf-8", errors="replace")
        written_checksum = hashlib.md5(written.encode("utf-8")).hexdigest()
        if written_checksum != checksum:
            if bak:
                _restore_from_backup(path)
            raise ValidationError(
                f"Checksum mismatch after write. Restored from backup."
            )

    return {
        "success": True,
        "checksum": checksum,
        "backup_path": bak,
        "info": _get_file_info(path),
    }


def insert_lines(
    path: str,
    content: str,
    *,
    after: Optional[int] = None,
    before: Optional[int] = None,
    backup: bool = True,
    preserve_perms: bool = True,
) -> dict:
    """
    Insert lines after or before a specific line number.

    Args:
        path: Path to the file
        content: Lines to insert
        after: Insert after this line (1-based)
        before: Insert before this line (1-based)
        backup: Create .bak before editing
        preserve_perms: Preserve original file permissions

    Returns:
        dict with result info
    """
    if after is not None and before is not None:
        raise ValueError("Specify either 'after' or 'before', not both")
    if after is None and before is None:
        raise ValueError("Specify either 'after' or 'before'")

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")

    text, lines = read_file(path)
    total_lines = len(lines)

    if after is not None:
        if after < 0 or after > total_lines:
            raise LineRangeError(f"after={after} out of range [0, {total_lines}]")
        insert_pos = after  # 0 = before first line
    else:
        if before < 1 or before > total_lines + 1:
            raise LineRangeError(f"before={before} out of range [1, {total_lines + 1}]")
        insert_pos = before - 1

    before_part = "".join(lines[:insert_pos])
    after_part = "".join(lines[insert_pos:])
    new_text = before_part + content + ("\n" if content and not content.endswith("\n") else "") + after_part

    bak = _backup(path) if backup else None
    try:
        checksum = _atomic_write(path, new_text, preserve_perms=preserve_perms)
    except Exception as e:
        if bak:
            _restore_from_backup(path)
        raise FileEditError(f"Insert failed, restored from backup: {e}") from e

    return {
        "success": True,
        "checksum": checksum,
        "backup_path": bak,
        "lines_before": total_lines,
        "lines_after": len(Path(path).read_text(encoding="utf-8").splitlines()),
        "info": _get_file_info(path),
    }


def delete_lines(
    path: str,
    from_line: int,
    to_line: int,
    *,
    backup: bool = True,
    preserve_perms: bool = True,
) -> dict:
    """
    Delete lines [from_line, to_line] (1-based, inclusive).

    Args:
        path: Path to the file
        from_line: Start line (1-based, inclusive)
        to_line: End line (1-based, inclusive)
        backup: Create .bak before editing
        preserve_perms: Preserve original file permissions

    Returns:
        dict with result info
    """
    return edit_lines(path, from_line, to_line, "", backup=backup, preserve_perms=preserve_perms)


def get_file_info(path: str) -> dict:
    """Get file metadata."""
    return _get_file_info(path)


def validate_file(path: str, *, check_syntax: bool = False) -> dict:
    """
    Validate file integrity.

    Args:
        path: Path to the file
        check_syntax: If True, try basic syntax validation for known types

    Returns:
        dict with validation results
    """
    p = Path(path)
    if not p.exists():
        return {"valid": False, "error": "File not found", "info": None}

    info = _get_file_info(path)
    result = {"valid": True, "error": None, "info": info}

    # Check file is not empty
    if info["size"] == 0:
        result["valid"] = False
        result["error"] = "File is empty"
        return result

    # Check content is valid UTF-8
    try:
        content = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        result["valid"] = False
        result["error"] = f"Invalid UTF-8: {e}"
        return result

    # Basic syntax checks for known extensions
    if check_syntax:
        ext = p.suffix.lower()
        if ext in (".json",):
            import json
            try:
                json.loads(content)
            except json.JSONDecodeError as e:
                result["valid"] = False
                result["error"] = f"Invalid JSON: {e}"
        elif ext in (".yaml", ".yml"):
            try:
                import yaml
                yaml.safe_load(content)
            except Exception as e:
                result["valid"] = False
                result["error"] = f"Invalid YAML: {e}"
        elif ext in (".xml", ".html", ".xhtml"):
            import xml.etree.ElementTree as ET
            try:
                ET.fromstring(content)
            except ET.ParseError as e:
                result["valid"] = False
                result["error"] = f"Invalid XML: {e}"

    return result


def fetch_remote(
    host: str,
    remote_path: str,
    local_path: str,
    *,
    port: int = 22,
    key_path: Optional[str] = None,
) -> dict:
    """
    Fetch a file from remote host via scp.

    Args:
        host: SSH host (user@hostname)
        remote_path: Path on remote host
        local_path: Local destination path
        port: SSH port
        key_path: Optional SSH key path

    Returns:
        dict with result info
    """
    import subprocess

    local = Path(local_path)
    local.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["scp", "-P", str(port)]
    if key_path:
        cmd.extend(["-i", key_path])
    cmd.append(f"{host}:{remote_path}")
    cmd.append(str(local))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise FileEditError(f"scp failed: {result.stderr.strip()}")

    return {
        "success": True,
        "local_path": str(local.resolve()),
        "remote": f"{host}:{remote_path}",
        "info": _get_file_info(str(local)),
    }


def sync_to_remote(
    local_path: str,
    host: str,
    remote_path: str,
    *,
    port: int = 22,
    key_path: Optional[str] = None,
    owner: Optional[str] = None,
    perms: Optional[str] = None,
    backup: bool = True,
    delete: bool = False,
) -> dict:
    """
    Sync local file to remote host via rsync.

    Args:
        local_path: Local file path
        host: SSH host (user@hostname)
        remote_path: Remote destination path
        port: SSH port
        key_path: Optional SSH key path
        owner: Set owner on remote (e.g., "www-data")
        perms: Set permissions on remote (e.g., "644")
        backup: Make backup on remote before sync
        delete: Delete extraneous files on remote (rsync --delete)

    Returns:
        dict with result info
    """
    import subprocess

    local = Path(local_path)
    if not local.exists():
        raise FileNotFoundError(f"Local file not found: {local_path}")

    # Build rsync command
    ssh_cmd = f"ssh -p {port}"
    if key_path:
        ssh_cmd += f" -i {key_path}"

    cmd = [
        "rsync", "-avz",
        "--progress",
        "-e", ssh_cmd,
    ]

    if delete:
        cmd.append("--delete")

    if backup:
        # Remote backup: copy existing file to .bak before overwriting
        backup_cmd = (
            f"ssh -p {port} {host} "
            f"\"test -f {remote_path} && cp {remote_path} {remote_path}.qd3_fsutils.bak || true\""
        )
        subprocess.run(backup_cmd, shell=True, capture_output=True, timeout=30)

    cmd.append(str(local))
    cmd.append(f"{host}:{remote_path}")

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise FileEditError(f"rsync failed: {result.stderr.strip()}")

    # Post-sync: set owner and permissions
    post_cmds = []
    if owner:
        post_cmds.append(f"chown {owner} {remote_path}")
    if perms:
        post_cmds.append(f"chmod {perms} {remote_path}")

    if post_cmds:
        post_ssh = f"ssh -p {port} {host} \"{' && '.join(post_cmds)}\""
        subprocess.run(post_ssh, shell=True, capture_output=True, timeout=30)

    return {
        "success": True,
        "local_path": str(local.resolve()),
        "remote": f"{host}:{remote_path}",
        "owner": owner,
        "perms": perms,
        "backup_on_remote": backup,
    }


def restore_backup(path: str) -> dict:
    """Restore file from .qd3_fsutils.bak backup."""
    restored = _restore_from_backup(path)
    return {
        "success": restored,
        "path": path,
        "info": _get_file_info(path) if restored else None,
    }


# ── SQL / Shell escaping ──────────────────────────────────────────

def escape_sql(value: str, dialect: str = "mysql") -> str:
    """
    Escape a string value for safe use in SQL queries.

    Args:
        value: The string value to escape
        dialect: SQL dialect - "mysql", "postgresql", or "sqlite"

    Returns:
        Escaped string (without surrounding quotes)

    Examples:
        escape_sql("O'Brien", "mysql")       → "O\\'Brien"
        escape_sql("O'Brien", "postgresql")  → "O''Brien"
        escape_sql("O'Brien", "sqlite")      → "O''Brien"
        escape_sql("test\nnewline", "mysql") → "test\\nnewline"
    """
    if dialect == "mysql":
        # MySQL: escape \, ', ", \n, \r, \0, \Z, \x1a
        result = value.replace("\\", "\\\\")
        result = result.replace("'", "\\'")
        result = result.replace('"', '\\"')
        result = result.replace("\0", "\\0")
        result = result.replace("\n", "\\n")
        result = result.replace("\r", "\\r")
        result = result.replace("\x1a", "\\Z")
        return result
    elif dialect in ("postgresql", "sqlite"):
        # PostgreSQL/SQLite: escape ' by doubling it
        return value.replace("'", "''")
    else:
        raise ValueError(f"Unknown SQL dialect: {dialect}. Use 'mysql', 'postgresql', or 'sqlite'.")


def escape_shell(value: str) -> str:
    """
    Escape a string for safe use in shell commands (single-quote wrapping).

    Strategy: wrap in single quotes, and for any single quote inside the string,
    end the single-quote, add escaped double-quoted single quote, resume single-quote.
    This is the safest approach that works in bash/sh/zsh.

    Examples:
        escape_shell("simple")        → \"'simple'\"
        escape_shell("it's fine")     → \"'it'\\''s fine'\"
        escape_shell("$HOME/test")    → \"'$HOME/test'\"  (no variable expansion)
        escape_shell("back`tick")     → \"'back`tick'\"   (no command substitution)
    """
    # Replace ' with '\'' (end single-quote, escaped double-quoted quote, resume single-quote)
    escaped = value.replace("'", "'\\''")
    return f"'{escaped}'"


def escape_heredoc(value: str, delimiter: str = "SQL") -> str:
    """
    Wrap content in a heredoc for safe shell usage.

    Uses 'delimiter' (quoted) to prevent shell expansion.
    Best for multi-line SQL or code blocks.

    Args:
        value: The content to wrap
        delimiter: Heredoc delimiter (default: "SQL")

    Returns:
        str: heredoc block string

    Example:
        escape_heredoc("SELECT * FROM users WHERE name = 'O\\''Brien'")
        → \"cat << 'SQL'\\nSELECT...\\nSQL\"
    """
    return f"cat << '{delimiter}'\n{value}\n{delimiter}"


def audit_sql(query: str) -> dict:
    """
    Audit a SQL query for escaping issues and potential problems.

    Checks:
    - Unescaped single quotes inside single-quoted strings
    - Unescaped backticks inside double-quoted shell context
    - $ signs that could cause shell variable expansion
    - Unmatched quotes
    - Potential SQL injection patterns (concatenation with user input)

    Args:
        query: SQL query string to audit

    Returns:
        dict with audit results
    """
    issues = []
    warnings = []

    # 1. Check for unmatched single quotes
    single_quotes = [m.start() for m in re.finditer(r"(?<!\\)'", query)]
    if len(single_quotes) % 2 != 0:
        issues.append({
            "type": "unmatched_single_quote",
            "severity": "error",
            "description": "Unmatched single quote detected. SQL will likely fail.",
            "positions": single_quotes,
        })

    # 2. Check for unescaped single quotes inside strings
    # Look for patterns like 'it's' where the inner ' is not escaped
    for m in re.finditer(r"'[^']*'[^,);\s]*'", query):
        issues.append({
            "type": "unescaped_quote_in_string",
            "severity": "error",
            "description": f"Possible unescaped quote in string near position {m.start()}: '{m.group()[:50]}...'",
            "position": m.start(),
            "context": m.group()[:80],
        })

    # 3. Check for backticks inside double-quoted shell context
    # Backticks in shell mean command substitution
    backtick_count = query.count("`")
    if backtick_count > 0 and backtick_count % 2 != 0:
        warnings.append({
            "type": "unmatched_backtick",
            "severity": "warning",
            "description": "Unmatched backtick. In shell context, backticks execute commands!",
            "count": backtick_count,
        })
    elif backtick_count >= 2:
        warnings.append({
            "type": "backtick_command_substitution",
            "severity": "warning",
            "description": f"Found {backtick_count} backtick(s). In shell double-quotes, backticks cause command substitution!",
            "count": backtick_count,
        })

    # 4. Check for $ that could cause shell variable expansion
    dollar_vars = re.findall(r'\$\w+', query)
    if dollar_vars:
        warnings.append({
            "type": "shell_variable_expansion",
            "severity": "warning",
            "description": f"Found {len(dollar_vars)} shell variable(s): {', '.join(dollar_vars[:5])}. In double-quoted shell context, these will be expanded!",
            "variables": dollar_vars[:10],
        })

    # 5. Check for potential SQL injection via string concatenation
    concat_patterns = re.findall(r"'\s*\+\s*\$?_?\w+|'\s*\.\s*\$?_?\w+", query)
    if concat_patterns:
        issues.append({
            "type": "sql_injection_concat",
            "severity": "error",
            "description": f"String concatenation with variables detected ({len(concat_patterns)} occurrence(s)). Potential SQL injection!",
            "patterns": concat_patterns[:5],
        })

    # 6. Check for common shell-breaking characters in what looks like string values
    shell_danger = re.findall(r"'[^']*[!@#$%^&*()\[\]{}|;:`\"\\][^']*'", query)
    if shell_danger:
        warnings.append({
            "type": "shell_dangerous_chars",
            "severity": "warning",
            "description": f"Found {len(shell_danger)} string(s) with special shell characters. These may break when passed through shell.",
            "examples": [s[:60] for s in shell_danger[:3]],
        })

    # 7. Check for heredoc delimiter collision
    heredoc_delims = re.findall(r"<<\s*'?(\w+)'?", query)
    if heredoc_delims:
        for delim in heredoc_delims:
            if query.count(f"\n{delim}") > 1 or query.count(f"\n{delim}\n") > 1:
                warnings.append({
                    "type": "heredoc_delimiter_collision",
                    "severity": "warning",
                    "description": f"Heredoc delimiter '{delim}' appears multiple times. May cause early termination.",
                    "delimiter": delim,
                })

    severity = "error" if any(i["severity"] == "error" for i in issues) else "warning" if issues or warnings else "ok"

    return {
        "severity": severity,
        "issues": issues,
        "warnings": warnings,
        "total_issues": len(issues),
        "total_warnings": len(warnings),
        "safe_for_shell": severity == "ok",
    }
