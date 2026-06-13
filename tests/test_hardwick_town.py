import pytest
from unittest.mock import MagicMock, patch

from towncommoniq.scraper import hardwick_town


_LISTING_HTML = """
<html><body><main>
<a href="/media/8601">Selectboard Meeting Minutes - March 30, 2026
  143.67 KB</a>
<a href="/media/8561">Selectboard Meeting Minutes - March 23, 2026
  200.47 KB</a>
<a href="/media/8086">Selectboard Meeting Minutes - September 15, 2025
  283.79 KB</a>
<a href="/other">Not a media link</a>
<a href="/media/9999/extra">Does not match /media/N pattern</a>
</main></body></html>
"""

_MEDIA_HTML_PDF = """
<html><body>
<h1>Selectboard Meeting Minutes - March 30, 2026</h1>
<a href="/sites/g/files/vyhlif13031/files/minutes/2026-03/march_30_2026.pdf">
Download PDF</a>
</body></html>
"""

_MEDIA_HTML_DOCX = """
<html><body>
<h1>Minutes March 23</h1>
<a href="/sites/g/files/vyhlif13031/files/minutes/march_23.docx">Download</a>
</body></html>
"""

_MEDIA_HTML_NOFILE = """
<html><body>
<p>No downloadable file here.</p>
<a href="/other-page">Some other link</a>
</body></html>
"""

_MEDIA_HTML_PDF_ABS = """
<html><body>
<a href="https://cdn.example.com/files/march_30.pdf">Download</a>
</body></html>
"""


class TestParseDateFromTitle:
    def test_standard_date_with_comma(self):
        result = hardwick_town._parse_date_from_title(
            'Selectboard Meeting Minutes - March 30, 2026',
        )
        assert result == '2026-03-30'

    def test_date_without_comma(self):
        result = hardwick_town._parse_date_from_title(
            'Selectboard Meeting Minutes - March 30 2026',
        )
        assert result == '2026-03-30'

    def test_abbreviated_month_in_format_string(self):
        result = hardwick_town._parse_date_from_title('Minutes - September 15, 2025')
        assert result == '2025-09-15'

    def test_returns_none_when_no_date(self):
        assert hardwick_town._parse_date_from_title('No date in this title') is None

    def test_returns_none_for_empty_string(self):
        assert hardwick_town._parse_date_from_title('') is None

    def test_two_digit_day(self):
        result = hardwick_town._parse_date_from_title('Minutes - January 5, 2025')
        assert result == '2025-01-05'

    def test_december_date(self):
        result = hardwick_town._parse_date_from_title('Minutes - December 22, 2025')
        assert result == '2025-12-22'

    def test_returns_none_for_invalid_day(self):
        result = hardwick_town._parse_date_from_title('Minutes - January 99, 2025')
        assert result is None


class TestParseListing:
    def test_extracts_all_media_links(self):
        result = hardwick_town._parse_listing(_LISTING_HTML)
        assert len(result) == 3

    def test_extracts_correct_dates(self):
        result = hardwick_town._parse_listing(_LISTING_HTML)
        assert result[0]['date'] == '2026-03-30'
        assert result[1]['date'] == '2026-03-23'
        assert result[2]['date'] == '2025-09-15'

    def test_extracts_media_ids(self):
        result = hardwick_town._parse_listing(_LISTING_HTML)
        assert result[0]['media_id'] == '8601'
        assert result[1]['media_id'] == '8561'

    def test_strips_size_suffix(self):
        result = hardwick_town._parse_listing(_LISTING_HTML)
        assert '143' not in result[0]['title']
        assert 'KB' not in result[0]['title']

    def test_builds_media_url(self):
        result = hardwick_town._parse_listing(_LISTING_HTML)
        assert result[0]['media_url'] == 'https://www.hardwick-ma.gov/media/8601'

    def test_file_url_and_filename_are_none(self):
        result = hardwick_town._parse_listing(_LISTING_HTML)
        assert result[0]['file_url'] is None
        assert result[0]['filename'] is None

    def test_skips_non_media_links(self):
        result = hardwick_town._parse_listing(_LISTING_HTML)
        media_ids = [rec['media_id'] for rec in result]
        assert '9999' not in media_ids

    def test_returns_empty_for_no_links(self):
        assert hardwick_town._parse_listing('<html><body></body></html>') == []


