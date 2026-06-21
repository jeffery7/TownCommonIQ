"""Command-line interface for the Hardwick minutes generator.

Entry point: `python -m towncommoniq <command> [options]`

Available commands:
  sync      — refresh meeting and video data from the web
  list      — display cached meetings (optionally filtered to those missing minutes)
  archive   — download all available documents and transcripts locally
  generate  — produce a draft .docx for one or more meetings

Run `python -m towncommoniq --help` for full usage.
"""
import argparse
import io
import logging
import sys
import time
from pathlib import Path

import requests
from pypdf import PdfReader

from towncommoniq import (
    archiver, board_sync, correlator, data_store, document_index, logging_setup, reporter,
    transcript,
)
from towncommoniq.minutes_generator import generate_minutes
from towncommoniq.scraper import hardwick_town, mytowngovernment, youtube

_logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = 30
_KEY_DATE = 'date'
_KEY_YOUTUBE_ID = 'youtube_id'
_KEY_MINUTES_URL = 'minutes_url'
_KEY_FOLDER = 'folder'
_KEY_STATUS = 'status'
_KEY_MEETING_URL = 'meeting_url'
_KEY_AGENDA_URL = 'agenda_url'
_KEY_TIME = 'time'
_KEY_TITLE = 'title'


def _out(msg: str, err: bool = False) -> None:
    """Write a message to stdout (or stderr when err=True), and mirror it to the log.

    stacklevel=2 attributes the log record to _out's caller (e.g. _cmd_sync)
    rather than to _out itself, so the log's funcName column stays meaningful.
    """
    stream = sys.stderr if err else sys.stdout
    stream.write(f'{msg}\n')
    if err:
        _logger.error(msg, stacklevel=2)
    else:
        _logger.info(msg, stacklevel=2)


def _folder_file(folder: Path, name: str) -> Path:
    """Return the path to a file inside a meeting folder, prefixed by folder name.

    For example, folder=data/meetings/2024-03-15_1830, name='transcript.txt'
    → data/meetings/2024-03-15_1830/2024-03-15_1830_transcript.txt
    """
    return folder / f'{folder.name}_{name}'


def _add_youtube_only_meetings(
    meetings: list[dict], videos: list[dict],
) -> list[dict]:
    """Add placeholder meeting records for videos that have no scraped meeting.

    After correlator.correlate() runs, some videos may still be unmatched (the
    board sometimes streams meetings that do not appear on MyTownGovernment yet).
    This function creates minimal meeting dicts for them so they can still be
    processed by the generate command.

    Videos with "test" in the title (e.g. equipment/audio tests) are skipped
    since they are not real meetings.
    """
    existing_dates = {meeting[_KEY_DATE] for meeting in meetings}
    matched_ids = {
        meeting[_KEY_YOUTUBE_ID]
        for meeting in meetings
        if meeting.get(_KEY_YOUTUBE_ID)
    }
    candidates = [
        video for video in videos
        if 'test' not in video.get(_KEY_TITLE, '').lower()
    ]
    added = 0
    for video in candidates:
        if video['video_id'] in matched_ids:
            continue
        video_date = video.get(_KEY_DATE)
        if not video_date or video_date in existing_dates:
            continue
        meetings.append({
            _KEY_DATE: video_date, _KEY_TIME: '', 'location': '',
            _KEY_STATUS: 'held', _KEY_AGENDA_URL: None, _KEY_MINUTES_URL: None,
            _KEY_YOUTUBE_ID: video['video_id'], _KEY_FOLDER: None,
        })
        existing_dates.add(video_date)
        added += 1
    if added:
        _out(f'  Added {added} new meetings from YouTube videos')
    return meetings


def _assign_folders(meetings: list[dict]) -> None:
    """Ensure every meeting record has a folder path set, creating it if needed.

    Meetings from MyTownGovernment may arrive without a folder because the
    folder is only created locally.  This step runs after correlate() and
    _add_youtube_only_meetings() so all records are present before folders
    are assigned.
    """
    for meeting in meetings:
        if not meeting.get(_KEY_FOLDER):
            folder = data_store.meeting_folder(
                meeting[_KEY_DATE], meeting.get(_KEY_TIME, ''),
            )
            meeting[_KEY_FOLDER] = str(folder)


