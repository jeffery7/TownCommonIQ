import json

import pytest

from towncommoniq import data_store


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(data_store, 'MEETINGS_JSON', tmp_path / 'meetings.json')
    monkeypatch.setattr(data_store, 'YOUTUBE_JSON', tmp_path / 'youtube.json')
    monkeypatch.setattr(data_store, 'BOARD_JSON', tmp_path / 'board.json')
    monkeypatch.setattr(data_store, 'BOARD_HISTORY_JSON', tmp_path / 'board_history.json')
    monkeypatch.setattr(data_store, 'TOWN_MINUTES_JSON', tmp_path / 'town_minutes.json')
    monkeypatch.setattr(data_store, 'TOWN_MEETING_FILES_JSON', tmp_path / 'town_meeting_files.json')
    monkeypatch.setattr(data_store, 'TOWN_ADMIN_REPORTS_JSON', tmp_path / 'town_admin_reports.json')
    (tmp_path / 'meetings').mkdir()


class TestPathsForBoard:
    def test_default_board_uses_top_level_layout(self, tmp_path):
        paths = data_store.paths_for_board()
        assert paths.board_dir == tmp_path
        assert paths.meetings_json == tmp_path / 'meetings.json'
        assert paths.board_json == tmp_path / 'board.json'
        assert paths.board_history_json == tmp_path / 'board_history.json'

    def test_select_board_explicit_matches_default(self, tmp_path):
        assert data_store.paths_for_board('Select Board') == data_store.paths_for_board()

    def test_other_board_gets_subdirectory(self, tmp_path):
        paths = data_store.paths_for_board('Board of Health')
        assert paths.board_dir == tmp_path / 'boards' / 'board-of-health'
        assert paths.meetings_json == tmp_path / 'boards' / 'board-of-health' / 'meetings.json'

    def test_different_boards_get_different_directories(self):
        health = data_store.paths_for_board('Board of Health')
        finance = data_store.paths_for_board('Finance Committee')
        assert health.board_dir != finance.board_dir


class TestSlug:
    def test_lowercases_and_hyphenates(self):
        assert data_store._slug('Board of Health') == 'board-of-health'

    def test_collapses_punctuation(self):
        assert data_store._slug('Finance Committee!') == 'finance-committee'

    def test_strips_leading_trailing_hyphens(self):
        assert data_store._slug('  Select Board  ') == 'select-board'


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

    def test_other_board_uses_its_own_subdirectory(self, tmp_path):
        paths = data_store.paths_for_board('Board of Health')
        folder = data_store.meeting_folder('2024-03-15', '6:30 PM', paths=paths)
        assert folder == tmp_path / 'boards' / 'board-of-health' / 'meetings' / '2024' / '2024-03-15_630'
        assert folder.exists()


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

    def test_other_board_writes_to_its_own_file(self, tmp_path):
        paths = data_store.paths_for_board('Finance Committee')
        data_store.save_meetings([{'date': '2024-01-01'}], paths=paths)
        assert data_store.load_meetings(paths=paths) == [{'date': '2024-01-01'}]
        assert not (tmp_path / 'meetings.json').exists()


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


class TestTownMeetingFiles:
    def test_load_returns_empty_when_no_file(self):
        assert data_store.load_town_meeting_files() == []

    def test_roundtrip(self):
        records = [{'media_id': '9046', 'date': '2026-08-12', 'file_url': None}]
        data_store.save_town_meeting_files(records)
        assert data_store.load_town_meeting_files() == records


class TestTownAdminReports:
    def test_load_returns_empty_when_no_file(self):
        assert data_store.load_town_admin_reports() == []

    def test_roundtrip(self):
        records = [{'media_id': '9036', 'date': '2026-07-27', 'file_url': None}]
        data_store.save_town_admin_reports(records)
        assert data_store.load_town_admin_reports() == records


class TestDatedRecordFolder:
    def test_creates_directory(self, tmp_path):
        folder = data_store._dated_record_folder('town_meeting_files', '2021-06-19')
        assert folder.exists()
        assert folder.is_dir()

    def test_folder_path_organised_by_year_and_subdir(self, tmp_path):
        folder = data_store._dated_record_folder('ta_reports', '2021-06-19')
        assert folder == tmp_path / 'ta_reports' / '2021' / '2021-06-19'

    def test_idempotent(self):
        folder1 = data_store._dated_record_folder('town_meeting_files', '2021-06-19')
        folder2 = data_store._dated_record_folder('town_meeting_files', '2021-06-19')
        assert folder1 == folder2

    def test_empty_date_uses_unknown_bucket(self, tmp_path):
        folder = data_store._dated_record_folder('town_meeting_files', '')
        assert folder == tmp_path / 'town_meeting_files' / 'unknown' / ''


