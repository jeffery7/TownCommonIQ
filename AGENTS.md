# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, ChatGPT/Codex, Gemini CLI, and similar tools) when working with code in this repository. It is the canonical source of project guidance — `CLAUDE.md` and `GEMINI.md` point here.

## Project Goal

To create a searchable data repository of meeting documents and data for a given entity in a town government in Massachusetts.  This code will be used to generate, maintain, and verify that data repository which includes fetching data from appropriate sources.  It should also maintain searchable metadata.

The official posting website for many towns is on [MyTownGovernment.org](https://www.mytowngovernment.org/) delineated by zip-code.  The zip-code used for Hardwick Massachusetts is 01031 (Gilbertville): [MyTownGovernment.org/01031](https://www.mytowngovernment.org/01031)

This code will also have the ability to generate missing minutes documents for meetings using YouTube videos or audio recordings to generate transcripts when they cannot be retrieved from YouTube or other sources.

### Hardwick Select Board

This code was primarily created to conduct oversight on the Town of Hardwick Massachusetts Select Board and administrative staff, it should be flexibile enough to be adapted to other towns in the future.

Meetings are pulled from [MyTownGovernment.org](https://www.mytowngovernment.org/board?board=ahNzfnRvd25nb3Zlcm5tZW50LWhychILEgpCb2FyZE1vZGVsGNn3FAw) and correlated with recordings on the [Hardwick TV YouTube channel](https://www.youtube.com/@hardwicktv2394/streams). Transcripts are used together with meeting agendas to generate [MGL Chapter 30A §22](https://malegislature.gov/Laws/GeneralLaws/PartI/TitleIII/Chapter30A/Section22) compliant draft minutes as `.docx` files.

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
export MUNICIPALIQ_TOWN=Hardwick   # defaults to Hardwick if not set
```

## Agent Permissions

This repo ships project-level permission configs so AI coding agents can run
routine commands (tests, lint, the CLI) without an approval prompt on every
step:

- **Claude Code**: `.claude/settings.json` pre-approves `pytest`, `flake8`,
  `python -m municipaliq`, and read-only `git status` / `git diff` / `git
  log`. Personal overrides go in `.claude/settings.local.json` (gitignored).
- **Codex CLI (ChatGPT)**: `.codex/config.toml` sets `approval_policy =
  "on-request"` and `sandbox_mode = "workspace-write"`. Each collaborator
  must mark this project as **trusted** in their own Codex CLI for the
  project config to take effect.

Commands with real side effects — `git push`, `archive --recordings`
(downloads large files), `generate` (calls the Claude API) — are
intentionally left out of these allowlists and should run with explicit
confirmation.

## CLI Usage

```bash
# Refresh meeting and video data from MyTownGovernment.org and YouTube
python -m municipaliq sync

# Rebuild board officer history from reorganization meeting transcripts
python -m municipaliq sync-board

# Sync minutes listing from the town website (hardwick-ma.gov); downloads files via Firefox
python -m municipaliq sync-town
python -m municipaliq sync-town --no-headless   # show browser window if Cloudflare challenges occur

# List meetings (combine flags freely)
python -m municipaliq list
python -m municipaliq list --missing            # only meetings with no official minutes URL
python -m municipaliq list --no-draft           # only meetings without a locally generated draft
python -m municipaliq list --has-transcript     # only meetings that have a local transcript

# Download documents, agendas, and transcripts for archived meetings
python -m municipaliq archive --date 2024-03-15
python -m municipaliq archive --since 2024-01-01
python -m municipaliq archive --all
python -m municipaliq archive --all --recordings           # also download YouTube video (~1.5 GB each)
python -m municipaliq archive --all --recordings --audio-only  # audio track only (~150 MB each)
python -m municipaliq archive --all --cookies cookies.txt  # Netscape cookies for YouTube IP blocks
python -m municipaliq archive --all --proxy socks5://127.0.0.1:1080

# Generate draft minutes (.docx)
python -m municipaliq generate --date 2024-03-15
python -m municipaliq generate --since 2024-01-01   # all eligible meetings on or after date
python -m municipaliq generate --all
python -m municipaliq generate --all --force         # overwrite existing drafts

# Record which board members were absent at a meeting (assumed all present otherwise)
python -m municipaliq set-attendance --date 2024-03-15 --absent "Eric W. Vollheim"
python -m municipaliq set-attendance --date 2024-03-15 --absent "Alice Smith, Bob Jones"

# Compare minutes availability between MyTownGovernment.org and the town website
python -m municipaliq compare
python -m municipaliq compare --output report.txt
```

## Style

Follow [WeMake Python Styleguide](https://wemake-python-styleguide.readthedocs.io/en/latest/).  Avoid using "# noqa:" comments or updating the flake8 configuration to solve problems unless absolutely necessary.

```bash
flake8 --format=html --htmldir=flake8-report municipaliq/ tests/  
```

## Tests

```bash
pytest tests/ -v --cov=municipaliq --cov-report=html

# Single test
pytest tests/test_correlator.py::TestCorrelate::test_matches_same_day
```

Target: near 100% unit test coverage. All external I/O (HTTP, subprocess, Claude API) must be mocked in tests.  Strive for zero flake8 violations, prefer not using "# noqa:" notations.

## Architecture

Data flows in one direction: **scrape → cache → correlate → transcribe → generate**.
Whenever possible, prefer the YouTube transcript over generating locally with Whisper.

```
municipaliq/
├── scraper/
│   ├── mytowngovernment.py   # requests + BeautifulSoup → list of meeting dicts
│   └── youtube.py            # yt-dlp (metadata-only) → list of video dicts
├── data_store.py             # read/write data/<town>/*.json and per-meeting
│                             #   folders under data/<town>/meetings/
├── correlator.py             # matches videos to meetings by date (±1 day window)
├── transcript.py             # YouTube transcript API, falls back to Whisper via yt-dlp
├── minutes_generator.py      # Claude API (claude-sonnet-4-6) → .docx via python-docx
└── cli.py                    # argparse entry point (sync / list / generate)
```

### Data folder layout

Data is organised by town under `data/<town>/`.  The active town is set via
the `MUNICIPALIQ_TOWN` environment variable (default: `Hardwick`).

```
data/
└── Hardwick/                      # one directory per town (MUNICIPALIQ_TOWN)
    ├── meetings.json              # master list of all meetings with status and cross-references
    ├── name_corrections.json      # a dictionary of name corrections
    ├── youtube.json               # cached YouTube stream list
    └── meetings/
        └── 2024-03-15_1830/                                   # YYYY-MM-DD_HHMM
            ├── 2024-03-15_1830_agenda.txt                     # fetched agenda text
            ├── 2024-03-15_1830_meeting.json                   # fetched metadata about meeting
            ├── 2024-03-15_1830_transcript.txt                 # YouTube or Whisper transcript
            ├── 2024-03-15_1830_minutes_draft_generated.docx   # generated draft — review before submitting
            └──[Any other downloaded files]
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
