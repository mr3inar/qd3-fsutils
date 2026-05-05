# Changelog

## 1.1.0 (2026-05-05)

### Added
- `escape` tool — escape strings for SQL (MySQL/PostgreSQL/SQLite), shell, and heredoc
- `audit_sql` tool — analyze SQL queries for escaping issues, backtick command substitution, shell variable expansion, injection patterns
- Full English documentation in README.md
- `pyproject.toml` — Python package configuration for PyPI publishing
- `LICENSE` — MIT license
- `CHANGELOG.md` — version history
- `Makefile` — convenience commands (install, test, clean)
- `examples/basic_usage.py` — usage examples
- `.gitignore` — Python project ignores

### Changed
- Server version bumped to 1.1.0
- README.md rewritten in English with comprehensive tool reference

## 1.0.0 (2026-04-30)

### Added
- `read_file` tool — read file contents with line numbers
- `edit_lines` tool — replace lines by line number range
- `write_file` tool — atomic file write with temp file + rename
- `insert_lines` tool — insert content after/before a line
- `delete_lines` tool — delete lines by range
- `validate` tool — file integrity validation (UTF-8, JSON/YAML/XML syntax)
- `get_file_info` tool — file metadata (size, lines, permissions, owner)
- `fetch` tool — download file from remote host via scp
- `sync` tool — upload file to remote host via rsync with owner/perms
- `restore` tool — restore from `.qd3_fsutils.bak` backup
- Atomic write with automatic backup and permission preservation
- Post-write validation with auto-restore on failure
- Russian documentation in README.md
