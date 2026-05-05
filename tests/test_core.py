"""
Tests for qd3_fsutils.core — atomic file operations and escaping.
"""

import os
import tempfile
import pytest
from pathlib import Path

from qd3_fsutils.core import (
    read_file,
    write_file,
    edit_lines,
    insert_lines,
    delete_lines,
    validate_file,
    get_file_info,
    restore_backup,
    escape_sql,
    escape_shell,
    escape_heredoc,
    audit_sql,
    FileNotFoundError,
    LineRangeError,
    FileEditError,
)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def tmp_file():
    """Create a temporary file with test content."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("line1\nline2\nline3\nline4\nline5\n")
        path = f.name
    yield path
    # Cleanup
    try:
        os.unlink(path)
    except OSError:
        pass
    # Cleanup backup
    bak = path + ".qd3_fsutils.bak"
    try:
        os.unlink(bak)
    except OSError:
        pass


# ── read_file ─────────────────────────────────────────────────────

class TestReadFile:
    def test_read_whole_file(self, tmp_file):
        text, lines = read_file(tmp_file)
        assert len(lines) == 5
        assert lines[0] == "line1\n"

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            read_file("/nonexistent/file.txt")


# ── write_file ────────────────────────────────────────────────────

class TestWriteFile:
    def test_atomic_write(self, tmp_file):
        result = write_file(tmp_file, "new content\n")
        assert result["success"] is True
        assert "checksum" in result
        text, lines = read_file(tmp_file)
        assert text == "new content\n"

    def test_write_creates_backup(self, tmp_file):
        result = write_file(tmp_file, "updated\n")
        assert result["backup_path"] is not None
        bak_path = result["backup_path"]
        assert Path(bak_path).exists()
        # Backup should contain original content
        bak_text = Path(bak_path).read_text()
        assert "line1" in bak_text

    def test_write_new_file(self):
        path = tempfile.mktemp(suffix=".txt")
        try:
            result = write_file(path, "hello\n", backup=False)
            assert result["success"] is True
            text, _ = read_file(path)
            assert text == "hello\n"
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def test_write_empty_content(self, tmp_file):
        result = write_file(tmp_file, "", backup=False)
        assert result["success"] is True
        text, _ = read_file(tmp_file)
        assert text == ""


# ── edit_lines ────────────────────────────────────────────────────

class TestEditLines:
    def test_replace_middle_lines(self, tmp_file):
        result = edit_lines(tmp_file, 2, 3, "modified2\nmodified3")
        assert result["success"] is True
        text, lines = read_file(tmp_file)
        assert lines[0] == "line1\n"
        assert lines[1] == "modified2\n"
        assert lines[2] == "modified3\n"
        assert lines[3] == "line4\n"
        assert lines[4] == "line5\n"

    def test_replace_single_line(self, tmp_file):
        edit_lines(tmp_file, 3, 3, "replaced")
        text, lines = read_file(tmp_file)
        assert lines[2] == "replaced\n"

    def test_replace_all_lines(self, tmp_file):
        edit_lines(tmp_file, 1, 5, "a\nb\nc")
        text, lines = read_file(tmp_file)
        assert len(lines) == 3
        assert lines[0] == "a\n"

    def test_invalid_from_line(self, tmp_file):
        with pytest.raises(LineRangeError):
            edit_lines(tmp_file, 0, 3, "x")

    def test_invalid_to_line(self, tmp_file):
        with pytest.raises(LineRangeError):
            edit_lines(tmp_file, 1, 99, "x")

    def test_to_line_before_from_line(self, tmp_file):
        with pytest.raises(LineRangeError):
            edit_lines(tmp_file, 5, 3, "x")


# ── insert_lines ──────────────────────────────────────────────────

class TestInsertLines:
    def test_insert_after(self, tmp_file):
        insert_lines(tmp_file, "inserted\n", after=2)
        text, lines = read_file(tmp_file)
        assert lines[0] == "line1\n"
        assert lines[1] == "line2\n"
        assert lines[2] == "inserted\n"
        assert lines[3] == "line3\n"

    def test_insert_before(self, tmp_file):
        insert_lines(tmp_file, "inserted\n", before=1)
        text, lines = read_file(tmp_file)
        assert lines[0] == "inserted\n"
        assert lines[1] == "line1\n"

    def test_insert_after_zero(self, tmp_file):
        insert_lines(tmp_file, "first\n", after=0)
        text, lines = read_file(tmp_file)
        assert lines[0] == "first\n"
        assert lines[1] == "line1\n"

    def test_insert_both_raises(self, tmp_file):
        with pytest.raises(ValueError):
            insert_lines(tmp_file, "x", after=1, before=2)

    def test_insert_neither_raises(self, tmp_file):
        with pytest.raises(ValueError):
            insert_lines(tmp_file, "x")


# ── delete_lines ──────────────────────────────────────────────────

class TestDeleteLines:
    def test_delete_middle(self, tmp_file):
        delete_lines(tmp_file, 2, 3)
        text, lines = read_file(tmp_file)
        assert len(lines) == 3
        assert lines[0] == "line1\n"
        assert lines[1] == "line4\n"
        assert lines[2] == "line5\n"

    def test_delete_all(self, tmp_file):
        delete_lines(tmp_file, 1, 5)
        text, lines = read_file(tmp_file)
        assert len(lines) == 0

    def test_delete_single(self, tmp_file):
        delete_lines(tmp_file, 3, 3)
        text, lines = read_file(tmp_file)
        assert len(lines) == 4


# ── validate_file ─────────────────────────────────────────────────

class TestValidate:
    def test_valid_file(self, tmp_file):
        result = validate_file(tmp_file)
        assert result["valid"] is True

    def test_nonexistent_file(self):
        result = validate_file("/nonexistent")
        assert result["valid"] is False
        assert "not found" in result["error"]

    def test_empty_file(self):
        path = tempfile.mktemp(suffix=".txt")
        try:
            Path(path).write_text("")
            result = validate_file(path)
            assert result["valid"] is False
            assert "empty" in result["error"]
        finally:
            os.unlink(path)

    def test_json_syntax(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            Path(path).write_text('{"key": "value"}')
            result = validate_file(path, check_syntax=True)
            assert result["valid"] is True
        finally:
            os.unlink(path)

    def test_invalid_json_syntax(self):
        path = tempfile.mktemp(suffix=".json")
        try:
            Path(path).write_text('{invalid json}')
            result = validate_file(path, check_syntax=True)
            assert result["valid"] is False
            assert "JSON" in result["error"]
        finally:
            os.unlink(path)


# ── get_file_info ─────────────────────────────────────────────────

class TestGetFileInfo:
    def test_existing_file(self, tmp_file):
        info = get_file_info(tmp_file)
        assert info["exists"] is True
        assert info["size"] > 0
        assert info["lines"] == 5

    def test_nonexistent_file(self):
        info = get_file_info("/nonexistent")
        assert info["exists"] is False


# ── restore_backup ────────────────────────────────────────────────

class TestRestore:
    def test_restore_from_backup(self, tmp_file):
        # Write new content (creates backup)
        write_file(tmp_file, "updated\n")
        # Restore
        result = restore_backup(tmp_file)
        assert result["success"] is True
        text, _ = read_file(tmp_file)
        assert "line1" in text

    def test_restore_no_backup(self):
        path = tempfile.mktemp(suffix=".txt")
        try:
            Path(path).write_text("test")
            result = restore_backup(path)
            assert result["success"] is False
        finally:
            os.unlink(path)


# ── escape_sql ────────────────────────────────────────────────────

class TestEscapeSQL:
    def test_mysql_simple(self):
        assert escape_sql("hello", "mysql") == "hello"

    def test_mysql_single_quote(self):
        assert escape_sql("O'Brien", "mysql") == "O\\'Brien"

    def test_mysql_double_quote(self):
        assert escape_sql('say "hello"', "mysql") == 'say \\"hello\\"'

    def test_mysql_backslash(self):
        assert escape_sql("path\\to\\file", "mysql") == "path\\\\to\\\\file"

    def test_mysql_newline(self):
        assert escape_sql("line1\nline2", "mysql") == "line1\\nline2"

    def test_postgresql_single_quote(self):
        assert escape_sql("O'Brien", "postgresql") == "O''Brien"

    def test_sqlite_single_quote(self):
        assert escape_sql("O'Brien", "sqlite") == "O''Brien"

    def test_postgresql_no_escape_backslash(self):
        # PostgreSQL doesn't escape backslash by default
        assert escape_sql("test\\path", "postgresql") == "test\\path"

    def test_unknown_dialect(self):
        with pytest.raises(ValueError):
            escape_sql("test", "oracle")


# ── escape_shell ──────────────────────────────────────────────────

class TestEscapeShell:
    def test_simple_string(self):
        assert escape_shell("hello") == "'hello'"

    def test_with_single_quote(self):
        assert escape_shell("it's fine") == "'it'\\''s fine'"

    def test_dollar_sign(self):
        result = escape_shell("$HOME")
        assert result == "'$HOME'"

    def test_backtick(self):
        result = escape_shell("`cmd`")
        assert result == "'`cmd`'"

    def test_mixed_dangerous(self):
        result = escape_shell("it's $HOME `id`")
        assert "'" in result
        assert "$HOME" in result
        assert "`id`" in result

    def test_empty_string(self):
        assert escape_shell("") == "''"


# ── escape_heredoc ────────────────────────────────────────────────

class TestEscapeHeredoc:
    def test_basic_heredoc(self):
        result = escape_heredoc("SELECT 1", "SQL")
        assert "cat << 'SQL'" in result
        assert "SELECT 1" in result
        assert result.endswith("SQL")

    def test_custom_delimiter(self):
        result = escape_heredoc("UPDATE t SET s = 'x'", "SQLEOF")
        assert "cat << 'SQLEOF'" in result
        assert "UPDATE t SET s = 'x'" in result
        assert result.endswith("SQLEOF")

    def test_multiline(self):
        content = "line1\nline2\nline3"
        result = escape_heredoc(content, "EOF")
        assert result == "cat << 'EOF'\nline1\nline2\nline3\nEOF"


# ── audit_sql ─────────────────────────────────────────────────────

class TestAuditSQL:
    def test_safe_query(self):
        result = audit_sql("SELECT * FROM users WHERE id = 1")
        assert result["severity"] == "ok"
        assert result["safe_for_shell"] is True

    def test_unmatched_single_quote(self):
        result = audit_sql("SELECT * FROM t WHERE name = 'broken")
        assert result["severity"] == "error"
        assert any(i["type"] == "unmatched_single_quote" for i in result["issues"])

    def test_backtick_warning(self):
        result = audit_sql("SELECT * FROM t WHERE name = 'test`id`'")
        assert result["severity"] == "warning"
        assert any(w["type"] == "backtick_command_substitution" for w in result["warnings"])

    def test_dollar_variable_warning(self):
        result = audit_sql("INSERT INTO t VALUES ('$USER', '$HOME')")
        assert any(w["type"] == "shell_variable_expansion" for w in result["warnings"])

    def test_sql_injection_concat(self):
        result = audit_sql("SELECT * FROM t WHERE name = '" + "' OR '1'='1" + "'")
        assert result["severity"] == "error"

    def test_heredoc_delimiter_collision(self):
        query = "cat << 'SQL'\nSELECT 1\nSQL\ncat << 'SQL'\nSELECT 2\nSQL"
        result = audit_sql(query)
        # May or may not detect, but shouldn't crash
        assert "issues" in result
        assert "warnings" in result


# ── Edge cases ────────────────────────────────────────────────────

class TestEdgeCases:
    def test_unicode_content(self, tmp_file):
        write_file(tmp_file, "héllo wörld\n🚀\n")
        text, lines = read_file(tmp_file)
        assert "héllo" in text
        assert "🚀" in text

    def test_file_without_newline_at_end(self):
        path = tempfile.mktemp(suffix=".txt")
        try:
            Path(path).write_text("no newline")
            text, lines = read_file(path)
            assert len(lines) == 1
            assert lines[0] == "no newline"
        finally:
            os.unlink(path)

    def test_concurrent_safety(self, tmp_file):
        """Multiple rapid writes should not corrupt the file."""
        for i in range(20):
            write_file(tmp_file, f"content {i}\n", backup=False)
        text, _ = read_file(tmp_file)
        assert text.startswith("content ")
