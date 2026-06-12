"""Builds a complete local archive of meeting source material.

For each meeting, documents (agendas, minutes PDFs) are downloaded and a
transcript is generated if one does not yet exist.  Draft minutes generation
is deliberately excluded — that remains the responsibility of
minutes_generator.py so the two workflows stay independent.
"""
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from termcolor import colored as _tc

from municipaliq import data_store, downloader, transcript
from municipaliq.scraper import mytowngovernment

_KEY_DOCS = 'docs_saved'
_KEY_AGENDA = 'agenda_saved'
_KEY_TRANS = 'transcript_saved'
_STATUS_CANCELLED = 'cancelled'
_ATTR_BOLD = ('bold',)
_ATTR_DARK = ('dark',)
_UNSAFE_FILENAME_RE = re.compile(r'[/\\:*?"<>|]')
_CLEANUP_STEM_RE = re.compile(r'_download(_text)?$')
_STALE_MINUTES_RE = re.compile(r'_minutes$')
_DOC_EXTENSIONS = frozenset(('.pdf', '.docx', '.doc', '.bin'))
_KEY_DOCUMENTS = 'documents'

_DOC_TYPE_MINUTES = 'minutes'
_DOC_TYPE_AGENDA = 'agenda'
_DOC_TYPE_UNKNOWN = 'unknown'
_KEY_DOC_TYPE = 'type'
_KEY_LOCAL_FILENAME = 'local_filename'
_KEY_DOWNLOADED = 'downloaded'
_TZ_ABBREV_RE = re.compile(r'\s+[A-Z]{2,4}$')
_DOC_DATE_FMT = '%b %d, %Y %I:%M %p'
_MEETING_DATE_FMT = '%Y-%m-%d'


def _col(text: str, color=None, attrs=None) -> str:
    """Apply ANSI color when stdout is a real interactive terminal.

    Respects the NO_COLOR environment variable.  Returns plain text when output
    is piped, redirected, or NO_COLOR is set so log files stay clean.
    """
    is_tty = getattr(sys.stdout, 'isatty', bool)()
    if is_tty and 'NO_COLOR' not in os.environ:
        return _tc(text, color, attrs=attrs)
    return text


def _ts() -> str:
    """Return a date+time prefix for log lines."""
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return f'[{stamp}] '


def _safe_filename(name: str) -> str:
    """Sanitize a server-provided filename for local storage.

    Removes characters illegal on common filesystems while preserving spaces,
    dots, and the original extension so the name stays human-readable.
    """
    return _UNSAFE_FILENAME_RE.sub('_', name).strip()


def _needs_download(dest: Path) -> bool:
    """Return True if dest should be fetched (or ETag-validated) from the server.

    Files that already exist without an ETag sidecar are assumed unchanged and
    skipped — many government servers omit ETags, so without one there is no
    way to detect updates, and re-fetching every run wastes bandwidth.
    """
    if not dest.exists():
        return True
    return bool(downloader._saved_etag(dest))


def _doc_is_new(doc: dict, folder: Path) -> bool:
    """Download a single page-data document; return True if it was newly saved."""
    filename = _safe_filename(doc.get('filename', ''))
    if not filename:
        return False
    dest = folder / filename
    if not _needs_download(dest):
        return False
    existed = dest.exists()
    return bool(downloader._try_download(doc['url'], dest)) and not existed


def _download_from_page_data(documents: list, folder: Path) -> int:
    """Download each document using its original server-side filename.

    Returns the number of newly saved files.  Files already on disk are
    skipped unless an ETag sidecar exists for conditional validation.
    """
    saved = 0
    for doc in documents:
        if _doc_is_new(doc, folder):
            saved += 1
    return saved


def _is_stale_minutes_doc(path: Path) -> bool:
    """Return True if path is an old canonical-named minutes document.

    Detects files whose stem ends with '_minutes' and whose extension is a
    known document format — these were written by the previous label-based
    archive flow and are superseded by original-named files from page_data.
    """
    stem_matches = bool(_STALE_MINUTES_RE.search(path.stem))
    return stem_matches and path.suffix.lower() in _DOC_EXTENSIONS


