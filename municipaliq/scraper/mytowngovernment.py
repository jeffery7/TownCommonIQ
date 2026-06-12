"""Scrapes meeting data from the Hardwick MyTownGovernment page.

The board page has three named anchor sections:
  - "Upcoming" — table of future meetings
  - "Past"     — table of past meetings (each row is one held meeting)
  - "Docs"     — table of downloadable documents (agendas, minutes PDFs)

This module fetches and parses all three, then merges the document URLs into
the meeting records so the rest of the pipeline has everything in one place.
"""
import contextlib
import re
from datetime import datetime
from types import MappingProxyType
from typing import Optional

import requests
from bs4 import BeautifulSoup

BOARD_URL = (
    'https://www.mytowngovernment.org/board'
    '?board=ahNzfnRvd25nb3Zlcm5tZW50LWhychILEgpCb2FyZE1vZGVsGNn3FAw'
)
BASE_URL = 'https://www.mytowngovernment.org'

_HEADERS = MappingProxyType({
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'
    ),
})

_REQUEST_TIMEOUT = 30
_DATE_FORMATS = ('%b %d, %Y', '%B %d, %Y', '%B %d %Y', '%m/%d/%Y')
# Matches the 'Agenda:' label cell on individual meeting pages (allows whitespace)
_AGENDA_LABEL_RE = re.compile(r'^\s*Agenda:\s*$')

# Matches dates like "April 10, 2023" in document filenames
_FILENAME_DATE_RE = re.compile(
    r'(January|February|March|April|May|June|July|August|September|'
    r'October|November|December)\s+\d{1,2},?\s+\d{4}',
    re.IGNORECASE,
)

# Matches time like "5:30 PM EDT" or "6:30 PM"
_TIME_RE = re.compile(r'(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)(?:\s+\w+)?)')

_TAG_TR = 'tr'
_TAG_TD = 'td'
_TAG_A = 'a'
_TAG_TABLE = 'table'
_ATTR_HREF = 'href'
_KEY_AGENDA_URL = 'agenda_url'
_KEY_MINUTES_URL = 'minutes_url'

# Role titles that may appear inline in the Members cell alongside names
_ROLE_TITLE_RE = re.compile(r'^(chair|vice\s+chair|clerk|member)s?$', re.IGNORECASE)

# Individual meeting page — section headings and label keys
_SECTION_DOCS = 'Minutes and Associated Documents'
_SECTION_REVISIONS = 'Meeting Revision History'
_LABEL_SCHEDULED_BY = 'Scheduled By:'
_LABEL_POSTED_AT = 'Posted At:'
_LABEL_LAST_MODIFIED = 'Last Modified:'
_HEADING_TAGS = ('b', 'strong', 'h2', 'h3', 'h4')
# Strips " ( download )" suffix from document link text to recover the original filename
_RE_DOWNLOAD_SUFFIX = re.compile(r'\s*\(\s*download\s*\)\s*$', re.IGNORECASE)


def _parse_date(raw: str) -> Optional[str]:
    """Try each known date format in turn; return the first ISO match or None.

    Handles formats like "March 15, 2024", "Mar 15, 2024", and "03/15/2024".
    """
    stripped = raw.strip()
    for fmt in _DATE_FORMATS:
        with contextlib.suppress(ValueError):
            return datetime.strptime(stripped, fmt).strftime('%Y-%m-%d')
    return None


def _split_datetime_cell(text: str) -> tuple[Optional[str], str]:
    """Return (ISO date, time string) from a combined datetime cell."""
    time_match = _TIME_RE.search(text)
    time_str = time_match.group(1).strip() if time_match else ''
    return _parse_date(_TIME_RE.sub('', text).strip()), time_str


def _absolute(href: str) -> str:
    """Prepend BASE_URL to a relative href; leave absolute URLs unchanged."""
    if href.startswith('http'):
        return href
    return BASE_URL + href


def _blank_meeting_dict(
    date_str: str, time_str: str, location: str, status: str, row,
) -> dict:
    """Build a meeting dict pre-populated with None for all optional fields.

    The meeting_url is extracted from the row's anchor tags so it is available
    for later agenda fetching even before the docs table is processed.
    """
    meeting_url = next(
        (_absolute(anchor[_ATTR_HREF]) for anchor in row.find_all(_TAG_A, href=True)
         if '/meeting?' in anchor[_ATTR_HREF]),
        None,
    )
    return {
        'date': date_str,
        'time': time_str,
        'location': location,
        'status': status,
        _KEY_AGENDA_URL: None,
        _KEY_MINUTES_URL: None,
        'meeting_url': meeting_url,
        'youtube_id': None,
        'folder': None,
    }


