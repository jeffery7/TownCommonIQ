"""Scrapes meeting minutes from the Hardwick town website (hardwick-ma.gov).

Uses Selenium with Firefox to bypass Cloudflare protection.  Documents are
downloaded through the browser session (Firefox handles the file download
directly to a temp directory).  Downloaded files carry FILE_PREFIX to
distinguish them from mytowngovernment.org files.
"""
import contextlib
import logging
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common import exceptions as selenium_exceptions

_logger = logging.getLogger(__name__)

LISTING_URL = (
    'https://www.hardwick-ma.gov'
    '/administration/page/selectboard-meeting-minutes'
)
BASE_URL = 'https://www.hardwick-ma.gov'
FILE_PREFIX = 'town_'

_CF_WAIT_SECS = 25
_POLL_INTERVAL = 0.5
_REQUEST_TIMEOUT = 30
_FF_DOWNLOAD_FOLDER_CUSTOM = 2

_HEADERS = MappingProxyType({
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64; rv:150.0) '
        'Gecko/20100101 Firefox/150.0'
    ),
})

# Matches full month name + day + year in a document title
_TITLE_DATE_RE = re.compile(
    r'(?:January|February|March|April|May|June|July|August'
    r'|September|October|November|December)\s+\d{1,2},?\s+\d{4}',
    re.IGNORECASE,
)
_DATE_FORMATS = ('%B %d, %Y', '%B %d %Y', '%b %d, %Y', '%b %d %Y')
_SIZE_SUFFIX_RE = re.compile(r'\s+\d+(?:\.\d+)?\s+(?:KB|MB)\s*$')
_FILE_EXT_RE = re.compile(r'\.(pdf|docx?|odt)(\?.*)?$', re.IGNORECASE)

_KEY_DATE = 'date'
_KEY_TITLE = 'title'
_KEY_MEDIA_ID = 'media_id'
_KEY_MEDIA_URL = 'media_url'
_KEY_FILE_URL = 'file_url'
_KEY_FILENAME = 'filename'
_KEY_DOWNLOADED = 'downloaded'


def _parse_date_from_title(title: str) -> str | None:
    """Return ISO date parsed from a title like 'Minutes - March 30, 2026'."""
    match = _TITLE_DATE_RE.search(title)
    if not match:
        return None
    raw = match.group(0).replace(',', '')
    for fmt in _DATE_FORMATS:
        with contextlib.suppress(ValueError):
            return datetime.strptime(raw.strip(), fmt).strftime('%Y-%m-%d')
    return None


