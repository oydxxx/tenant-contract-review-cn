#!/usr/bin/env python3
"""Fail closed when the files selected for public release contain obvious leakage."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_SUFFIXES = {".json", ".yaml", ".yml", ".txt", ".md"}
FORBIDDEN_PATH_PARTS = {"work", "tmp", "temp", "outputs", "host-logs", "session-logs"}
FORBIDDEN_FILENAMES = {".env", "id_rsa", "id_ed25519"}
SECRET_PATTERNS = (
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("OpenAI-style key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Bearer token", re.compile(r"(?i)\bbearer[ \t]+[A-Za-z0-9._~+/-]{20,}\b")),
    (
        "assigned secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|token|password)[ \t]*[:=][ \t]*[\"']?[A-Za-z0-9._~+/-]{16,}"
        ),
    ),
)
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9_])/(?:Users|home|private|var/folders|tmp)/[^\s'\"`]+"),
    re.compile(r"\b[A-Za-z]:\\(?:Users|Documents and Settings|Temp|tmp)\\[^\s'\"`]+"),
)
CHINA_ID_PATTERN = re.compile(
    r"(?<!\d)[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?![\dXx])"
)


def _git_public_files(repository_root: Path) -> list[Path] | None:
    if not (repository_root / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(repository_root), "ls-files", "-z"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return [repository_root / item for item in result.stdout.decode("utf-8", errors="replace").split("\0") if item]


def public_files(repository_root: Path) -> list[Path]:
    """Return Git's public manifest, or a deterministic tree for isolated tests."""
    tracked = _git_public_files(repository_root)
    if tracked is not None:
        return sorted(tracked)
    ignored_parts = {".git", "__pycache__", ".pytest_cache"}
    return sorted(
        path
        for path in repository_root.rglob("*")
        if path.is_file() and not any(part in ignored_parts for part in path.relative_to(repository_root).parts)
    )


def _relative_path(repository_root: Path, path: Path) -> str:
    try:
        return path.relative_to(repository_root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_fixture(relative_path: Path) -> bool:
    return len(relative_path.parts) >= 2 and relative_path.parts[:2] == ("tests", "fixtures") and relative_path.suffix in FIXTURE_SUFFIXES


def _contains_synthetic_marker(content: str) -> bool:
    return bool(re.search(r'(?im)(?:["\']synthetic["\']\s*:\s*true\b|^\s*synthetic\s*:\s*true\b)', content))


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def validate_publication(repository_root: Path = REPOSITORY_ROOT) -> list[str]:
    """Return sorted, actionable public-release errors; never claim a clean tree is sufficient."""
    errors: list[str] = []
    for path in public_files(repository_root):
        relative_path = Path(_relative_path(repository_root, path))
        display_path = relative_path.as_posix()
        lowered_parts = {part.lower() for part in relative_path.parts}
        if lowered_parts & FORBIDDEN_PATH_PARTS:
            errors.append(f"{display_path}: forbidden work, temporary, output, or host-log artifact")
        if relative_path.name.lower() in FORBIDDEN_FILENAMES or relative_path.suffix.lower() in {".log", ".sqlite", ".sqlite3"}:
            errors.append(f"{display_path}: forbidden secret, log, or local-state artifact")
        content = _read_text(path)
        if content is None:
            errors.append(f"{display_path}: non-text file cannot be reviewed for public release")
            continue
        if _is_fixture(relative_path) and not _contains_synthetic_marker(content):
            errors.append(f"{display_path}: fixture lacks explicit synthetic: true marker")
        if any(pattern.search(content) for pattern in ABSOLUTE_PATH_PATTERNS):
            errors.append(f"{display_path}: contains a local absolute path")
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                errors.append(f"{display_path}: contains {label}")
        if CHINA_ID_PATTERN.search(content):
            errors.append(f"{display_path}: contains an apparent mainland China identity number")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan the public Git manifest for common privacy and secret leaks.")
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT, help="repository root (for isolated validation tests)")
    args = parser.parse_args()
    errors = validate_publication(args.root.resolve())
    if errors:
        print("Publication safety validation failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Publication safety validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
