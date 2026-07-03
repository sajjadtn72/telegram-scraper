"""
Telegram channel scraper (Telethon).

Fetches all posts from one or more Telegram channels and saves them as JSON
and/or CSV. Supports incremental (resume) runs, optional media download, and
multiple channels in a single invocation.

Setup:
    python -m pip install -r requirements.txt
    edit .env                   # fill in API_ID / API_HASH / PHONE / CHANNELS

Usage:
    python scraper.py
    python scraper.py --channel mychannel --channel otherchannel
    python scraper.py --format csv --download-media --no-save-text
    python scraper.py --no-resume --limit 500
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import ChannelPrivateError, ChatAdminRequiredError, FloodWaitError
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.tl.types import (
    ChatInviteAlready,
    ChatInvitePeek,
    MessageMediaDocument,
    MessageMediaPhoto,
)

# Persian/emoji text crashes the default Windows console (cp1252); force UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

load_dotenv()


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def repair_dotenv_path(value: str) -> str:
    """Undo common escapes from double-quoted Windows paths in .env files."""
    replacements = {
        "\a": r"\a",
        "\b": r"\b",
        "\f": r"\f",
        "\n": r"\n",
        "\r": r"\r",
        "\t": r"\t",
        "\v": r"\v",
    }
    for escaped, literal in replacements.items():
        value = value.replace(escaped, literal)
    return value


def prompt_yes_no(question: str, *, default: bool) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        try:
            answer = input(question + suffix).strip().lower()
        except EOFError:
            return default
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def prompt_output_format(default: str = "json") -> str:
    choices = {"1": "json", "2": "csv", "3": "both",
               "json": "json", "csv": "csv", "both": "both"}
    while True:
        try:
            answer = input(
                f"Output format: 1) json  2) csv  3) both [{default}]: "
            ).strip().lower()
        except EOFError:
            return default
        if not answer:
            return default
        if answer in choices:
            return choices[answer]
        print("Please choose 1, 2, 3, json, csv, or both.")


def prompt_channels() -> list:
    while True:
        try:
            answer = input(
                "Channel/group username, link, invite link, or numeric id "
                "(comma-separated for multiple): "
            ).strip()
        except EOFError:
            return []
        channels = [c.strip() for c in answer.split(",") if c.strip()]
        if channels:
            return channels
        print("Please enter at least one channel or group.")


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class Post:
    id: int
    date: str               # ISO 8601, UTC
    text: str
    media_count: int
    sender_id: Optional[int] = None
    sender_name: str = ""
    sender_username: str = ""
    sender_type: str = ""
    media_files: list = field(default_factory=list)
    reactions: int = 0
    views: Optional[int] = None
    forwards: Optional[int] = None
    link: str = ""

    @property
    def sort_key(self):
        return self.id


CSV_FIELDS = ["id", "date", "sender_id", "sender_name", "sender_username",
              "sender_type", "text", "media_count", "media_files",
              "reactions", "views", "forwards", "link"]


# --------------------------------------------------------------------------- #
# Flood-wait safe request wrapper
# --------------------------------------------------------------------------- #

async def safe_call(coro_factory, *, retries: int = 5):
    for attempt in range(retries):
        try:
            return await coro_factory()
        except FloodWaitError as e:
            wait = e.seconds + 1
            log(f"  FloodWait: sleeping {wait}s (attempt {attempt + 1}/{retries})")
            await asyncio.sleep(wait)
    raise RuntimeError("Exceeded flood-wait retries")


# --------------------------------------------------------------------------- #
# Entity resolution
# --------------------------------------------------------------------------- #

async def resolve_entity(client: TelegramClient, value: str):
    value = value.strip()
    if not value:
        fail("Empty channel value.")

    if "t.me/+" in value or "joinchat" in value or value.startswith("+"):
        invite_hash = value.split("+")[-1].split("/")[-1]
        log(f"Resolving private invite (hash={invite_hash}) ...")
        invite = await safe_call(lambda: client(CheckChatInviteRequest(invite_hash)))
        if isinstance(invite, (ChatInviteAlready, ChatInvitePeek)):
            return await client.get_entity(invite.chat)
        fail(f"Not a member of the private channel behind {value!r} yet. "
             "Join it with this account first, then re-run.")

    if "t.me/" in value:
        value = value.rstrip("/").split("/")[-1]
    value = value.lstrip("@")

    try:
        return await client.get_entity(int(value))
    except ValueError:
        return await client.get_entity(value)


async def get_sender_info(msg) -> dict:
    sender_id = getattr(msg, "sender_id", None)
    sender_name = ""
    sender_username = ""
    sender_type = ""

    try:
        sender = await safe_call(lambda: msg.get_sender())
    except Exception:
        sender = None

    if sender:
        sender_id = sender_id or getattr(sender, "id", None)
        sender_username = getattr(sender, "username", None) or ""
        sender_type = type(sender).__name__

        first_name = getattr(sender, "first_name", None) or ""
        last_name = getattr(sender, "last_name", None) or ""
        full_name = " ".join(part for part in (first_name, last_name) if part)
        sender_name = (
            full_name
            or getattr(sender, "title", None)
            or getattr(sender, "name", None)
            or sender_username
            or ""
        )

    return {
        "sender_id": sender_id,
        "sender_name": sender_name,
        "sender_username": sender_username,
        "sender_type": sender_type,
    }


# --------------------------------------------------------------------------- #
# Scraping
# --------------------------------------------------------------------------- #

async def scrape_channel(client, entity, channel_label: str, *, min_id: int = 0,
                          limit: Optional[int] = None, download_media: bool,
                          save_text: bool, media_dir: Path) -> list:
    """Fetch posts newer than min_id (0 = all history). Albums are merged into
    a single Post using the message that carries the caption."""
    log(f"[{channel_label}] Fetching messages"
        + (f" newer than id={min_id}" if min_id else " (full history)")
        + (f", limit={limit}" if limit else "") + " ...")

    grouped = {}
    count = 0
    async for msg in client.iter_messages(entity, limit=limit, min_id=min_id):
        gid = getattr(msg, "grouped_id", None)
        key = gid if gid else f"single_{msg.id}"
        grouped.setdefault(key, []).append(msg)
        count += 1
        if count % 500 == 0:
            log(f"[{channel_label}]  ...{count} raw messages scanned")

    log(f"[{channel_label}] {count} raw messages -> {len(grouped)} post groups")

    posts = []
    media_count_total = 0
    for key, msgs in grouped.items():
        text_msg = next((m for m in msgs if m.text), msgs[-1])
        text = (text_msg.text or "") if save_text else ""
        msg_id = text_msg.id
        iso_date = text_msg.date.astimezone(timezone.utc).isoformat()
        sender_info = await get_sender_info(text_msg)

        media_files = []
        media_count = 0
        for m in msgs:
            if m.media and isinstance(m.media, (MessageMediaPhoto, MessageMediaDocument)):
                media_count += 1
                if download_media:
                    fname = f"{msg_id}_{m.id}.jpg"
                    fpath = media_dir / fname
                    if not fpath.exists():
                        try:
                            await safe_call(
                                lambda m=m, fpath=fpath: client.download_media(m.media, file=str(fpath)))
                            media_count_total += 1
                        except Exception as e:
                            log(f"[{channel_label}]  media download failed for "
                                f"msg {m.id}: {type(e).__name__}")
                            continue
                    media_files.append(fname)

        reactions = 0
        if text_msg.reactions and text_msg.reactions.results:
            reactions = sum(r.count for r in text_msg.reactions.results)

        username = getattr(entity, "username", None)
        link = f"https://t.me/{username}/{msg_id}" if username else ""

        posts.append(Post(
            id=msg_id,
            date=iso_date,
            text=text,
            media_count=media_count,
            **sender_info,
            media_files=media_files,
            reactions=reactions,
            views=getattr(text_msg, "views", None),
            forwards=getattr(text_msg, "forwards", None),
            link=link,
        ))

    posts.sort(key=lambda p: p.sort_key)
    if download_media:
        log(f"[{channel_label}] Downloaded {media_count_total} new media files.")
    return posts


# --------------------------------------------------------------------------- #
# Persistence (resume support)
# --------------------------------------------------------------------------- #

def load_existing(json_path: Path) -> list:
    if not json_path.exists():
        return []
    try:
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log(f"Could not read existing {json_path.name} ({type(e).__name__}); "
            "starting fresh.")
        return []


def merge_posts(existing: list, new_posts: list) -> list:
    by_id = {p["id"]: p for p in existing}
    for p in new_posts:
        by_id[p.id] = asdict(p)
    return sorted(by_id.values(), key=lambda p: p["id"])


def write_json(path: Path, posts: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def write_csv(path: Path, posts: list) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for p in posts:
            row = {k: p.get(k, "") for k in CSV_FIELDS}
            if isinstance(row["media_files"], list):
                row["media_files"] = "|".join(row["media_files"])
            writer.writerow(row)


def apply_text_preference(posts: list, *, save_text: bool) -> list:
    if save_text:
        return posts
    return [{**p, "text": ""} for p in posts]


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--channel", "-c", action="append", dest="channels",
                   help="Channel to scrape (repeatable). Defaults to CHANNELS in .env.")
    p.add_argument("--output-dir", default=None,
                   help="Output directory (default: 'output').")
    p.add_argument("--format", choices=["json", "csv", "both"], default=None,
                   help="Output format. If omitted, the script asks before starting.")
    p.add_argument("--download-media", action="store_true",
                   help="Download photos/documents without asking.")
    p.add_argument("--save-text", action=argparse.BooleanOptionalAction, default=None,
                   help="Save message text. If omitted, the script asks before starting.")
    p.add_argument("--limit", type=int, default=None,
                   help="Max messages to scan per channel (default: no limit).")
    p.add_argument("--no-resume", action="store_true",
                   help="Ignore any existing output and re-fetch full history.")
    return p.parse_args()


def configure_run(args):
    if sys.stdin.isatty():
        download_media = args.download_media or prompt_yes_no(
            "Download photos/files?", default=False)
        save_text = args.save_text
        if save_text is None:
            save_text = prompt_yes_no("Save message texts?", default=True)
        output_format = args.format or prompt_output_format("json")
    else:
        download_media = args.download_media
        save_text = True if args.save_text is None else args.save_text
        output_format = args.format or "json"

    log("Options: "
        f"media={'yes' if download_media else 'no'}, "
        f"text={'yes' if save_text else 'no'}, "
        f"format={output_format}")
    return download_media, save_text, output_format


async def main():
    args = parse_args()

    api_id = (os.getenv("API_ID") or "").strip()
    api_hash = (os.getenv("API_HASH") or "").strip()
    phone = (os.getenv("PHONE") or "").strip() or None
    session_name = "session"
    if not api_id or not api_hash:
        fail("API_ID / API_HASH missing. Edit .env and fill them in.")
    try:
        api_id = int(api_id)
    except ValueError:
        fail(f"API_ID must be a number, got {api_id!r}. Check your .env.")

    channels = args.channels or [
        c.strip() for c in (os.getenv("CHANNELS") or "").split(",") if c.strip()
    ]
    if not channels:
        if sys.stdin.isatty():
            channels = prompt_channels()
        if not channels:
            fail("No channels given. Use --channel or set CHANNELS in .env.")

    output_dir_value = args.output_dir or "output"
    output_dir = Path(repair_dotenv_path(output_dir_value))
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        fail(f"Invalid output directory path {output_dir_value!r}: {e}")

    download_media, save_text, output_format = configure_run(args)

    client = TelegramClient(session_name, api_id, api_hash)
    client.flood_sleep_threshold = 60
    # phone=None falls back to Telethon's interactive "Please enter your phone" prompt.
    # If PHONE is set in .env, only the login code (sent via Telegram) is asked for.
    log("If this is your first login, Telegram may take about 10 seconds "
        "to show the code prompt. Check your Telegram app for the code.")
    await client.start(phone=phone)
    log("Client connected.")

    for raw_channel in channels:
        entity = await resolve_entity(client, raw_channel)
        label = getattr(entity, "username", None) or getattr(entity, "title", raw_channel)
        safe_label = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(label))

        json_path = output_dir / f"{safe_label}_posts.json"
        csv_path = output_dir / f"{safe_label}_posts.csv"
        media_dir = output_dir / safe_label / "media"
        if download_media:
            media_dir.mkdir(parents=True, exist_ok=True)

        existing = [] if args.no_resume else load_existing(json_path)
        resume_min_id = max((p["id"] for p in existing), default=0) if existing else 0
        scrape_min_id = 0 if download_media else resume_min_id
        if existing:
            log(f"[{label}] Resuming: {len(existing)} posts already saved "
                f"(newest id={resume_min_id}).")
            if download_media:
                log(f"[{label}] Media download requested; scanning full history "
                    "to download media from already saved posts. Existing files "
                    "will be skipped.")

        try:
            new_posts = await scrape_channel(
                client, entity, label,
                min_id=scrape_min_id, limit=args.limit,
                download_media=download_media, save_text=save_text,
                media_dir=media_dir,
            )
        except (ChatAdminRequiredError, ChannelPrivateError) as e:
            log(f"[{label}] Cannot access channel: {type(e).__name__}. Skipping.")
            continue

        merged = apply_text_preference(merge_posts(existing, new_posts),
                                       save_text=save_text)

        if output_format in ("json", "both"):
            write_json(json_path, merged)
        if output_format in ("csv", "both"):
            write_csv(csv_path, merged)

        new_count = sum(1 for p in new_posts if p.id > resume_min_id)
        log(f"[{label}] Done: {new_count} new, {len(merged)} total posts "
            f"saved to '{output_dir}/'.")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
