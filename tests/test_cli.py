import argparse
import sys
from unittest.mock import MagicMock, patch

import pytest

from towncommoniq import cli, data_store, document_index


MEETINGS = [
    {
        'date': '2024-03-15',
        'time': '6:30 PM',
        'location': 'Town Hall',
        'status': 'held',
        'agenda_url': None,
        'minutes_url': None,
        'meeting_url': 'http://example.com/meeting?meeting=abc',
        'youtube_id': 'abc123',
        'folder': None,
    },
    {
        'date': '2024-04-10',
        'time': '6:30 PM',
        'location': 'Town Hall',
        'status': 'held',
        'agenda_url': None,
        'minutes_url': 'http://example.com/minutes',
        'meeting_url': None,
        'youtube_id': 'def456',
        'folder': None,
    },
]

VIDEOS = [
    {'video_id': 'abc123', 'date': '2024-03-15', 'title': 'Select Board 3/15', 'url': 'https://yt.be/abc123'},
    {'video_id': 'def456', 'date': '2024-04-10', 'title': 'Select Board 4/10', 'url': 'https://yt.be/def456'},
]


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(data_store, 'MEETINGS_JSON', tmp_path / 'meetings.json')
    monkeypatch.setattr(data_store, 'YOUTUBE_JSON', tmp_path / 'youtube.json')
    monkeypatch.setattr(data_store, 'BOARD_JSON', tmp_path / 'board.json')
    monkeypatch.setattr(document_index, '_INDEX_JSON', tmp_path / 'index.json')
    (tmp_path / 'meetings').mkdir()


class TestFetchDocText:
    def test_returns_pdf_text(self):
        mock_resp = MagicMock()
        mock_resp.content = b'%PDFfake'
        mock_resp.raise_for_status = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = 'page text'
        with patch('requests.get', return_value=mock_resp), \
             patch('towncommoniq.cli.PdfReader') as mock_reader_class:
            mock_reader_class.return_value.pages = [mock_page]
            result = cli._fetch_doc_text('http://example.com/doc.pdf')
        assert result == 'page text'

    def test_returns_plain_text(self):
        mock_resp = MagicMock()
        mock_resp.content = b'plain content'
        mock_resp.text = 'plain content'
        mock_resp.raise_for_status = MagicMock()
        with patch('requests.get', return_value=mock_resp):
            result = cli._fetch_doc_text('http://example.com/doc.txt')
        assert result == 'plain content'

    def test_returns_empty_on_error(self):
        with patch('requests.get', side_effect=Exception('timeout')):
            result = cli._fetch_doc_text('http://example.com/doc.pdf')
        assert result == ''


