# TownCommonIQ

TownCommonIQ builds a searchable archive of local government meeting records —
agendas, recordings, transcripts, and minutes — and can generate draft minutes
for meetings where none have been posted.

It was created to support oversight of the **Town of Hardwick, Massachusetts
Select Board**, but is designed to be adaptable to other Massachusetts towns.

## What it does

- **Scrapes** meeting listings and agendas from
  [MyTownGovernment.org](https://www.mytowngovernment.org/) and the town
  website, and pulls stream metadata from the town's YouTube channel.
- **Correlates** meetings with their corresponding YouTube recordings by
  date.
- **Archives** agendas, posted documents, and (optionally) recordings or
  audio for each meeting into a local per-meeting folder.
- **Transcribes** recordings via the YouTube transcript API, falling back to
  Whisper when no transcript is available.
- **Generates** draft `.docx` minutes from agendas and transcripts using the
  Claude API, aiming for compliance with Massachusetts Open Meeting Law
  (MGL Chapter 30A §22/§23).
- **Compares** minutes availability between the official posting site and the
  town website to flag gaps.

## Quick start (macOS / Linux)

> Windows users: see [Windows Setup](#windows-setup) below instead.

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
export TOWNCOMMONIQ_TOWN=Hardwick   # defaults to Hardwick if not set

python -m towncommoniq sync       # refresh meeting and video listings
python -m towncommoniq list       # see what's known
python -m towncommoniq archive --all
python -m towncommoniq generate --all
```

## Windows Setup

A step-by-step guide for getting the full pipeline running on Windows,
including the browser-based scraper, transcription, and OCR. Commands below
are for **PowerShell** (Start menu → "PowerShell").

### 1. Install prerequisites

Install these first, in any order:

| Tool | Why it's needed | Get it from |
|---|---|---|
| Git for Windows | Clone and update the code | https://git-scm.com/download/win |
| Python 3.11+ | Runs the project | https://www.python.org/downloads/ — **check "Add python.exe to PATH"** on the first install screen |
| Mozilla Firefox | `sync-town` drives a real browser via Selenium | https://www.mozilla.org/firefox/ |
| Tesseract OCR | Reads text from scanned PDF minutes | https://github.com/UB-Mannheim/tesseract/wiki (Windows installer) |

Selenium automatically downloads the matching `geckodriver` the first time it
runs — no manual driver setup needed, just install Firefox.

Two more tools need to be downloaded as zip files and added to your PATH
manually:

**FFmpeg** (needed by yt-dlp and Whisper for audio):
1. Download a build from https://www.gyan.dev/ffmpeg/builds/ (the
   "release essentials" zip).
2. Extract it to a permanent location, e.g. `C:\ffmpeg`.
3. Add `C:\ffmpeg\bin` to your PATH.

**Poppler** (needed by pdf2image for OCR):
1. Download the latest release from
   https://github.com/oschwartz10612/poppler-windows/releases (zip
   containing a `Library\bin` folder).
2. Extract it to a permanent location, e.g. `C:\poppler`.
3. Add `C:\poppler\Library\bin` to your PATH.

**Editing your PATH:**
1. Press Win, type "environment variables", open "Edit environment
   variables for your account".
2. Under "User variables", select `Path` → Edit → New, and add each folder
   (also add Tesseract's install folder, usually
   `C:\Program Files\Tesseract-OCR`, if its installer didn't do so already).
3. Click OK on all dialogs, then **close and reopen PowerShell** so the
   change takes effect.

### 2. Get the code

```powershell
git clone https://github.com/jeffery7/TownCommonIQ.git
cd TownCommonIQ
```

If prompted to sign in, a browser window will open — log in with your GitHub
account and approve.

### 3. Create a virtual environment and install dependencies

A virtual environment keeps this project's Python packages separate from
everything else on your machine.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell refuses to run the activation script ("running scripts is
disabled on this system"), run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

You'll need to run `.venv\Scripts\Activate.ps1` again every time you open a
new terminal for this project — your prompt will start with `(.venv)` when
it's active.

### 4. Set your environment variables

Get your own key from https://console.anthropic.com/ — each person should
use their own API key, not a shared one.

For the current terminal session only:

```powershell
$env:ANTHROPIC_API_KEY = "your_key_here"
```

To set it permanently (so new terminals pick it up automatically):

```powershell
setx ANTHROPIC_API_KEY "your_key_here"
```

`TOWNCOMMONIQ_TOWN` defaults to `Hardwick`, so you only need to set it if
working on a different town.

### 5. Run the CLI

With the virtual environment active, the commands are the same as on
macOS/Linux — see the full reference in [AGENTS.md](AGENTS.md):

```powershell
python -m towncommoniq sync
python -m towncommoniq list
python -m towncommoniq archive --all
python -m towncommoniq generate --all
```

### Troubleshooting

- **`python` / `git` not recognized** — close and reopen PowerShell so it
  picks up PATH changes, or reinstall with "Add to PATH" checked.
- **`tesseract is not installed or it's not in your PATH`** — add
  `C:\Program Files\Tesseract-OCR` to PATH and reopen PowerShell.
- **OCR/poppler errors** (e.g. `Unable to get page count`) — confirm
  `...\poppler\Library\bin` is on PATH.
- **`ffmpeg not found`** during `generate` or transcription — confirm
  `C:\ffmpeg\bin` is on PATH.
- **`sync-town` seems to hang** — try `python -m towncommoniq sync-town
  --no-headless` to watch the Firefox window and see if a Cloudflare
  challenge needs solving manually.

## YouTube Cookies (for IP Blocks)

`archive` fetches transcripts from YouTube (captions first, falling back to
downloading audio for Whisper). Processing many meetings in one run can
trigger YouTube's anonymous-IP rate limiting — you'll see
"YouTube is blocking requests from your IP" / "429 Too Many Requests" in the
log (`data/<town>/logs/towncommoniq.log`). Authenticating as a logged-in
user raises that limit substantially. `archive` accepts a cookies file
for this:

```bash
python -m towncommoniq archive --all --cookies cookies.txt
```

To get a cookies file:

1. Log in to [youtube.com](https://www.youtube.com) in your regular browser.
2. Install a "cookies.txt" export extension — e.g.
   [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
   for Chrome/Edge, or search your browser's extension store for the
   equivalent (any extension that exports in Netscape cookie format works).
3. While on youtube.com, use the extension to export cookies for that site
   to a file, e.g. `cookies.txt`.
4. Pass that file's path via `--cookies` on `archive`.

The cookies file contains a live login session — treat it like a password
(don't commit it to git; `*.txt` cookie exports aren't covered by
`.gitignore` by default, so keep it outside the repo or name it something
covered by an ignore rule). It will expire eventually (YouTube sessions
typically last months), at which point re-export a fresh one the same way.

If blocking persists even with cookies, `--proxy` routes requests through a
different IP instead, e.g. `--proxy socks5://127.0.0.1:1080` via an SSH
tunnel (`ssh -D 1080 user@host`).

## Running Tests and Linting

These commands are identical on macOS/Linux and Windows — on Windows, just
make sure your virtual environment is activated first
(`.venv\Scripts\Activate.ps1`).

### Tests with a coverage report

```bash
pytest tests/ -v --cov=towncommoniq --cov-report=html
```

This writes an HTML report to `htmlcov/index.html`. Open it in a browser:

```bash
open htmlcov/index.html       # macOS
xdg-open htmlcov/index.html   # Linux
```

```powershell
start htmlcov/index.html      # Windows
```

### flake8 with an HTML report

```bash
flake8 --format=html --htmldir=flake8-report towncommoniq/ tests/
```

This writes an HTML report to `flake8-report/index.html`. Open it the same
way:

```bash
open flake8-report/index.html       # macOS
xdg-open flake8-report/index.html   # Linux
```

```powershell
start flake8-report/index.html      # Windows
```

## Documentation

Full CLI reference, architecture, data layout, coding style, and test
instructions live in [AGENTS.md](AGENTS.md) — this is the canonical
documentation source for both human contributors and AI coding agents
(Claude Code, ChatGPT/Codex, Gemini CLI).

## License

No license has been chosen yet; all rights reserved.
