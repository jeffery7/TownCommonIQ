"""Reads and writes meeting data to and from the local data/ cache directory.

Data is organised by town under data/<town>/ at the project root.  The active
town is read from the TOWNCOMMONIQ_TOWN environment variable, defaulting to
'Hardwick'.  Meeting source files each get their own sub-folder named after
the meeting date and time, e.g. data/Hardwick/meetings/YYYY/YYYY-MM-DD_HHMM/.

Board membership is tracked in two files:
  board.json         — current board (updated by sync)
  board_history.json — list of dated board compositions for historical accuracy

board_history.json format:
  [
    {
      "from_date": "2022-01-01",
      "to_date": null,
      "chair": "Eric Vollheim",
      "clerk": "Jeffrey Schaaf",
      "members": ["Jeffrey S. Schaaf", "Eric W. Vollheim", "William F. Tinker"]
    }
  ]
Set to_date to the last date that entry was in effect; null means still current.
"""
import json
import os
import re
from pathlib import Path
from typing import NamedTuple, Optional

_ROOT = Path(__file__).parent.parent
TOWN_NAME = os.environ.get('TOWNCOMMONIQ_TOWN', 'Hardwick')
DATA_DIR = _ROOT / 'data' / TOWN_NAME
MEETINGS_JSON = DATA_DIR / 'meetings.json'
YOUTUBE_JSON = DATA_DIR / 'youtube.json'
BOARD_JSON = DATA_DIR / 'board.json'
BOARD_HISTORY_JSON = DATA_DIR / 'board_history.json'
TOWN_MINUTES_JSON = DATA_DIR / 'town_minutes.json'

# The tool was built single-board (Hardwick's Select Board); DEFAULT_BOARD
# keeps that board's data at today's existing top-level layout (52GB+
# already archived and cited elsewhere by that path — it must never move).
# Any other board gets its own subdirectory; see paths_for_board(). Board
# selection is a per-invocation choice (the CLI's --board flag), not an env
# var like TOWNCOMMONIQ_TOWN — there is no single "current board" for a
# whole process the way there's a single "current town".
DEFAULT_BOARD = 'Select Board'


class BoardPaths(NamedTuple):
    board_dir: Path
    meetings_json: Path
    board_json: Path
    board_history_json: Path


def _slug(board: str) -> str:
    """Turn a board name into a filesystem-safe, kebab-case directory name."""
    return re.sub(r'[^a-z0-9]+', '-', board.lower()).strip('-')


def paths_for_board(board: Optional[str] = None) -> BoardPaths:
    """Return the data paths for a given board.

    DEFAULT_BOARD resolves to today's existing top-level layout, unchanged.
    Any other board gets its own data/<town>/boards/<slug>/ subtree, so
    tracking a new board never requires moving an existing one's data.
    """
    board = board or DEFAULT_BOARD
    board_dir = DATA_DIR if board == DEFAULT_BOARD else DATA_DIR / 'boards' / _slug(board)
    return BoardPaths(
        board_dir=board_dir,
        meetings_json=board_dir / 'meetings.json',
        board_json=board_dir / 'board.json',
        board_history_json=board_dir / 'board_history.json',
    )


def _ensure_dirs(board_dir: Optional[Path] = None) -> None:
    """Create <board_dir>/meetings/ (and any missing parent folders) if absent.

    Defaults to DATA_DIR (resolved at call time, not import time, so tests
    that monkeypatch DATA_DIR still take effect).
    """
    board_dir = DATA_DIR if board_dir is None else board_dir
    (board_dir / 'meetings').mkdir(parents=True, exist_ok=True)


def meeting_folder(date: str, time: str, paths: Optional[BoardPaths] = None) -> Path:
    """Return the Path for a meeting's data folder, creating it if needed.

    Folders are organised by year to match the pre-existing archive structure:
    <board_dir>/meetings/YYYY/YYYY-MM-DD_HHMM/.
    """
    paths = paths or paths_for_board()
    safe_time = re.sub(r'[^0-9]', '', time)[:4]
    year = date[:4] if date else 'unknown'
    folder = paths.board_dir / 'meetings' / year / f'{date}_{safe_time}'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def load_meetings(paths: Optional[BoardPaths] = None) -> list[dict]:
    """Load the list of all known meetings from meetings.json.

    Returns an empty list if the file has not been created yet (i.e. before
    the first sync run). Defaults to the module-level MEETINGS_JSON (today's
    behavior); pass `paths` (see paths_for_board) to target another board.
    """
    meetings_json = paths.meetings_json if paths else MEETINGS_JSON
    if not meetings_json.exists():
        return []
    return json.loads(meetings_json.read_text())


def save_meetings(meetings: list[dict], paths: Optional[BoardPaths] = None) -> None:
    """Write the full meetings list to meetings.json, replacing the old file."""
    board_dir = paths.board_dir if paths else DATA_DIR
    meetings_json = paths.meetings_json if paths else MEETINGS_JSON
    _ensure_dirs(board_dir)
    meetings_json.write_text(json.dumps(meetings, indent=2))