def _cleanup_folder(folder: Path, page_docs: list = None) -> int:
    """Remove intermediate files left by the previous archive approach.

    Always deletes files whose stem ends with '_download' or '_download_text'.
    When page_docs is non-empty (original-named files are present), also
    removes old canonical '_minutes.{pdf,docx,doc}' duplicates.
    Returns the number of files deleted.
    """
    removed = 0
    for path in list(folder.iterdir()):
        if _CLEANUP_STEM_RE.search(path.stem):
            path.unlink()
            removed += 1
        elif page_docs and _is_stale_minutes_doc(path):
            path.unlink()
            removed += 1
    return removed


def _parse_doc_date(created_str: str) -> Optional[date]:
    """Parse a MyTownGovernment 'created' timestamp; return None on failure.

    The format is 'Mar 25, 2014 8:22 AM EDT' — the timezone abbreviation
    varies (EST, EDT, ET …) and is stripped before parsing.
    """
    clean = _TZ_ABBREV_RE.sub('', created_str.strip())
    try:
        return datetime.strptime(clean, _DOC_DATE_FMT).date()
    except ValueError:
        return None


def _classify_doc(
    doc: dict,
    meeting_date: date,
    minutes_url: str,
    agenda_url: str,
) -> str:
    """Return 'minutes', 'agenda', or 'unknown' for a single page-data document.

    Priority: URL match against known minutes/agenda URLs, then upload date
    relative to the meeting date (documents uploaded after the meeting are
    almost always minutes; those uploaded before are agendas).
    """
    url = doc.get('url', '')
    if minutes_url and url == minutes_url:
        return _DOC_TYPE_MINUTES
    if agenda_url and url == agenda_url:
        return _DOC_TYPE_AGENDA
    created = _parse_doc_date(doc.get('created', ''))
    if created is None:
        return _DOC_TYPE_UNKNOWN
    return _DOC_TYPE_MINUTES if created > meeting_date else _DOC_TYPE_AGENDA


def _enrich_doc(
    doc: dict,
    meeting_date: Optional[date],
    minutes_url: str,
    agenda_url: str,
    folder: Path,
) -> dict:
    """Return a copy of doc with type, local_filename, and downloaded added."""
    doc = dict(doc)
    if meeting_date is None:
        doc[_KEY_DOC_TYPE] = _DOC_TYPE_UNKNOWN
    else:
        doc[_KEY_DOC_TYPE] = _classify_doc(doc, meeting_date, minutes_url, agenda_url)
    local = _safe_filename(doc.get('filename', ''))
    doc[_KEY_LOCAL_FILENAME] = local
    doc[_KEY_DOWNLOADED] = bool(local and (folder / local).exists())
    return doc


def _enrich_documents(
    documents: list,
    meeting: dict,
    folder: Path,
) -> list:
    """Return documents list with type, local_filename, and downloaded added.

    Each document is classified as 'minutes', 'agenda', or 'unknown' based
    on URL match or upload date relative to the meeting date.  The
    local_filename field holds the sanitised on-disk name; downloaded is
    True when that file currently exists in the meeting folder.
    """
    date_str = meeting.get('date', '')
    try:
        meeting_date = datetime.strptime(date_str, _MEETING_DATE_FMT).date()
    except ValueError:
        meeting_date = None
    minutes_url = meeting.get('minutes_url') or ''
    agenda_url = meeting.get('agenda_url') or ''
    return [
        _enrich_doc(doc, meeting_date, minutes_url, agenda_url, folder)
        for doc in documents
    ]


def _ensure_agenda(meeting: dict, folder: Path) -> bool:
    """Fetch and cache agenda text from the meeting's web page; return True if saved.

    Uses the meeting_url field which points to the individual meeting page on
    MyTownGovernment.org.  Skips silently if the URL is absent, the page has
    no agenda section, or the agenda file is already cached on disk.
    """
    agenda_path = folder / f'{folder.name}_agenda.txt'
    if agenda_path.exists():
        return False
    meeting_url = meeting.get('meeting_url')
    if not meeting_url:
        return False
    text = mytowngovernment.fetch_agenda_text(meeting_url)
    if not text:
        return False
    agenda_path.write_text(text)
    return True


