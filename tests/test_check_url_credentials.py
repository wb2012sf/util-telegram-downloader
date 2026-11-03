"""Unit tests for scripts/check_url_credentials.py."""

from __future__ import annotations

from scripts.check_url_credentials import find_url_credentials, main


def test_finds_simple_basic_auth_url() -> None:
    text = "--index-url https://user:token@example.com/simple"  # pragma: allowlist secret
    hits = find_url_credentials(text)
    assert len(hits) == 1
    assert hits[0][0] == 1


def test_finds_email_as_username_url() -> None:
    """An email-like username (itself containing "@") followed by a token
    before the host -- the shape detect-secrets misses."""
    text = "--index-url https://jane.doe@example.com:TOKEN@artifactory.example.com/simple"  # pragma: allowlist secret
    hits = find_url_credentials(text)
    assert len(hits) == 1


def test_ignores_plain_urls() -> None:
    assert find_url_credentials("See https://my.telegram.org for details.") == []
    assert find_url_credentials("https://example.com/path?query=1") == []


def test_ignores_lines_marked_as_allowlisted() -> None:
    text = "fake = 'https://user:token@example.com/'  # pragma: allowlist secret"
    assert find_url_credentials(text) == []


def test_reports_correct_line_number() -> None:
    text = "line one\nline two\nhttps://user:token@example.com/\nline four"  # pragma: allowlist secret
    hits = find_url_credentials(text)
    assert hits == [(3, "https://user:token@example.com/")]  # pragma: allowlist secret


def test_main_returns_nonzero_when_credentials_found(tmp_path) -> None:
    bad_file = tmp_path / "bad.txt"
    bad_file.write_text("--index-url https://user:token@example.com/simple")  # pragma: allowlist secret
    assert main([str(bad_file)]) == 1


def test_main_returns_zero_when_clean(tmp_path) -> None:
    clean_file = tmp_path / "clean.txt"
    clean_file.write_text("nothing to see here")
    assert main([str(clean_file)]) == 0


def test_main_skips_binary_files_without_crashing(tmp_path) -> None:
    binary_file = tmp_path / "binary.bin"
    binary_file.write_bytes(b"\xff\xfe\x00\x01not-utf8\x80")
    assert main([str(binary_file)]) == 0


def test_main_handles_utf8_bom_without_crashing(tmp_path) -> None:
    """Windows tools (Windows PowerShell's `-Encoding utf8`, Notepad's
    default "UTF-8" save, etc.) commonly write a leading BOM. Plain "utf-8"
    decoding leaves that BOM as a literal character in the text, which then
    crashed printing on a Windows console using a legacy codepage that
    can't represent it -- reproduced exactly by a user hitting this."""
    bom_file = tmp_path / "bom.txt"
    bom_file.write_bytes(
        b"\xef\xbb\xbf" + b"--index-url https://user:token@example.com/simple"  # pragma: allowlist secret
    )
    assert main([str(bom_file)]) == 1


def test_main_does_not_flag_bom_itself_as_part_of_a_credential(tmp_path) -> None:
    bom_file = tmp_path / "bom_clean.txt"
    bom_file.write_bytes(b"\xef\xbb\xbf" + b"nothing to see here")
    assert main([str(bom_file)]) == 0
