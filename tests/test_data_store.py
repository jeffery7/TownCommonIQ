import json

import pytest

from municipaliq import data_store


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(data_store, 'MEETINGS_JSON', tmp_path / 'meetings.json')
    monkeypatch.setattr(data_store, 'YOUTUBE_JSON', tmp_path / 'youtube.json')
    monkeypatch.setattr(data_store, 'BOARD_JSON', tmp_path / 'board.json')
    monkeypatch.setattr(data_store, 'BOARD_HISTORY_JSON', tmp_path / 'board_history.json')
    monkeypatch.setattr(data_store, 'TOWN_MINUTES_JSON', tmp_path / 'town_minutes.json')
    (tmp_path / 'meetings').mkdir()


class TestMeetingFolder:
    def test_creates_directory(self, tmp_path):
        folder = data_store.meeting_folder('2024-03-15', '6:30 PM')
        assert folder.exists()
        assert folder.is_dir()

    def test_folder_name_format(self, tmp_path):
        folder = data_store.meeting_folder('2024-03-15', '6:30 PM')
        assert '2024-03-15' in folder.name
        assert folder.parent.name == '2024'

    def test_idempotent(self, tmp_path):
        folder1 = data_store.meeting_folder('2024-03-15', '6:30 PM')
        folder2 = data_store.meeting_folder('2024-03-15', '6:30 PM')
        assert folder1 == folder2


class TestLoadSaveMeetings:
    def test_load_returns_empty_when_no_file(self):
        assert data_store.load_meetings() == []

    def test_roundtrip(self):
        meetings = [{'date': '2024-03-15', 'status': 'held'}]
        data_store.save_meetings(meetings)
        assert data_store.load_meetings() == meetings

    def test_save_writes_valid_json(self, tmp_path):
        data_store.save_meetings([{'date': '2024-01-01'}])
        raw = (tmp_path / 'meetings.json').read_text()
        assert json.loads(raw) == [{'date': '2024-01-01'}]


class TestLoadSaveYoutube:
    def test_load_returns_empty_when_no_file(self):
        assert data_store.load_youtube() == []

    def test_roundtrip(self):
        videos = [{'video_id': 'abc', 'title': 'Test'}]
        data_store.save_youtube(videos)
        assert data_store.load_youtube() == videos


class TestFindMeeting:
    def test_finds_by_date(self):
        meetings = [{'date': '2024-01-01'}, {'date': '2024-02-01'}]
        assert data_store.find_meeting(meetings, '2024-01-01') == {'date': '2024-01-01'}

    def test_returns_none_when_not_found(self):
        assert data_store.find_meeting([], '2024-01-01') is None


class TestLoadBoardInfo:
    def test_returns_default_when_no_file(self):
        assert data_store.load_board_info() == {'chair': None, 'clerk': None, 'members': []}

    def test_roundtrip(self):
        data_store.save_board_info({'chair': 'Alice', 'members': ['Alice', 'Bob']})
        result = data_store.load_board_info()
        assert result['chair'] == 'Alice'


class TestMeetingMetadata:
    def test_saves_json_file_in_folder(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meeting = {'date': '2024-03-15', 'youtube_id': 'abc123'}
        data_store.save_meeting_metadata(meeting, folder)
        assert (folder / '2024-03-15_1830_meeting.json').exists()

    def test_round_trip(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meeting = {'date': '2024-03-15', 'youtube_id': 'abc123'}
        data_store.save_meeting_metadata(meeting, folder)
        loaded = data_store.load_meeting_metadata(folder)
        assert loaded == meeting

    def test_load_returns_none_when_absent(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        assert data_store.load_meeting_metadata(folder) is None


class TestUpsertMeeting:
    def test_inserts_new(self):
        result = data_store.upsert_meeting([], {'date': '2024-01-01'})
        assert result == [{'date': '2024-01-01'}]

    def test_replaces_existing(self):
        old = [{'date': '2024-01-01', 'status': 'upcoming'}]
        result = data_store.upsert_meeting(old, {'date': '2024-01-01', 'status': 'held'})
        assert len(result) == 1
        assert result[0]['status'] == 'held'


class TestBoardHistory:
    _history = [
        {
            'from_date': '2020-01-01', 'to_date': '2021-12-31',
            'chair': 'Alice', 'clerk': 'Bob', 'members': ['Alice', 'Bob', 'Carol'],
        },
        {
            'from_date': '2022-01-01', 'to_date': None,
            'chair': 'Carol', 'clerk': 'Alice', 'members': ['Alice', 'Bob', 'Carol'],
        },
    ]

    def test_round_trip(self):
        data_store.save_board_history(self._history)
        assert data_store.load_board_history() == self._history

    def test_load_returns_empty_when_no_file(self):
        assert data_store.load_board_history() == []

    def test_board_info_for_date_matches_entry(self):
        info = data_store.board_info_for_date('2020-06-15', self._history)
        assert info['chair'] == 'Alice'

    def test_board_info_for_date_uses_latest_matching(self):
        info = data_store.board_info_for_date('2023-03-15', self._history)
        assert info['chair'] == 'Carol'

    def test_board_info_for_date_returns_none_before_history(self):
        assert data_store.board_info_for_date('2019-01-01', self._history) is None

    def test_board_info_for_date_returns_none_for_empty_history(self):
        assert data_store.board_info_for_date('2024-01-01', []) is None

    def test_board_info_includes_members(self):
        info = data_store.board_info_for_date('2020-06-15', self._history)
        assert 'Alice' in info['members']


class TestTownMinutes:
    def test_load_returns_empty_when_no_file(self):
        assert data_store.load_town_minutes() == []

    def test_roundtrip(self):
        records = [{'media_id': '8601', 'date': '2026-03-30', 'file_url': None}]
        data_store.save_town_minutes(records)
        assert data_store.load_town_minutes() == records

    def test_sorted_by_date(self):
        meetings = [{'date': '2024-03-01'}, {'date': '2024-01-01'}]
        result = data_store.upsert_meeting(meetings, {'date': '2024-02-01'})
        dates = [m['date'] for m in result]
        assert dates == sorted(dates)
