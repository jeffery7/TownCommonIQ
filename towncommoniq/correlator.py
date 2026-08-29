"""Correlates YouTube stream videos with meeting records by date.

The core idea: a YouTube stream is "matched" to a meeting when the video's
upload date falls within _WINDOW_DAYS of the meeting date.  Once a video is
matched it cannot be used again (each video maps to exactly one meeting).
"""
from datetime import date
from types import MappingProxyType
from typing import Optional

from towncommoniq import data_store

_WINDOW_DAYS = 1

# Hardwick TV posts recordings for several town boards, and matching is by
# date alone.  A video titled for a different board than the one being synced
# can get matched onto a real meeting record that happens to share a date,
# silently attaching the wrong transcript/recording to it (this has happened
# at least once: a 2026-02-05 Board of Health hearing was matched onto that
# day's real Select Board meeting). These keywords flag that risk for human
# review rather than trying to auto-resolve it: some titles that mention
# another board (e.g. "Finance Committee Meeting") turn out on inspection to
# be genuine joint sessions, so this must not be used to silently reject a
# match — only to surface it. Keep in sync with mytowngovernment.BOARD_IDS
# when adding a newly-tracked board.
BOARD_TITLE_KEYWORDS = MappingProxyType({
    'Select Board': ('select board', 'selectmen', 'selectman'),
    'Board of Health': ('board of health',),
    'Finance Committee': ('finance committee',),
    'Gilbertville-Wheelwright Sewer Commissioners': ('sewer commission', 'sewer commissioners'),
    'Planning Board': ('planning board',),
    'Conservation Commission': ('conservation commission',),
    'Capital Planning Committee': ('capital planning',),
    'Board of Assessors': ('board of assessors', 'assessors'),
    'Master Plan Steering Committee': ('master plan steering', 'master plan'),
})
_JOINT_INDICATOR = 'joint'


def looks_like_wrong_board(title: str, expected_board: str) -> bool:
    """Return True if a video title suggests it covers a different tracked board.

    Only flags titles that mention another tracked board's name *and* give no
    indication of the expected board's involvement (no "joint" or the
    expected board's own keywords in the title). A title with no recognizable
    board name at all is never flagged. See BOARD_TITLE_KEYWORDS for why this
    is a for-review signal, not grounds for automatic exclusion of an
    existing correlation.
    """
    lowered = title.lower()
    if _JOINT_INDICATOR in lowered:
        return False
    expected_keywords = BOARD_TITLE_KEYWORDS.get(expected_board, ())
    if any(keyword in lowered for keyword in expected_keywords):
        return False
    other_keywords = (
        keyword
        for board, keywords in BOARD_TITLE_KEYWORDS.items()
        if board != expected_board
        for keyword in keywords
    )
    return any(keyword in lowered for keyword in other_keywords)


def _to_date(iso: Optional[str]) -> Optional[date]:
    """Parse an ISO-format date string (YYYY-MM-DD) into a date object.

    Returns None if the string is empty or cannot be parsed, rather than
    raising an exception — callers check for None before comparing.
    """
    if not iso:
        return None
    try:
        return date.fromisoformat(iso)
    except ValueError:
        return None


def _dates_within(
    date_a: Optional[str], date_b: Optional[str], days: int = _WINDOW_DAYS,
) -> bool:
    """Return True if two ISO date strings are within `days` of each other.

    Returns False if either string is missing or unparseable.
    """
    parsed_a = _to_date(date_a)
    parsed_b = _to_date(date_b)
    if parsed_a is None or parsed_b is None:
        return False
    return abs((parsed_a - parsed_b).days) <= days


def correlate(
    meetings: list[dict], videos: list[dict],
    expected_board: str = data_store.DEFAULT_BOARD,
) -> list[dict]:
    """Return meetings with youtube_id populated where a match is found.

    Searches within _WINDOW_DAYS of the meeting date. Each video matched once.
    `expected_board` is the board these meetings belong to (see
    looks_like_wrong_board) — used only to flag suspicious matches, not to
    reject them.
    """
    matched_video_ids: set[str] = set()
    correlated = []

    for meeting in meetings:
        if meeting.get('youtube_id'):
            correlated.append(meeting)
            matched_video_ids.add(meeting['youtube_id'])
            continue

        match = _find_video(meeting['date'], videos, matched_video_ids)
        updated = dict(meeting)
        if match:
            updated['youtube_id'] = match['video_id']
            matched_video_ids.add(match['video_id'])
            if looks_like_wrong_board(match.get('title', ''), expected_board):
                updated['video_board_mismatch'] = True
        correlated.append(updated)

    return correlated


def _closest_days(meeting_date: str, vid: dict) -> int:
    """Return the absolute day difference between a meeting date and a video date.

    Used as a sort key so that when multiple videos fall within the window,
    the closest one wins.
    """
    vid_date = vid['date']
    diff = _to_date(meeting_date) - _to_date(vid_date)  # type:ignore[operator]
    return abs(diff.days)


def _find_video(
    meeting_date: str,
    videos: list[dict],
    already_matched: set[str],
) -> Optional[dict]:
    """Return the best unmatched video for a given meeting date, or None.

    Filters to videos within _WINDOW_DAYS, then picks the one whose date is
    closest to the meeting date.  Videos already assigned to another meeting
    are excluded via `already_matched`.
    """
    candidates = [
        vid for vid in videos
        if vid.get('video_id') not in already_matched
        and _dates_within(  # type:ignore[arg-type]
            meeting_date, vid.get('date'),
        )
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda vid: _closest_days(meeting_date, vid))