def load_youtube() -> list[dict]:
    """Load the cached YouTube stream list from youtube.json.

    Returns an empty list if no sync has been run yet.
    """
    if not YOUTUBE_JSON.exists():
        return []
    return json.loads(YOUTUBE_JSON.read_text())


def save_youtube(videos: list[dict]) -> None:
    """Write the YouTube stream list to youtube.json, replacing the old file."""
    _ensure_dirs()
    YOUTUBE_JSON.write_text(json.dumps(videos, indent=2))


def load_board_info(paths: Optional[BoardPaths] = None) -> dict:
    """Load board member info (chair, clerk, members list) from board.json.

    Returns default empty values if the file does not exist yet. Defaults to
    the module-level BOARD_JSON (today's behavior); pass `paths` (see
    paths_for_board) to target another board.
    """
    board_json = paths.board_json if paths else BOARD_JSON
    if not board_json.exists():
        return {'chair': None, 'clerk': None, 'members': []}
    return json.loads(board_json.read_text())


def save_board_info(board_info: dict, paths: Optional[BoardPaths] = None) -> None:
    """Write board member info to board.json."""
    board_dir = paths.board_dir if paths else DATA_DIR
    board_json = paths.board_json if paths else BOARD_JSON
    _ensure_dirs(board_dir)
    board_json.write_text(json.dumps(board_info, indent=2))


def save_meeting_metadata(meeting: dict, folder: Path) -> None:
    """Write the meeting metadata dict to a JSON file inside the meeting folder.

    Saved as {folder.name}_meeting.json so the folder is self-contained —
    the date, time, location, YouTube ID, and document URLs are all readable
    without opening the central meetings.json.  Overwrites on every archive
    run so the file stays current (e.g. when a minutes_url is later added).
    """
    meta_path = folder / f'{folder.name}_meeting.json'
    meta_path.write_text(json.dumps(meeting, indent=2))


def load_meeting_metadata(folder: Path) -> Optional[dict]:
    """Load the meeting metadata from its folder JSON file, or None if absent."""
    meta_path = folder / f'{folder.name}_meeting.json'
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


def load_board_history(paths: Optional[BoardPaths] = None) -> list:
    """Load the dated board history from board_history.json.

    Returns an empty list if the file has not been created yet.  Populate
    this file manually to enable date-accurate member lists in generated
    minutes. Defaults to the module-level BOARD_HISTORY_JSON (today's
    behavior); pass `paths` (see paths_for_board) to target another board.
    """
    board_history_json = paths.board_history_json if paths else BOARD_HISTORY_JSON
    if not board_history_json.exists():
        return []
    return json.loads(board_history_json.read_text())


def save_board_history(history: list, paths: Optional[BoardPaths] = None) -> None:
    """Write the board history list to board_history.json."""
    board_dir = paths.board_dir if paths else DATA_DIR
    board_history_json = paths.board_history_json if paths else BOARD_HISTORY_JSON
    _ensure_dirs(board_dir)
    board_history_json.write_text(json.dumps(history, indent=2))


def load_town_minutes() -> list:
    """Load the cached town-website minutes list from town_minutes.json."""
    if not TOWN_MINUTES_JSON.exists():
        return []
    return json.loads(TOWN_MINUTES_JSON.read_text())


def save_town_minutes(records: list) -> None:
    """Write the town-website minutes list to town_minutes.json."""
    _ensure_dirs()
    TOWN_MINUTES_JSON.write_text(json.dumps(records, indent=2))


def board_info_for_date(date: str, history: list) -> Optional[dict]:
    """Return the board composition that was in effect on the given date, or None.

    Iterates the history list and returns the last entry whose date range covers
    the meeting date.  'to_date' of null means the entry is still current.
    Returns None if no entry matches — callers should fall back to board.json.
    """
    matched = None
    for entry in history:
        from_date = entry.get('from_date', '')
        to_date = entry.get('to_date') or '9999-12-31'
        if from_date <= date <= to_date:
            matched = entry
    if not matched:
        return None
    return {
        'chair': matched.get('chair'),
        'clerk': matched.get('clerk'),
        'members': matched.get('members', []),
    }


_KEY_DATE = 'date'


def find_meeting(meetings: list[dict], target_date: str) -> Optional[dict]:
    """Search a meetings list for an exact date match; return the dict or None."""
    for meeting in meetings:
        if meeting.get(_KEY_DATE) == target_date:
            return meeting
    return None


def upsert_meeting(meetings: list[dict], record: dict) -> list[dict]:
    """Insert or replace a meeting record matched by date.

    If a record for the same date already exists it is removed first, then the
    new record is appended and the list is re-sorted by date so it stays in
    chronological order.
    """
    record_date = record[_KEY_DATE]
    updated = [rec for rec in meetings if rec.get(_KEY_DATE) != record_date]
    updated.append(record)
    updated.sort(key=lambda rec: rec[_KEY_DATE])
    return updated
