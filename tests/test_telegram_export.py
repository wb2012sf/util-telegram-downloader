"""Unit tests for telegram_export.export_chat's client-sharing behavior and
output file naming.

The GUI downloads several chats in a row by passing its own already-
connected client via the `client` parameter; export_chat must not
connect/disconnect that client itself. Everything else in telegram_export.py
is exercised via the CLI in normal use and isn't re-tested here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import telegram_export
from telegram_export import safe_filename


class FakeEntity:
    """A user/channel-like entity: has a username."""

    id = 999
    username = "fakeuser"
    title = "Fake Chat"


class FakeGroupEntity:
    """A basic-group-like entity: Telegram never gives these a username."""

    id = 555
    username = None
    title = "My Group Chat"


class FakeClient:
    def __init__(self, *_args, entity: object = None, **_kwargs) -> None:
        self.connect_calls = 0
        self.disconnect_calls = 0
        self.entity = entity if entity is not None else FakeEntity()

    async def connect(self) -> None:
        self.connect_calls += 1

    async def disconnect(self) -> None:
        self.disconnect_calls += 1

    async def __aenter__(self) -> "FakeClient":
        await self.connect()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.disconnect()

    async def get_entity(self, _value: object) -> object:
        return self.entity

    async def iter_participants(self, _entity: object):
        return
        yield  # pragma: no cover -- makes this an (empty) async generator

    def iter_messages(self, _entity: object, limit: int | None = None):
        async def _empty():
            return
            yield  # pragma: no cover

        return _empty()


@pytest.fixture()
def fake_client() -> FakeClient:
    return FakeClient()


async def _export(tmp_path: Path, **overrides: object) -> None:
    kwargs: dict[str, object] = dict(
        chat="999",
        api_id=1,
        api_hash="a" * 32,
        session="unused",
        out_dir=tmp_path,
        make_html=False,
        limit=None,
    )
    kwargs.update(overrides)
    await telegram_export.export_chat(**kwargs)  # type: ignore[arg-type]


def test_shared_client_is_not_connected_or_disconnected_by_export_chat(
    tmp_path: Path, fake_client: FakeClient
) -> None:
    asyncio.run(_export(tmp_path, client=fake_client))

    assert fake_client.connect_calls == 0
    assert fake_client.disconnect_calls == 0
    assert (tmp_path / "fakeuser.json").exists()


def test_no_client_given_opens_and_closes_its_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created: list[FakeClient] = []

    def fake_constructor(*args: object, **kwargs: object) -> FakeClient:
        client = FakeClient(*args, **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(telegram_export, "TelegramClient", fake_constructor)

    asyncio.run(_export(tmp_path))

    assert len(created) == 1
    assert created[0].connect_calls == 1
    assert created[0].disconnect_calls == 1
    assert (tmp_path / "fakeuser.json").exists()


# --- output file naming -------------------------------------------------------


def test_export_prefers_username_over_title(tmp_path: Path) -> None:
    client = FakeClient(entity=FakeEntity())
    asyncio.run(_export(tmp_path, client=client))
    assert (tmp_path / "fakeuser.json").exists()


def test_export_falls_back_to_title_when_no_username(tmp_path: Path) -> None:
    """Basic (non-super) groups never have a username in Telegram's data
    model -- without this fallback, every group download used its bare
    numeric ID as the file name instead of something recognizable."""
    client = FakeClient(entity=FakeGroupEntity())
    asyncio.run(_export(tmp_path, client=client))
    assert (tmp_path / "My Group Chat.json").exists()


def test_export_falls_back_to_id_when_neither_username_nor_title(tmp_path: Path) -> None:
    class BareEntity:
        id = 42
        username = None
        # no `title` attribute at all, unlike FakeGroupEntity

    client = FakeClient(entity=BareEntity())
    asyncio.run(_export(tmp_path, client=client))
    assert (tmp_path / "42.json").exists()


def test_export_sanitizes_unsafe_characters_in_title(tmp_path: Path) -> None:
    class UnsafeTitleEntity:
        id = 777
        username = None
        title = 'Group: "Weekend" Plans / 2026'

    client = FakeClient(entity=UnsafeTitleEntity())
    asyncio.run(_export(tmp_path, client=client))

    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert files[0].name == safe_filename(UnsafeTitleEntity.title) + ".json"
    # the raw title has characters that can't appear in a Windows file name
    assert "/" not in files[0].name and ":" not in files[0].name


# --- safe_filename -------------------------------------------------------------


def test_safe_filename_passes_through_plain_names() -> None:
    assert safe_filename("My Group Chat") == "My Group Chat"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('Weird: "Name" / Here', 'Weird_ _Name_ _ Here'),
        ("trailing dots...", "trailing dots"),
        ("", "chat"),
        ("   ", "chat"),
    ],
)
def test_safe_filename_handles_edge_cases(raw: str, expected: str) -> None:
    assert safe_filename(raw) == expected