def _try_cache_agenda(meeting: dict) -> bool:
    """Fetch and save the agenda text for one meeting; return True if saved.

    Only runs for meetings that have both a YouTube video (meaning they were
    held) and a meeting_url to fetch from.  Skips meetings whose agenda file
    already exists on disk.
    """
    if not meeting.get(_KEY_YOUTUBE_ID) or not meeting.get(_KEY_FOLDER):
        return False
    agenda_path = _folder_file(Path(meeting[_KEY_FOLDER]), 'agenda.txt')
    if agenda_path.exists():
        return False
    meeting_url = meeting.get(_KEY_MEETING_URL)
    if not meeting_url:
        return False
    agenda_text = mytowngovernment.fetch_agenda_text(meeting_url)
    if agenda_text:
        agenda_path.write_text(agenda_text)
        return True
    return False


def _fetch_and_correlate() -> tuple[list[dict], list[dict]]:
    _out('Fetching meetings from MyTownGovernment.org...')
    meetings, board_info = mytowngovernment.fetch_meetings()
    _out(f'  Found {len(meetings)} meetings')
    data_store.save_board_info(board_info)
    chair = board_info.get('chair') or 'Unknown'
    _out(f'  Board chair: {chair}')

    _out('Fetching streams from YouTube...')
    videos = youtube.fetch_streams()
    _out(f'  Found {len(videos)} videos')

    _out('Correlating...')
    meetings.sort(key=lambda mtg: mtg.get(_KEY_DATE, ''))
    meetings = correlator.correlate(meetings, videos)
    matched = sum(1 for meeting in meetings if meeting.get(_KEY_YOUTUBE_ID))
    _out(f'  Matched {matched}/{len(meetings)} meetings to videos')
    return meetings, videos


def _had_minutes(date: str, old_by_date: dict) -> bool:
    """Return True if the meeting on date already had a minutes URL in old_by_date."""
    return bool(old_by_date.get(date, {}).get(_KEY_MINUTES_URL))


def _notify_new_minutes(old_meetings: list[dict], fresh: list[dict]) -> None:
    """Print a notice if any meetings gained a minutes URL since the last sync."""
    old_by_date = {mtg[_KEY_DATE]: mtg for mtg in old_meetings if mtg.get(_KEY_DATE)}
    newly_posted = [
        mtg for mtg in fresh
        if mtg.get(_KEY_DATE)
        and mtg.get(_KEY_MINUTES_URL)
        and not _had_minutes(mtg.get(_KEY_DATE, ''), old_by_date)
    ]
    if not newly_posted:
        return
    earliest = min(mtg.get(_KEY_DATE, '') for mtg in newly_posted)
    count = len(newly_posted)
    _out(
        f'  {count} meeting(s) have newly-posted official minutes'
        f' — run `archive --since {earliest}` to download',
    )


def _cmd_sync(args: argparse.Namespace) -> int:
    old_meetings = data_store.load_meetings()
    meetings, videos = _fetch_and_correlate()
    meetings = _add_youtube_only_meetings(meetings, videos)
    _assign_folders(meetings)
    meetings.sort(key=lambda mtg: mtg.get(_KEY_DATE, ''))
    data_store.save_meetings(meetings)
    data_store.save_youtube(videos)
    saved = sum(_try_cache_agenda(meeting) for meeting in meetings)
    if saved:
        _out(f'  Cached {saved} agenda(s) to meeting folders')
    _notify_new_minutes(old_meetings, meetings)
    _out('Sync complete.')
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    meetings = data_store.load_meetings()
    index = document_index.load_index()
    if args.missing:
        meetings = [
            mtg for mtg in meetings
            if not mtg.get(_KEY_MINUTES_URL) and mtg.get(_KEY_STATUS) == 'held'
        ]
    if args.no_draft:
        meetings = [
            mtg for mtg in meetings
            if not index.get(mtg.get(_KEY_DATE, ''), {}).get('draft')
        ]
    if args.has_transcript:
        meetings = [
            mtg for mtg in meetings
            if index.get(mtg.get(_KEY_DATE, ''), {}).get('transcript')
        ]
    if args.undownloaded:
        meetings = [
            mtg for mtg in meetings
            if mtg.get(_KEY_MINUTES_URL) and not _has_local_minutes(mtg)
        ]
    if not meetings:
        _out('No meetings found.')
        return 0
    for meeting in meetings:
        date_str = meeting.get(_KEY_DATE, '')
        status_str = document_index.format_status(index.get(date_str, {}))
        yt_str = meeting.get(_KEY_YOUTUBE_ID) or '(no video)'
        _out(f'  {date_str}  {status_str}  YT:{yt_str}')
    return 0


