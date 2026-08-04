# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, ChatGPT/Codex, Gemini CLI, and similar tools) when working with code in this repository. It is the canonical source of project guidance — `CLAUDE.md` and `GEMINI.md` point here.

## Project Goal

To create a searchable data repository of meeting documents and data for a given entity in a town government in Massachusetts.  This code will be used to generate, maintain, and verify that data repository which includes fetching data from appropriate sources.  It should also maintain searchable metadata.

The official posting website for many towns is on [MyTownGovernment.org](https://www.mytowngovernment.org/) delineated by zip-code.  The zip-code used for Hardwick Massachusetts is 01031 (Gilbertville): [MyTownGovernment.org/01031](https://www.mytowngovernment.org/01031)

This code will also have the ability to generate missing minutes documents for meetings using YouTube videos or audio recordings to generate transcripts when they cannot be retrieved from YouTube or other sources.

### Hardwick Select Board

This code was primarily created to conduct oversight on the Town of Hardwick Massachusetts Select Board and administrative staff, it should be flexibile enough to be adapted to other towns in the future.

Meetings are pulled from [MyTownGovernment.org](https://www.mytowngovernment.org/board?board=ahNzfnRvd25nb3Zlcm5tZW50LWhychILEgpCb2FyZE1vZGVsGNn3FAw) and correlated with recordings on the [Hardwick TV YouTube channel](https://www.youtube.com/@hardwicktv2394/streams). Transcripts are used together with meeting agendas to generate [MGL Chapter 30A §22](https://malegislature.gov/Laws/GeneralLaws/PartI/TitleIII/Chapter30A/Section22) compliant draft minutes as `.docx` files.

### Other tracked boards

The Hardwick TV YouTube channel posts recordings for several town boards, not
just Select Board — Board of Health and Finance Committee are also tracked
(`sync`/`list`/`archive`/`set-attendance` all take `--board "Board of
Health"` or `--board "Finance Committee"`; default is Select Board). This
started because a Board of Health video was silently matched onto a real
Select Board meeting by date alone (see `correlator.looks_like_wrong_board`)
— tracking those boards for real, instead of just filtering their videos out
as noise, is the actual fix.

**AI minutes drafting (`generate`) and the minutes-source `compare` stay
Select Board-only** — that's this project's actual oversight purpose. Those
commands (plus `sync-board`, `sync-town`) have no `--board` flag and always
operate on Select Board's data, regardless of what other boards are synced.

To add a new board: look up its opaque `board=<id>` on
[MyTownGovernment.org/01031](https://www.mytowngovernment.org/01031) (Hardwick's
zip code), add it to `mytowngovernment.BOARD_IDS`, and add its title keyword(s)
to `correlator.BOARD_TITLE_KEYWORDS` (used to flag a video whose title suggests
the wrong board — see the docstring on `looks_like_wrong_board` for why a
title with no recognizable board name, or the word "joint", is never flagged).

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
export TOWNCOMMONIQ_TOWN=Hardwick   # defaults to Hardwick if not set
```

## Agent Permissions

This repo ships project-level permission configs so AI coding agents can run
routine commands (tests, lint, the CLI) without an approval prompt on every
step:

- **Claude Code**: `.claude/settings.json` pre-approves `pytest`, `flake8`,
  `python -m towncommoniq`, and read-only `git status` / `git diff` / `git
  log`. Personal overrides go in `.claude/settings.local.json` (gitignored).
- **Codex CLI (ChatGPT)**: `.codex/config.toml` sets `approval_policy =
  "on-request"` and `sandbox_mode = "workspace-write"`. Each collaborator
  must mark this project as **trusted** in their own Codex CLI for the
  project config to take effect.
- **Gemini CLI**: `.gemini/settings.json` lists the same commands under
  `tools.allowed` (e.g. `run_shell_command(pytest)`) so they run without a
  confirmation prompt.

Commands with real side effects — `git push`, `archive --recordings`
(downloads large files), `generate` (calls the Claude API) — are
intentionally left out of these allowlists and should run with explicit
confirmation.

## CLI Usage

```bash
# Refresh meeting and video data from MyTownGovernment.org and YouTube
python -m towncommoniq sync
python -m towncommoniq sync --board "Board of Health"    # sync/list/archive/set-attendance
python -m towncommoniq sync --board "Finance Committee"  # all take --board (default: Select Board)

# Rebuild board officer history from reorganization meeting transcripts
python -m towncommoniq sync-board

# Sync minutes listing from the town website (hardwick-ma.gov); downloads files via Firefox
python -m towncommoniq sync-town
python -m towncommoniq sync-town --no-headless   # show browser window if Cloudflare challenges occur

# List meetings (combine flags freely)
python -m towncommoniq list
python -m towncommoniq list --missing            # only meetings with no official minutes URL
python -m towncommoniq list --no-draft           # only meetings without a locally generated draft
python -m towncommoniq list --has-transcript     # only meetings that have a local transcript

# Download documents, agendas, and transcripts for archived meetings
python -m towncommoniq archive --date 2024-03-15
python -m towncommoniq archive --since 2024-01-01
python -m towncommoniq archive --all
python -m towncommoniq archive --all --recordings           # also download YouTube video (~1.5 GB each)
python -m towncommoniq archive --all --recordings --audio-only  # audio track only (~150 MB each)
python -m towncommoniq archive --all --cookies cookies.txt  # Netscape cookies for YouTube IP blocks
python -m towncommoniq archive --all --proxy socks5://127.0.0.1:1080

# Generate draft minutes (.docx)
python -m towncommoniq generate --date 2024-03-15
python -m towncommoniq generate --since 2024-01-01   # all eligible meetings on or after date
python -m towncommoniq generate --all
python -m towncommoniq generate --all --force         # overwrite existing drafts

# Record which board members were absent at a meeting (assumed all present otherwise)
python -m towncommoniq set-attendance --date 2024-03-15 --absent "Eric W. Vollheim"
python -m towncommoniq set-attendance --date 2024-03-15 --absent "Alice Smith, Bob Jones"

# Compare minutes availability between MyTownGovernment.org and the town website
python -m towncommoniq compare
python -m towncommoniq compare --output report.txt
```

## Style

Follow [WeMake Python Styleguide](https://wemake-python-styleguide.readthedocs.io/en/latest/).  Avoid using "# noqa:" comments or updating the flake8 configuration to solve problems unless absolutely necessary.

```bash
flake8 --format=html --htmldir=flake8-report towncommoniq/ tests/  
```

## Tests

```bash
pytest tests/ -v --cov=towncommoniq --cov-report=html

# Single test
pytest tests/test_correlator.py::TestCorrelate::test_matches_same_day
```

Target: near 100% unit test coverage. All external I/O (HTTP, subprocess, Claude API) must be mocked in tests.  Strive for zero flake8 violations, prefer not using "# noqa:" notations.

## Architecture

Data flows in one direction: **scrape → cache → correlate → transcribe → generate**.
Whenever possible, prefer the YouTube transcript over generating locally with Whisper.

```
towncommoniq/
├── scraper/
│   ├── mytowngovernment.py   # requests + BeautifulSoup → list of meeting dicts
│   └── youtube.py            # yt-dlp (metadata-only) → list of video dicts
├── data_store.py             # read/write data/<town>/*.json and per-meeting
│                             #   folders under data/<town>/meetings/ (Select
│                             #   Board) or data/<town>/boards/<slug>/ (other
│                             #   tracked boards) — see paths_for_board()
├── correlator.py             # matches videos to meetings by date (±1 day window)
├── transcript.py             # YouTube transcript API, falls back to Whisper via yt-dlp
├── minutes_generator.py      # Claude API (claude-sonnet-4-6) → .docx via python-docx
└── cli.py                    # argparse entry point (sync / list / generate)
```

### Data folder layout

Data is organised by town under `data/<town>/`.  The active town is set via
the `TOWNCOMMONIQ_TOWN` environment variable (default: `Hardwick`).

Within a town, Select Board keeps the layout below directly under
`data/<town>/` — that's ~52GB of already-archived data and cannot move. Any
other tracked board (see `--board` above) gets its own subtree at
`data/<town>/boards/<slug>/`, mirroring the same internal shape
(`meetings.json`, `meetings/YYYY-MM-DD_HHMM/...`, etc.) — see
`data_store.paths_for_board()`. `youtube.json`, `name_corrections.json`, and
`town_minutes.json` stay at the town level regardless of board: one YouTube
channel and one name-correction dictionary serve every board.

```
data/
└── Hardwick/                      # one directory per town (TOWNCOMMONIQ_TOWN)
    ├── meetings.json              # Select Board's meetings, with status and cross-references
    ├── board.json                 # Select Board's current chair/clerk/members
    ├── board_history.json         # Select Board's dated officer history
    ├── name_corrections.json      # a dictionary of name corrections (town-wide)
    ├── youtube.json               # cached YouTube stream list (town-wide, all boards)
    ├── meetings/
    │   └── 2024-03-15_1830/                                   # Select Board, YYYY-MM-DD_HHMM
    │       ├── 2024-03-15_1830_agenda.txt                     # fetched agenda text
    │       ├── 2024-03-15_1830_meeting.json                   # fetched metadata about meeting
    │       ├── 2024-03-15_1830_transcript.txt                 # YouTube or Whisper transcript
    │       ├── 2024-03-15_1830_minutes_draft_generated.docx   # generated draft — review before submitting
    │       └──[Any other downloaded files]
    └── boards/
        └── board-of-health/                # data_store._slug("Board of Health")
            ├── meetings.json                # same shape as Select Board's, scoped to this board
            └── meetings/
                └── 2024-03-15_1730/          # same per-meeting layout as above
```

### Meeting record schema (`meetings.json`)

```json
{
  "date": "2024-03-15",
  "time": "6:30 PM",
  "location": "Town Hall",                                // "Cancelled" here means the meeting was cancelled
  "status": "held",                                       // "held" | "cancelled" | "upcoming"
  "meeting_url": "https://mytowngovernment.org/meeting",  // Individual meeting page; agenda text is scraped from here
  "youtube_id": "abc123",                                 // null if no correlated video
  "folder": "data/Hardwick/meetings/2024-03-15_1830",
  "minutes_url": null,                                    // null = missing on official site (generation target)
  "agenda_url": null,                                     // direct download link for agenda PDF if posted
  "posted_meeting_files": []                              // list of {filename, size, created, url} from official site
}
```

### [MGL §22](https://malegislature.gov/Laws/GeneralLaws/PartI/TitleIII/Chapter30A/Section22) required elements

Every generated minutes document must include: body name, date, time, location; members present/absent; summary of discussion per agenda item; all decisions and actions; all votes by roll call.  If they do not, note that in the meeting record.

### [MGL §23](https://malegislature.gov/Laws/GeneralLaws/PartI/TitleIII/Chapter30A/Section23) required elements

Governs executive (closed) sessions. Key requirements:

- The board must vote to enter executive session by roll call, stating the specific statutory purpose (from the enumerated list in §21).
- The presiding officer must announce whether the session will be followed by a return to open session or adjournment.
- Minutes must be kept of executive sessions, but are **not** required to be released until publication would no longer defeat the purpose of the session.
- A brief record of executive session actions must appear in the open-session minutes (e.g., "Voted to enter executive session under §21(a)(3) to discuss pending litigation").
- Any decision or vote reached in executive session that binds the board must be ratified in open session before it takes effect.
