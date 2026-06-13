"""Downloads meeting documents from remote URLs to the local archive.

Each document is saved to the meeting's data folder.  A sidecar .etag file
stores the server's ETag value so subsequent calls can skip unchanged files
(304 Not Modified).  Network and I/O errors on individual documents are
caught and returned as None so a single bad URL does not abort an archive run.
"""
from pathlib import Path
from types import MappingProxyType
from typing import Optional

import requests

_REQUEST_TIMEOUT = 30
_ETAG_SUFFIX = '.etag'
_HTTP_NOT_MODIFIED = 304
_DEFAULT_EXT = '.bin'
_PDF_MAGIC = b'%PDF'
_ZIP_MAGIC = b'PK'
_OLE2_MAGIC = b'\xd0\xcf\x11\xe0'  # pre-2007 Word/Excel compound document

_BROWSER_HEADERS = MappingProxyType({
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'
    ),
})


def _etag_path(dest: Path) -> Path:
    """Return the sidecar ETag file path stored alongside dest."""
    return dest.parent / (dest.name + _ETAG_SUFFIX)


def _saved_etag(dest: Path) -> Optional[str]:
    """Return the ETag stored from a previous download of dest, or None."""
    etag_file = _etag_path(dest)
    return etag_file.read_text().strip() if etag_file.exists() else None


def _save_etag(dest: Path, etag: str) -> None:
    """Write an ETag value alongside dest for future change detection."""
    _etag_path(dest).write_text(etag)


def _content_ext(content_type: str) -> str:
    """Return a file extension inferred from a Content-Type header value.

    Handles the common document types returned by government meeting sites
    (PDF and Word).  Falls back to '.bin' for unrecognised types.
    """
    parts = content_type.split(';')
    ctype = parts[0].strip().lower()
    if ctype == 'application/pdf':
        return '.pdf'
    if 'word' in ctype or 'officedocument' in ctype:
        return '.docx'
    if ctype == 'text/plain':
        return '.txt'
    return _DEFAULT_EXT


def _magic_ext(raw_bytes: bytes) -> str:
    """Infer file extension from magic bytes when Content-Type is unhelpful.

    Servers sometimes respond with 'application/octet-stream' for files that
    are really PDFs or DOCX.  Checking the first few bytes is more reliable.
    The OLE2 compound-document format covers pre-2007 Word (.doc) and Excel
    (.xls) files; .doc is assumed since minutes/agendas are text documents.
    """
    if raw_bytes[:4] == _PDF_MAGIC:
        return '.pdf'
    if raw_bytes[:2] == _ZIP_MAGIC:
        return '.docx'
    if raw_bytes[:4] == _OLE2_MAGIC:
        return '.doc'
    return _DEFAULT_EXT


def download_file(url: str, dest: Path) -> bool:
    """Download url to dest; return True if the file is new or was updated.

    Sends a browser User-Agent so sites that block Python's default agent
    respond normally.  Also sends If-None-Match with the previously saved
    ETag when one exists; a 304 Not Modified response keeps the existing
    file and returns False.
    """
    request_headers = dict(_BROWSER_HEADERS)
    saved = _saved_etag(dest)
    if saved:
        request_headers['If-None-Match'] = saved
    response = requests.get(url, headers=request_headers, timeout=_REQUEST_TIMEOUT)
    if response.status_code == _HTTP_NOT_MODIFIED:
        return False
    response.raise_for_status()
    dest.write_bytes(response.content)
    new_etag = response.headers.get('ETag')
    if new_etag:
        _save_etag(dest, new_etag)
    return True


def _try_download(url: Optional[str], dest: Path) -> Optional[Path]:
    """Download url to dest; return dest on success, None if url is absent or fails."""
    if not url:
        return None
    try:
        download_file(url, dest)
    except (requests.RequestException, OSError):
        return None
    return dest


def _download_doc(url: Optional[str], folder: Path, base_name: str) -> Optional[Path]:
    """Download a document into folder using Content-Type to pick the file extension.

    Checks for an already-downloaded file matching base_name.* and sends its
    ETag so unchanged files are skipped.  Returns the Path actually written,
    or None on failure.
    """
    if not url:
        return None
    request_headers = dict(_BROWSER_HEADERS)
    existing = next(folder.glob(f'{base_name}.*'), None)
    if existing:
        saved = _saved_etag(existing)
        if saved:
            request_headers['If-None-Match'] = saved
    try:
        response = requests.get(url, headers=request_headers, timeout=_REQUEST_TIMEOUT)
    except (requests.RequestException, OSError):
        return None
    if response.status_code == _HTTP_NOT_MODIFIED:
        return existing
    try:
        response.raise_for_status()
    except requests.HTTPError:
        return None
    ext = _content_ext(response.headers.get('Content-Type', ''))
    if ext == _DEFAULT_EXT:
        ext = _magic_ext(response.content)
    dest = folder / f'{base_name}{ext}'
    dest.write_bytes(response.content)
    etag = response.headers.get('ETag')
    if etag:
        _save_etag(dest, etag)
    return dest