def _upcoming_row(row) -> Optional[dict]:
    """Parse one row from the Upcoming meetings table; return a dict or None.

    The date/time is in column index 1 (index 0 is a blank status column).
    Returns None for header rows or rows with unparseable dates.
    """
    cells = row.find_all(_TAG_TD)
    num_cells = len(cells)
    if num_cells < 2:
        return None
    date_str, time_str = _split_datetime_cell(
        cells[1].get_text(' ', strip=True),
    )
    if not date_str:
        return None
    location = _location_from_cell(cells[2]) if num_cells > 2 else ''
    return _blank_meeting_dict(date_str, time_str, location, 'upcoming', row)


def _parse_upcoming_table(table) -> list[dict]:
    """Parse all data rows in the Upcoming meetings table, skipping the header."""
    rows = table.find_all(_TAG_TR)[1:]
    return list(filter(None, (_upcoming_row(row) for row in rows)))


def _location_from_cell(cell) -> str:
    """Extract location text from a table cell, preferring link text over plain text."""
    loc_link = cell.find(_TAG_A)
    if loc_link:
        return loc_link.get_text(strip=True)
    return cell.get_text(strip=True)


def _past_row(row) -> Optional[dict]:
    """Parse one row from the Past meetings table; return a dict or None.

    The date/time is in column index 0 (unlike Upcoming where it is index 1).
    Returns None for header rows or rows with unparseable dates.
    """
    cells = row.find_all(_TAG_TD)
    if len(cells) < 2:
        return None
    date_str, time_str = _split_datetime_cell(
        cells[0].get_text(' ', strip=True),
    )
    if not date_str:
        return None
    location = _location_from_cell(cells[1])
    status = 'cancelled' if location.lower() == 'cancelled' else 'held'
    return _blank_meeting_dict(date_str, time_str, location, status, row)


def _parse_past_table(table) -> list[dict]:
    """Parse the Past anchor's table — one row per past meeting."""
    rows = table.find_all(_TAG_TR)[1:]
    return list(filter(None, (_past_row(row) for row in rows)))


def _apply_doc_link(doc_entry: dict, link, row_lower: str) -> None:
    """Classify a download link as an agenda or minutes URL and store it.

    Skips links that are not download links (e.g. 'View' links).  Unlabelled
    download links default to minutes_url if one has not been set yet.
    """
    href = link[_ATTR_HREF]
    if 'download' not in href:
        return
    label = link.get_text(strip=True).lower()
    if 'agenda' in label or 'agenda' in row_lower:
        doc_entry[_KEY_AGENDA_URL] = _absolute(href)
    elif 'minute' in label or 'minute' in row_lower:
        doc_entry[_KEY_MINUTES_URL] = _absolute(href)
    elif not doc_entry[_KEY_MINUTES_URL]:
        doc_entry[_KEY_MINUTES_URL] = _absolute(href)


def _process_docs_row(date_docs: dict, row) -> None:
    """Extract the date from a document row and classify any download links.

    Skips rows that contain no recognisable date (e.g. header rows).  Updates
    `date_docs` in-place with {date: {agenda_url, minutes_url}} entries.
    """
    row_text = row.get_text(' ', strip=True)
    date_match = _FILENAME_DATE_RE.search(row_text)
    if not date_match:
        return
    date_str = _parse_date(date_match.group(0))
    if not date_str:
        return
    if date_str not in date_docs:
        date_docs[date_str] = {_KEY_AGENDA_URL: None, _KEY_MINUTES_URL: None}
    row_lower = row_text.lower()
    for link in row.find_all(_TAG_A, href=True):
        _apply_doc_link(date_docs[date_str], link, row_lower)


def _parse_docs_table(table) -> dict[str, dict]:
    """Return {date: {agenda_url, minutes_url}} from the documents table."""
    date_docs: dict[str, dict] = {}
    for row in table.find_all(_TAG_TR)[1:]:
        _process_docs_row(date_docs, row)
    return date_docs


