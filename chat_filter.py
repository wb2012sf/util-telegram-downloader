"""
chat_filter.py

Filter/search over the list of Telegram chats shown in the GUI's chat
selection table.

ChatSummary is a lightweight, Telethon-independent representation of one
dialog, built from a real telethon.tl.custom.dialog.Dialog by
chat_summary_from_dialog(). Keeping the filtering logic decoupled from
Telethon's own types means matches()/filter_chats() need no network access
and no real client to unit test.

Participant names are deliberately not fetched here. Pulling every member
of every chat up front is slow and rate-limited, so the GUI is expected to
fetch participants lazily (only for chats the user has expanded or
searched) and cache them for the session, then pass the current cache in
via `participants_by_chat_id` on each filter call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ChatType = Literal["user", "group", "channel"]


@dataclass(frozen=True)
class ChatSummary:
    id: int
    name: str
    type: ChatType
    participant_count: int | None = None


def chat_type_from_dialog(dialog: Any) -> ChatType:
    """Classify a telethon Dialog as "user", "group", or "channel"."""
    if dialog.is_user:
        return "user"
    if dialog.is_channel:
        return "channel"
    assert dialog.is_group, "dialog is neither a user, a channel, nor a group"
    return "group"


def chat_summary_from_dialog(dialog: Any) -> ChatSummary:
    """Build a ChatSummary from a real telethon Dialog (as yielded by client.iter_dialogs())."""
    return ChatSummary(
        id=dialog.id,
        name=dialog.name or "",
        type=chat_type_from_dialog(dialog),
        participant_count=getattr(dialog.entity, "participants_count", None),
    )


def matches(chat: ChatSummary, query: str, participants: tuple[str, ...] = ()) -> bool:
    """Whether `chat` matches a single search query.

    Case-insensitive substring match against the chat name, the chat ID
    (as a decimal string), and any known participant display names/usernames
    passed in via `participants` (empty if this chat's members haven't been
    fetched yet).
    """
    assert isinstance(chat, ChatSummary), "chat must be a ChatSummary"
    assert isinstance(query, str), "query must be a string"

    needle = query.strip().lower()
    if not needle:
        return True

    if needle in chat.name.lower():
        return True

    if needle in str(chat.id):
        return True

    return any(needle in participant.lower() for participant in participants)


def filter_chats(
    chats: list[ChatSummary],
    query: str,
    participants_by_chat_id: dict[int, tuple[str, ...]] | None = None,
    exclude_empty_names: bool = False,
) -> list[ChatSummary]:
    """Return the subset of `chats` matching `query`, preserving order.

    `participants_by_chat_id` is the GUI's session-level participant cache
    (chat id -> known member display names/usernames); chats missing from
    it are matched on name/ID only. `exclude_empty_names` additionally
    drops chats with a blank/whitespace-only name, regardless of `query`.
    """
    assert isinstance(chats, list), "chats must be a list"
    assert isinstance(query, str), "query must be a string"

    cache = participants_by_chat_id or {}
    return [
        chat
        for chat in chats
        if (not exclude_empty_names or chat.name.strip()) and matches(chat, query, cache.get(chat.id, ()))
    ]