def _create_driver(
    headless: bool = True, download_dir: str | None = None,
) -> webdriver.Firefox:
    """Return a configured Firefox WebDriver instance.

    When download_dir is provided, Firefox is configured to download files
    automatically to that directory instead of opening them in the viewer.
    """
    opts = webdriver.FirefoxOptions()
    if headless:
        opts.add_argument('--headless')
    if download_dir:
        opts.set_preference('browser.download.folderList', _FF_DOWNLOAD_FOLDER_CUSTOM)
        opts.set_preference('browser.download.dir', download_dir)
        opts.set_preference('browser.download.manager.showWhenStarting', False)
        opts.set_preference('pdfjs.disabled', True)
        opts.set_preference(
            'browser.helperApps.neverAsk.saveToDisk',
            'application/pdf,application/x-pdf,application/octet-stream'
            ',application/msword'
            ',application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
    return webdriver.Firefox(options=opts)


def _wait_past_cloudflare(driver: webdriver.Firefox, timeout: int = _CF_WAIT_SECS) -> None:
    """Block until the Cloudflare challenge resolves or raise TimeoutException."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if 'Just a moment' not in driver.title:
            return
        time.sleep(_POLL_INTERVAL)
    raise selenium_exceptions.TimeoutException('Cloudflare challenge did not resolve in time')


def _parse_listing(html: str) -> list[dict]:
    """Parse the listing page and return a list of media record dicts."""
    soup = BeautifulSoup(html, 'html.parser')
    records = []
    for anchor in soup.find_all('a', href=re.compile(r'^/media/\d+$')):
        media_id = anchor['href'].split('/')[-1]
        raw_text = anchor.get_text(separator=' ', strip=True)
        title = _SIZE_SUFFIX_RE.sub('', raw_text).strip()
        media_url = f'{BASE_URL}/media/{media_id}'
        records.append({
            _KEY_DATE: _parse_date_from_title(title),
            _KEY_TITLE: title,
            _KEY_MEDIA_ID: media_id,
            _KEY_MEDIA_URL: media_url,
            _KEY_FILE_URL: None,
            _KEY_FILENAME: None,
            _KEY_DOWNLOADED: False,
        })
    return records


def _fetch_file_url(driver: webdriver.Firefox, media_id: str) -> str | None:
    """Navigate to a media page; return the file URL or None.

    Checks the page title first — the site serves files directly at the media
    URL, so Firefox's title becomes the filename.  Falls back to HTML anchor
    parsing for forward compatibility with sites that embed a download link.
    """
    url = f'{BASE_URL}/media/{media_id}'
    driver.get(url)
    try:
        _wait_past_cloudflare(driver)
    except (selenium_exceptions.TimeoutException, selenium_exceptions.WebDriverException):
        return None
    if _FILE_EXT_RE.search(driver.title):
        return url
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    for anchor in soup.find_all('a', href=_FILE_EXT_RE):
        href = anchor['href']
        if href.startswith('http'):
            return href
        return f'{BASE_URL}{href}'
    return None


def _wait_for_download(download_dir: Path, dest: Path, timeout: int = _REQUEST_TIMEOUT) -> bool:
    """Wait for a browser download to complete, then copy the file to dest.

    Returns True if a complete file appeared before timeout, False otherwise.
    Cleans up any partial or leftover files in download_dir on timeout.
    """
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        files = [fp for fp in download_dir.iterdir() if fp.suffix != '.part']
        if files:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(files[0].read_bytes())
            files[0].unlink()
            return True
        time.sleep(_POLL_INTERVAL)
    for leftover in download_dir.iterdir():
        leftover.unlink(missing_ok=True)
    return False


def download_file(url: str, dest: Path) -> bool:
    """Download a file from url to dest using requests; return True on success."""
    try:
        response = requests.get(url, headers=dict(_HEADERS), timeout=_REQUEST_TIMEOUT, stream=True)
    except Exception:
        _logger.warning('Download failed for %s', url, exc_info=True)
        return False
    try:
        response.raise_for_status()
    except Exception:
        _logger.warning('Download failed for %s', url, exc_info=True)
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)
    return True


def fetch_minutes_list(headless: bool = True) -> list[dict]:
    """Fetch the listing page and return all meeting minutes records.

    Each record has date, title, media_id, media_url, and placeholders
    for file_url/filename (resolved later by resolve_file_urls).
    """
    with _create_driver(headless=headless) as driver:
        driver.get(LISTING_URL)
        _wait_past_cloudflare(driver)
        time.sleep(_POLL_INTERVAL)
        return _parse_listing(driver.page_source)


def resolve_file_urls(town_records: list[dict], headless: bool = True) -> None:
    """Visit each media page to fill in file_url and filename.

    Modifies town_records in place; skips records that already have a file_url.
    The file_url is set to the media URL itself (the site serves files there
    directly).  The filename is taken from the browser's page title.
    """
    with _create_driver(headless=headless) as driver:
        for rec in town_records:
            if rec.get(_KEY_FILE_URL):
                continue
            file_url = _fetch_file_url(driver, rec[_KEY_MEDIA_ID])
            if not file_url:
                continue
            rec[_KEY_FILE_URL] = file_url
            title = driver.title
            if _FILE_EXT_RE.search(title):
                rec[_KEY_FILENAME] = title
            else:
                rec[_KEY_FILENAME] = file_url.split('/')[-1]


def merge_cached(fresh: list[dict], cached: list[dict]) -> list[dict]:
    """Return fresh records enriched with resolved URLs from cached records.

    Matches by media_id so previously resolved URLs survive a re-fetch.
    """
    by_id = {rec[_KEY_MEDIA_ID]: rec for rec in cached}
    for rec in fresh:
        prev = by_id.get(rec[_KEY_MEDIA_ID])
        if not prev:
            continue
        rec[_KEY_FILE_URL] = prev.get(_KEY_FILE_URL)
        rec[_KEY_FILENAME] = prev.get(_KEY_FILENAME)
        rec[_KEY_DOWNLOADED] = prev.get(_KEY_DOWNLOADED, False)
    return fresh


def download_all(town_records: list[dict], folders_by_date: dict, headless: bool = True) -> int:
    """Download files for records with a URL that are not yet saved locally.

    Uses a browser session (with Cloudflare bypass) to download each file.
    folders_by_date maps date strings to local folder path strings.
    Returns the number of files successfully downloaded.
    """
    count = 0
    with tempfile.TemporaryDirectory() as tmpdir_str:
        with _create_driver(headless, tmpdir_str) as driver:
            driver.get(LISTING_URL)
            _wait_past_cloudflare(driver)
            driver.set_page_load_timeout(_REQUEST_TIMEOUT)
            for rec in town_records:
                file_url = rec.get(_KEY_FILE_URL)
                folder_str = folders_by_date.get(rec.get(_KEY_DATE, ''))
                filename = rec.get(_KEY_FILENAME)
                if rec.get(_KEY_DOWNLOADED) or not file_url or not folder_str or not filename:
                    continue
                local_name = f'{FILE_PREFIX}{filename}'
                with contextlib.suppress(selenium_exceptions.TimeoutException):
                    driver.get(file_url)
                if _wait_for_download(Path(tmpdir_str), Path(folder_str) / local_name):
                    rec[_KEY_DOWNLOADED] = True
                    rec['local_filename'] = local_name
                    count += 1
    return count
