"""Guards the public repository against leaking private information.

This repository is public. AGENTS.md ("Public repository") lists what must
never be committed; these tests catch the parts a pattern can catch:
real-looking IDs and tokens, local machine paths, references to the private
server codebase, and notebook outputs. They scan every file git tracks or
would track, so a leak fails the suite before it is committed.

Customer and project names cannot be listed here without leaking them, so
those stay a review rule in AGENTS.md.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

FORBIDDEN = {
    "real-looking SweatStack ID (ULID); use an obvious fake like app_123": re.compile(
        r"\b01[0-9A-HJKMNP-TV-Z]{24}\b"
    ),
    "JWT; use an obvious fake like 'access_token_value'": re.compile(
        r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}"
    ),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    "local machine path": re.compile(r"/Users/[a-z]|/home/[a-z]"),
    "private server reference; describe the public contract instead": re.compile(
        r"[Ss]erver plans? \d{3}|\bapp/(routers|logic)/|\.\./sweatstack/"
    ),
}

SKIPPED_SUFFIXES = {".lock", ".png", ".jpg", ".ico", ".whl", ".gz"}


def _repo_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    paths = (REPO / line for line in out.splitlines())
    return [p for p in paths if p.is_file() and p.suffix not in SKIPPED_SUFFIXES]


def test_no_private_information_in_tracked_files():
    hits = []
    for path in _repo_files():
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for reason, pattern in FORBIDDEN.items():
                if pattern.search(line):
                    hits.append(f"{path.relative_to(REPO)}:{lineno}: {reason}")
    assert not hits, "\n".join(hits)


def test_notebooks_have_no_outputs():
    # Outputs carry whatever data the author ran against: their own
    # activities, user names, IDs. Commit notebooks cleared.
    dirty = []
    for path in _repo_files():
        if path.suffix != ".ipynb":
            continue
        cells = json.loads(path.read_text())["cells"]
        if any(cell.get("outputs") for cell in cells):
            dirty.append(str(path.relative_to(REPO)))
    assert not dirty, f"clear outputs before committing: {dirty}"
