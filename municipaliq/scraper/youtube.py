"""Fetches stream metadata from the Hardwick TV YouTube channel via yt-dlp.

yt-dlp is run with --flat-playlist so it only retrieves metadata (title, ID,
upload date) without downloading any video content.  This is fast and does not
require a YouTube API key.
"""
import json
import re
import subprocess
from datetime import datetime
from typing import Optional

CHANNEL_URL = 'https://www.youtube.com/@hardwicktv2394/streams'

_YT_DLP_TIMEOUT = 120
_UPLOAD_DATE_LEN = 8
_CENTURY_OFFSET = 2000

# Matches M/D/YY, MM/DD/YY, M/D/YYYY, MM/DD/YYYY anywhere in the title.
# Handles a leading * and optional extra slash (typo like 05//12/25).
_DATE_RE = re.compile(r'\b(\d{1,2})//?\s*(\d{1,2})/(\d{2,4})\b')


def _parse_upload_date(raw: Optional[str]) -> Optional[str]:
    """Convert yt-dlp's upload_date field (YYYYMMDD) to ISO format (YYYY-MM-DD).

    Returns None if the string is missing or the wrong length rather than
    raising, so callers can fall back to _date_from_title.
    """
    if not raw or len(raw) != _UPLOAD_DATE_LEN:
        return None
    try:
        return datetime.strptime(raw, '%Y%m%d').strftime('%Y-%m-%d')
    except ValueError:
        return None


def _date_from_title(title: str) -> Optional[str]:
    """Extract the first parseable M/D/YY or M/D/YYYY date from a video title.

    Hardwick TV titles often contain the meeting date, e.g. "Select Board 3/15/24".
    Two-digit years are interpreted as 20YY.  Returns None if no date is found.
    """
    date_match = _DATE_RE.search(title)
    if not date_match:
        return None
    month, day, year_raw = (
        date_match.group(1), date_match.group(2), date_match.group(3),
    )
    year = int(year_raw)
    if year < 100:
        year += _CENTURY_OFFSET
    try:
        return datetime(year, int(month), int(day)).strftime('%Y-%m-%d')
    except ValueError:
        return None


def _entry_to_video(entry: dict) -> dict:
    """Convert a single yt-dlp playlist entry dict into a normalised video dict.

    Prefers the upload_date field for the date; falls back to parsing the title
    when yt-dlp does not return an upload date (e.g. for some live streams).
    """
    raw_url = entry.get('url', '')
    video_id = entry.get('id') or raw_url.split('v=')[-1]
    title = entry.get('title', '')
    upload_date = (
        _parse_upload_date(entry.get('upload_date'))
        or _date_from_title(title)
    )
    return {
        'video_id': video_id,
        'title': title,
        'date': upload_date,
        'url': f'https://www.youtube.com/watch?v={video_id}',
        'description': entry.get('description', ''),
    }


def fetch_streams(channel_url: str = CHANNEL_URL) -> list[dict]:
    """Return a list of stream metadata dicts from the YouTube channel."""
    cmd = [
        'yt-dlp',
        '--flat-playlist',
        '--dump-single-json',
        '--no-warnings',
        channel_url,
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_YT_DLP_TIMEOUT,
    )
    proc.check_returncode()
    playlist = json.loads(proc.stdout)
    return [_entry_to_video(entry) for entry in playlist.get('entries') or []]