class TestCmdSync:
    def test_sync_saves_meetings_and_videos(self):
        board_info = {'chair': 'Eric Vollheim', 'members': ['Eric W. Vollheim']}
        with patch('towncommoniq.scraper.mytowngovernment.fetch_meetings', return_value=(MEETINGS, board_info)), \
             patch('towncommoniq.scraper.youtube.fetch_streams', return_value=VIDEOS), \
             patch('towncommoniq.correlator.correlate', return_value=MEETINGS):
            args = MagicMock()
            result = cli._cmd_sync(args)
        assert result == 0
        assert len(data_store.load_meetings()) > 0
        assert len(data_store.load_youtube()) > 0

    def test_sync_adds_meeting_from_unmatched_video(self):
        unmatched_video = {'video_id': 'zzz999', 'date': '2024-06-01', 'title': 'June meeting', 'url': 'https://yt.be/zzz999'}
        board_info = {'chair': None, 'members': []}
        with patch('towncommoniq.scraper.mytowngovernment.fetch_meetings', return_value=([], board_info)), \
             patch('towncommoniq.scraper.youtube.fetch_streams', return_value=[unmatched_video]), \
             patch('towncommoniq.correlator.correlate', return_value=[]), \
             patch('towncommoniq.scraper.mytowngovernment.fetch_agenda_text', return_value=''):
            args = MagicMock()
            cli._cmd_sync(args)
        meetings = data_store.load_meetings()
        assert any(m['date'] == '2024-06-01' for m in meetings)

    def test_sync_skips_video_with_test_in_title(self):
        test_video = {'video_id': 'zzz111', 'date': '2024-06-02', 'title': 'HardwickTV Audio Test 6/2/24', 'url': 'https://yt.be/zzz111'}
        board_info = {'chair': None, 'members': []}
        with patch('towncommoniq.scraper.mytowngovernment.fetch_meetings', return_value=([], board_info)), \
             patch('towncommoniq.scraper.youtube.fetch_streams', return_value=[test_video]), \
             patch('towncommoniq.correlator.correlate', return_value=[]):
            args = MagicMock()
            cli._cmd_sync(args)
        assert data_store.load_meetings() == []

    def test_sync_skips_video_with_no_date(self):
        no_date_video = {'video_id': 'zzz000', 'date': None, 'title': 'No date', 'url': 'https://yt.be/zzz000'}
        board_info = {'chair': None, 'members': []}
        with patch('towncommoniq.scraper.mytowngovernment.fetch_meetings', return_value=([], board_info)), \
             patch('towncommoniq.scraper.youtube.fetch_streams', return_value=[no_date_video]), \
             patch('towncommoniq.correlator.correlate', return_value=[]):
            args = MagicMock()
            cli._cmd_sync(args)
        assert data_store.load_meetings() == []

    def test_sync_skips_agenda_when_no_youtube_id(self, tmp_path):
        folder = tmp_path / 'meetings' / '2024-03-15_1830'
        folder.mkdir(parents=True)
        meeting_no_yt = {**MEETINGS[0], 'folder': str(folder), 'youtube_id': None, 'meeting_url': None}
        board_info = {'chair': None, 'members': []}
        with patch('towncommoniq.scraper.mytowngovernment.fetch_meetings', return_value=([meeting_no_yt], board_info)), \
             patch('towncommoniq.scraper.youtube.fetch_streams', return_value=[]), \
             patch('towncommoniq.correlator.correlate', return_value=[meeting_no_yt]), \
             patch('towncommoniq.scraper.mytowngovernment.fetch_agenda_text') as mock_fetch:
            args = MagicMock()
            cli._cmd_sync(args)
        mock_fetch.assert_not_called()

    def test_sync_skips_agenda_when_no_meeting_url(self, tmp_path):
        folder = tmp_path / 'meetings' / '2024-03-15_1830'
        folder.mkdir(parents=True)
        meeting_no_url = {**MEETINGS[0], 'folder': str(folder), 'meeting_url': None}
        board_info = {'chair': None, 'members': []}
        with patch('towncommoniq.scraper.mytowngovernment.fetch_meetings', return_value=([meeting_no_url], board_info)), \
             patch('towncommoniq.scraper.youtube.fetch_streams', return_value=[]), \
             patch('towncommoniq.correlator.correlate', return_value=[meeting_no_url]), \
             patch('towncommoniq.scraper.mytowngovernment.fetch_agenda_text') as mock_fetch:
            args = MagicMock()
            cli._cmd_sync(args)
        mock_fetch.assert_not_called()

    def test_sync_skips_agenda_when_already_cached(self, tmp_path):
        folder = tmp_path / 'meetings' / '2024-03-15_1830'
        folder.mkdir(parents=True)
        (folder / '2024-03-15_1830_agenda.txt').write_text('existing')
        meeting = {**MEETINGS[0], 'folder': str(folder)}
        board_info = {'chair': None, 'members': []}
        with patch('towncommoniq.scraper.mytowngovernment.fetch_meetings', return_value=([meeting], board_info)), \
             patch('towncommoniq.scraper.youtube.fetch_streams', return_value=[]), \
             patch('towncommoniq.correlator.correlate', return_value=[meeting]), \
             patch('towncommoniq.scraper.mytowngovernment.fetch_agenda_text') as mock_fetch:
            args = MagicMock()
            cli._cmd_sync(args)
        mock_fetch.assert_not_called()

    def test_sync_caches_agenda(self, tmp_path):
        folder = tmp_path / 'meetings' / '2024-03-15_1830'
        folder.mkdir(parents=True)
        meetings_with_url = [
            {**MEETINGS[0], 'folder': str(folder)},
        ]
        board_info = {'chair': None, 'members': []}
        with patch('towncommoniq.scraper.mytowngovernment.fetch_meetings', return_value=(meetings_with_url, board_info)), \
             patch('towncommoniq.scraper.youtube.fetch_streams', return_value=[]), \
             patch('towncommoniq.correlator.correlate', return_value=meetings_with_url), \
             patch('towncommoniq.scraper.mytowngovernment.fetch_agenda_text', return_value='1. Call to order\n2. Adjournment'):
            args = MagicMock()
            cli._cmd_sync(args)
        assert (folder / '2024-03-15_1830_agenda.txt').exists()

    def test_sync_sorts_meetings_before_correlating(self):
        # Scraper returns meetings newest-first; correlator must receive them
        # chronologically so the exact-date meeting wins over a ±1-day neighbour.
        scraped = [
            {'date': '2024-03-16', 'status': 'cancelled', 'youtube_id': None},
            {'date': '2024-03-15', 'status': 'held', 'youtube_id': None},
        ]
        board_info = {'chair': None, 'members': []}
        received_order = []

        def capture_correlate(meetings, videos):
            received_order.extend(m['date'] for m in meetings)
            return meetings

        with patch('towncommoniq.scraper.mytowngovernment.fetch_meetings', return_value=(scraped, board_info)), \
             patch('towncommoniq.scraper.youtube.fetch_streams', return_value=[]), \
             patch('towncommoniq.correlator.correlate', side_effect=capture_correlate):
            args = MagicMock()
            cli._cmd_sync(args)

        assert received_order == ['2024-03-15', '2024-03-16']