def _do_request(url: str):
    """Perform a GET request with the configured timeout and browser User-Agent.

    Raises requests.HTTPError if the server returns a 4xx or 5xx status.
    """
    response = requests.get(url, timeout=_REQUEST_TIMEOUT, headers=_HEADERS)
    response.raise_for_status()
    return response


def _fetch_soup(url: str) -> Optional[BeautifulSoup]:
    """Fetch a URL and parse it into a BeautifulSoup tree; return None on any error.

    Silently swallows all exceptions so callers can treat a failed fetch as
    'no content available' rather than crashing the whole pipeline.
    """
    try:
        return BeautifulSoup(_do_request(url).text, 'html.parser')
    except Exception:
        return None


def _scrape_label_value(soup: BeautifulSoup, label: str) -> str:
    """Return the text of the cell that follows a two-cell row whose first cell matches label."""
    for row in soup.find_all(_TAG_TR):
        cells = row.find_all(_TAG_TD)
        if len(cells) < 2:
            continue
        if cells[0].get_text(strip=True) == label:
            return cells[1].get_text(' ', strip=True)
    return ''


def _find_section_table(soup: BeautifulSoup, section_text: str):
    """Return the first table that follows a heading tag containing section_text, or None."""
    for tag in soup.find_all(_HEADING_TAGS):
        if section_text in tag.get_text(strip=True):
            return tag.find_next(_TAG_TABLE)
    return None


def _scrape_documents(soup: BeautifulSoup) -> list:
    """Extract document records from the 'Minutes and Associated Documents' table.

    Each record has 'filename' (original server name), 'size', 'created', and 'url'.

    Each cell contains two links: a bold viewer link whose text is the filename,
    and a separate download link whose href is used as the download URL.
    """
    table = _find_section_table(soup, _SECTION_DOCS)
    if not table:
        return []
    docs = []
    for row in table.find_all(_TAG_TR)[1:]:
        cells = row.find_all(_TAG_TD)
        if len(cells) < 3:
            continue
        dl_links = [
            anc for anc in cells[0].find_all(_TAG_A, href=True)
            if 'download' in anc[_ATTR_HREF]
        ]
        if not dl_links:
            continue
        view_links = [
            anc for anc in cells[0].find_all(_TAG_A, href=True)
            if 'viewer' in anc[_ATTR_HREF]
        ]
        if view_links:
            filename = view_links[0].get_text(strip=True)
        else:
            raw_name = cells[0].get_text(strip=True)
            filename = _RE_DOWNLOAD_SUFFIX.sub('', raw_name).strip()
        docs.append({
            'filename': filename,
            'size': cells[1].get_text(strip=True),
            'created': cells[2].get_text(strip=True),
            'url': _absolute(dl_links[0][_ATTR_HREF]),
        })
    return docs


def _scrape_revisions(soup: BeautifulSoup) -> list:
    """Extract revision history entries from the 'Meeting Revision History' table.

    Each record has 'date', 'changes' (e.g. 'Agenda'), and 'detail_url' (may be None).
    """
    table = _find_section_table(soup, _SECTION_REVISIONS)
    if not table:
        return []
    revisions = []
    for row in table.find_all(_TAG_TR)[1:]:
        cells = row.find_all(_TAG_TD)
        num_cells = len(cells)
        if num_cells < 2:
            continue
        detail_link = None
        if num_cells > 2:
            detail_link = cells[2].find(_TAG_A, href=True)
        revisions.append({
            'date': cells[0].get_text(strip=True),
            'changes': cells[1].get_text(strip=True),
            'detail_url': _absolute(detail_link[_ATTR_HREF]) if detail_link else None,
        })
    return revisions


def fetch_meeting_page_data(meeting_url: str) -> dict:
    """Extract supplementary data from an individual meeting page.

    Returns a dict with:
      'scheduled_by'  — person who scheduled the meeting
      'posted_at'     — when the meeting was first posted (string as displayed)
      'last_modified' — when the meeting record was last changed (string)
      'documents'     — list of {filename, size, created, url} dicts from the
                        'Minutes and Associated Documents' table; filename is the
                        original server-side name, not our generated stem
      'revisions'     — list of {date, changes, detail_url} dicts from the
                        'Meeting Revision History' table
    Returns an empty dict if the page cannot be fetched.
    """
    soup = _fetch_soup(meeting_url)
    if not soup:
        return {}
    return {
        'scheduled_by': _scrape_label_value(soup, _LABEL_SCHEDULED_BY),
        'posted_at': _scrape_label_value(soup, _LABEL_POSTED_AT),
        'last_modified': _scrape_label_value(soup, _LABEL_LAST_MODIFIED),
        'documents': _scrape_documents(soup),
        'revisions': _scrape_revisions(soup),
    }


