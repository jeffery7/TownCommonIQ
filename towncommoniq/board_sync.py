"""Builds board_history.json from reorganization meeting transcripts.

After each annual town election the Select Board holds a reorganization
meeting where it votes to elect a new Chair, Vice Chair, and Clerk.
This module finds those meetings in the local archive, uses the LLM to
extract the officer assignments from the transcript, and writes the
results to data/board_history.json.

For meetings that have a transcript, the extraction is automatic.
For meetings without a transcript the entry must be filled in manually.
"""
import json
import operator
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from openai import OpenAI

from towncommoniq import data_store
from towncommoniq.minutes_generator import OLLAMA_HOST, _MODEL, _strip_thinking

_REORG_RE = re.compile(r'reorgani[sz]', re.IGNORECASE)

_KEY_CHAIR = 'chair'
_KEY_VICE_CHAIR = 'vice_chair'
_KEY_CLERK = 'clerk'
_KEY_DATE = 'date'
_KEY_FROM_DATE = 'from_date'
_KEY_MEMBERS = 'members'
_KEY_FOLDER = 'folder'
_OFFICER_ROLES = (_KEY_CHAIR, _KEY_VICE_CHAIR, _KEY_CLERK)
_MAX_TRANSCRIPT_CHARS = 8000

_EXTRACT_SYSTEM = """\
You are reading a transcript of a Massachusetts town selectboard meeting.
Your task: identify who was VOTED IN (elected/nominated and seconded) as
Chair, Vice Chair, and Clerk during the board reorganization.

Known board member names (use these exact spellings): {members}

Return ONLY a JSON object — no commentary, no markdown fences — in this form:
{{"chair": "Full Name", "vice_chair": "Full Name", "clerk": "Full Name"}}

Use null for any role where no clear vote is recorded.
Match transcript names to the known member list even if the transcript
mis-spells or truncates them (e.g. "Fhheim" → "Vollheim", "Sha" → "Schaaf").
"""


def _is_reorg_meeting(folder: Path) -> bool:
    """Return True if this meeting folder has a reorganization agenda."""
    agenda = next(folder.glob('*_agenda.txt'), None)
    if not agenda:
        return False
    return bool(_REORG_RE.search(agenda.read_text()))


def _meeting_is_reorg_with_transcript(meeting: dict) -> bool:
    """Return True if the meeting has a reorg agenda and a transcript file."""
    folder_str = meeting.get(_KEY_FOLDER)
    if not folder_str:
        return False
    folder = Path(folder_str)
    if not folder.exists():
        return False
    return bool(
        _is_reorg_meeting(folder)
        and next(folder.glob('*_transcript.txt'), None),
    )


def find_reorg_meetings(meetings: list[dict]) -> list[dict]:
    """Return meetings that are reorganization meetings and have a transcript.

    Scans all meeting folders for an agenda that mentions 'reorganiz'.
    Only returns meetings that also have a transcript, since extraction
    requires one.
    """
    return [mtg for mtg in meetings if _meeting_is_reorg_with_transcript(mtg)]