class TestCmdList:
    def test_list_all(self, capsys):
        data_store.save_meetings(MEETINGS)
        args = MagicMock()
        args.missing = False
        args.no_draft = False
        args.has_transcript = False
        args.undownloaded = False
        cli._cmd_list(args)
        out = capsys.readouterr().out
        assert '2024-03-15' in out
        assert '2024-04-10' in out

    def test_list_missing_filters(self, capsys):
        data_store.save_meetings(MEETINGS)
        args = MagicMock()
        args.missing = True
        args.no_draft = False
        args.has_transcript = False
        args.undownloaded = False
        cli._cmd_list(args)
        out = capsys.readouterr().out
        assert '2024-03-15' in out
        assert '2024-04-10' not in out  # already has minutes

    def test_list_no_draft_filters(self, capsys, tmp_path):
        from towncommoniq import document_index
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_minutes_draft_generated.docx').write_bytes(b'PK')
        meetings = [{**MEETINGS[0], 'folder': str(folder)}, MEETINGS[1]]
        data_store.save_meetings(meetings)
        index = document_index.build_index(meetings)
        document_index.save_index(index)
        args = MagicMock()
        args.missing = False
        args.no_draft = True
        args.has_transcript = False
        args.undownloaded = False
        cli._cmd_list(args)
        out = capsys.readouterr().out
        assert '2024-03-15' not in out  # has a draft
        assert '2024-04-10' in out

    def test_list_has_transcript_filters(self, capsys, tmp_path):
        from towncommoniq import document_index
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_transcript.txt').write_text('text')
        meetings = [{**MEETINGS[0], 'folder': str(folder)}, MEETINGS[1]]
        data_store.save_meetings(meetings)
        index = document_index.build_index(meetings)
        document_index.save_index(index)
        args = MagicMock()
        args.missing = False
        args.no_draft = False
        args.has_transcript = True
        args.undownloaded = False
        cli._cmd_list(args)
        out = capsys.readouterr().out
        assert '2024-03-15' in out      # has transcript
        assert '2024-04-10' not in out  # no transcript

    def test_shows_index_status(self, capsys, tmp_path):
        from towncommoniq import document_index
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_transcript.txt').write_text('text')
        meetings = [{**MEETINGS[0], 'folder': str(folder)}]
        data_store.save_meetings(meetings)
        index = document_index.build_index(meetings)
        document_index.save_index(index)
        args = MagicMock()
        args.missing = False
        args.no_draft = False
        args.has_transcript = False
        args.undownloaded = False
        cli._cmd_list(args)
        out = capsys.readouterr().out
        assert 'transcript:Y' in out
        assert 'draft:N' in out

    def test_empty_list(self, capsys):
        args = MagicMock()
        args.missing = False
        args.no_draft = False
        args.has_transcript = False
        args.undownloaded = False
        cli._cmd_list(args)
        out = capsys.readouterr().out
        assert 'No meetings' in out

    def test_undownloaded_shows_meeting_with_minutes_url_not_downloaded(self, capsys):
        meeting = {
            'date': '2024-03-15', 'status': 'held', 'youtube_id': None,
            'minutes_url': 'http://example.com/minutes.pdf',
            'posted_meeting_files': [],
        }
        data_store.save_meetings([meeting])
        args = MagicMock()
        args.missing = False
        args.no_draft = False
        args.has_transcript = False
        args.undownloaded = True
        cli._cmd_list(args)
        assert '2024-03-15' in capsys.readouterr().out

    def test_undownloaded_excludes_already_downloaded(self, capsys):
        meeting = {
            'date': '2024-03-15', 'status': 'held', 'youtube_id': None,
            'minutes_url': 'http://example.com/minutes.pdf',
            'posted_meeting_files': [{'type': 'minutes', 'downloaded': True, 'filename': 'f.pdf'}],
        }
        data_store.save_meetings([meeting])
        args = MagicMock()
        args.missing = False
        args.no_draft = False
        args.has_transcript = False
        args.undownloaded = True
        cli._cmd_list(args)
        assert 'No meetings' in capsys.readouterr().out

    def test_undownloaded_excludes_meetings_without_minutes_url(self, capsys):
        data_store.save_meetings([MEETINGS[0]])  # MEETINGS[0] has no minutes_url
        args = MagicMock()
        args.missing = False
        args.no_draft = False
        args.has_transcript = False
        args.undownloaded = True
        cli._cmd_list(args)
        assert 'No meetings' in capsys.readouterr().out


