"""
telegram_export.py

Export the full message history of a single Telegram chat/group to JSON
(and optionally a minimal HTML rendering) using Telethon (MTProto API) —
i.e. logged in as your own user account, not a bot, so it can read the
same history you can see in the app.

Setup
-----
1. Get free API credentials (one-time) from https://my.telegram.org
   -> "API development tools" -> create an app -> note the api_id (int)
   and api_hash (str).
2. python -m venv .venv && source .venv/bin/activate   (Windows: .venv\\Scripts\\activate)
3. pip install -r requirements.txt
4. Create a .env file (see .env_example) in this directory:
       TELEGRAM_API_ID=123456
       TELEGRAM_API_HASH=your_api_hash_here
   Never commit .env -- add it to .gitignore. .env_example (dummy values)
   is the one safe to commit, so others know which variables are required.
5. python telegram_export.py --chat "my_group_username_or_invite_or_id" --html

   On first run you'll be prompted for your phone number, then the login
   code Telegram sends you (and your 2FA password if enabled). This
   creates a local *.session file so you won't be prompted again.
   Treat that session file like a password — anyone with it can act as you.

   --api-id/--api-hash can still be passed on the command line if you want
   to override the .env values for a one-off run.

Output
------
Writes <chat>.json (list of message records) into --out-dir, and
<chat>.html as well if --html is passed.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.types import Message, MessageEmpty, MessageService


@dataclass
class ExportedMessage:
    id: int
    date: str
    sender_id: int | None
    text: str
    reply_to_msg_id: int | None
    has_media: bool
    message_type: str  # "message", "service" (join/leave/pin/etc.), or "empty" (deleted)
    sender_name: str | None = None  # filled in from the chat's participant list, if resolvable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a Telegram chat's history.")
    parser.add_argument("--chat", required=True, help="Chat username, invite link, or numeric ID")
    parser.add_argument(
        "--api-id", type=int, default=None,
        help="Overrides TELEGRAM_API_ID from .env, if given",
    )
    parser.add_argument(
        "--api-hash", type=str, default=None,
        help="Overrides TELEGRAM_API_HASH from .env, if given",
    )
    parser.add_argument("--session", default="telegram_export", help="Session file name/path (no extension)")
    parser.add_argument("--out-dir", default="export", help="Output directory")
    parser.add_argument("--html", action="store_true", help="Also write a minimal HTML rendering")
    parser.add_argument("--limit", type=int, default=None, help="Max number of messages (default: all)")
    return parser.parse_args()


def load_credentials(cli_api_id: int | None, cli_api_hash: str | None) -> tuple[int, str]:
    """Resolve api_id/api_hash.

    CLI arguments take precedence if given; otherwise these are read from a
    .env file (TELEGRAM_API_ID / TELEGRAM_API_HASH) in the current working
    directory. load_dotenv() is a no-op if no .env file is present, and by
    default won't override variables already set in the real environment.
    """
    load_dotenv()

    raw_api_id = cli_api_id if cli_api_id is not None else os.environ.get("TELEGRAM_API_ID")
    api_hash = cli_api_hash if cli_api_hash is not None else os.environ.get("TELEGRAM_API_HASH")

    assert raw_api_id is not None, "api_id missing: pass --api-id or set TELEGRAM_API_ID in a .env file"
    assert api_hash, "api_hash missing: pass --api-hash or set TELEGRAM_API_HASH in a .env file"

    api_id = int(raw_api_id)
    assert api_id > 0, "TELEGRAM_API_ID must be a positive integer"

    return api_id, str(api_hash)


def message_to_record(message: Message | MessageService | MessageEmpty) -> ExportedMessage:
    """Convert any of Telegram's three message variants into a flat record.

    A chat's history isn't only regular text messages (Message) -- it also
    contains service events like joins/leaves/pins (MessageService) and
    placeholders for deleted messages that still occupy an ID (MessageEmpty).
    Handling only Message and asserting on the rest crashes on the first
    join/leave notice in any real group history.
    """
    assert hasattr(message, "id"), "Expected a Telegram message object with an id"

    if isinstance(message, MessageEmpty):
        return ExportedMessage(
            id=message.id,
            date="",
            sender_id=None,
            text="",
            reply_to_msg_id=None,
            has_media=False,
            message_type="empty",
        )

    text = getattr(message, "message", None) or ""
    if isinstance(message, MessageService) and not text:
        text = f"[service event: {type(message.action).__name__}]"

    return ExportedMessage(
        id=message.id,
        date=message.date.isoformat() if getattr(message, "date", None) else "",
        sender_id=getattr(message, "sender_id", None),
        text=text,
        reply_to_msg_id=getattr(message, "reply_to_msg_id", None),
        has_media=getattr(message, "media", None) is not None,
        message_type="service" if isinstance(message, MessageService) else "message",
    )


def write_json(records: list[ExportedMessage], out_path: Path) -> None:
    assert out_path.suffix == ".json", "out_path must end in .json"
    payload: list[dict[str, Any]] = [asdict(r) for r in records]
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_html(records: list[ExportedMessage], out_path: Path, chat_name: str) -> None:
    assert out_path.suffix == ".html", "out_path must end in .html"
    rows = "\n".join(
        f"<div class='msg'><span class='meta'>[{html.escape(r.date)}] "
        f"{html.escape(r.sender_name or 'Unknown')}"
        f"{f' ({r.sender_id})' if r.sender_id is not None else ''}"
        f"</span><p>{html.escape(r.text)}</p></div>"
        for r in records
    )
    document = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{html.escape(chat_name)} export</title>
<style>
  body {{ font-family: sans-serif; max-width: 700px; margin: 2rem auto; }}
  .msg {{ border-bottom: 1px solid #eee; padding: 0.5rem 0; }}
  .meta {{ color: #888; font-size: 0.8rem; }}
</style></head>
<body><h1>{html.escape(chat_name)}</h1>{rows}</body></html>"""
    out_path.write_text(document, encoding="utf-8")


