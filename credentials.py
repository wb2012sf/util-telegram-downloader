"""
credentials.py

Manage Telegram API credentials (api_id, api_hash, phone number) for the
GUI: format validation, persistent storage, and a connection test against
the real Telegram API.

Storage prefers the OS credential store via the `keyring` package. If no
keyring backend is available (e.g. a headless Linux box with no secret
service running), credentials fall back to a JSON file in the user's config
directory (~/.config/telegram_downloader/credentials.json), stored outside
this repository so it can never be committed by accident. That fallback
file is unencrypted -- anyone with read access to the account can read it.

This module is pure functions/classes with no GUI widget code, so it can be
unit tested with a mocked Telegram client (see tests/test_credentials.py).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

try:
    import keyring
    import keyring.errors

    _KEYRING_AVAILABLE = True
except ImportError:
    keyring = None  # type: ignore[assignment]
    _KEYRING_AVAILABLE = False


KEYRING_SERVICE = "telegram_downloader"
CONFIG_DIR = Path.home() / ".config" / "telegram_downloader"
CONFIG_FILE = CONFIG_DIR / "credentials.json"

_API_HASH_RE = re.compile(r"^[0-9a-f]{32}$")
_PHONE_RE = re.compile(r"^\+?[0-9][0-9 ()-]{5,}$")

MY_TELEGRAM_ORG_APPS_URL = "https://my.telegram.org/apps"

CREDENTIALS_HELP_TEXT = """\
1. Go to https://my.telegram.org and log in with your phone number.
2. Click "API development tools".
3. Fill in "App title" and "Short name" with any values; leave the rest as
   default.