class TestFetchFileUrl:
    def _make_driver(self, html: str, title: str = 'Real Page') -> MagicMock:
        driver = MagicMock()
        driver.title = title
        driver.page_source = html
        driver.get = MagicMock()
        return driver

    def test_returns_media_url_when_title_is_filename(self):
        driver = self._make_driver('', title='march_30_2026.pdf')
        with patch.object(hardwick_town, '_wait_past_cloudflare'):
            result = hardwick_town._fetch_file_url(driver, '8601')
        assert result == 'https://www.hardwick-ma.gov/media/8601'

    def test_falls_back_to_html_when_title_has_no_extension(self):
        driver = self._make_driver(_MEDIA_HTML_PDF)
        with patch.object(hardwick_town, '_wait_past_cloudflare'):
            result = hardwick_town._fetch_file_url(driver, '8601')
        assert result == (
            'https://www.hardwick-ma.gov'
            '/sites/g/files/vyhlif13031/files/minutes/2026-03/march_30_2026.pdf'
        )

    def test_returns_docx_url_from_html_fallback(self):
        driver = self._make_driver(_MEDIA_HTML_DOCX)
        with patch.object(hardwick_town, '_wait_past_cloudflare'):
            result = hardwick_town._fetch_file_url(driver, '8561')
        assert result is not None
        assert result.endswith('.docx')

    def test_returns_none_when_no_file_link(self):
        driver = self._make_driver(_MEDIA_HTML_NOFILE)
        with patch.object(hardwick_town, '_wait_past_cloudflare'):
            result = hardwick_town._fetch_file_url(driver, '9999')
        assert result is None

    def test_returns_absolute_href_unchanged(self):
        driver = self._make_driver(_MEDIA_HTML_PDF_ABS)
        with patch.object(hardwick_town, '_wait_past_cloudflare'):
            result = hardwick_town._fetch_file_url(driver, '8601')
        assert result == 'https://cdn.example.com/files/march_30.pdf'

    def test_returns_none_on_cloudflare_timeout(self):
        from selenium.common.exceptions import TimeoutException
        driver = self._make_driver('')
        with patch.object(
            hardwick_town, '_wait_past_cloudflare', side_effect=TimeoutException(),
        ):
            result = hardwick_town._fetch_file_url(driver, '8601')
        assert result is None


