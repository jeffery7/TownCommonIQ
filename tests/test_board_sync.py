from unittest.mock import MagicMock, patch

import pytest

from towncommoniq import board_sync, data_store


@pytest.fixture()
def reorg_folder(tmp_path):
    folder = tmp_path / '2025-05-12_630'
    folder.mkdir()
    (folder / '2025-05-12_630_agenda.txt').write_text(
        'AGENDA\n1. Reorganization of Select Board',
    )
    (folder / '2025-05-12_630_transcript.txt').write_text(
        'nominate Eric Vollheim for chairman. Jeff will be clerk. '
        'William Tinker for vice chair.',
    )
    return folder


@pytest.fixture()
def non_reorg_folder(tmp_path):
    folder = tmp_path / '2025-06-09_600'
    folder.mkdir()
    (folder / '2025-06-09_600_agenda.txt').write_text(
        'AGENDA\n1. New business',
    )
    return folder


class TestIsReorgMeeting:
    def test_detects_reorganization_agenda(self, reorg_folder):
        assert board_sync._is_reorg_meeting(reorg_folder) is True

    def test_non_reorg_agenda_returns_false(self, non_reorg_folder):
        assert board_sync._is_reorg_meeting(non_reorg_folder) is False

    def test_no_agenda_returns_false(self, tmp_path):
        folder = tmp_path / 'empty'
        folder.mkdir()
        assert board_sync._is_reorg_meeting(folder) is False


class TestFindReorgMeetings:
    def test_returns_reorg_meeting_with_transcript(self, reorg_folder):
        meetings = [{'date': '2025-05-12', 'folder': str(reorg_folder)}]
        result = board_sync.find_reorg_meetings(meetings)
        assert len(result) == 1
        assert result[0]['date'] == '2025-05-12'

    def test_skips_reorg_without_transcript(self, tmp_path):
        folder = tmp_path / '2025-05-12_630'
        folder.mkdir()
        (folder / '2025-05-12_630_agenda.txt').write_text('1. Reorganization')
        meetings = [{'date': '2025-05-12', 'folder': str(folder)}]
        assert board_sync.find_reorg_meetings(meetings) == []

    def test_skips_non_reorg_meeting(self, non_reorg_folder):
        meetings = [{'date': '2025-06-09', 'folder': str(non_reorg_folder)}]
        assert board_sync.find_reorg_meetings(meetings) == []

    def test_skips_meeting_without_folder(self):
        meetings = [{'date': '2025-05-12', 'folder': None}]
        assert board_sync.find_reorg_meetings(meetings) == []


class TestDayBefore:
    def test_simple_date(self):
        assert board_sync._day_before('2025-05-12') == '2025-05-11'

    def test_month_boundary(self):
        assert board_sync._day_before('2025-05-01') == '2025-04-30'

    def test_year_boundary(self):
        assert board_sync._day_before('2026-01-01') == '2025-12-31'


class TestBuildHistoryEntry:
    def test_uses_extracted_officers(self, reorg_folder):
        meeting = {'date': '2025-05-12', 'folder': str(reorg_folder)}
        officers = {
            'chair': 'Eric W. Vollheim',
            'vice_chair': 'William F. Tinker',
            'clerk': 'Jeffrey S. Schaaf',
        }
        all_meetings = [meeting]
        with patch.object(data_store, 'load_board_history', return_value=[]):
            entry = board_sync.build_history_entry(meeting, officers, all_meetings)
        assert entry['chair'] == 'Eric W. Vollheim'
        assert entry['clerk'] == 'Jeffrey S. Schaaf'
        assert entry['vice_chair'] == 'William F. Tinker'
        assert entry['from_date'] == '2025-05-12'

    def test_to_date_is_day_before_next_reorg(self, tmp_path):
        folder_a = tmp_path / '2025-05-12_630'
        folder_b = tmp_path / '2026-05-04_600'
        folder_a.mkdir()
        folder_b.mkdir()
        (folder_a / '2025-05-12_630_agenda.txt').write_text('Reorganization')
        (folder_b / '2026-05-04_600_agenda.txt').write_text('Reorganization')
        meeting = {'date': '2025-05-12', 'folder': str(folder_a)}
        all_meetings = [
            meeting,
            {'date': '2026-05-04', 'folder': str(folder_b)},
        ]
        with patch.object(data_store, 'load_board_history', return_value=[]):
            entry = board_sync.build_history_entry(meeting, {}, all_meetings)
        assert entry['to_date'] == '2026-05-03'

    def test_to_date_is_null_when_no_next_reorg(self, reorg_folder):
        meeting = {'date': '2025-05-12', 'folder': str(reorg_folder)}
        with patch.object(data_store, 'load_board_history', return_value=[]):
            entry = board_sync.build_history_entry(meeting, {}, [meeting])
        assert entry['to_date'] is None

    def test_members_includes_all_officers(self, reorg_folder):
        meeting = {'date': '2025-05-12', 'folder': str(reorg_folder)}
        officers = {
            'chair': 'Alice',
            'vice_chair': 'Bob',
            'clerk': 'Carol',
        }
        with patch.object(data_store, 'load_board_history', return_value=[]):
            entry = board_sync.build_history_entry(meeting, officers, [meeting])
        assert 'Alice' in entry['members']
        assert 'Bob' in entry['members']
        assert 'Carol' in entry['members']