def _fetch_doc_text(doc_url: str) -> str:
    """Fetch a document (PDF or plain text) and return its text."""
    try:
        response = requests.get(doc_url, timeout=_REQUEST_TIMEOUT)
    except Exception:
        _logger.warning('Document fetch failed for %s', doc_url, exc_info=True)
        return ''
    try:
        response.raise_for_status()
    except Exception:
        _logger.warning('Document fetch failed for %s', doc_url, exc_info=True)
        return ''
    if response.content[:4] == b'%PDF':
        reader = PdfReader(io.BytesIO(response.content))
        return '\n'.join(page.extract_text() or '' for page in reader.pages)
    return response.text


def _has_local_minutes(meeting: dict) -> bool:
    """Return True if a downloaded minutes document is recorded in the meeting metadata."""
    return any(
        doc.get('type') == 'minutes' and doc.get('downloaded')
        for doc in meeting.get('posted_meeting_files', [])
    )


def _has_video_or_audio(meeting: dict) -> bool:
    """Return True if the meeting has a YouTube video or a local audio recording."""
    if meeting.get(_KEY_YOUTUBE_ID):
        return True
    folder_str = meeting.get(_KEY_FOLDER)
    if not folder_str:
        return False
    return transcript.find_audio_file(Path(folder_str)) is not None


def _eligible(meeting: dict) -> bool:
    """Return True if a meeting is a candidate for minutes generation.

    A meeting is eligible when it was held, has no official minutes URL on
    mytowngovernment.org, no locally downloaded minutes document in the
    archived metadata, and has either a correlated YouTube video or a local
    audio recording.
    """
    if meeting.get(_KEY_STATUS) != 'held':
        return False
    if meeting.get(_KEY_MINUTES_URL):
        return False
    if _has_local_minutes(meeting):
        return False
    return _has_video_or_audio(meeting)


def _cmd_generate(args: argparse.Namespace) -> int:
    meetings = data_store.load_meetings()

    if args.all or args.since:
        since = args.since or ''
        targets = [
            meeting for meeting in meetings
            if _eligible(meeting) and meeting.get(_KEY_DATE, '') >= since
        ]
    elif args.date:
        target = data_store.find_meeting(meetings, args.date)
        if not target:
            _out(f'No meeting found for date: {args.date}', err=True)
            return 1
        targets = [target]
    else:
        _out('Specify --date DATE, --since DATE, or --all', err=True)
        return 1

    if not targets:
        _out('No eligible meetings to generate minutes for.')
        return 0

    for meeting in targets:
        _generate_one(meeting, meetings, force=args.force)
    return 0


def _get_agenda_text(meeting: dict, folder: Path) -> str:
    agenda_path = _folder_file(folder, 'agenda.txt')
    if agenda_path.exists():
        _out('  Reading cached agenda...')
        return agenda_path.read_text()
    if meeting.get(_KEY_MEETING_URL):
        _out('  Fetching agenda from meeting page...')
        text = mytowngovernment.fetch_agenda_text(meeting[_KEY_MEETING_URL])
        if text:
            agenda_path.write_text(text)
        return text
    if meeting.get(_KEY_AGENDA_URL):
        _out('  Fetching agenda document...')
        text = _fetch_doc_text(meeting[_KEY_AGENDA_URL])
        if text:
            agenda_path.write_text(text)
        return text
    return ''


