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
- **Media download is opt-in** (`--download-media`) — by default only a
  `media_count` is recorded, nothing is downloaded.
- **Album-aware** — grouped photos/videos are merged into a single post
  using the message that carries the caption.
- **Flood-wait safe** — automatically sleeps and retries when Telegram
  rate-limits requests.

## Install & run (Windows / PowerShell)

Open PowerShell in the project folder and run:

```powershell
cd path\to\telegram-channel-scraper
pip install -r requirements.txt
copy .env.example .env
notepad .env          # fill in your own values, see below — then save & close
python scraper.py
```

(On macOS/Linux, same idea: `cp .env.example .env`, edit it with any editor,
then `python3 scraper.py`.)

## Configure `.env`

Edit the values between the quotes — don't remove the quotes themselves:

```env
API_ID = ""
API_HASH = ""
PHONE = "+98"
SESSION_NAME = "my_session"
CHANNELS = ""
OUTPUT_DIR = "output"
```

| Key | Meaning |
|---|---|
| `API_ID`, `API_HASH` | From https://my.telegram.org → API development tools |
| `PHONE` | Your Telegram phone number with country code — required to log in |
| `SESSION_NAME` | Any name you like for the session file (created on first login) |
| `CHANNELS` | Comma-separated list of channels **or groups** (username, link, or numeric id) |
| `OUTPUT_DIR` | Where JSON/CSV/media get written (default: `output/`) |

**Logging in the first time:** the script needs your phone number, and
Telegram will send a login code to your Telegram app (not SMS necessarily —
check the app). When you run `python scraper.py` the first time, it will ask
you to type that code in the terminal. If your account has two-factor
authentication (2FA) enabled, it will also ask for your password. After this
first successful login, a `.session` file is created and you won't be asked
again on future runs.

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

# Force a full re-scrape instead of resuming from the last saved post
python scraper.py --no-resume

# Cap how many messages are scanned (useful for a quick test)
python scraper.py --limit 200
```

## Output

For each channel, two files are written to `OUTPUT_DIR`:

- `<channel>_posts.json` — array of posts:
  ```json
  {
    "id": 123,
    "date": "2026-07-02T10:00:00+00:00",
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

If `--download-media` is set, files are saved under
`OUTPUT_DIR/<channel>/media/`.

## Notes & limitations

- Resume matching is by message id; if a post is edited after being scraped,
  re-running will not pick up the edit (only new posts are fetched).
- Private channels require the logged-in account to already be a member.
- Be patient on large channels — the script respects Telegram's flood-wait
  limits and will sleep when asked to.
- Keep `.env` and your `.session` file private — both are excluded via
  `.gitignore`.

## License

MIT — see [LICENSE](LICENSE).