class TestExtractOfficers:
    def test_parses_clean_json_response(self):
        client = MagicMock()
        client.chat.completions.create.return_value.choices[0].message.content = (
            '{"chair": "Alice Smith", "vice_chair": "Bob Jones", "clerk": "Carol Lee"}'
        )
        result = board_sync._extract_officers(client, 'transcript text', [])
        assert result['chair'] == 'Alice Smith'
        assert result['clerk'] == 'Carol Lee'

    def test_falls_back_to_json_in_prose(self):
        client = MagicMock()
        client.chat.completions.create.return_value.choices[0].message.content = (
            'Here is what I found:\n'
            '{"chair": "Alice", "vice_chair": null, "clerk": "Bob"}\n'
            'End of response.'
        )
        result = board_sync._extract_officers(client, 'text', [])
        assert result['chair'] == 'Alice'

    def test_returns_nulls_on_parse_failure(self):
        client = MagicMock()
        client.chat.completions.create.return_value.choices[0].message.content = (
            'I could not determine the officers.'
        )
        result = board_sync._extract_officers(client, 'text', [])
        assert result == {'chair': None, 'vice_chair': None, 'clerk': None}


class TestSyncBoardHistory:
    def test_updates_history_from_transcript(self, tmp_path, monkeypatch):
        monkeypatch.setattr(data_store, 'DATA_DIR', tmp_path)
        monkeypatch.setattr(
            data_store, 'BOARD_HISTORY_JSON', tmp_path / 'board_history.json',
        )
        folder = tmp_path / '2025-05-12_630'
        folder.mkdir()
        (folder / '2025-05-12_630_agenda.txt').write_text('1. Reorganization')
        (folder / '2025-05-12_630_transcript.txt').write_text('transcript')
        meetings = [{'date': '2025-05-12', 'folder': str(folder)}]

        mock_officers = {'chair': 'Alice', 'vice_chair': 'Bob', 'clerk': 'Carol'}
        with patch.object(data_store, 'load_meetings', return_value=meetings), \
             patch.object(board_sync, '_extract_officers', return_value=mock_officers), \
             patch('towncommoniq.board_sync.OpenAI'):
            count = board_sync.sync_board_history(verbose=False)

        assert count == 1
        history = data_store.load_board_history()
        assert history[0]['chair'] == 'Alice'
        assert history[0]['from_date'] == '2025-05-12'


class TestMeetingIsReorgWithTranscript:
    def test_returns_false_when_folder_missing(self):
        meeting = {'folder': '/nonexistent/path/2025-01-01_600'}
        assert board_sync._meeting_is_reorg_with_transcript(meeting) is False

    def test_returns_false_without_folder_key(self):
        assert board_sync._meeting_is_reorg_with_transcript({}) is False


class TestGetExistingMembers:
    def test_returns_members_for_matching_date(self):
        history = [
            {'from_date': '2025-05-12', 'members': ['Alice', 'Bob']},
        ]
        result = board_sync._get_existing_members(history, '2025-05-12')
        assert result == ['Alice', 'Bob']

    def test_returns_empty_when_no_match(self):
        history = [{'from_date': '2024-05-01', 'members': ['Alice']}]
        assert board_sync._get_existing_members(history, '2025-05-12') == []


class TestCollectKnownNames:
    def test_collects_from_history_roles(self):
        history = [{'from_date': '2024-05-01', 'chair': 'Alice', 'clerk': 'Bob', 'members': []}]
        with patch.object(data_store, 'load_board_info', return_value={'members': ['Carol']}):
            names = board_sync._collect_known_names(history)
        assert 'Alice' in names
        assert 'Bob' in names
        assert 'Carol' in names


class TestNextReorgDate:
    def test_returns_none_when_no_later_reorg(self, tmp_path):
        folder = tmp_path / '2025-05-12_630'
        folder.mkdir()
        (folder / '2025-05-12_630_agenda.txt').write_text('Reorganization')
        meetings = [{'date': '2025-05-12', 'folder': str(folder)}]
        result = board_sync._next_reorg_date(meetings, '2025-05-12')
        assert result is None


class TestFolderIsReorg:
    def test_returns_false_when_folder_not_exist(self):
        meeting = {'folder': '/nonexistent/2025-01-01_600'}
        assert board_sync._folder_is_reorg(meeting) is False


class TestProcessReorg:
    def test_verbose_output(self, tmp_path, capsys):
        folder = tmp_path / '2025-05-12_630'
        folder.mkdir()
        (folder / '2025-05-12_630_transcript.txt').write_text('test transcript')
        meeting = {'date': '2025-05-12', 'folder': str(folder)}
        officers = {'chair': 'Alice', 'vice_chair': 'Bob', 'clerk': 'Carol'}
        with patch.object(board_sync, '_extract_officers', return_value=officers), \
             patch.object(data_store, 'load_board_history', return_value=[]):
            board_sync._process_reorg(None, meeting, [meeting], [], verbose=True)
        output = capsys.readouterr().out
        assert 'Alice' in output
        assert '2025-05-12' in output