def _get_board_for_meeting(meeting: dict) -> dict:
    """Return the board composition that was in effect on the meeting date.

    Checks board_history.json for a date-matched entry first.  For dates
    before the earliest history entry, uses that earliest entry rather than
    the current board (which may include members not yet seated at the time).
    Falls back to the current board.json only when history is empty.
    """
    history = data_store.load_board_history()
    if not history:
        return data_store.load_board_info()
    date_str = meeting.get(_KEY_DATE, '')
    dated = data_store.board_info_for_date(date_str, history)
    if dated:
        return dated
    earliest = min(history, key=lambda entry: entry.get('from_date', ''))
    if date_str < earliest.get('from_date', ''):
        return earliest
    return data_store.load_board_info()


def _generate_one(meeting: dict, meetings: list[dict], force: bool = False) -> None:
    """Generate a minutes draft for a single meeting.

    Skips if a draft already exists unless `force=True` is passed.
    """
    date_str = meeting[_KEY_DATE]
    _out(f'Generating minutes for {date_str}...')
    folder = (
        Path(meeting[_KEY_FOLDER]) if meeting.get(_KEY_FOLDER)
        else data_store.meeting_folder(meeting[_KEY_DATE], meeting.get(_KEY_TIME, ''))
    )
    video_id = meeting.get(_KEY_YOUTUBE_ID)
    audio_file = transcript.find_audio_file(folder)
    if not video_id and not audio_file:
        _out(f'  Skipping {date_str}: no YouTube video or local audio found.')
        return

    output_path = _folder_file(folder, 'minutes_draft_generated.docx')
    if output_path.exists() and not force:
        _out(f'  Skipping {date_str}: draft already exists.')
        return

    transcript_path = _folder_file(folder, 'transcript.txt')
    _out('  Fetching/generating transcript...')
    if audio_file:
        _out(f'  Transcribing local audio ({audio_file.name})...')
        transcript_text = transcript.transcribe_audio(audio_file, transcript_path)
    else:
        transcript_text = transcript.get_transcript(video_id, transcript_path)

    agenda_text = _get_agenda_text(meeting, folder)
    _out('  Calling Ollama...')
    generate_minutes(
        meeting, agenda_text, transcript_text, output_path, _get_board_for_meeting(meeting),
    )
    _out(f'  Saved: {output_path}')


def _cmd_sync_board(args: argparse.Namespace) -> int:
    """Extract board officer assignments from reorganization meeting transcripts.

    Scans all archived meeting folders for reorganization meetings that have
    a transcript, calls the LLM to identify who was elected Chair/Vice Chair/
    Clerk, and writes the results to board_history.json.  Entries are merged
    so existing manual edits for meetings without transcripts are preserved.
    """
    _out('Scanning reorganization meeting transcripts...')
    count = board_sync.sync_board_history(verbose=True)
    _out(f'Updated {count} board history entry/entries in board_history.json.')
    return 0


def _cmd_set_attendance(args: argparse.Namespace) -> int:
    meetings = data_store.load_meetings()
    meeting = data_store.find_meeting(meetings, args.date)
    if not meeting:
        _out(f'No meeting found for date: {args.date}', err=True)
        return 1
    absent_str = args.absent or ''
    absent = [name.strip() for name in absent_str.split(',') if name.strip()]
    meeting['members_absent'] = absent
    data_store.save_meetings(meetings)
    _out(f'Set attendance for {args.date}: absent={absent}')
    return 0