def fetch_agenda_text(meeting_url: str) -> str:
    """Extract agenda text from an individual meeting page.

    Looks for a table row with the label 'Agenda:' and returns the text of
    the adjacent cell.  Returns an empty string if the page cannot be fetched
    or has no agenda section.
    """
    soup = _fetch_soup(meeting_url)
    if not soup:
        return ''
    agenda_td = soup.find(_TAG_TD, string=_AGENDA_LABEL_RE)
    if not agenda_td:
        return ''
    content_td = agenda_td.find_next_sibling(_TAG_TD)
    if not content_td:
        return ''
    return content_td.get_text(separator='\n', strip=True)


def _parse_board_row(board_data: dict, cells) -> None:
    """Update board_data in-place for a single two-cell table row.

    Recognises 'Chair:', 'Clerk:', and 'Members:' labels.  The Members cell
    may list names separated by newlines or commas, so both are split on.
    """
    label = cells[0].get_text(strip=True)
    cell_value = cells[1]
    if label == 'Chair:':
        board_data['chair'] = cell_value.get_text(strip=True)
    elif label == 'Clerk:':
        board_data['clerk'] = cell_value.get_text(strip=True)
    elif label == 'Members:':
        board_data['members'] = [
            name.strip()
            for name in re.split(
                r'[\n,]+', cell_value.get_text(', ', strip=True),
            )
            if name.strip() and not _ROLE_TITLE_RE.match(name.strip())
        ]


def fetch_board_members(soup: BeautifulSoup) -> dict:
    """Extract chair, clerk, and member names from the board info table."""
    board_data: dict = {'chair': None, 'clerk': None, 'members': []}
    for row in soup.find_all(_TAG_TR):
        cells = row.find_all(_TAG_TD)
        if len(cells) == 2:
            _parse_board_row(board_data, cells)
    return board_data


def _supplement_from_docs(meetings: list[dict], docs_anchor) -> None:
    """Copy agenda and minutes download URLs from the Docs table into meetings.

    Modifies the meeting dicts in `meetings` in-place.  Documents whose date
    does not match any known meeting are silently ignored (could be older
    records or typos in the site's document table).
    """
    table = docs_anchor.find_next(_TAG_TABLE)
    if not table:
        return
    docs = _parse_docs_table(table)
    by_date = {meeting['date']: meeting for meeting in meetings}
    for date_str, urls in docs.items():
        if date_str not in by_date:
            continue
        if urls.get(_KEY_MINUTES_URL):
            by_date[date_str][_KEY_MINUTES_URL] = urls[_KEY_MINUTES_URL]
        if urls.get(_KEY_AGENDA_URL):
            by_date[date_str][_KEY_AGENDA_URL] = urls[_KEY_AGENDA_URL]


def fetch_meetings(url: str = BOARD_URL) -> tuple[list[dict], dict]:
    """
    Fetch meetings and board member info from the MyTownGovernment board page.

    Returns (meetings, board_info). Uses the Past table as the primary source.
    Supplements with minutes/agenda download URLs from the Docs table.
    """
    response = requests.get(url, timeout=_REQUEST_TIMEOUT, headers=_HEADERS)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    meetings: list[dict] = []

    upcoming_anchor = soup.find(_TAG_A, attrs={'name': 'Upcoming'})
    if upcoming_anchor:
        table = upcoming_anchor.find_next(_TAG_TABLE)
        if table:
            meetings.extend(_parse_upcoming_table(table))

    past_anchor = soup.find(_TAG_A, attrs={'name': 'Past'})
    if past_anchor:
        table = past_anchor.find_next(_TAG_TABLE)
        if table:
            meetings.extend(_parse_past_table(table))

    docs_anchor = soup.find(_TAG_A, attrs={'name': 'Docs'})
    if docs_anchor:
        _supplement_from_docs(meetings, docs_anchor)

    return meetings, fetch_board_members(soup)