class TestDownloadFile:
    def test_downloads_and_writes_bytes(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.content = b'%PDF-1.4 fake content'
        mock_resp.raise_for_status = MagicMock()
        dest = tmp_path / 'town_file.pdf'
        with patch('requests.get', return_value=mock_resp):
            result = hardwick_town.download_file('http://example.com/file.pdf', dest)
        assert result is True
        assert dest.read_bytes() == b'%PDF-1.4 fake content'

    def test_creates_parent_dirs(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.content = b'data'
        mock_resp.raise_for_status = MagicMock()
        dest = tmp_path / 'sub' / 'dir' / 'file.pdf'
        with patch('requests.get', return_value=mock_resp):
            hardwick_town.download_file('http://example.com/file.pdf', dest)
        assert dest.exists()

    def test_returns_false_on_network_error(self, tmp_path):
        with patch('requests.get', side_effect=Exception('network error')):
            result = hardwick_town.download_file(
                'http://example.com/file.pdf', tmp_path / 'file.pdf',
            )
        assert result is False

    def test_returns_false_on_http_error(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception('404')
        with patch('requests.get', return_value=mock_resp):
            result = hardwick_town.download_file(
                'http://example.com/file.pdf', tmp_path / 'file.pdf',
            )
        assert result is False


class TestMergeCached:
    def test_preserves_file_url_from_cache(self):
        fresh = [
            {'media_id': '8601', 'date': '2026-03-30', 'file_url': None, 'filename': None, 'downloaded': False},
        ]
        cached = [
            {'media_id': '8601', 'file_url': 'http://example.com/file.pdf', 'filename': 'file.pdf', 'downloaded': True},
        ]
        result = hardwick_town.merge_cached(fresh, cached)
        assert result[0]['file_url'] == 'http://example.com/file.pdf'
        assert result[0]['downloaded'] is True

    def test_new_records_keep_none_file_url(self):
        fresh = [
            {'media_id': '9999', 'date': '2026-04-01', 'file_url': None, 'filename': None, 'downloaded': False},
        ]
        result = hardwick_town.merge_cached(fresh, [])
        assert result[0]['file_url'] is None

    def test_returns_fresh_list(self):
        fresh = [{'media_id': '1', 'file_url': None, 'filename': None, 'downloaded': False}]
        result = hardwick_town.merge_cached(fresh, [])
        assert result is fresh


class TestDownloadAll:
    def _make_driver_ctx(self):
        mock_driver = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_driver)
        mock_cm.__exit__ = MagicMock(return_value=False)
        return mock_cm, mock_driver

    def test_downloads_undownloaded_records(self, tmp_path):
        records = [{
            'media_id': '8601',
            'date': '2026-03-30',
            'file_url': 'https://www.hardwick-ma.gov/media/8601',
            'filename': 'file.pdf',
            'downloaded': False,
        }]
        folders = {'2026-03-30': str(tmp_path)}
        ctx, _ = self._make_driver_ctx()
        with patch.object(hardwick_town, '_create_driver', return_value=ctx), \
             patch.object(hardwick_town, '_wait_past_cloudflare'), \
             patch.object(hardwick_town, '_wait_for_download', return_value=True):
            count = hardwick_town.download_all(records, folders)
        assert count == 1
        assert records[0]['downloaded'] is True

    def test_skips_already_downloaded(self, tmp_path):
        records = [{
            'media_id': '8601',
            'date': '2026-03-30',
            'file_url': 'https://www.hardwick-ma.gov/media/8601',
            'filename': 'file.pdf',
            'downloaded': True,
        }]
        ctx, _ = self._make_driver_ctx()
        with patch.object(hardwick_town, '_create_driver', return_value=ctx), \
             patch.object(hardwick_town, '_wait_past_cloudflare'), \
             patch.object(hardwick_town, '_wait_for_download') as mock_wait:
            hardwick_town.download_all(records, {'2026-03-30': str(tmp_path)})
        mock_wait.assert_not_called()

    def test_skips_records_without_folder(self, tmp_path):
        records = [{
            'media_id': '8601',
            'date': '2099-01-01',
            'file_url': 'https://www.hardwick-ma.gov/media/8601',
            'filename': 'file.pdf',
            'downloaded': False,
        }]
        ctx, _ = self._make_driver_ctx()
        with patch.object(hardwick_town, '_create_driver', return_value=ctx), \
             patch.object(hardwick_town, '_wait_past_cloudflare'), \
             patch.object(hardwick_town, '_wait_for_download', return_value=True):
            count = hardwick_town.download_all(records, {})
        assert count == 0

    def test_skips_records_without_file_url(self, tmp_path):
        records = [{
            'media_id': '8601',
            'date': '2026-03-30',
            'file_url': None,
            'filename': None,
            'downloaded': False,
        }]
        ctx, _ = self._make_driver_ctx()
        with patch.object(hardwick_town, '_create_driver', return_value=ctx), \
             patch.object(hardwick_town, '_wait_past_cloudflare'), \
             patch.object(hardwick_town, '_wait_for_download', return_value=True):
            count = hardwick_town.download_all(records, {'2026-03-30': str(tmp_path)})
        assert count == 0

    def test_sets_local_filename_with_prefix(self, tmp_path):
        records = [{
            'media_id': '8601',
            'date': '2026-03-30',
            'file_url': 'https://www.hardwick-ma.gov/media/8601',
            'filename': 'march_30.pdf',
            'downloaded': False,
        }]
        ctx, _ = self._make_driver_ctx()
        with patch.object(hardwick_town, '_create_driver', return_value=ctx), \
             patch.object(hardwick_town, '_wait_past_cloudflare'), \
             patch.object(hardwick_town, '_wait_for_download', return_value=True):
            hardwick_town.download_all(records, {'2026-03-30': str(tmp_path)})
        assert records[0]['local_filename'] == 'town_march_30.pdf'


class TestCreateDriver:
    def _make_opts(self):
        mock_opts = MagicMock()
        return mock_opts

    def test_headless_adds_argument(self):
        with patch('towncommoniq.scraper.hardwick_town.webdriver.Firefox'), \
             patch('towncommoniq.scraper.hardwick_town.FirefoxOptions') as mock_cls:
            mock_opts = self._make_opts()
            mock_cls.return_value = mock_opts
            hardwick_town._create_driver(headless=True)
        mock_opts.add_argument.assert_called_once_with('--headless')

    def test_non_headless_skips_argument(self):
        with patch('towncommoniq.scraper.hardwick_town.webdriver.Firefox'), \
             patch('towncommoniq.scraper.hardwick_town.FirefoxOptions') as mock_cls:
            mock_opts = self._make_opts()
            mock_cls.return_value = mock_opts
            hardwick_town._create_driver(headless=False)
        mock_opts.add_argument.assert_not_called()

    def test_download_dir_sets_preferences(self):
        with patch('towncommoniq.scraper.hardwick_town.webdriver.Firefox'), \
             patch('towncommoniq.scraper.hardwick_town.FirefoxOptions') as mock_cls:
            mock_opts = self._make_opts()
            mock_cls.return_value = mock_opts
            hardwick_town._create_driver(download_dir='/tmp/dl')
        pref_names = [c.args[0] for c in mock_opts.set_preference.call_args_list]
        assert 'browser.download.dir' in pref_names
        assert 'pdfjs.disabled' in pref_names

    def test_no_preferences_without_download_dir(self):
        with patch('towncommoniq.scraper.hardwick_town.webdriver.Firefox'), \
             patch('towncommoniq.scraper.hardwick_town.FirefoxOptions') as mock_cls:
            mock_opts = self._make_opts()
            mock_cls.return_value = mock_opts
            hardwick_town._create_driver(download_dir=None)
        mock_opts.set_preference.assert_not_called()


class TestWaitPastCloudflare:
    def test_returns_when_title_is_clear(self):
        driver = MagicMock()
        driver.title = 'Selectboard Meeting Minutes'
        hardwick_town._wait_past_cloudflare(driver)

    def test_raises_timeout_when_cf_persists(self):
        from selenium.common.exceptions import TimeoutException
        driver = MagicMock()
        driver.title = 'Just a moment...'
        with pytest.raises(TimeoutException):
            hardwick_town._wait_past_cloudflare(driver, timeout=0)

    def test_sleeps_while_cf_title_active(self):
        from selenium.common.exceptions import TimeoutException
        driver = MagicMock()
        driver.title = 'Just a moment...'
        calls = iter([0, 0, 100])
        with patch.object(hardwick_town, 'time') as mock_time:
            mock_time.monotonic = lambda: next(calls)
            mock_time.sleep = MagicMock()
            with pytest.raises(TimeoutException):
                hardwick_town._wait_past_cloudflare(driver, timeout=1)
        mock_time.sleep.assert_called_once()


class TestWaitForDownload:
    def test_returns_true_and_copies_file(self, tmp_path):
        dl_dir = tmp_path / 'dl'
        dl_dir.mkdir()
        dest = tmp_path / 'out' / 'file.pdf'
        (dl_dir / 'file.pdf').write_bytes(b'PDF content')
        result = hardwick_town._wait_for_download(dl_dir, dest)
        assert result is True
        assert dest.read_bytes() == b'PDF content'
        assert not (dl_dir / 'file.pdf').exists()

    def test_creates_parent_dirs_for_dest(self, tmp_path):
        dl_dir = tmp_path / 'dl'
        dl_dir.mkdir()
        dest = tmp_path / 'a' / 'b' / 'file.pdf'
        (dl_dir / 'file.pdf').write_bytes(b'data')
        hardwick_town._wait_for_download(dl_dir, dest)
        assert dest.exists()

    def test_sleeps_and_cleans_up_on_timeout(self, tmp_path):
        dl_dir = tmp_path / 'dl'
        dl_dir.mkdir()
        dest = tmp_path / 'file.pdf'
        (dl_dir / 'tmp.pdf.part').write_bytes(b'partial')
        calls = iter([0, 0, 100])
        with patch.object(hardwick_town, 'time') as mock_time:
            mock_time.monotonic = lambda: next(calls)
            mock_time.sleep = MagicMock()
            result = hardwick_town._wait_for_download(dl_dir, dest, timeout=1)
        assert result is False
        assert not dest.exists()
        assert not (dl_dir / 'tmp.pdf.part').exists()
        mock_time.sleep.assert_called_once()

    def test_returns_false_on_immediate_timeout(self, tmp_path):
        dl_dir = tmp_path / 'dl'
        dl_dir.mkdir()
        dest = tmp_path / 'file.pdf'
        (dl_dir / 'leftover.pdf.part').write_bytes(b'x')
        result = hardwick_town._wait_for_download(dl_dir, dest, timeout=0)
        assert result is False
        assert not (dl_dir / 'leftover.pdf.part').exists()


class TestFetchMinutesList:
    def _make_ctx(self, html):
        driver = MagicMock()
        driver.page_source = html
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=driver)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    def test_returns_parsed_records(self):
        ctx = self._make_ctx(_LISTING_HTML)
        with patch.object(hardwick_town, '_create_driver', return_value=ctx), \
             patch.object(hardwick_town, '_wait_past_cloudflare'), \
             patch('towncommoniq.scraper.hardwick_town.time.sleep'):
            result = hardwick_town.fetch_minutes_list()
        assert len(result) == 3
        assert result[0]['date'] == '2026-03-30'

    def test_returns_empty_for_empty_page(self):
        ctx = self._make_ctx('<html><body></body></html>')
        with patch.object(hardwick_town, '_create_driver', return_value=ctx), \
             patch.object(hardwick_town, '_wait_past_cloudflare'), \
             patch('towncommoniq.scraper.hardwick_town.time.sleep'):
            result = hardwick_town.fetch_minutes_list()
        assert result == []


class TestResolveFileUrls:
    def _make_ctx(self, title='file.pdf'):
        driver = MagicMock()
        driver.title = title
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=driver)
        cm.__exit__ = MagicMock(return_value=False)
        return cm, driver

    def test_resolves_url_and_filename_from_title(self):
        records = [{'media_id': '8601', 'file_url': None, 'filename': None}]
        ctx, _ = self._make_ctx(title='march_30.pdf')
        with patch.object(hardwick_town, '_create_driver', return_value=ctx), \
             patch.object(hardwick_town, '_fetch_file_url',
                          return_value='https://www.hardwick-ma.gov/media/8601'):
            hardwick_town.resolve_file_urls(records)
        assert records[0]['file_url'] == 'https://www.hardwick-ma.gov/media/8601'
        assert records[0]['filename'] == 'march_30.pdf'

    def test_uses_url_basename_when_title_has_no_extension(self):
        records = [{'media_id': '8601', 'file_url': None, 'filename': None}]
        ctx, _ = self._make_ctx(title='Generic Page Title')
        with patch.object(hardwick_town, '_create_driver', return_value=ctx), \
             patch.object(hardwick_town, '_fetch_file_url',
                          return_value='https://example.com/8601'):
            hardwick_town.resolve_file_urls(records)
        assert records[0]['filename'] == '8601'

    def test_skips_already_resolved_records(self):
        records = [{'media_id': '8601', 'file_url': 'http://x.com/f.pdf', 'filename': 'f.pdf'}]
        ctx, _ = self._make_ctx()
        with patch.object(hardwick_town, '_create_driver', return_value=ctx), \
             patch.object(hardwick_town, '_fetch_file_url') as mock_fetch:
            hardwick_town.resolve_file_urls(records)
        mock_fetch.assert_not_called()

    def test_skips_record_when_fetch_returns_none(self):
        records = [{'media_id': '8601', 'file_url': None, 'filename': None}]
        ctx, _ = self._make_ctx()
        with patch.object(hardwick_town, '_create_driver', return_value=ctx), \
             patch.object(hardwick_town, '_fetch_file_url', return_value=None):
            hardwick_town.resolve_file_urls(records)
        assert records[0]['file_url'] is None