class TestNotifyNewMinutes:
    def test_no_output_when_nothing_new(self, capsys):
        old = [{'date': '2024-03-15', 'minutes_url': 'http://example.com/m.pdf'}]
        fresh = [{'date': '2024-03-15', 'minutes_url': 'http://example.com/m.pdf'}]
        cli._notify_new_minutes(old, fresh)
        assert capsys.readouterr().out == ''

    def test_no_output_when_fresh_also_has_no_minutes(self, capsys):
        old = [{'date': '2024-03-15', 'minutes_url': None}]
        fresh = [{'date': '2024-03-15', 'minutes_url': None}]
        cli._notify_new_minutes(old, fresh)
        assert capsys.readouterr().out == ''

    def test_prints_notice_for_newly_posted_minutes(self, capsys):
        old = [{'date': '2024-03-15', 'minutes_url': None}]
        fresh = [{'date': '2024-03-15', 'minutes_url': 'http://example.com/m.pdf'}]
        cli._notify_new_minutes(old, fresh)
        out = capsys.readouterr().out
        assert '1 meeting(s)' in out
        assert '2024-03-15' in out
        assert 'archive --since' in out

    def test_includes_earliest_date_in_archive_hint(self, capsys):
        old = [
            {'date': '2024-01-15', 'minutes_url': None},
            {'date': '2024-03-15', 'minutes_url': None},
        ]
        fresh = [
            {'date': '2024-01-15', 'minutes_url': 'http://example.com/a.pdf'},
            {'date': '2024-03-15', 'minutes_url': 'http://example.com/b.pdf'},
        ]
        cli._notify_new_minutes(old, fresh)
        out = capsys.readouterr().out
        assert '2 meeting(s)' in out
        assert '2024-01-15' in out

    def test_skips_meetings_with_no_date(self, capsys):
        old = []
        fresh = [{'date': None, 'minutes_url': 'http://example.com/m.pdf'}]
        cli._notify_new_minutes(old, fresh)
        assert capsys.readouterr().out == ''

    def test_sync_prints_notice_for_newly_posted_minutes(self, capsys):
        old = [{'date': '2024-03-15', 'status': 'held', 'minutes_url': None,
                'youtube_id': 'abc', 'folder': None}]
        fresh_with_minutes = [{**old[0], 'minutes_url': 'http://example.com/m.pdf'}]
        board_info = {'chair': None, 'members': []}
        data_store.save_meetings(old)
        with patch('towncommoniq.scraper.mytowngovernment.fetch_meetings',
                   return_value=(fresh_with_minutes, board_info)), \
             patch('towncommoniq.scraper.youtube.fetch_streams', return_value=[]), \
             patch('towncommoniq.correlator.correlate', return_value=fresh_with_minutes):
            cli._cmd_sync(MagicMock())
        assert 'newly-posted' in capsys.readouterr().out


class TestGetBoardForMeeting:
    def test_returns_matched_history_entry(self):
        history = [{'from_date': '2024-01-01', 'to_date': '2024-12-31', 'members': ['A']}]
        with patch.object(data_store, 'load_board_history', return_value=history):
            result = cli._get_board_for_meeting({'date': '2024-06-01'})
        assert result['members'] == ['A']

    def test_uses_earliest_entry_for_pre_history_dates(self):
        history = [{'from_date': '2025-05-01', 'to_date': None, 'members': ['B']}]
        with patch.object(data_store, 'load_board_history', return_value=history):
            result = cli._get_board_for_meeting({'date': '2024-02-26'})
        assert result['members'] == ['B']

    def test_falls_back_to_board_json_when_history_empty(self):
        board = {'members': ['C']}
        with patch.object(data_store, 'load_board_history', return_value=[]), \
             patch.object(data_store, 'load_board_info', return_value=board):
            result = cli._get_board_for_meeting({'date': '2024-02-26'})
        assert result['members'] == ['C']

    def test_uses_current_board_for_post_history_dates(self):
        history = [{'from_date': '2024-01-01', 'to_date': '2024-12-31', 'members': ['A']}]
        current = {'members': ['D']}
        with patch.object(data_store, 'load_board_history', return_value=history), \
             patch.object(data_store, 'load_board_info', return_value=current):
            result = cli._get_board_for_meeting({'date': '2025-06-01'})
        assert result['members'] == ['D']


