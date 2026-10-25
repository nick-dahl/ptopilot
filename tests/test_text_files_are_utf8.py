"""Fixtures and packaged data must be UTF-8 so tests read the same on Windows and Linux."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIRS = [ROOT / "tests" / "sources" / "fixtures", ROOT / "ptopilot" / "data"]
FILES = sorted(
    p
    for d in DIRS
    for p in d.rglob("*")
    if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
)


def test_there_are_files_to_check():
    assert FILES


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_file_decodes_as_utf8(path):
    path.read_bytes().decode("utf-8")