def _ensure_transcript(meeting: dict, folder: Path) -> bool:
    """Ensure a transcript file exists for the meeting; return True if created.

    Priority order:
      1. YouTube auto-captions (fast, preferred).
      2. Local .ogg/.m4a audio file → Whisper.
      3. Local recording file (.mp4 etc.) → Whisper.
    Returns False if already cached or no source is available.
    """
    transcript_path = folder / f'{folder.name}_transcript.txt'
    if transcript_path.exists():
        return False
    video_id = meeting.get('youtube_id')
    if video_id:
        sys.stdout.write(f'{_ts()}    {_col("→ fetching YouTube captions...", "cyan")}\n')
        sys.stdout.flush()
        if transcript.get_captions(video_id, transcript_path):
            return True
    audio_file = transcript.find_audio_file(folder)
    if audio_file:
        msg = f'→ transcribing {audio_file.name} with Whisper (may take several minutes)...'
        sys.stdout.write(f'{_ts()}    {_col(msg, "cyan")}\n')
        sys.stdout.flush()
        transcript.transcribe_audio(audio_file, transcript_path)
        return True
    recording = transcript.find_recording_file(folder)
    if recording:
        msg = f'→ transcribing {recording.name} with Whisper (may take several minutes)...'
        sys.stdout.write(f'{_ts()}    {_col(msg, "cyan")}\n')
        sys.stdout.flush()
        transcript.transcribe_audio(recording, transcript_path)
        return True
    return False


def _ensure_recording(meeting: dict, folder: Path, audio_only: bool = False) -> bool:
    """Download the YouTube recording for a meeting if not already on disk.

    Saves the file as {folder_name}_recording.mp4 (video) or
    {folder_name}_recording.m4a (audio-only).  Skips silently if the meeting
    has no YouTube ID or a recording file already exists.  Returns True if a
    new file was saved.
    """
    if transcript.find_recording_file(folder):
        return False
    video_id = meeting.get('youtube_id')
    if not video_id:
        return False
    ext = '.m4a' if audio_only else '.mp4'
    dest = folder / f'{folder.name}_recording{ext}'
    try:
        transcript.download_recording(video_id, dest, audio_only=audio_only)
    except Exception:
        return False
    return True


_KEY_RECORDING = 'recording_saved'
_KEY_AGENDA_EXISTS = 'agenda_exists'
_KEY_TRANS_EXISTS = 'transcript_exists'
_KEY_REC_EXISTS = 'recording_exists'
_KEY_OFFICIAL_DOCS = 'official_docs'
_UNKNOWN_DOC_COUNT = -1  # page data unavailable — official count unknown


def _is_cancelled(meeting: dict) -> bool:
    """Return True when a meeting is cancelled.

    Checks both the 'status' field (set by scraper going forward) and the
    legacy case where status is 'held' but location is 'Cancelled' (older
    scraped records before the scraper learnt to detect cancellations).
    """
    status = meeting.get('status', '')
    return status == _STATUS_CANCELLED or (
        status == 'held' and meeting.get('location', '').lower() == _STATUS_CANCELLED
    )


def _save_meeting_page_data(meeting: dict, folder: Path) -> dict:
    """Fetch and save supplementary meeting page data to a JSON sidecar.

    Writes {folder}/{folder_name}_page_data.json containing the original
    document filenames with sizes and created dates, the revision history, and
    meeting-level metadata (scheduled_by, posted_at, last_modified).  Always
    overwrites so the revision history stays current.

    Returns the fetched data dict so callers can inspect it (e.g. to count
    official documents).  Returns an empty dict when the meeting has no
    meeting_url or the page cannot be fetched.
    """
    meeting_url = meeting.get('meeting_url')
    if not meeting_url:
        return {}
    fetched = mytowngovernment.fetch_meeting_page_data(meeting_url)
    if not fetched:
        return {}
    out_path = folder / f'{folder.name}_page_data.json'
    out_path.write_text(json.dumps(fetched, indent=2))
    return fetched


