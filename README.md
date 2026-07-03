# telegram-channel-scraper

**[راهنمای فارسی](README.fa.md)**

A small Telethon-based CLI that scrapes all messages from one or more public
or private Telegram **channels or groups** into JSON/CSV — with incremental
(resume) runs, optional media download, and multi-target support in a single
invocation.

Works on channels, regular groups, and supergroups alike — including a
private group you belong to. That makes it useful not just for archiving a
channel's posts, but also for pulling a personal group's message history to
gauge its health (activity level, most active members, engagement trends).

> Read-only: it only reads messages from channels/groups you already have
> access to. It never posts, edits, or joins anything on your behalf.

## Features

- **Multiple channels in one run** — pass `--channel` more than once, or a
  comma-separated `CHANNELS` list in `.env`.
- **Resume / incremental scraping** — re-running only fetches posts newer
  than the last saved id and merges them into the existing file. Use
  `--no-resume` to force a full re-scrape.
- **JSON and/or CSV output** (`--format json|csv|both`).
- **Sender info for groups** — saves sender id/name/username when Telegram
  exposes it, so AI tools can analyze who said what in group exports.
- **Media download is opt-in** (`--download-media`) — by default only a
  `media_count` is recorded, nothing is downloaded.
- **Album-aware** — grouped photos/videos are merged into a single post
  using the message that carries the caption.
- **Flood-wait safe** — automatically sleeps and retries when Telegram
  rate-limits requests.

## Install & run (Windows / PowerShell)

Open PowerShell in the folder that contains `scraper.py`, then run:

```powershell
cd "path\to\telegram-channel-scraper"
Get-ChildItem scraper.py, .env
python -m pip install -r requirements.txt
python .\scraper.py
```

If `Get-ChildItem scraper.py, .env` says a file does not exist, you are in
the wrong folder. Edit `.env` and run `python .\scraper.py` from the project
folder, not from a parent folder such as `F:\Telegram app`.

Use `python -m pip ...` instead of `pip ...` on Windows. It installs packages
with the same Python that runs `scraper.py`, even if the standalone `pip`
launcher points to an old or removed Python install.

(On macOS/Linux, same idea: edit `.env` with any editor, then
`python3 scraper.py`.)

## Configure `.env`

The repository already includes `.env`. Edit only these four values:

```env
API_ID = 123456
API_HASH = ""
PHONE = "+98"
CHANNELS = ""
```

`API_ID` is a number and does not need quotes. Keep quotes around the text
values. You do not need to set a session name or output path.

| Key | Meaning |
|---|---|
| `API_ID`, `API_HASH` | From https://my.telegram.org → API development tools |
| `PHONE` | Your Telegram phone number with country code — required to log in |
| `CHANNELS` | Comma-separated list of channels **or groups** (username, link, or numeric id) |

You can leave `CHANNELS = ""` empty. If it is empty, the script asks for the
channel/group in PowerShell when you run it.

**Logging in the first time:** the script needs your phone number, and
Telegram will send a login code to your Telegram app (not SMS necessarily —
check the app). After you run `python .\scraper.py`, it can take about 10
seconds before the terminal asks for the code. Type the Telegram code in the
same PowerShell window. If your account has two-factor authentication (2FA)
enabled, it will also ask for your password. After this first successful
login, a `.session` file is created and you won't be asked again on future
runs.

This is not hacking and it is not a security exploit. You log in through
Telegram's official API credentials and approve access yourself. The script is
read-only: it reads channels/groups you already have access to and does not
send messages, edit messages, or join anything.

Before scraping starts, the script asks:

- whether to download photos/files
- whether to save message text
- which output format to write: `json`, `csv`, or `both`

## Usage

```bash
# Scrape everything in CHANNELS from .env, save as JSON
python scraper.py

# Scrape specific channels or groups, ignoring .env (mix freely)
python scraper.py --channel mychannel --channel https://t.me/mygroup

# Also write CSV
python scraper.py --format both

# Download media too (off by default)
python scraper.py --download-media

# Skip message text and save only metadata/media info
python scraper.py --no-save-text

# Force a full re-scrape instead of resuming from the last saved post
python scraper.py --no-resume

# Cap how many messages are scanned (useful for a quick test)
python scraper.py --limit 200
```

## Output

After you run the script, an `output` folder is created in the same folder
where you ran `python .\scraper.py`. For each channel, files are written
there:

- `<channel>_posts.json` — array of posts:
  ```json
  {
    "id": 123,
    "date": "2026-07-02T10:00:00+00:00",
    "sender_id": 123456789,
    "sender_name": "Example User",
    "sender_username": "exampleuser",
    "sender_type": "User",
    "text": "full post text, not truncated",
    "media_count": 1,
    "media_files": ["123_124.jpg"],
    "reactions": 4,
    "views": 5231,
    "forwards": 12,
    "link": "https://t.me/mychannel/123"
  }
  ```
- `<channel>_posts.csv` — same fields, flattened (only with `--format csv|both`).

If `--download-media` is set, photos and files are saved under
`output/<channel>/media/`.

If you already scraped a channel without media, run the script again and
answer `y` to photos/files. It will scan the saved history too and skip files
that already exist.

## Notes & limitations

- Resume matching is by message id; if a post is edited after being scraped,
  re-running will not pick up the edit (only new posts are fetched).
- Sender fields are saved for newly scraped messages. If you already exported
  a group before this feature existed, run with `--no-resume` to rebuild the
  output with sender details.
- Private channels require the logged-in account to already be a member.
- Be patient on large channels — the script respects Telegram's flood-wait
  limits and will sleep when asked to.
- Keep your `.session` file private — it is excluded via `.gitignore`.

## License

MIT — see [LICENSE](LICENSE).
