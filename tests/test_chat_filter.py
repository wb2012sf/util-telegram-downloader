"""Unit tests for chat_filter.py. No network access, no real telethon dialogs."""

from __future__ import annotations

from types import SimpleNamespace

from chat_filter import (
    ChatSummary,
    chat_summary_from_dialog,
    chat_type_from_dialog,
    filter_chats,
    matches,
)


def _fake_dialog(*, is_user: bool, is_group: bool, is_channel: bool, participants_count: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        name="Some Chat",
        is_user=is_user,
        is_group=is_group,
        is_channel=is_channel,
        entity=SimpleNamespace(participants_count=participants_count),
    )


# --- chat_type_from_dialog / chat_summary_from_dialog --------------------------


def test_chat_type_from_dialog_user() -> None:
    dialog = _fake_dialog(is_user=True, is_group=False, is_channel=False)
    assert chat_type_from_dialog(dialog) == "user"


def test_chat_type_from_dialog_channel() -> None:
    dialog = _fake_dialog(is_user=False, is_group=False, is_channel=True)
    assert chat_type_from_dialog(dialog) == "channel"


def test_chat_type_from_dialog_group() -> None:
    dialog = _fake_dialog(is_user=False, is_group=True, is_channel=False)
    assert chat_type_from_dialog(dialog) == "group"


def test_chat_summary_from_dialog_builds_expected_fields() -> None:
    dialog = _fake_dialog(is_user=False, is_channel=True, is_group=False, participants_count=250)
    summary = chat_summary_from_dialog(dialog)

    assert summary == ChatSummary(id=42, name="Some Chat", type="channel", participant_count=250)


def test_chat_summary_from_dialog_handles_missing_name() -> None:
    dialog = _fake_dialog(is_user=True, is_group=False, is_channel=False)
    dialog.name = None

    summary = chat_summary_from_dialog(dialog)

    assert summary.name == ""


# --- matches ---------------------------------------------------------------


CHAT = ChatSummary(id=-4012345678, name="Acme Corp - Project Team", type="group", participant_count=12)


def test_matches_empty_query_matches_everything() -> None:
    assert matches(CHAT, "") is True
    assert matches(CHAT, "   ") is True


def test_matches_name_substring_case_insensitive() -> None:
    assert matches(CHAT, "acme") is True
    assert matches(CHAT, "TEAM") is True


def test_matches_name_no_match() -> None:
    assert matches(CHAT, "totally unrelated") is False


def test_matches_chat_id_substring() -> None:
    assert matches(CHAT, "4012345678") is True
    assert matches(CHAT, "-4012345678") is True
    assert matches(CHAT, "12345") is True


def test_matches_chat_id_no_match() -> None:
    assert matches(CHAT, "99999") is False


def test_matches_participant_name() -> None:
    participants = ("Jane Doe", "@johnsmith")
    assert matches(CHAT, "jane", participants) is True
    assert matches(CHAT, "johnsmith", participants) is True


def test_matches_participant_no_match_when_not_provided() -> None:
    assert matches(CHAT, "jane") is False


# --- filter_chats ------------------------------------------------------------


CHATS = [
    ChatSummary(id=1, name="Alice", type="user"),
    ChatSummary(id=2, name="Bob's Group", type="group", participant_count=5),
    ChatSummary(id=3, name="News Channel", type="channel", participant_count=10000),
]


def test_filter_chats_empty_query_returns_all_in_order() -> None:
    assert filter_chats(CHATS, "") == CHATS


def test_filter_chats_by_name() -> None:
    assert filter_chats(CHATS, "group") == [CHATS[1]]


def test_filter_chats_by_id() -> None:
    assert filter_chats(CHATS, "3") == [CHATS[2]]


def test_filter_chats_no_matches() -> None:
    assert filter_chats(CHATS, "nonexistent") == []


def test_filter_chats_uses_participant_cache() -> None:
    cache = {2: ("Bob Builder",)}
    assert filter_chats(CHATS, "builder", cache) == [CHATS[1]]


def test_filter_chats_participant_cache_only_applies_to_its_own_chat() -> None:
    cache = {2: ("Bob Builder",)}
    assert filter_chats(CHATS, "builder", cache) == [CHATS[1]]


def test_filter_chats_exclude_empty_names() -> None:
    chats_with_blank = CHATS + [ChatSummary(id=4, name="", type="user"), ChatSummary(id=5, name="   ", type="user")]
    assert filter_chats(chats_with_blank, "", exclude_empty_names=True) == CHATS


def test_filter_chats_exclude_empty_names_combines_with_query() -> None:
    chats_with_blank = CHATS + [ChatSummary(id=4, name="", type="user")]
    assert filter_chats(chats_with_blank, "group", exclude_empty_names=True) == [CHATS[1]]


def test_filter_chats_exclude_empty_names_defaults_to_off() -> None:
    blank = ChatSummary(id=4, name="", type="user")
    assert filter_chats([blank], "") == [blank]