def _count_all_docs(documents: list, folder: Path) -> int:
    """Download all docs from the page-data list; return the count of newly saved files."""
    return _download_from_page_data(documents, folder)


def _status_mark(saved: int, exists: bool) -> str:
    """'+' if newly saved this run, '=' if already present, '-' if absent."""
    if saved:
        return '+'
    return '=' if exists else '-'


def archive_meeting(
    meeting: dict,
    folder: Path,
    recordings: bool = False,
    audio_only: bool = False,
) -> dict:
    """Download all available documents and ensure agenda text and transcript exist.

    When recordings=True the YouTube video (or audio track when audio_only=True)
    is also downloaded to the meeting folder.

    Returns a summary dict with:
      'docs_saved'         — number of PDF/DOCX documents newly downloaded
      'agenda_saved'       — 1 if agenda text was newly fetched, else 0
      'agenda_exists'      — True if agenda text file is present
      'transcript_saved'   — 1 if a transcript was newly created, else 0
      'transcript_exists'  — True if transcript file is present
      'recording_saved'    — 1 if a recording was newly downloaded, else 0
      'recording_exists'   — True if a recording file is present
    """
    page_data = _save_meeting_page_data(meeting, folder)
    raw_docs = page_data.get(_KEY_DOCUMENTS, []) if page_data else []
    official_docs = len(raw_docs) if page_data else _UNKNOWN_DOC_COUNT
    _cleanup_folder(folder, raw_docs or None)
    if _is_cancelled(meeting):
        meeting['posted_meeting_files'] = _enrich_documents(raw_docs, meeting, folder)
        data_store.save_meeting_metadata(meeting, folder)
        return {
            _KEY_DOCS: 0, _KEY_OFFICIAL_DOCS: official_docs,
            _KEY_AGENDA: 0, _KEY_AGENDA_EXISTS: False,
            _KEY_TRANS: 0, _KEY_TRANS_EXISTS: False,
            _KEY_RECORDING: 0, _KEY_REC_EXISTS: False,
        }
    docs_count = _count_all_docs(raw_docs, folder)
    meeting['posted_meeting_files'] = _enrich_documents(raw_docs, meeting, folder)
    data_store.save_meeting_metadata(meeting, folder)
    agenda_saved = 1 if _ensure_agenda(meeting, folder) else 0
    transcript_saved = 1 if _ensure_transcript(meeting, folder) else 0
    recording_saved = 1 if (
        recordings and _ensure_recording(meeting, folder, audio_only=audio_only)
    ) else 0
    return {
        _KEY_DOCS: docs_count,
        _KEY_OFFICIAL_DOCS: official_docs,
        _KEY_AGENDA: agenda_saved,
        _KEY_AGENDA_EXISTS: bool(agenda_saved) or (folder / f'{folder.name}_agenda.txt').exists(),
        _KEY_TRANS: transcript_saved,
        _KEY_TRANS_EXISTS: (
            bool(transcript_saved) or (folder / f'{folder.name}_transcript.txt').exists()
        ),
        _KEY_RECORDING: recording_saved,
        _KEY_REC_EXISTS: bool(recording_saved) or bool(transcript.find_recording_file(folder)),
    }


def _log_start(num: int, total: int, meeting: dict) -> None:
    """Print the per-meeting header line before any work begins."""
    date_str = meeting.get('date', '?')
    width = len(str(total))
    status = meeting.get('status', '')
    if status == 'held' and meeting.get('location', '').lower() == _STATUS_CANCELLED:
        status = _STATUS_CANCELLED
    prefix = f'[{num:{width}}/{total}] {date_str}'
    if status == _STATUS_CANCELLED:
        header = _col(f'{prefix}  [{_STATUS_CANCELLED}]', attrs=_ATTR_DARK)
    else:
        header = _col(prefix, 'white', attrs=_ATTR_BOLD)
        if status and status != 'held':
            status_tag = _col(f'[{status}]', 'yellow')
            header = f'{header}  {status_tag}'
    sys.stdout.write(f'{_ts()}{header}\n')
    sys.stdout.flush()


