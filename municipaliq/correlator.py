"""Correlates YouTube stream videos with meeting records by date.

The core idea: a YouTube stream is "matched" to a meeting when the video's
upload date falls within _WINDOW_DAYS of the meeting date.  Once a video is
matched it cannot be used again (each video maps to exactly one meeting).
"""
from datetime import date
from typing import Optional


_WINDOW_DAYS = 1


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


def correlate(meetings: list[dict], videos: list[dict]) -> list[dict]:
    """Return meetings with youtube_id populated where a match is found.

    Searches within _WINDOW_DAYS of the meeting date. Each video matched once.
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