class TestGenerateOne:
    def test_skips_when_no_youtube_id(self, capsys, tmp_path):
        meeting = {**MEETINGS[0], 'youtube_id': None, 'folder': str(tmp_path)}
        cli._generate_one(meeting, [meeting])
        out = capsys.readouterr().out
        assert 'Skipping' in out

    def test_generates_docx(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meeting = {**MEETINGS[0], 'folder': str(folder)}
        with patch('towncommoniq.transcript.get_transcript', return_value='text'), \
             patch('towncommoniq.cli.generate_minutes') as mock_gen:
            cli._generate_one(meeting, [meeting])
        assert mock_gen.called

    def test_fetches_agenda_from_meeting_url(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meeting = {**MEETINGS[0], 'folder': str(folder)}
        with patch('towncommoniq.transcript.get_transcript', return_value='text'), \
             patch('towncommoniq.cli.generate_minutes'), \
             patch('towncommoniq.scraper.mytowngovernment.fetch_agenda_text', return_value='Agenda content') as mock_fetch:
            cli._generate_one(meeting, [meeting])
        mock_fetch.assert_called_once_with(MEETINGS[0]['meeting_url'])
        assert (folder / '2024-03-15_1830_agenda.txt').read_text() == 'Agenda content'

    def test_reads_cached_agenda_txt(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_agenda.txt').write_text('Cached agenda content')
        meeting = {**MEETINGS[0], 'folder': str(folder)}
        captured = {}

        def fake_generate(mtg, agenda_text, transcript_text, output_path, board_info=None):
            captured['agenda_text'] = agenda_text
        with patch('towncommoniq.transcript.get_transcript', return_value='text'), \
             patch('towncommoniq.cli.generate_minutes', side_effect=fake_generate), \
             patch('towncommoniq.scraper.mytowngovernment.fetch_agenda_text') as mock_fetch:
            cli._generate_one(meeting, [meeting])
        assert captured['agenda_text'] == 'Cached agenda content'
        mock_fetch.assert_not_called()  # should not fetch when cache exists

    def test_uses_local_audio_when_no_youtube_id(self, tmp_path):
        folder = tmp_path / '2025-07-15_0000'
        folder.mkdir()
        (folder / 'meeting.ogg').write_bytes(b'audio')
        meeting = {**MEETINGS[0], 'youtube_id': None, 'folder': str(folder)}
        with patch('towncommoniq.transcript.transcribe_audio', return_value='text') as mock_ta, \
             patch('towncommoniq.cli.generate_minutes') as mock_gen:
            cli._generate_one(meeting, [meeting])
        mock_ta.assert_called_once()
        mock_gen.assert_called_once()

    def test_skips_when_draft_exists(self, capsys, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_minutes_draft_generated.docx').write_bytes(b'existing')
        meeting = {**MEETINGS[0], 'folder': str(folder)}
        with patch('towncommoniq.transcript.get_transcript') as mock_t, \
             patch('towncommoniq.cli.generate_minutes') as mock_gen:
            cli._generate_one(meeting, [meeting])
        assert 'Skipping' in capsys.readouterr().out
        mock_t.assert_not_called()
        mock_gen.assert_not_called()

    def test_force_regenerates_existing_draft(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_minutes_draft_generated.docx').write_bytes(b'existing')
        meeting = {**MEETINGS[0], 'folder': str(folder)}
        with patch('towncommoniq.transcript.get_transcript', return_value='text'), \
             patch('towncommoniq.cli.generate_minutes') as mock_gen:
            cli._generate_one(meeting, [meeting], force=True)
        mock_gen.assert_called_once()


class TestGenerateOneAgendaUrl:
    def test_fetches_agenda_from_agenda_url(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meeting = {
            **MEETINGS[0],
            'folder': str(folder),
            'meeting_url': None,
            'agenda_url': 'http://example.com/agenda.pdf',
        }
        with patch('towncommoniq.transcript.get_transcript', return_value='text'), \
             patch('towncommoniq.cli.generate_minutes'), \
             patch('towncommoniq.cli._fetch_doc_text', return_value='Agenda text') as mock_fetch:
            cli._generate_one(meeting, [meeting])
        mock_fetch.assert_called_once_with('http://example.com/agenda.pdf')
        assert (folder / '2024-03-15_1830_agenda.txt').read_text() == 'Agenda text'

    def test_returns_empty_when_no_urls(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meeting = {
            **MEETINGS[0],
            'folder': str(folder),
            'meeting_url': None,
            'agenda_url': None,
        }
        captured = {}

        def fake_generate(mtg, agenda_text, transcript_text, output_path, board_info=None):
            captured['agenda_text'] = agenda_text
        with patch('towncommoniq.transcript.get_transcript', return_value='text'), \
             patch('towncommoniq.cli.generate_minutes', side_effect=fake_generate):
            cli._generate_one(meeting, [meeting])
        assert captured['agenda_text'] == ''


class TestCmdArchive:
    def test_archive_all_calls_archiver(self):
        data_store.save_meetings(MEETINGS)
        with patch.object(cli.archiver, 'archive_all',
                          return_value={'docs_saved': 2, 'agendas_saved': 1, 'transcripts_saved': 1}) as mock_aa:
            args = MagicMock()
            args.date = None
            args.all = True
            args.since = None
            args.cookies = None
            args.proxy = None
            result = cli._cmd_archive(args)
        assert result == 0
        mock_aa.assert_called_once()

    def test_archive_specific_date(self):
        data_store.save_meetings(MEETINGS)
        with patch.object(cli.archiver, 'archive_all',
                          return_value={'docs_saved': 0, 'agendas_saved': 0, 'transcripts_saved': 0}):
            args = MagicMock()
            args.date = '2024-03-15'
            args.all = False
            args.since = None
            args.cookies = None
            args.proxy = None
            result = cli._cmd_archive(args)
        assert result == 0

    def test_archive_unknown_date_returns_error(self, capsys):
        data_store.save_meetings([])
        args = MagicMock()
        args.date = '1999-01-01'
        args.all = False
        args.since = None
        args.cookies = None
        args.proxy = None
        assert cli._cmd_archive(args) == 1

    def test_archive_since_filters_by_date(self):
        data_store.save_meetings(MEETINGS)
        with patch.object(cli.archiver, 'archive_all',
                          return_value={'docs_saved': 0, 'agendas_saved': 0, 'transcripts_saved': 0}) as mock_aa:
            args = MagicMock()
            args.date = None
            args.all = False
            args.since = '2024-04-01'
            args.cookies = None
            args.proxy = None
            cli._cmd_archive(args)
        meetings_passed = mock_aa.call_args[0][0]
        dates = [m['date'] for m in meetings_passed]
        assert '2024-03-15' not in dates
        assert '2024-04-10' in dates

    def test_archive_no_targets_returns_zero(self, capsys):
        data_store.save_meetings([])
        args = MagicMock()
        args.date = None
        args.all = True
        args.since = None
        args.cookies = None
        args.proxy = None
        result = cli._cmd_archive(args)
        assert result == 0
        assert 'No meetings' in capsys.readouterr().out

    def test_archive_no_flag_returns_error(self, capsys):
        args = MagicMock()
        args.date = None
        args.all = False
        args.since = None
        args.cookies = None
        args.proxy = None
        assert cli._cmd_archive(args) == 1

    def test_archive_with_cookies_configures_client(self, tmp_path):
        data_store.save_meetings([])
        args = MagicMock()
        args.date = None
        args.all = True
        args.since = None
        args.cookies = str(tmp_path / 'cookies.txt')
        args.proxy = None
        with patch.object(cli.transcript, 'configure_cookies') as mock_cc:
            cli._cmd_archive(args)
        mock_cc.assert_called_once_with(args.cookies)

    def test_archive_with_proxy_configures_proxy(self):
        data_store.save_meetings([])
        args = MagicMock()
        args.date = None
        args.all = True
        args.since = None
        args.cookies = None
        args.proxy = 'socks5://127.0.0.1:1080'
        with patch.object(cli.transcript, 'configure_proxy') as mock_cp:
            cli._cmd_archive(args)
        mock_cp.assert_called_once_with('socks5://127.0.0.1:1080')


class TestMain:
    def test_sync_command(self):
        assert callable(cli.main)

    def test_no_args_exits(self):
        with patch.object(sys, 'argv', ['prog']):
            with pytest.raises(SystemExit):
                cli.main()

    def test_dispatches_list(self):
        with patch.object(sys, 'argv', ['prog', 'list']), \
             patch.object(cli, '_cmd_list', return_value=0) as mock_list:
            cli.main()
        mock_list.assert_called_once()

    def test_dispatches_generate(self):
        with patch.object(sys, 'argv', ['prog', 'generate', '--date', '2024-01-01']), \
             patch.object(cli, '_cmd_generate', return_value=0) as mock_gen:
            cli.main()
        mock_gen.assert_called_once()


class TestCmdGenerate:
    def test_generate_no_date_no_all_returns_error(self, capsys):
        args = MagicMock()
        args.date = None
        args.all = False
        args.since = None
        result = cli._cmd_generate(args)
        assert result == 1

    def test_generate_all_no_eligible_returns_zero(self, capsys):
        data_store.save_meetings([])
        args = MagicMock()
        args.date = None
        args.all = True
        args.since = None
        result = cli._cmd_generate(args)
        assert result == 0
        assert 'No eligible' in capsys.readouterr().out

    def test_generate_specific_date(self, tmp_path):
        data_store.save_meetings(MEETINGS)
        meeting = MEETINGS[0].copy()
        meeting['folder'] = str(tmp_path / 'meetings' / '2024-03-15_1830')

        with patch.object(cli, '_generate_one') as mock_gen:
            args = MagicMock()
            args.date = '2024-03-15'
            args.all = False
            args.since = None
            cli._cmd_generate(args)
        assert mock_gen.called

    def test_generate_unknown_date_returns_error(self, capsys):
        data_store.save_meetings([])
        args = MagicMock()
        args.date = '1999-01-01'
        args.all = False
        args.since = None
        result = cli._cmd_generate(args)
        assert result == 1

    def test_generate_all_skips_with_minutes(self):
        data_store.save_meetings(MEETINGS)
        with patch.object(cli, '_generate_one') as mock_gen:
            args = MagicMock()
            args.date = None
            args.all = True
            args.since = None
            cli._cmd_generate(args)
        assert mock_gen.call_count == 1

    def test_generate_all_includes_local_audio_meetings(self, tmp_path):
        folder = tmp_path / '2025-07-15_0000'
        folder.mkdir()
        (folder / 'meeting.ogg').write_bytes(b'audio')
        audio_meeting = {
            'date': '2025-07-15', 'time': '', 'location': '', 'status': 'held',
            'agenda_url': None, 'minutes_url': None, 'meeting_url': None,
            'youtube_id': None, 'folder': str(folder),
        }
        data_store.save_meetings([audio_meeting])
        with patch.object(cli, '_generate_one') as mock_gen:
            args = MagicMock()
            args.date = None
            args.all = True
            args.since = None
            args.force = False
            cli._cmd_generate(args)
        assert mock_gen.call_count == 1
        assert mock_gen.call_args[0][0]['date'] == '2025-07-15'

    def test_generate_since_filters_by_date(self):
        data_store.save_meetings(MEETINGS)
        with patch.object(cli, '_generate_one') as mock_gen:
            args = MagicMock()
            args.date = None
            args.all = False
            args.since = '2024-04-01'
            cli._cmd_generate(args)
        dates = [call.args[0]['date'] for call in mock_gen.call_args_list]
        assert '2024-03-15' not in dates

    def test_generate_since_includes_on_and_after(self):
        data_store.save_meetings(MEETINGS)
        eligible = {**MEETINGS[1], 'minutes_url': None, 'youtube_id': 'xyz'}
        data_store.save_meetings([MEETINGS[0], eligible])
        with patch.object(cli, '_generate_one') as mock_gen:
            args = MagicMock()
            args.date = None
            args.all = False
            args.since = '2024-04-10'
            cli._cmd_generate(args)
        dates = [call.args[0]['date'] for call in mock_gen.call_args_list]
        assert '2024-04-10' in dates
        assert '2024-03-15' not in dates


class TestHasLocalMinutes:
    def test_returns_true_when_minutes_doc_downloaded(self):
        meeting = {'posted_meeting_files': [{'type': 'minutes', 'downloaded': True}]}
        assert cli._has_local_minutes(meeting) is True

    def test_returns_false_when_minutes_not_downloaded(self):
        meeting = {'posted_meeting_files': [{'type': 'minutes', 'downloaded': False}]}
        assert cli._has_local_minutes(meeting) is False

    def test_returns_false_when_only_agenda_downloaded(self):
        meeting = {'posted_meeting_files': [{'type': 'agenda', 'downloaded': True}]}
        assert cli._has_local_minutes(meeting) is False

    def test_returns_false_when_no_posted_files(self):
        assert cli._has_local_minutes({}) is False


class TestEligibleLocalFilesIgnored:
    def test_eligible_even_when_local_minutes_pdf_exists_in_filesystem(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_minutes.pdf').write_bytes(b'fake')
        meeting = {
            'status': 'held', 'minutes_url': None,
            'youtube_id': 'abc', 'folder': str(folder),
            'posted_meeting_files': [],
        }
        assert cli._eligible(meeting) is True

    def test_eligible_when_draft_exists_but_no_minutes_url(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_minutes_draft_generated.docx').write_bytes(b'fake')
        meeting = {
            'status': 'held', 'minutes_url': None,
            'youtube_id': 'abc', 'folder': str(folder),
            'posted_meeting_files': [],
        }
        assert cli._eligible(meeting) is True

    def test_ineligible_when_minutes_url_set_regardless_of_local_files(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meeting = {
            'status': 'held', 'minutes_url': 'http://example.com/minutes.pdf',
            'youtube_id': 'abc', 'folder': str(folder),
        }
        assert cli._eligible(meeting) is False

    def test_ineligible_when_metadata_has_downloaded_minutes(self):
        meeting = {
            'status': 'held', 'minutes_url': None, 'youtube_id': 'abc',
            'posted_meeting_files': [{'type': 'minutes', 'downloaded': True}],
        }
        assert cli._eligible(meeting) is False


class TestFetchDocTextExtra:
    def test_returns_empty_on_http_error(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception('404')
        with patch('requests.get', return_value=mock_resp):
            result = cli._fetch_doc_text('http://example.com/doc.pdf')
        assert result == ''


class TestCmdSyncBoard:
    def test_runs_sync_and_reports_count(self, capsys):
        with patch.object(cli.board_sync, 'sync_board_history', return_value=3):
            args = MagicMock()
            result = cli._cmd_sync_board(args)
        assert result == 0
        assert '3' in capsys.readouterr().out


class TestDoArchiveWork:
    def test_no_recordings_branch(self, tmp_path):
        data_store.save_meetings(MEETINGS)
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        targets = [{**MEETINGS[0], 'folder': str(folder)}]
        summary = {'docs_saved': 0, 'agendas_saved': 0, 'transcripts_saved': 0}
        args = MagicMock()
        args.recordings = False
        args.audio_only = False
        with patch.object(cli.archiver, 'archive_all', return_value=summary), \
             patch.object(cli.document_index, 'save_index'), \
             patch.object(cli.document_index, 'build_index', return_value={}):
            cli._do_archive_work(args, targets, list(MEETINGS))


class TestHasVideoOrAudio:
    def test_returns_true_when_youtube_id_set(self):
        assert cli._has_video_or_audio({'youtube_id': 'abc123'}) is True

    def test_returns_false_when_no_folder(self):
        assert cli._has_video_or_audio({'youtube_id': None, 'folder': None}) is False

    def test_returns_true_when_audio_file_in_folder(self, tmp_path):
        (tmp_path / 'meeting_recording.ogg').write_bytes(b'fake')
        assert cli._has_video_or_audio({'youtube_id': None, 'folder': str(tmp_path)}) is True

    def test_returns_false_when_no_audio_in_folder(self, tmp_path):
        assert cli._has_video_or_audio({'youtube_id': None, 'folder': str(tmp_path)}) is False


class TestEligibleAllBranches:
    def test_not_held_returns_false(self):
        assert cli._eligible({'status': 'upcoming', 'minutes_url': None}) is False

    def test_no_folder_returns_false(self):
        meeting = {
            'status': 'held', 'minutes_url': None,
            'youtube_id': None, 'folder': None, 'posted_meeting_files': [],
        }
        assert cli._eligible(meeting) is False

    def test_audio_file_in_folder_returns_true(self, tmp_path):
        (tmp_path / 'meeting_recording.ogg').write_bytes(b'fake')
        meeting = {
            'status': 'held', 'minutes_url': None,
            'youtube_id': None, 'folder': str(tmp_path), 'posted_meeting_files': [],
        }
        assert cli._eligible(meeting) is True


class TestFolderIsReorgBranch:
    def test_returns_false_when_folder_key_absent(self):
        from towncommoniq import board_sync
        assert board_sync._folder_is_reorg({'date': '2025-05-12'}) is False


class TestCmdSyncTown:
    def test_sync_town_saves_records(self, tmp_path):
        town_dir = tmp_path / 'meetings' / '2024' / '2026-03-30_1830'
        town_dir.mkdir(parents=True)
        meetings = [{'date': '2026-03-30', 'folder': str(town_dir)}]
        data_store.save_meetings(meetings)
        fresh_records = [
            {
                'date': '2026-03-30', 'title': 'Minutes March 30',
                'media_id': '8601', 'media_url': 'http://town.example.com/media/8601',
                'file_url': 'http://town.example.com/file.pdf',
                'filename': 'file.pdf', 'downloaded': False,
            },
        ]
        args = argparse.Namespace(no_headless=False)
        with patch.object(cli.hardwick_town, 'fetch_minutes_list', return_value=fresh_records), \
             patch.object(cli.hardwick_town, 'merge_cached', return_value=fresh_records), \
             patch.object(cli.hardwick_town, 'resolve_file_urls'), \
             patch.object(cli.hardwick_town, 'download_all', return_value=1):
            result = cli._cmd_sync_town(args)
        assert result == 0
        saved = data_store.load_town_minutes()
        assert len(saved) == 1

    def test_sync_town_resolves_unresolved_urls(self):
        data_store.save_meetings([])
        fresh_records = [
            {
                'date': '2026-03-30', 'title': 'Minutes',
                'media_id': '8601', 'media_url': 'http://x.com/media/8601',
                'file_url': None, 'filename': None, 'downloaded': False,
            },
        ]
        args = argparse.Namespace(no_headless=False)
        with patch.object(cli.hardwick_town, 'fetch_minutes_list', return_value=fresh_records), \
             patch.object(cli.hardwick_town, 'merge_cached', return_value=fresh_records), \
             patch.object(cli.hardwick_town, 'resolve_file_urls') as mock_resolve, \
             patch.object(cli.hardwick_town, 'download_all', return_value=0):
            cli._cmd_sync_town(args)
        mock_resolve.assert_called_once()


class TestCmdCompare:
    def test_compare_outputs_report(self, capsys):
        data_store.save_meetings([])
        args = argparse.Namespace(output='')
        result = cli._cmd_compare(args)
        assert result == 0
        out = capsys.readouterr().out
        assert 'Hardwick Select Board' in out

    def test_compare_saves_to_file(self, tmp_path, capsys):
        data_store.save_meetings([])
        output_file = str(tmp_path / 'report.txt')
        args = argparse.Namespace(output=output_file)
        cli._cmd_compare(args)
        assert (tmp_path / 'report.txt').exists()
        assert 'Hardwick Select Board' in (tmp_path / 'report.txt').read_text()


class TestCmdSetAttendance:
    def test_sets_absent_members(self):
        meetings = [{'date': '2024-03-15', 'status': 'held', 'folder': None}]
        data_store.save_meetings(meetings)
        args = argparse.Namespace(date='2024-03-15', absent='Eric Vollheim,Bob Jones')
        result = cli._cmd_set_attendance(args)
        assert result == 0
        updated = data_store.load_meetings()
        assert updated[0]['members_absent'] == ['Eric Vollheim', 'Bob Jones']

    def test_returns_error_for_unknown_date(self, capsys):
        data_store.save_meetings([])
        args = argparse.Namespace(date='2099-01-01', absent='Eric Vollheim')
        result = cli._cmd_set_attendance(args)
        assert result == 1

    def test_empty_absent_sets_empty_list(self):
        meetings = [{'date': '2024-03-15', 'status': 'held', 'folder': None}]
        data_store.save_meetings(meetings)
        args = argparse.Namespace(date='2024-03-15', absent='')
        result = cli._cmd_set_attendance(args)
        assert result == 0
        updated = data_store.load_meetings()
        assert updated[0]['members_absent'] == []

    def test_strips_whitespace_from_names(self):
        meetings = [{'date': '2024-03-15', 'status': 'held', 'folder': None}]
        data_store.save_meetings(meetings)
        args = argparse.Namespace(date='2024-03-15', absent=' Eric Vollheim , Bob Jones ')
        cli._cmd_set_attendance(args)
        updated = data_store.load_meetings()
        assert updated[0]['members_absent'] == ['Eric Vollheim', 'Bob Jones']