_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(name: str) -> str:
    """Make `name` safe to use as a file name on Windows/macOS/Linux alike.

    Chat titles are freeform user text and can contain characters that are
    illegal in a Windows file name (: " / \\ | ? * and control characters);
    usernames and numeric IDs are already safe but pass through unharmed.
    """
    assert isinstance(name, str), "name must be a string"
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", name).strip().rstrip(".")
    return cleaned or "chat"


def normalize_chat_id(raw: str) -> int | None:
    """Convert a web.telegram.org-style chat ID into the plain positive ID
    Telethon entities expose as `.id`, or return None if `raw` isn't numeric
    at all (e.g. a username or a chat title like "Acme Corp - Project Team").

    web.telegram.org shows "-100<channel_id>" for supergroups/channels and
    plain "-<chat_id>" for basic (non-super) groups.
    """
    s = raw.strip()
    if not s.lstrip("-").isdigit():
        return None
    if s.startswith("-100"):
        return int(s[4:])
    if s.startswith("-"):
        return int(s[1:])
    return int(s)


async def build_sender_names(client: TelegramClient, entity: Any) -> dict[int, str]:
    """Map each current member's user ID to a human-readable display name.

    Uses the chat's participant list (fine for small groups; for large ones
    consider caching this, since it fetches the full member list up front).
    Members who left before this ran won't be in the list, so their messages
    will still show a bare ID -- Telegram doesn't expose a way around that
    for people no longer in the chat.
    """
    names: dict[int, str] = {}
    async for user in client.iter_participants(entity):
        display = " ".join(part for part in (user.first_name, user.last_name) if part)
        if not display:
            display = f"@{user.username}" if user.username else f"user_{user.id}"
        names[user.id] = display
    return names


