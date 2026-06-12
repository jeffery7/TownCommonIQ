from unittest.mock import MagicMock, patch

import pytest
import requests

from municipaliq import downloader


@pytest.fixture()
def mock_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.content = b'%PDFfake content'
    resp.raise_for_status = MagicMock()
    resp.headers = {'Content-Type': 'application/pdf'}
    return resp


class TestEtagHelpers:
    def test_etag_path_is_alongside_dest(self, tmp_path):
        dest = tmp_path / 'agenda.pdf'
        assert downloader._etag_path(dest) == tmp_path / 'agenda.pdf.etag'

    def test_saved_etag_returns_none_when_missing(self, tmp_path):
        dest = tmp_path / 'agenda.pdf'
        assert downloader._saved_etag(dest) is None

    def test_saved_etag_returns_stored_value(self, tmp_path):
        dest = tmp_path / 'agenda.pdf'
        (tmp_path / 'agenda.pdf.etag').write_text('"abc123"\n')
        assert downloader._saved_etag(dest) == '"abc123"'

    def test_save_etag_writes_file(self, tmp_path):
        dest = tmp_path / 'agenda.pdf'
        downloader._save_etag(dest, '"xyz"')
        assert (tmp_path / 'agenda.pdf.etag').read_text() == '"xyz"'


class TestMagicExt:
    def test_pdf_magic_bytes(self):
        assert downloader._magic_ext(b'%PDFfake') == '.pdf'

    def test_zip_magic_bytes_gives_docx(self):
        assert downloader._magic_ext(b'PK\x03\x04fake') == '.docx'

    def test_ole2_magic_bytes_gives_doc(self):
        assert downloader._magic_ext(b'\xd0\xcf\x11\xe0fake') == '.doc'

    def test_unknown_bytes_returns_bin(self):
        assert downloader._magic_ext(b'\x00\x01\x02\x03') == '.bin'

    def test_empty_bytes_returns_bin(self):
        assert downloader._magic_ext(b'') == '.bin'


class TestContentExt:
    def test_pdf_content_type(self):
        assert downloader._content_ext('application/pdf') == '.pdf'

    def test_word_docx_content_type(self):
        ctype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        assert downloader._content_ext(ctype) == '.docx'

    def test_msword_content_type(self):
        assert downloader._content_ext('application/msword') == '.docx'

    def test_plain_text_content_type(self):
        assert downloader._content_ext('text/plain') == '.txt'

    def test_unknown_type_returns_bin(self):
        assert downloader._content_ext('application/octet-stream') == '.bin'

    def test_strips_charset_suffix(self):
        assert downloader._content_ext('application/pdf; charset=utf-8') == '.pdf'

    def test_empty_string_returns_bin(self):
        assert downloader._content_ext('') == '.bin'


class TestDownloadFile:
    def test_writes_content_to_dest(self, tmp_path, mock_response):
        dest = tmp_path / 'doc.pdf'
        with patch('requests.get', return_value=mock_response):
            result = downloader.download_file('http://example.com/doc', dest)
        assert result is True
        assert dest.read_bytes() == b'%PDFfake content'

    def test_sends_browser_user_agent(self, tmp_path, mock_response):
        dest = tmp_path / 'doc.pdf'
        with patch('requests.get', return_value=mock_response) as mock_get:
            downloader.download_file('http://example.com/doc', dest)
        headers_sent = mock_get.call_args[1]['headers']
        assert 'Mozilla' in headers_sent.get('User-Agent', '')

    def test_returns_false_on_not_modified(self, tmp_path):
        dest = tmp_path / 'doc.pdf'
        dest.write_bytes(b'existing')
        resp = MagicMock()
        resp.status_code = 304
        with patch('requests.get', return_value=resp):
            result = downloader.download_file('http://example.com/doc', dest)
        assert result is False
        assert dest.read_bytes() == b'existing'

    def test_sends_if_none_match_when_etag_exists(self, tmp_path, mock_response):
        dest = tmp_path / 'doc.pdf'
        downloader._save_etag(dest, '"stored-etag"')
        with patch('requests.get', return_value=mock_response) as mock_get:
            downloader.download_file('http://example.com/doc', dest)
        headers_sent = mock_get.call_args[1]['headers']
        assert headers_sent.get('If-None-Match') == '"stored-etag"'

    def test_saves_new_etag_from_response(self, tmp_path, mock_response):
        dest = tmp_path / 'doc.pdf'
        mock_response.headers = {'ETag': '"new-etag"', 'Content-Type': 'application/pdf'}
        with patch('requests.get', return_value=mock_response):
            downloader.download_file('http://example.com/doc', dest)
        assert downloader._saved_etag(dest) == '"new-etag"'

    def test_raises_on_http_error(self, tmp_path):
        dest = tmp_path / 'doc.pdf'
        with patch('requests.get', side_effect=requests.HTTPError('404')):
            with pytest.raises(requests.HTTPError):
                downloader.download_file('http://example.com/doc', dest)


