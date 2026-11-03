"""Unit tests for credentials.py.

No network access and no real Telegram/keyring backend needed: the keyring
path is exercised against a small in-memory fake, the config-file fallback
is redirected into pytest's tmp_path, and test_connection is exercised
against a fake TelegramClient that only implements the async methods it
actually calls.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

import credentials
from credentials import (
    Credentials,
    CredentialsError,
    validate_api_hash,
    validate_api_id,
    validate_credentials,
    validate_phone,
)
from credentials import test_connection as run_connection_test
from telethon.errors import SessionPasswordNeededError


# --- validate_api_id -------------------------------------------------------


def test_validate_api_id_accepts_positive_integer() -> None:
    assert validate_api_id("123456") == 123456


def test_validate_api_id_strips_whitespace() -> None:
    assert validate_api_id("  123456  ") == 123456


@pytest.mark.parametrize("raw", ["", "abc", "-5", "0", "12.5", "1 2 3"])
def test_validate_api_id_rejects_non_positive_integers(raw: str) -> None:
    with pytest.raises(CredentialsError):
        validate_api_id(raw)


# --- validate_api_hash -------------------------------------------------------


def test_validate_api_hash_accepts_32_char_hex() -> None:
    assert validate_api_hash("a" * 32) == "a" * 32


def test_validate_api_hash_lowercases_and_strips() -> None:
    assert validate_api_hash("  " + "A" * 32 + "  ") == "a" * 32


@pytest.mark.parametrize("raw", ["", "a" * 31, "a" * 33, "g" * 32, "not-hex-at-all"])
def test_validate_api_hash_rejects_bad_format(raw: str) -> None:
    with pytest.raises(CredentialsError):
        validate_api_hash(raw)


# --- validate_phone ----------------------------------------------------------


@pytest.mark.parametrize("raw", ["+15551234567", "15551234567", "+41 79 123 45 67"])
def test_validate_phone_accepts_reasonable_numbers(raw: str) -> None:
    assert validate_phone(raw) == raw.strip()


@pytest.mark.parametrize("raw", ["", "abc", "123"])
def test_validate_phone_rejects_bad_format(raw: str) -> None:
    with pytest.raises(CredentialsError):
        validate_phone(raw)


# --- validate_credentials -----------------------------------------------------


def test_validate_credentials_builds_credentials_object() -> None:
    creds = validate_credentials("123456", "a" * 32, "+15551234567")
    assert creds == Credentials(api_id=123456, api_hash="a" * 32, phone="+15551234567")


def test_validate_credentials_raises_on_first_invalid_field() -> None:
    with pytest.raises(CredentialsError):
        validate_credentials("not-a-number", "a" * 32, "+15551234567")


# --- storage: config-file fallback (keyring unavailable) ----------------------


@pytest.fixture()
def config_file_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Force the no-keyring fallback and redirect it into tmp_path."""
    config_dir = tmp_path / "telegram_downloader"
    config_file = config_dir / "credentials.json"
    monkeypatch.setattr(credentials, "_KEYRING_AVAILABLE", False)
    monkeypatch.setattr(credentials, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(credentials, "CONFIG_FILE", config_file)
    return config_file


def test_load_credentials_returns_none_when_nothing_saved(config_file_backend: Path) -> None:
    assert credentials.load_credentials() is None


def test_save_and_load_credentials_round_trip_via_config_file(config_file_backend: Path) -> None:
    creds = Credentials(api_id=123456, api_hash="a" * 32, phone="+15551234567")
    credentials.save_credentials(creds)

    assert config_file_backend.exists()
    loaded = credentials.load_credentials()
    assert loaded == creds


def test_delete_credentials_removes_config_file(config_file_backend: Path) -> None:
    creds = Credentials(api_id=123456, api_hash="a" * 32, phone="+15551234567")
    credentials.save_credentials(creds)
    credentials.delete_credentials()

    assert not config_file_backend.exists()
    assert credentials.load_credentials() is None


# --- storage: keyring backend ------------------------------------------------


class FakeKeyringError(Exception):
    pass


class FakeNoKeyringError(FakeKeyringError):
    pass


class FakePasswordDeleteError(FakeKeyringError):
    pass


class FakeKeyring:
    """Minimal in-memory stand-in for the `keyring` module's public surface.

    With `unavailable=True`, every call raises NoKeyringError, mirroring a
    real machine with the keyring package installed but no usable OS
    backend (e.g. headless Linux with no secret service running).
    """

    def __init__(self, *, unavailable: bool = False) -> None:
        self._store: dict[tuple[str, str], str] = {}
        self._unavailable = unavailable
        self.errors = type(
            "errors",
            (),
            {
                "KeyringError": FakeKeyringError,
                "NoKeyringError": FakeNoKeyringError,
                "PasswordDeleteError": FakePasswordDeleteError,
            },
        )

    def set_password(self, service: str, key: str, value: str) -> None:
        if self._unavailable:
            raise self.errors.NoKeyringError("no backend available")
        self._store[(service, key)] = value

    def get_password(self, service: str, key: str) -> str | None:
        if self._unavailable:
            raise self.errors.NoKeyringError("no backend available")
        return self._store.get((service, key))

    def delete_password(self, service: str, key: str) -> None:
        if self._unavailable:
            raise self.errors.NoKeyringError("no backend available")
        try:
            del self._store[(service, key)]
        except KeyError:
            raise self.errors.PasswordDeleteError("not found") from None


@pytest.fixture()
def keyring_backend(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    fake = FakeKeyring()
    monkeypatch.setattr(credentials, "_KEYRING_AVAILABLE", True)
    monkeypatch.setattr(credentials, "keyring", fake)
    return fake


@pytest.fixture()
def unavailable_keyring_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A keyring backend that's importable but has no usable OS credential store."""
    config_dir = tmp_path / "telegram_downloader"
    config_file = config_dir / "credentials.json"
    monkeypatch.setattr(credentials, "_KEYRING_AVAILABLE", True)
    monkeypatch.setattr(credentials, "keyring", FakeKeyring(unavailable=True))
    monkeypatch.setattr(credentials, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(credentials, "CONFIG_FILE", config_file)
    return config_file


def test_save_and_load_credentials_round_trip_via_keyring(keyring_backend: FakeKeyring) -> None:
    creds = Credentials(api_id=123456, api_hash="a" * 32, phone="+15551234567")
    credentials.save_credentials(creds)

    loaded = credentials.load_credentials()
    assert loaded == creds


def test_save_and_load_falls_back_to_config_file_when_keyring_has_no_backend(
    unavailable_keyring_backend: Path,
) -> None:
    """keyring being importable doesn't mean a backend is running (e.g. headless Linux).

    save_credentials/load_credentials must catch that failure and fall back
    to the config file rather than raising keyring.errors.NoKeyringError.
    """
    creds = Credentials(api_id=123456, api_hash="a" * 32, phone="+15551234567")
    credentials.save_credentials(creds)

    assert unavailable_keyring_backend.exists()
    assert credentials.load_credentials() == creds


def test_delete_credentials_clears_keyring_entries(keyring_backend: FakeKeyring) -> None:
    creds = Credentials(api_id=123456, api_hash="a" * 32, phone="+15551234567")
    credentials.save_credentials(creds)
    credentials.delete_credentials()

    assert credentials.load_credentials() is None


# --- test_connection -----------------------------------------------------------


class FakeTelegramClient:
    """Implements just enough of TelegramClientLike to drive test_connection."""

    def __init__(
        self,
        *,
        already_authorized: bool,
        needs_password: bool = False,
        expected_code: str = "12345",
        expected_password: str = "hunter2",
        me_name: str = "Jane",
    ) -> None:
        self.already_authorized = already_authorized
        self.needs_password = needs_password
        self.expected_code = expected_code
        self.expected_password = expected_password
        self.me_name = me_name
        self.calls: list[str] = []
        self._password_attempted = False

    async def connect(self) -> None:
        self.calls.append("connect")

    async def is_user_authorized(self) -> bool:
        self.calls.append("is_user_authorized")
        return self.already_authorized

    async def send_code_request(self, phone: str) -> Any:
        self.calls.append("send_code_request")

    async def sign_in(
        self,
        phone: str | None = None,
        code: str | None = None,
        *,
        password: str | None = None,
    ) -> Any:
        self.calls.append("sign_in")
        if password is not None:
            if password != self.expected_password:
                raise ValueError("wrong password")
            return
        if self.needs_password and not self._password_attempted:
            self._password_attempted = True
            raise SessionPasswordNeededError(request=None)
        if code != self.expected_code:
            raise ValueError("wrong code")

    async def get_me(self) -> Any:
        self.calls.append("get_me")
        return type("Me", (), {"first_name": self.me_name, "username": None, "id": 1})()

    async def disconnect(self) -> None:
        self.calls.append("disconnect")


def test_connection_when_already_authorized_skips_login_flow() -> None:
    client = FakeTelegramClient(already_authorized=True)

    result = asyncio.run(
        run_connection_test(
            client, "+15551234567", request_code=_unused_requester, request_password=_unused_requester
        )
    )

    assert result == "Connected as Jane"
    assert "send_code_request" not in client.calls
    assert "sign_in" not in client.calls
    assert client.calls[0] == "connect"
    assert client.calls[-1] == "disconnect"


def test_connection_first_login_asks_for_code() -> None:
    client = FakeTelegramClient(already_authorized=False)

    result = asyncio.run(
        run_connection_test(
            client, "+15551234567", request_code=lambda: "12345", request_password=_unused_requester
        )
    )

    assert result == "Connected as Jane"
    assert client.calls == ["connect", "is_user_authorized", "send_code_request", "sign_in", "get_me", "disconnect"]


def test_connection_falls_back_to_2fa_password_when_required() -> None:
    client = FakeTelegramClient(already_authorized=False, needs_password=True)

    result = asyncio.run(
        run_connection_test(
            client, "+15551234567", request_code=lambda: "12345", request_password=lambda: "hunter2"
        )
    )

    assert result == "Connected as Jane"
    assert client.calls.count("sign_in") == 2
    assert client.calls[-1] == "disconnect"


def test_connection_disconnects_even_when_login_fails() -> None:
    client = FakeTelegramClient(already_authorized=False)

    with pytest.raises(ValueError):
        asyncio.run(
            run_connection_test(
                client, "+15551234567", request_code=lambda: "wrong-code", request_password=_unused_requester
            )
        )

    assert client.calls[-1] == "disconnect"


def _unused_requester() -> str:
    raise AssertionError("this requester should not have been called")