def _cmd_sync_town(args: argparse.Namespace) -> int:
    """Fetch the town-website minutes listing, resolve file URLs, and download."""
    headless = not args.no_headless
    town_records = data_store.load_town_minutes()
    _out('Fetching minutes listing from hardwick-ma.gov...')
    fresh = hardwick_town.fetch_minutes_list(headless=headless)
    _out(f'  Found {len(fresh)} records')
    town_records = hardwick_town.merge_cached(fresh, town_records)
    unresolved = [rec for rec in town_records if not rec.get('file_url')]
    if unresolved:
        _out(f'  Resolving {len(unresolved)} file URL(s) via browser...')
        hardwick_town.resolve_file_urls(town_records, headless=headless)
    meetings = data_store.load_meetings()
    folders = {
        mtg[_KEY_DATE]: mtg[_KEY_FOLDER]
        for mtg in meetings
        if mtg.get(_KEY_DATE) and mtg.get(_KEY_FOLDER)
    }
    to_download = any(
        not rec.get('downloaded') and rec.get('file_url')
        and folders.get(rec.get('date', '')) and rec.get('filename')
        for rec in town_records
    )
    if to_download:
        _out('  Downloading file(s) via browser...')
        count = hardwick_town.download_all(town_records, folders, headless=headless)
    else:
        count = 0
    data_store.save_town_minutes(town_records)
    _out(f'  Downloaded {count} file(s).')
    _out('Town website sync complete.')
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    """Generate a comparison report between the two minutes sources."""
    meetings = data_store.load_meetings()
    town_records = data_store.load_town_minutes()
    report = reporter.compare_report(meetings, town_records)
    _out(report)
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(report)
        _out(f'Report saved to {args.output}')
    return 0


def _get_archive_targets(
    args: argparse.Namespace, meetings: list[dict],
):
    """Return meetings to archive, or None on invalid args / unknown date."""
    if args.all or args.since:
        since = args.since or ''
        return [mtg for mtg in meetings if mtg.get(_KEY_DATE, '') >= since]
    if not args.date:
        _out('Specify --date DATE, --since DATE, or --all', err=True)
        return None
    found = data_store.find_meeting(meetings, args.date)
    if not found:
        _out(f'No meeting found for date: {args.date}', err=True)
        return None
    return [found]


def _archive_report(summary: dict, elapsed: float) -> None:
    """Print the final archive summary line."""
    docs_n = summary['docs_saved']
    agendas_n = summary['agendas_saved']
    trans_n = summary['transcripts_saved']
    rec_n = summary.get('recordings_saved', 0)
    mins, secs = divmod(int(elapsed), 60)
    elapsed_str = f'{mins}m {secs}s' if mins else f'{secs}s'
    _out(
        f'  Saved {docs_n} document(s), {agendas_n} agenda(s),'
        f' {trans_n} transcript(s), {rec_n} recording(s) in {elapsed_str}.',
    )


def _configure_transport(args: argparse.Namespace) -> None:
    """Configure cookie and proxy settings for YouTube requests if provided."""
    if args.cookies:
        transcript.configure_cookies(args.cookies)
    if args.proxy:
        transcript.configure_proxy(args.proxy)


def _do_archive_work(
    args: argparse.Namespace, targets: list[dict], all_meetings: list[dict],
) -> None:
    """Assign folders, run the archive, persist mutations, and print a summary."""
    _assign_folders(targets)
    label = 'audio recordings' if args.audio_only else 'video recordings'
    if args.recordings:
        _out(f'Archiving {len(targets)} meeting(s) (including {label})...')
    else:
        _out(f'Archiving {len(targets)} meeting(s)...')
    t_start = time.time()
    summary = archiver.archive_all(targets, recordings=args.recordings, audio_only=args.audio_only)
    _archive_report(summary, time.time() - t_start)
    data_store.save_meetings(all_meetings)
    document_index.save_index(document_index.build_index(all_meetings))


def _cmd_archive(args: argparse.Namespace) -> int:
    """Download all available documents and transcripts for meetings."""
    _configure_transport(args)
    all_meetings = data_store.load_meetings()
    targets = _get_archive_targets(args, all_meetings)
    if targets is None:
        return 1
    if not targets:
        _out('No meetings to archive.')
        return 0
    _do_archive_work(args, targets, all_meetings)
    return 0


_ACTION_STORE_TRUE = 'store_true'
_DATE_METAVAR = 'YYYY-MM-DD'