async def resolve_chat(client: TelegramClient, chat: str) -> Any:
    """Resolve a chat given a username, invite link, numeric ID, or its display title.

    Telethon's get_entity() understands usernames/phone numbers/invite links,
    and *Python-int* numeric IDs already cached in this session -- but not a
    numeric-looking string, and not a chat's display title. If the direct
    lookup fails, fall back to scanning the dialog list and matching either
    the numeric ID or the title, so both `-4012345678` and
    `"Acme Corp - Project Team"` work as `--chat`.
    """
    assert chat, "chat must not be empty"

    numeric_id = normalize_chat_id(chat)
    try:
        return await client.get_entity(numeric_id if numeric_id is not None else chat)
    except ValueError:
        pass  # not resolvable directly -> fall back to scanning dialogs below

    needle = chat.strip().lower()
    id_matches = []
    title_exact = []
    title_partial: list[tuple[str, Any]] = []
    async for dialog in client.iter_dialogs():
        entity_id = getattr(dialog.entity, "id", None)
        if numeric_id is not None and entity_id == numeric_id:
            id_matches.append(dialog.entity)
            continue
        name = (dialog.name or "").strip()
        if not name:
            continue
        if name.lower() == needle:
            title_exact.append(dialog.entity)
        elif needle in name.lower():
            title_partial.append((name, dialog.entity))

    if len(id_matches) == 1:
        return id_matches[0]
    if len(title_exact) == 1:
        return title_exact[0]
    if len(title_exact) > 1 or (not title_exact and len(title_partial) > 1):
        candidates = title_exact or [entity for _, entity in title_partial]
        names = ", ".join(getattr(c, "title", str(getattr(c, "id", "?"))) for c in candidates)
        raise ValueError(f"Multiple chats match '{chat}': {names}. Use a more specific name or numeric ID.")
    if len(title_partial) == 1:
        return title_partial[0][1]

    raise ValueError(
        f"Cannot find any chat matching '{chat}' among your dialogs. "
        "Double-check the ID/title against web.telegram.org, and make sure "
        "this account is currently a member of that chat."
    )


async def export_chat(
    chat: str,
    api_id: int,
    api_hash: str,
    session: str,
    out_dir: Path,
    make_html: bool,
    limit: int | None,
    client: TelegramClient | None = None,
) -> None:
    """Export one chat's history.

    If `client` is given, it's used as-is (assumed already connected and
    authorized) and this function does not connect or disconnect it --
    callers exporting several chats in a row should share one client rather
    than reconnecting per chat, which is both slow and, against the same
    local session file, prone to a transient lock on the second connection.
    If `client` is omitted (the CLI's usage), a client is opened and closed
    for just this one call, as before.
    """
    assert api_id > 0, "api_id must be a positive integer"
    assert api_hash, "api_hash must not be empty"
    assert chat, "chat must not be empty"

    out_dir.mkdir(parents=True, exist_ok=True)

    if client is not None:
        await _export_chat_with_client(client, chat, out_dir, make_html, limit)
        return

    async with TelegramClient(session, api_id, api_hash) as owned_client:
        await _export_chat_with_client(owned_client, chat, out_dir, make_html, limit)


async def _export_chat_with_client(
    client: TelegramClient, chat: str, out_dir: Path, make_html: bool, limit: int | None
) -> None:
    entity = await resolve_chat(client, chat)
    sender_names = await build_sender_names(client, entity)

    records: list[ExportedMessage] = []
    async for message in client.iter_messages(entity, limit=limit):
        record = message_to_record(message)
        if record.sender_id is not None:
            record.sender_name = sender_names.get(record.sender_id, f"user_{record.sender_id}")
        records.append(record)

    records.reverse()  # Telethon yields newest-first; flip to chronological order

    # Basic (non-super) groups never have a username at all in Telegram's
    # data model, so without a title fallback these always landed on the
    # numeric ID.
    safe_name = safe_filename(str(getattr(entity, "username", None) or getattr(entity, "title", None) or getattr(entity, "id")))
    write_json(records, out_dir / f"{safe_name}.json")
    if make_html:
        title = getattr(entity, "title", safe_name)
        write_html(records, out_dir / f"{safe_name}.html", title)

    print(f"Exported {len(records)} messages to {out_dir}/")


def main() -> None:
    args = parse_args()
    api_id, api_hash = load_credentials(args.api_id, args.api_hash)
    asyncio.run(
        export_chat(
            chat=args.chat,
            api_id=api_id,
            api_hash=api_hash,
            session=args.session,
            out_dir=Path(args.out_dir),
            make_html=args.html,
            limit=args.limit,
        )
    )


if __name__ == "__main__":
    main()