4. Click "Create application".
5. Copy the "App api_id" and "App api_hash" values shown on that page.
"""


class CredentialsError(ValueError):
    """Raised when a user-supplied credential field fails validation."""


@dataclass(frozen=True)
class Credentials:
    api_id: int
    api_hash: str
    phone: str


def validate_api_id(raw: str) -> int:
    """Parse and validate an api_id string. Raises CredentialsError if invalid."""
    assert isinstance(raw, str), "raw must be a string"

    stripped = raw.strip()
    if not stripped.isdigit():
        raise CredentialsError("api_id must be a positive integer (see my.telegram.org)")

    value = int(stripped)
    if value <= 0:
        raise CredentialsError("api_id must be a positive integer (see my.telegram.org)")
    return value


def validate_api_hash(raw: str) -> str:
    """Validate an api_hash string. Raises CredentialsError if invalid."""
    assert isinstance(raw, str), "raw must be a string"

    stripped = raw.strip().lower()
    if not _API_HASH_RE.match(stripped):
        raise CredentialsError("api_hash must be a 32-character hex string (see my.telegram.org)")
    return stripped


def validate_phone(raw: str) -> str:
    """Validate a phone number string. Raises CredentialsError if invalid."""
    assert isinstance(raw, str), "raw must be a string"

    stripped = raw.strip()
    if not _PHONE_RE.match(stripped):
        raise CredentialsError("phone number looks invalid -- include the country code, e.g. +15551234567")
    return stripped


def validate_credentials(api_id_raw: str, api_hash_raw: str, phone_raw: str) -> Credentials:
    """Validate all three fields together. Raises CredentialsError on the first invalid one."""
    assert isinstance(api_id_raw, str), "api_id_raw must be a string"
    assert isinstance(api_hash_raw, str), "api_hash_raw must be a string"
    assert isinstance(phone_raw, str), "phone_raw must be a string"

    return Credentials(
        api_id=validate_api_id(api_id_raw),
        api_hash=validate_api_hash(api_hash_raw),
        phone=validate_phone(phone_raw),
    )


def save_credentials(creds: Credentials) -> None:
    """Persist credentials via keyring, or the gitignored fallback config file."""
    assert isinstance(creds, Credentials), "creds must be a Credentials instance"

    if _KEYRING_AVAILABLE:
        try:
            keyring.set_password(KEYRING_SERVICE, "api_id", str(creds.api_id))
            keyring.set_password(KEYRING_SERVICE, "api_hash", creds.api_hash)
            keyring.set_password(KEYRING_SERVICE, "phone", creds.phone)
            return
        except keyring.errors.KeyringError:
            pass  # no usable OS backend (e.g. headless Linux with no secret service) -- fall back

    _save_to_config_file(creds)


def load_credentials() -> Credentials | None:
    """Load previously saved credentials, or None if none are stored."""
    if _KEYRING_AVAILABLE:
        try:
            api_id = keyring.get_password(KEYRING_SERVICE, "api_id")
            api_hash = keyring.get_password(KEYRING_SERVICE, "api_hash")
            phone = keyring.get_password(KEYRING_SERVICE, "phone")
            if api_id and api_hash and phone:
                return Credentials(api_id=int(api_id), api_hash=api_hash, phone=phone)
            return None
        except keyring.errors.KeyringError:
            pass  # no usable OS backend -- fall back to the config file

    return _load_from_config_file()


def delete_credentials() -> None:
    """Remove any stored credentials."""
    if _KEYRING_AVAILABLE:
        try:
            for key in ("api_id", "api_hash", "phone"):
                try:
                    keyring.delete_password(KEYRING_SERVICE, key)
                except keyring.errors.PasswordDeleteError:
                    pass
            return
        except keyring.errors.KeyringError:
            pass  # no usable OS backend -- fall back to the config file

    if CONFIG_FILE.exists():
        CONFIG_FILE.unlink()


def _save_to_config_file(creds: Credentials) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps({"api_id": creds.api_id, "api_hash": creds.api_hash, "phone": creds.phone}),
        encoding="utf-8",
    )
    CONFIG_FILE.chmod(0o600)


def _load_from_config_file() -> Credentials | None:
    if not CONFIG_FILE.exists():
        return None

    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return Credentials(api_id=int(data["api_id"]), api_hash=data["api_hash"], phone=data["phone"])


class TelegramClientLike(Protocol):
    """The subset of TelegramClient's async interface test_connection needs.

    A real telethon.TelegramClient satisfies this structurally. Tests pass a
    lightweight fake instead, so test_connection needs no network access and
    no real Telegram credentials to verify.
    """

    async def connect(self) -> None: ...

    async def is_user_authorized(self) -> bool: ...

    async def send_code_request(self, phone: str) -> Any: ...

    async def sign_in(
        self,
        phone: str | None = None,
        code: str | None = None,
        *,
        password: str | None = None,
    ) -> Any: ...

    async def get_me(self) -> Any: ...

    async def disconnect(self) -> None: ...


CodeRequester = Callable[[], str]
PasswordRequester = Callable[[], str]


def create_client(creds: Credentials, session: str) -> TelegramClient:
    """Build a real telethon TelegramClient from validated credentials.

    Thin glue, not itself unit tested -- test_connection takes the client as
    a parameter precisely so it doesn't need this.
    """
    assert isinstance(creds, Credentials), "creds must be a Credentials instance"
    assert session, "session must not be empty"

    return TelegramClient(session, creds.api_id, creds.api_hash)


async def test_connection(
    client: TelegramClientLike,
    phone: str,
    request_code: CodeRequester,
    request_password: PasswordRequester,
) -> str:
    """Connect and (if needed) authorize `client`, then confirm who we're logged in as.

    request_code/request_password are called with no arguments to obtain the
    login code / 2FA password from the user when the session isn't already
    authorized. The GUI supplies dialog-box callbacks; tests supply plain
    functions returning fixed strings.

    Returns a short human-readable success message such as "Connected as
    Jane". Raises on failure (wrong credentials, wrong code, network error,
    etc.) -- the caller shows that error to the user.
    """
    assert phone, "phone must not be empty"

    await client.connect()
    try:
        if not await client.is_user_authorized():
            await client.send_code_request(phone)
            code = request_code()
            try:
                await client.sign_in(phone, code)
            except SessionPasswordNeededError:
                password = request_password()
                await client.sign_in(password=password)

        me = await client.get_me()
        name = getattr(me, "first_name", None) or getattr(me, "username", None) or str(getattr(me, "id", "?"))
        return f"Connected as {name}"
    finally:
        await client.disconnect()