class TestTryDownload:
    def test_returns_none_when_url_is_none(self, tmp_path):
        assert downloader._try_download(None, tmp_path / 'doc.pdf') is None

    def test_returns_dest_on_success(self, tmp_path):
        dest = tmp_path / 'doc.pdf'
        with patch.object(downloader, 'download_file', return_value=True):
            assert downloader._try_download('http://example.com/doc', dest) == dest

    def test_returns_none_on_network_error(self, tmp_path):
        dest = tmp_path / 'doc.pdf'
        with patch.object(downloader, 'download_file', side_effect=requests.RequestException):
            assert downloader._try_download('http://example.com/doc', dest) is None

    def test_returns_none_on_os_error(self, tmp_path):
        dest = tmp_path / 'doc.pdf'
        with patch.object(downloader, 'download_file', side_effect=OSError):
            assert downloader._try_download('http://example.com/doc', dest) is None


class TestDownloadDoc:
    def test_returns_none_when_url_is_none(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        assert downloader._download_doc(None, folder, 'base') is None

    def test_saves_with_pdf_extension(self, tmp_path, mock_response):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch('requests.get', return_value=mock_response):
            result = downloader._download_doc('http://example.com/doc', folder, 'base')
        assert result == folder / 'base.pdf'
        assert result.read_bytes() == b'%PDFfake content'

    def test_falls_back_to_magic_bytes_when_octet_stream(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'%PDFfake'
        resp.raise_for_status = MagicMock()
        resp.headers = {'Content-Type': 'application/octet-stream'}
        with patch('requests.get', return_value=resp):
            result = downloader._download_doc('http://example.com/doc', folder, 'base')
        assert result == folder / 'base.pdf'

    def test_saves_with_docx_extension(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'PK\x03\x04'
        resp.raise_for_status = MagicMock()
        ctype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        resp.headers = {'Content-Type': ctype}
        with patch('requests.get', return_value=resp):
            result = downloader._download_doc('http://example.com/doc', folder, 'base')
        assert result == folder / 'base.docx'

    def test_returns_none_on_forbidden(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        resp = MagicMock()
        resp.status_code = 403
        resp.raise_for_status.side_effect = requests.HTTPError('403')
        with patch('requests.get', return_value=resp):
            result = downloader._download_doc('http://example.com/doc', folder, 'base')
        assert result is None

    def test_returns_none_on_network_error(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch('requests.get', side_effect=requests.RequestException):
            result = downloader._download_doc('http://example.com/doc', folder, 'base')
        assert result is None

    def test_sends_browser_user_agent(self, tmp_path, mock_response):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch('requests.get', return_value=mock_response) as mock_get:
            downloader._download_doc('http://example.com/doc', folder, 'base')
        headers_sent = mock_get.call_args[1]['headers']
        assert 'Mozilla' in headers_sent.get('User-Agent', '')

    def test_returns_existing_on_not_modified(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        existing = folder / 'base.pdf'
        existing.write_bytes(b'old content')
        resp = MagicMock()
        resp.status_code = 304
        with patch('requests.get', return_value=resp):
            result = downloader._download_doc('http://example.com/doc', folder, 'base')
        assert result == existing


class TestDownloadDocEtag:
    def test_sends_if_none_match_when_etag_exists(self, tmp_path, mock_response):
        folder = tmp_path / 'meeting'
        folder.mkdir()
        existing = folder / 'doc.pdf'
        existing.write_bytes(b'old content')
        (folder / 'doc.pdf.etag').write_text('"abc123"')
        mock_response.status_code = 200
        with patch('requests.get', return_value=mock_response) as mock_get:
            downloader._download_doc('http://example.com/doc', folder, 'doc')
        headers = mock_get.call_args[1]['headers']
        assert headers.get('If-None-Match') == '"abc123"'

    def test_saves_etag_from_response(self, tmp_path, mock_response):
        folder = tmp_path / 'meeting'
        folder.mkdir()
        mock_response.headers = {'Content-Type': 'application/pdf', 'ETag': '"newetag"'}
        with patch('requests.get', return_value=mock_response):
            result = downloader._download_doc('http://example.com/doc', folder, 'doc')
        assert result is not None
        etag_file = folder / f'{result.name}.etag'
        assert etag_file.exists()
        assert '"newetag"' in etag_file.read_text()