class TestTownMeetingFileFolder:
    def test_delegates_to_dated_record_folder(self, tmp_path):
        folder = data_store.town_meeting_file_folder('2021-06-19')
        assert folder == tmp_path / 'town_meeting_files' / '2021' / '2021-06-19'


class TestSelectBoardFolders:
    def test_maps_dated_meetings_to_their_folders(self):
        data_store.save_meetings([{'date': '2024-03-15', 'folder': '/some/path'}])
        folders = data_store._select_board_folders([], lambda title: None)
        assert folders == {'2024-03-15': '/some/path'}

    def test_ignores_meetings_missing_date_or_folder(self):
        data_store.save_meetings([{'date': '2024-03-15'}, {'folder': '/some/path'}])
        folders = data_store._select_board_folders([], lambda title: None)
        assert folders == {}

    def test_ignores_its_records_argument(self):
        data_store.save_meetings([{'date': '2024-03-15', 'folder': '/some/path'}])
        folders = data_store._select_board_folders(
            [{'date': '2099-01-01', 'title': 'irrelevant'}], lambda title: None,
        )
        assert folders == {'2024-03-15': '/some/path'}

    def test_never_reports(self):
        data_store.save_meetings([])
        reported = []
        data_store._select_board_folders([], reported.append)
        assert reported == []


class TestDatedFolders:
    def test_maps_dated_records_to_their_own_folder(self, tmp_path):
        records = [{'date': '2021-06-19', 'title': 'Annual Town Meeting Minutes'}]
        folders = data_store._dated_folders('town_meeting_files', records, lambda title: None)
        assert folders == {'2021-06-19': str(tmp_path / 'town_meeting_files' / '2021' / '2021-06-19')}

    def test_undated_record_gets_unknown_bucket_not_dropped(self, tmp_path):
        records = [{'date': None, 'title': '2025 Annual Town Report'}]
        folders = data_store._dated_folders('town_meeting_files', records, lambda title: None)
        assert folders == {None: str(tmp_path / 'town_meeting_files' / 'unknown')}

    def test_reports_only_undated_records(self):
        records = [
            {'date': '2021-06-19', 'title': 'Annual Town Meeting Minutes'},
            {'date': None, 'title': '2025 Annual Town Report'},
        ]
        reported = []
        data_store._dated_folders('town_meeting_files', records, reported.append)
        assert reported == ['2025 Annual Town Report']

    def test_uses_given_subdir(self, tmp_path):
        records = [{'date': '2026-07-27', 'title': '7-27-2026 Administrator Report'}]
        folders = data_store._dated_folders('ta_reports', records, lambda title: None)
        assert folders == {'2026-07-27': str(tmp_path / 'ta_reports' / '2026' / '2026-07-27')}


class TestSyncTownTargets:
    def test_select_board_target_fields(self):
        target = data_store.select_board_sync_target()
        assert target.label == 'minutes'
        assert target.listing_url == data_store.hardwick_town.LISTING_URL
        assert target.load == data_store.load_town_minutes
        assert target.save == data_store.save_town_minutes
        assert target.folders == data_store._select_board_folders

    def test_town_meeting_files_target_fields(self):
        target = data_store.town_meeting_files_sync_target()
        assert target.label == 'Town Meeting Files'
        assert target.listing_url == data_store.hardwick_town.TOWN_MEETING_FILES_URL
        assert target.load == data_store.load_town_meeting_files
        assert target.save == data_store.save_town_meeting_files
        assert (target.folders.func, target.folders.args) == (data_store._dated_folders, ('town_meeting_files',))

    def test_town_admin_reports_target_fields(self):
        target = data_store.town_admin_reports_sync_target()
        assert target.label == "Town Administrator's Reports"
        assert target.listing_url == data_store.hardwick_town.TOWN_ADMIN_REPORTS_URL
        assert target.load == data_store.load_town_admin_reports
        assert target.save == data_store.save_town_admin_reports
        assert (target.folders.func, target.folders.args) == (data_store._dated_folders, ('ta_reports',))

    def test_sorted_by_date(self):
        meetings = [{'date': '2024-03-01'}, {'date': '2024-01-01'}]
        result = data_store.upsert_meeting(meetings, {'date': '2024-02-01'})
        dates = [m['date'] for m in result]
        assert dates == sorted(dates)