def _colored_field(label: str, mark: str, critical: bool = False) -> str:
    """Return 'label:mark' colored by marker.

    '+' → bold green, '=' → dim, '-' → yellow normally or bright red when
    critical=True (used for agenda which should never be absent on a held meeting).
    """
    text = f'{label}:{mark}'
    if mark == '+':
        return _col(text, 'green', attrs=_ATTR_BOLD)
    if mark == '=':
        return _col(text, 'white', attrs=_ATTR_DARK)
    if critical:
        return _col(text, 'light_red', attrs=_ATTR_BOLD)
    return _col(text, 'yellow')


def _log_progress(summary: dict, cancelled: bool = False) -> None:
    """Write indented result detail showing current state of each file type.

    Markers: '+' newly saved this run, '=' already present, '-' absent.
    When cancelled=True the entire detail line is dim and no colours are applied.
    Always prints so every meeting's folder state is visible.
    The per-meeting header is always printed by archive_all via _log_start.
    """
    if cancelled:
        sys.stdout.write(
            f'{_ts()}    {_col("docs:0  agenda:-  trans:-  rec:-", attrs=_ATTR_DARK)}\n',
        )
        return
    docs_new = summary[_KEY_DOCS]
    docs_official = summary.get(_KEY_OFFICIAL_DOCS, _UNKNOWN_DOC_COUNT)
    if docs_official == _UNKNOWN_DOC_COUNT:
        docs_text = _col('docs:?', 'yellow')
    elif docs_official == 0:
        docs_text = _col('docs:0', 'red')
    else:
        docs_text = _col(f'docs:{docs_official}', 'green')
        if docs_new > 0:
            docs_text += _col(f'(+{docs_new})', 'green', attrs=_ATTR_BOLD)
    agenda_mark = _status_mark(summary[_KEY_AGENDA], summary.get(_KEY_AGENDA_EXISTS, False))
    trans_mark = _status_mark(summary[_KEY_TRANS], summary.get(_KEY_TRANS_EXISTS, False))
    rec_mark = _status_mark(summary.get(_KEY_RECORDING, 0), summary.get(_KEY_REC_EXISTS, False))
    sys.stdout.write(
        f'{_ts()}    {docs_text}  {_colored_field("agenda", agenda_mark, critical=True)}'
        f'  {_colored_field("trans", trans_mark)}  {_colored_field("rec", rec_mark)}\n',
    )


def _archive_one(
    num: int,
    total: int,
    meeting: dict,
    recordings: bool,
    audio_only: bool,
) -> dict:
    """Archive a single meeting and log its progress; return the summary dict."""
    _log_start(num, total, meeting)
    folder_str = meeting.get('folder')
    if not folder_str:
        return {}
    summary = archive_meeting(
        meeting, Path(folder_str),
        recordings=recordings, audio_only=audio_only,
    )
    _log_progress(summary, cancelled=_is_cancelled(meeting))
    return summary


def archive_all(
    meetings: list[dict],
    recordings: bool = False,
    audio_only: bool = False,
) -> dict:
    """Archive every meeting that has a folder path assigned.

    Skips meetings whose 'folder' key is absent or empty (they have not
    been through sync yet).  Logs a line for each meeting where something
    new was saved.  Returns aggregate counts:
      'docs_saved'        — total new documents downloaded
      'agendas_saved'     — total new agenda text files fetched
      'transcripts_saved' — total new transcripts created
      'recordings_saved'  — total new recordings downloaded
    """
    total_docs = 0
    total_agendas = 0
    total_transcripts = 0
    total_recordings = 0
    total = len(meetings)
    for num, meeting in enumerate(meetings, 1):
        summary = _archive_one(num, total, meeting, recordings, audio_only)
        total_docs += summary.get(_KEY_DOCS, 0)
        total_agendas += summary.get(_KEY_AGENDA, 0)
        total_transcripts += summary.get(_KEY_TRANS, 0)
        total_recordings += summary.get(_KEY_RECORDING, 0)
    return {
        'docs_saved': total_docs,
        'agendas_saved': total_agendas,
        'transcripts_saved': total_transcripts,
        'recordings_saved': total_recordings,
    }