def _try_json_parse(text: str) -> Optional[dict]:
    """Attempt to parse text as JSON; return None on any parse failure."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_officers(client: OpenAI, transcript_text: str, members: list[str]) -> dict:
    """Ask the LLM to pull Chair/Vice Chair/Clerk from a reorganization transcript.

    Returns a dict with keys 'chair', 'vice_chair', 'clerk' (values may be None).
    """
    system = _EXTRACT_SYSTEM.format(members=', '.join(members) if members else 'unknown')
    response = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': transcript_text[:_MAX_TRANSCRIPT_CHARS]},
        ],
    )
    raw = _strip_thinking(response.choices[0].message.content)
    parsed = _try_json_parse(raw)
    if parsed is not None:
        return parsed
    json_match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
    if json_match:
        parsed = _try_json_parse(json_match.group())
        if parsed is not None:
            return parsed
    return {_KEY_CHAIR: None, _KEY_VICE_CHAIR: None, _KEY_CLERK: None}


def _next_reorg_date(meetings: list[dict], current_date: str) -> Optional[str]:
    """Return the date of the next reorganization meeting after current_date, or None."""
    reorg_dates = sorted(
        mtg[_KEY_DATE]
        for mtg in meetings
        if mtg.get(_KEY_DATE) and _folder_is_reorg(mtg)
        and mtg[_KEY_DATE] > current_date
    )
    return reorg_dates[0] if reorg_dates else None


def _folder_is_reorg(meeting: dict) -> bool:
    """Return True if the meeting has a reorganization agenda (without reading transcript)."""
    folder_str = meeting.get(_KEY_FOLDER)
    if not folder_str:
        return False
    folder = Path(folder_str)
    if not folder.exists():
        return False
    return _is_reorg_meeting(folder)


def _day_before(date_str: str) -> str:
    """Return the ISO date one day before date_str."""
    day = date.fromisoformat(date_str)
    return (day - timedelta(days=1)).isoformat()


def _get_existing_members(history: list, from_date: str) -> list:
    """Return the members list for the history entry matching from_date, or []."""
    for hist_entry in history:
        if hist_entry.get(_KEY_FROM_DATE) == from_date:
            return hist_entry.get(_KEY_MEMBERS, [])
    return []


def build_history_entry(
    meeting: dict,
    officers: dict,
    all_meetings: list[dict],
) -> dict:
    """Construct one board_history entry from extracted officer data.

    The entry spans from the reorganization date until the day before
    the next reorganization, or null if there is no later one on record.
    """
    from_date = meeting[_KEY_DATE]
    next_date = _next_reorg_date(all_meetings, from_date)
    to_date = _day_before(next_date) if next_date else None
    existing = _get_existing_members(data_store.load_board_history(), from_date)
    names = [officers.get(role) for role in _OFFICER_ROLES]
    members = sorted(set(existing) | {name for name in names if name})
    return {
        _KEY_FROM_DATE: from_date,
        'to_date': to_date,
        _KEY_CHAIR: officers.get(_KEY_CHAIR),
        _KEY_VICE_CHAIR: officers.get(_KEY_VICE_CHAIR),
        _KEY_CLERK: officers.get(_KEY_CLERK),
        _KEY_MEMBERS: members,
    }


def _collect_known_names(history: list) -> list[str]:
    """Collect all known board member names from history and board.json."""
    names: set[str] = set(data_store.load_board_info().get(_KEY_MEMBERS) or [])
    for hist_entry in history:
        names.update(hist_entry.get(_KEY_MEMBERS) or [])
        for role in _OFFICER_ROLES:
            name = hist_entry.get(role)
            if name:
                names.add(name)
    return sorted(names)


def _process_reorg(
    client: OpenAI,
    meeting: dict,
    all_meetings: list[dict],
    known: list[str],
    verbose: bool,
) -> dict:
    """Extract officers from one reorg transcript; return {date: entry} to merge."""
    text = next(Path(meeting[_KEY_FOLDER]).glob('*_transcript.txt')).read_text()
    officers = _extract_officers(client, text, known)
    entry = build_history_entry(meeting, officers, all_meetings)
    if verbose:
        sys.stdout.write(
            f'  {meeting[_KEY_DATE]}  chair={entry[_KEY_CHAIR]}  '
            f'vice_chair={entry[_KEY_VICE_CHAIR]}  clerk={entry[_KEY_CLERK]}\n',
        )
    return {meeting[_KEY_DATE]: entry}


def sync_board_history(verbose: bool = True) -> int:
    """Extract officer assignments from all archived reorganization transcripts.

    Reads every reorganization meeting that has a transcript, calls the LLM
    to identify who was elected Chair/Vice Chair/Clerk, then merges those
    entries into board_history.json (existing entries for the same date are
    replaced).  Returns the number of entries added or updated.
    """
    client = OpenAI(base_url=f'{OLLAMA_HOST}/v1', api_key='ollama')
    meetings = data_store.load_meetings()
    reorg_meetings = find_reorg_meetings(meetings)
    history = data_store.load_board_history()
    existing_by_date = {hist[_KEY_FROM_DATE]: hist for hist in history}
    all_known = _collect_known_names(history)
    for meeting in sorted(reorg_meetings, key=operator.itemgetter(_KEY_DATE)):
        existing_by_date.update(_process_reorg(client, meeting, meetings, all_known, verbose))
    new_history = sorted(existing_by_date.values(), key=operator.itemgetter(_KEY_FROM_DATE))
    data_store.save_board_history(new_history)
    return len(reorg_meetings)
