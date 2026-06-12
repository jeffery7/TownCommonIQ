"""Indexes local file availability across all meeting folders.

After running 'archive', use this module to find gaps (meetings missing
transcripts, agendas, etc.) without querying the network.  The index is a
snapshot written to data/index.json; call build_index() and save_index()
to refresh it after new content is archived.

Tracked file types:
  agenda     — any file whose name contains 'agenda' (text or PDF), or a
               document classified as 'agenda' in the meeting metadata
  minutes    — any PDF/DOCX whose name contains 'minute' but not 'draft',
               or a document classified as 'minutes' in the meeting metadata
  transcript — *_transcript.txt
  draft      — *_minutes_draft_generated.docx

Filename-based detection is the first pass.  When it fails (e.g. for old
government files named by date like '01272014.doc.docx.doc'), the metadata
written by the archiver into *_meeting.json is used as a fallback.  That
metadata records an authoritative 'type' field for each downloaded document.
"""
import json
from pathlib import Path

from municipaliq import data_store

_INDEX_JSON = data_store.DATA_DIR / 'index.json'
_DOC_SUFFIXES = frozenset(('.pdf', '.docx', '.doc'))
_TYPE_AGENDA = 'agenda'
_DOC_TYPES = (_TYPE_AGENDA, 'minutes', 'transcript', 'draft')


def _is_minutes_doc(path: Path) -> bool:
    """Return True for a document file whose name indicates it is minutes."""
    name = path.name.lower()
    return path.suffix.lower() in _DOC_SUFFIXES and 'minute' in name and 'draft' not in name


def _is_agenda_doc(path: Path) -> bool:
    """Return True for any file whose name contains 'agenda'."""
    return _TYPE_AGENDA in path.name.lower()


def _is_transcript(path: Path) -> bool:
    """Return True for the canonical transcript file."""
    return path.name.endswith('_transcript.txt')


def _is_draft(path: Path) -> bool:
    """Return True for a generated draft minutes document."""
    return path.name.endswith('_minutes_draft_generated.docx')


def _typed_doc_present(folder: Path, doc_type: str) -> bool:
    """Return True if the meeting metadata records a downloaded doc of doc_type.

    Reads {folder}/{folder.name}_meeting.json and checks the
    posted_meeting_files list for an entry whose 'type' matches and whose
    'downloaded' flag is True.  Returns False when the metadata file is
    absent or contains no matching entry.
    """
    meta_path = folder / f'{folder.name}_meeting.json'
    if not meta_path.exists():
        return False
    meeting = json.loads(meta_path.read_text())
    return any(
        doc.get('type') == doc_type and doc.get('downloaded')
        for doc in meeting.get('posted_meeting_files', [])
    )


def scan_folder(folder: Path) -> dict:
    """Return {doc_type: bool} showing which tracked files exist in folder.

    First pass: filename-based detection (both original server-side names
    like '08102015 Minutes.pdf' and canonical names are recognised).
    Fallback: the 'type' metadata written by the archiver into
    *_meeting.json is consulted for documents with non-standard names.
    Returns all-False if the folder does not exist.
    """
    if not folder.is_dir():
        return dict.fromkeys(_DOC_TYPES, False)
    files = list(folder.iterdir())
    has_minutes = (
        any(_is_minutes_doc(path) for path in files)
        or _typed_doc_present(folder, 'minutes')
    )
    has_agenda = (
        any(_is_agenda_doc(path) for path in files)
        or _typed_doc_present(folder, _TYPE_AGENDA)
    )
    return {
        _TYPE_AGENDA: has_agenda,
        'minutes': has_minutes,
        'transcript': any(_is_transcript(path) for path in files),
        'draft': any(_is_draft(path) for path in files),
    }


def build_index(meetings: list[dict]) -> dict:
    """Scan every meeting folder and return a date-keyed availability index.

    Meetings without a 'folder' entry (not yet synced) are skipped.
    Returns {date: {doc_type: bool, ...}, ...}.
    """
    index = {}
    for meeting in meetings:
        date_str = meeting.get('date')
        folder_str = meeting.get('folder')
        if date_str and folder_str:
            index[date_str] = scan_folder(Path(folder_str))
    return index


def save_index(index: dict) -> None:
    """Write the index dict to data/index.json."""
    _INDEX_JSON.write_text(json.dumps(index, indent=2))


def load_index() -> dict:
    """Load the index from data/index.json; return an empty dict if absent."""
    if not _INDEX_JSON.exists():
        return {}
    return json.loads(_INDEX_JSON.read_text())


def missing(index: dict, doc_type: str) -> list:
    """Return a sorted list of meeting dates that lack the given doc_type.

    Example: missing(index, 'transcript') lists all meetings without a
    locally cached transcript file.
    """
    dates = []
    for date, docs in index.items():
        if not docs.get(doc_type):
            dates.append(date)
    return sorted(dates)


def format_status(docs: dict) -> str:
    """Format a scan-result dict as a compact one-line string.

    Each tracked doc type is shown as 'key:Y' (present) or 'key:N' (absent).
    Example: 'agenda:Y  minutes:N  transcript:Y  draft:N'
    """
    parts = []
    for key, present in docs.items():
        indicator = 'Y' if present else 'N'
        parts.append(f'{key}:{indicator}')
    return '  '.join(parts)
