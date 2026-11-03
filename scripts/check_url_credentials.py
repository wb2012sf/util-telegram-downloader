"""
scripts/check_url_credentials.py

Pre-commit hook: block committing a URL with embedded basic-auth
credentials (<scheme>://<user>:<password>@<host>), e.g. a --index-url line
with a token baked in.

This exists as a companion to detect-secrets, not a replacement for it:
detect-secrets' own BasicAuthDetector plugin misses this exact shape when
the "user" portion itself contains an "@" (e.g. an email address used as a
username -- some.name@example.com:TOKEN@host, three "@"/"."-laden parts
before the real host) -- its regex treats the first "@" as the user/host
separator and never finds the real one. That's a common shape for
private package-index credentials in requirements.txt, hence a dedicated
check for it rather than trusting entropy/keyword heuristics to catch it
another way.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_URL_CREDENTIAL_RE = re.compile(r"""[a-zA-Z][a-zA-Z0-9+.-]*://[^\s'"]+:[^\s'"@]+@""")

_ALLOWLIST_MARKER = "pragma: allowlist secret"


def find_url_credentials(text: str) -> list[tuple[int, str]]:
    """Return (line_number, line_text) for each line with an embedded URL credential."""
    assert isinstance(text, str), "text must be a string"

    hits: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if _ALLOWLIST_MARKER in line:
            continue
        if _URL_CREDENTIAL_RE.search(line):
            hits.append((line_number, line))
    return hits


def main(argv: list[str]) -> int:
    # Windows tools (Windows PowerShell's `-Encoding utf8`, Notepad's
    # default "UTF-8" save, etc.) commonly write a leading BOM that plain
    # "utf-8" decoding leaves as a literal ﻿ character in the text --
    # "utf-8-sig" strips it if present, and behaves identically to "utf-8"
    # otherwise. And some Windows consoles print through a legacy codepage
    # (e.g. cp1252) that can't represent every Unicode character at all;
    # reconfiguring stdout to UTF-8 with a lossy fallback means a stray
    # character in a bad URL gets shown as best-effort text instead of
    # crashing this hook outright.
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    had_hits = False
    for path_str in argv:
        path = Path(path_str)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable file -- not a text credential leak

        for line_number, line in find_url_credentials(text):
            had_hits = True
            print(f"{path}:{line_number}: URL with embedded credentials: {line.strip()}")

    if had_hits:
        print(
            "\nRemove the embedded credential (use an environment variable or a "
            "pip.conf/.netrc instead), or if this is a false positive, add "
            f"'# {_ALLOWLIST_MARKER}' at the end of the line."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