def _add_archive_subparser(sub) -> None:
    """Register the 'archive' subcommand and its arguments."""
    arc_parser = sub.add_parser('archive', help='Download documents and transcripts')
    arc_group = arc_parser.add_mutually_exclusive_group(required=True)
    arc_group.add_argument('--date', metavar=_DATE_METAVAR, help='Archive a specific meeting')
    arc_group.add_argument(
        '--since', metavar=_DATE_METAVAR, help='Archive all meetings on or after date',
    )
    arc_group.add_argument('--all', action=_ACTION_STORE_TRUE, help='Archive all meetings')
    arc_parser.add_argument(
        '--recordings', action=_ACTION_STORE_TRUE,
        help='Also download YouTube recordings (large — ~1.5 GB per meeting)',
    )
    arc_parser.add_argument(
        '--audio-only', action=_ACTION_STORE_TRUE,
        help='With --recordings: save audio track only (~150 MB per meeting)',
    )
    arc_parser.add_argument(
        '--cookies', metavar='FILE',
        help='Netscape cookies file for bypassing YouTube IP blocks',
    )
    arc_parser.add_argument(
        '--proxy', metavar='URL',
        help='Proxy URL for YouTube requests, e.g. socks5://127.0.0.1:1080',
    )


def _add_generate_subparser(sub) -> None:
    """Register the 'generate' subcommand and its arguments."""
    gen_parser = sub.add_parser('generate', help='Generate draft minutes')
    group = gen_parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--date', metavar=_DATE_METAVAR, help='Generate for a specific date')
    group.add_argument(
        '--since', metavar=_DATE_METAVAR, help='Generate for eligible meetings on or after date',
    )
    group.add_argument('--all', action=_ACTION_STORE_TRUE, help='Generate for all missing minutes')
    gen_parser.add_argument('--force', action=_ACTION_STORE_TRUE, help='Overwrite existing drafts')


def _add_list_subparser(sub) -> None:
    """Register the 'list' subcommand and its arguments."""
    list_parser = sub.add_parser('list', help='List meetings')
    list_parser.add_argument(
        '--missing', action=_ACTION_STORE_TRUE, help='Show meetings missing official minutes',
    )
    list_parser.add_argument(
        '--no-draft', action=_ACTION_STORE_TRUE, dest='no_draft',
        help='Show meetings without a locally generated draft',
    )
    list_parser.add_argument(
        '--has-transcript', action=_ACTION_STORE_TRUE, dest='has_transcript',
        help='Show only meetings with a local transcript',
    )
    list_parser.add_argument(
        '--undownloaded', action=_ACTION_STORE_TRUE,
        help='Show meetings with official minutes URL not yet downloaded locally',
    )


def _build_arg_parser() -> argparse.ArgumentParser:
    """Construct and return the top-level argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog='python -m towncommoniq',
        description='Generate Hardwick Select Board draft meeting minutes.',
    )
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('sync', help='Refresh data from web sources')
    sub.add_parser('sync-board', help='Build board history from reorganization transcripts')
    _add_list_subparser(sub)
    _add_archive_subparser(sub)
    _add_generate_subparser(sub)
    att_parser = sub.add_parser('set-attendance', help='Record absent board members for a meeting')
    att_parser.add_argument('--date', metavar=_DATE_METAVAR, required=True, help='Meeting date')
    att_parser.add_argument(
        '--absent', metavar='NAME[,NAME,...]', default='',
        help='Comma-separated list of absent board members',
    )
    town_parser = sub.add_parser('sync-town', help='Sync minutes from hardwick-ma.gov')
    town_parser.add_argument(
        '--no-headless', action=_ACTION_STORE_TRUE, dest='no_headless',
        help='Show the Firefox browser window (useful when Cloudflare challenges occur)',
    )
    cmp_parser = sub.add_parser('compare', help='Compare minutes availability on both sites')
    cmp_parser.add_argument(
        '--output', metavar='FILE', default='',
        help='Save report to FILE in addition to printing it',
    )
    return parser


def main() -> int:
    """Parse command-line arguments and dispatch to the appropriate command handler."""
    logging_setup.configure_logging()
    args = _build_arg_parser().parse_args()
    dispatch = {
        'sync': _cmd_sync,
        'sync-board': _cmd_sync_board,
        'sync-town': _cmd_sync_town,
        'list': _cmd_list,
        'archive': _cmd_archive,
        'generate': _cmd_generate,
        'set-attendance': _cmd_set_attendance,
        'compare': _cmd_compare,
    }
    return dispatch[args.command](args)


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
