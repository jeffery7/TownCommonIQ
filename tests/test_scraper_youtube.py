import json
from unittest.mock import MagicMock

import pytest

from towncommoniq.scraper import youtube


SAMPLE_PLAYLIST = {
    'entries': [
        {
            'id': 'abc123',
            'title': 'Select Board Meeting 3/15/2024',
            'upload_date': '20240315',
            'description': 'Hardwick Select Board',
        },
        {
            'id': 'def456',
            'title': 'Select Board Meeting 4/10/2024',
            'upload_date': '20240410',
            'description': '',
        },
        {
            'id': 'ghi789',
            'title': 'No date video',
            'upload_date': None,
            'description': '',
        },
    ],
}


@pytest.fixture()
def mock_subprocess(monkeypatch):
    result = MagicMock()
    result.stdout = json.dumps(SAMPLE_PLAYLIST)
    result.check_returncode = MagicMock()
    monkeypatch.setattr('subprocess.run', lambda *a, **kw: result)
    return result


class TestParseUploadDate:
    def test_valid_date(self):
        assert youtube._parse_upload_date('20240315') == '2024-03-15'

    def test_none_returns_none(self):
        assert youtube._parse_upload_date(None) is None

    def test_invalid_length_returns_none(self):
        assert youtube._parse_upload_date('2024') is None

    def test_invalid_format_returns_none(self):
        assert youtube._parse_upload_date('not-date') is None


class TestDateFromTitle:
    def test_extracts_slash_date(self):
        assert youtube._date_from_title('Select Board 3/15/2024') == '2024-03-15'

    def test_returns_none_when_no_date(self):
        assert youtube._date_from_title('No date here') is None

    def test_two_digit_year(self):
        assert youtube._date_from_title('Meeting 3/15/24') == '2024-03-15'

    def test_invalid_date_returns_none(self):
        assert youtube._date_from_title('Meeting 2/30/2024') is None


class TestFetchStreams:
    def test_returns_list(self, mock_subprocess):
        videos = youtube.fetch_streams()
        assert isinstance(videos, list)
        assert len(videos) == 3

    def test_video_structure(self, mock_subprocess):
        videos = youtube.fetch_streams()
        video = videos[0]
        assert 'video_id' in video
        assert 'title' in video
        assert 'date' in video
        assert 'url' in video

    def test_parses_date(self, mock_subprocess):
        videos = youtube.fetch_streams()
        assert videos[0]['date'] == '2024-03-15'

    def test_none_date_for_missing(self, mock_subprocess):
        videos = youtube.fetch_streams()
        no_date_video = next(v for v in videos if v['video_id'] == 'ghi789')
        assert no_date_video['date'] is None

    def test_url_contains_video_id(self, mock_subprocess):
        videos = youtube.fetch_streams()
        assert 'abc123' in videos[0]['url']
