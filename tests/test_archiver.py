import datetime
from unittest.mock import patch

from municipaliq import archiver, data_store, downloader, transcript
from municipaliq.scraper import mytowngovernment


MEETING = {
    'date': '2024-03-15',
    'youtube_id': 'abc123',
    'meeting_url': 'http://example.com/meeting?meeting=abc',
    'folder': None,
}


class TestSafeFilename:
    def test_preserves_normal_name(self):
        assert archiver._safe_filename('03-11-2024 Minutes.pdf') == '03-11-2024 Minutes.pdf'

    def test_removes_forward_slash(self):
        assert '/' not in archiver._safe_filename('path/to/file.pdf')

    def test_removes_backslash(self):
        assert '\\' not in archiver._safe_filename(r'path\file.pdf')

    def test_strips_leading_trailing_whitespace(self):
        assert archiver._safe_filename('  name.pdf  ') == 'name.pdf'

    def test_removes_colon(self):
        assert ':' not in archiver._safe_filename('C:file.pdf')


class TestNeedsDownload:
    def test_returns_true_when_file_absent(self, tmp_path):
        assert archiver._needs_download(tmp_path / 'nonexistent.pdf') is True

    def test_returns_false_when_file_exists_no_etag(self, tmp_path):
        dest = tmp_path / 'Minutes.pdf'
        dest.write_bytes(b'data')
        assert archiver._needs_download(dest) is False

    def test_returns_true_when_file_exists_with_etag(self, tmp_path):
        dest = tmp_path / 'Minutes.pdf'
        dest.write_bytes(b'data')
        (tmp_path / 'Minutes.pdf.etag').write_text('"abc"')
        assert archiver._needs_download(dest) is True


class TestDownloadFromPageData:
    def test_downloads_each_document(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        docs = [
            {'filename': '03-15-2024 Minutes.pdf', 'url': 'http://example.com/d/1'},
            {'filename': '03-15-2024 Agenda.pdf', 'url': 'http://example.com/d/2'},
        ]
        with patch.object(downloader, '_try_download', return_value=folder / 'f.pdf') as mock_dl:
            count = archiver._download_from_page_data(docs, folder)
        assert mock_dl.call_count == 2
        assert count == 2

    def test_skips_failed_downloads(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        docs = [{'filename': 'Minutes.pdf', 'url': 'http://example.com/d/1'}]
        with patch.object(downloader, '_try_download', return_value=None):
            count = archiver._download_from_page_data(docs, folder)
        assert count == 0

    def test_skips_docs_with_empty_filename(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        docs = [{'filename': '', 'url': 'http://example.com/d/1'}]
        with patch.object(downloader, '_try_download') as mock_dl:
            archiver._download_from_page_data(docs, folder)
        mock_dl.assert_not_called()

    def test_uses_sanitised_filename_as_destination(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        docs = [{'filename': '03-15-2024 Minutes.pdf', 'url': 'http://example.com/d/1'}]
        with patch.object(downloader, '_try_download', return_value=None) as mock_dl:
            archiver._download_from_page_data(docs, folder)
        dest_used = mock_dl.call_args[0][1]
        assert dest_used.name == '03-15-2024 Minutes.pdf'

    def test_returns_zero_for_empty_list(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        assert archiver._download_from_page_data([], folder) == 0

    def test_skips_existing_file_without_etag(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '03-15-2024 Minutes.pdf').write_bytes(b'cached')
        docs = [{'filename': '03-15-2024 Minutes.pdf', 'url': 'http://example.com/d/1'}]
        with patch.object(downloader, '_try_download') as mock_dl:
            count = archiver._download_from_page_data(docs, folder)
        mock_dl.assert_not_called()
        assert count == 0

    def test_validates_existing_file_with_etag(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        existing = folder / '03-15-2024 Minutes.pdf'
        existing.write_bytes(b'cached')
        (folder / '03-15-2024 Minutes.pdf.etag').write_text('"abc"')
        docs = [{'filename': '03-15-2024 Minutes.pdf', 'url': 'http://example.com/d/1'}]
        with patch.object(downloader, '_try_download', return_value=existing) as mock_dl:
            count = archiver._download_from_page_data(docs, folder)
        mock_dl.assert_called_once()
        assert count == 0

    def test_counts_only_newly_created_files(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        docs = [
            {'filename': 'New.pdf', 'url': 'http://example.com/d/1'},
            {'filename': 'Existing.pdf', 'url': 'http://example.com/d/2'},
        ]
        (folder / 'Existing.pdf').write_bytes(b'old')
        (folder / 'Existing.pdf.etag').write_text('"xyz"')
        with patch.object(downloader, '_try_download', return_value=folder / 'New.pdf'):
            count = archiver._download_from_page_data(docs, folder)
        assert count == 1


class TestParseDocDate:
    def test_parses_edt_date(self):
        result = archiver._parse_doc_date('Mar 25, 2014 8:22 AM EDT')
        assert result == datetime.date(2014, 3, 25)

    def test_parses_est_date(self):
        result = archiver._parse_doc_date('Jan 25, 2023 10:33 AM EST')
        assert result == datetime.date(2023, 1, 25)

    def test_returns_none_for_empty_string(self):
        assert archiver._parse_doc_date('') is None

    def test_returns_none_for_invalid_format(self):
        assert archiver._parse_doc_date('not a date') is None


_CLASSIFY_DOC_DATE = datetime.date(2024, 3, 15)


class TestClassifyDoc:
    def test_minutes_url_match(self):
        doc = {'url': 'http://example.com/minutes', 'created': ''}
        result = archiver._classify_doc(doc, _CLASSIFY_DOC_DATE, 'http://example.com/minutes', '')
        assert result == 'minutes'

    def test_agenda_url_match(self):
        doc = {'url': 'http://example.com/agenda', 'created': ''}
        result = archiver._classify_doc(doc, _CLASSIFY_DOC_DATE, '', 'http://example.com/agenda')
        assert result == 'agenda'

    def test_minutes_url_takes_priority_over_agenda_url(self):
        doc = {'url': 'http://example.com/doc', 'created': ''}
        result = archiver._classify_doc(
            doc, _CLASSIFY_DOC_DATE,
            'http://example.com/doc', 'http://example.com/doc',
        )
        assert result == 'minutes'

    def test_uploaded_after_meeting_date_classified_as_minutes(self):
        doc = {'url': 'http://example.com/doc', 'created': 'Apr 01, 2024 9:00 AM EST'}
        result = archiver._classify_doc(doc, _CLASSIFY_DOC_DATE, '', '')
        assert result == 'minutes'

    def test_uploaded_before_meeting_date_classified_as_agenda(self):
        doc = {'url': 'http://example.com/doc', 'created': 'Mar 10, 2024 9:00 AM EST'}
        result = archiver._classify_doc(doc, _CLASSIFY_DOC_DATE, '', '')
        assert result == 'agenda'

    def test_uploaded_on_meeting_date_classified_as_agenda(self):
        doc = {'url': 'http://example.com/doc', 'created': 'Mar 15, 2024 9:00 AM EST'}
        result = archiver._classify_doc(doc, _CLASSIFY_DOC_DATE, '', '')
        assert result == 'agenda'

    def test_unknown_when_created_missing(self):
        doc = {'url': 'http://example.com/doc'}
        result = archiver._classify_doc(doc, _CLASSIFY_DOC_DATE, '', '')
        assert result == 'unknown'

    def test_unknown_when_created_unparseable(self):
        doc = {'url': 'http://example.com/doc', 'created': 'bad date'}
        result = archiver._classify_doc(doc, _CLASSIFY_DOC_DATE, '', '')
        assert result == 'unknown'


class TestEnrichDocuments:
    def test_adds_type_to_each_doc(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        docs = [
            {'filename': 'Minutes.pdf', 'url': 'http://x.com/1', 'created': 'Apr 01, 2024 9:00 AM EDT'},
            {'filename': 'Agenda.pdf', 'url': 'http://x.com/2', 'created': 'Mar 10, 2024 9:00 AM EDT'},
        ]
        meeting = {'date': '2024-03-15'}
        result = archiver._enrich_documents(docs, meeting, folder)
        assert result[0]['type'] == 'minutes'
        assert result[1]['type'] == 'agenda'

    def test_adds_local_filename(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        docs = [{'filename': 'some:file.pdf', 'url': 'http://x.com/1', 'created': ''}]
        meeting = {'date': '2024-03-15'}
        result = archiver._enrich_documents(docs, meeting, folder)
        assert result[0]['local_filename'] == 'some_file.pdf'

    def test_downloaded_true_when_file_exists(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / 'Minutes.pdf').write_bytes(b'data')
        docs = [{'filename': 'Minutes.pdf', 'url': 'http://x.com/1', 'created': ''}]
        meeting = {'date': '2024-03-15'}
        result = archiver._enrich_documents(docs, meeting, folder)
        assert result[0]['downloaded'] is True

    def test_downloaded_false_when_file_absent(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        docs = [{'filename': 'Minutes.pdf', 'url': 'http://x.com/1', 'created': ''}]
        meeting = {'date': '2024-03-15'}
        result = archiver._enrich_documents(docs, meeting, folder)
        assert result[0]['downloaded'] is False

    def test_unknown_type_when_meeting_date_missing(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        docs = [{'filename': 'File.pdf', 'url': 'http://x.com/1', 'created': 'Apr 01, 2024 9:00 AM EDT'}]
        meeting = {'date': 'not-a-date'}
        result = archiver._enrich_documents(docs, meeting, folder)
        assert result[0]['type'] == 'unknown'

    def test_minutes_url_used_for_classification(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        docs = [{'filename': 'File.pdf', 'url': 'http://x.com/m', 'created': 'Mar 10, 2024 9:00 AM EDT'}]
        meeting = {'date': '2024-03-15', 'minutes_url': 'http://x.com/m'}
        result = archiver._enrich_documents(docs, meeting, folder)
        assert result[0]['type'] == 'minutes'

    def test_returns_empty_for_empty_input(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        assert archiver._enrich_documents([], {'date': '2024-03-15'}, folder) == []

    def test_does_not_mutate_original_docs(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        original = {'filename': 'File.pdf', 'url': 'http://x.com/1', 'created': ''}
        docs = [original]
        archiver._enrich_documents(docs, {'date': '2024-03-15'}, folder)
        assert 'type' not in original


class TestCleanupFolder:
    def test_removes_download_pdf(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_download.pdf').write_bytes(b'old')
        archiver._cleanup_folder(folder)
        assert not (folder / '2024-03-15_1830_download.pdf').exists()

    def test_removes_download_docx(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_download.docx').write_bytes(b'old')
        archiver._cleanup_folder(folder)
        assert not (folder / '2024-03-15_1830_download.docx').exists()

    def test_removes_download_text_txt(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_download_text.txt').write_text('cached text')
        archiver._cleanup_folder(folder)
        assert not (folder / '2024-03-15_1830_download_text.txt').exists()

    def test_preserves_minutes_pdf_when_no_page_docs(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        minutes = folder / '2024-03-15_1830_minutes.pdf'
        minutes.write_bytes(b'keep')
        archiver._cleanup_folder(folder)
        assert minutes.exists()

    def test_removes_minutes_pdf_when_page_docs_present(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        minutes = folder / '2024-03-15_1830_minutes.pdf'
        minutes.write_bytes(b'old')
        docs = [{'filename': '03-15-2024 Minutes.pdf', 'url': 'http://x.com/d/1'}]
        archiver._cleanup_folder(folder, docs)
        assert not minutes.exists()

    def test_preserves_minutes_docx_when_no_page_docs(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        minutes = folder / '2024-03-15_1830_minutes.docx'
        minutes.write_bytes(b'keep')
        archiver._cleanup_folder(folder)
        assert minutes.exists()

    def test_removes_minutes_docx_when_page_docs_present(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        minutes = folder / '2024-03-15_1830_minutes.docx'
        minutes.write_bytes(b'old')
        docs = [{'filename': 'Minutes.docx', 'url': 'http://x.com/d/1'}]
        archiver._cleanup_folder(folder, docs)
        assert not minutes.exists()

    def test_preserves_agenda_pdf_even_when_page_docs_present(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        agenda = folder / '2024-03-15_1830_agenda.pdf'
        agenda.write_bytes(b'keep')
        docs = [{'filename': 'Agenda.pdf', 'url': 'http://x.com/d/1'}]
        archiver._cleanup_folder(folder, docs)
        assert agenda.exists()

    def test_preserves_transcript(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        t = folder / '2024-03-15_1830_transcript.txt'
        t.write_text('keep')
        archiver._cleanup_folder(folder)
        assert t.exists()

    def test_returns_count_of_removed_files(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_download.pdf').write_bytes(b'old')
        (folder / '2024-03-15_1830_download_text.txt').write_text('old')
        (folder / '2024-03-15_1830_minutes.pdf').write_bytes(b'old')
        docs = [{'filename': '03-15-2024 Minutes.pdf', 'url': 'http://x.com/d/1'}]
        count = archiver._cleanup_folder(folder, docs)
        assert count == 3


class TestEnsureAgenda:
    def test_returns_false_when_agenda_exists(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_agenda.txt').write_text('cached')
        assert archiver._ensure_agenda(MEETING, folder) is False

    def test_returns_false_when_no_meeting_url(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meeting = {**MEETING, 'meeting_url': None}
        assert archiver._ensure_agenda(meeting, folder) is False

    def test_saves_agenda_text_and_returns_true(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch.object(mytowngovernment, 'fetch_agenda_text', return_value='Agenda text'):
            result = archiver._ensure_agenda(MEETING, folder)
        assert result is True
        assert (folder / '2024-03-15_1830_agenda.txt').read_text() == 'Agenda text'

    def test_returns_false_when_page_has_no_agenda(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch.object(mytowngovernment, 'fetch_agenda_text', return_value=''):
            assert archiver._ensure_agenda(MEETING, folder) is False


class TestEnsureTranscript:
    def test_returns_false_when_transcript_exists(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_transcript.txt').write_text('cached')
        assert archiver._ensure_transcript(MEETING, folder) is False

    def test_uses_youtube_captions_first(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / 'recording.ogg').write_bytes(b'audio')
        with patch.object(transcript, 'get_captions', return_value=True) as mock_gc, \
             patch.object(transcript, 'transcribe_audio') as mock_ta:
            result = archiver._ensure_transcript(MEETING, folder)
        mock_gc.assert_called_once()
        mock_ta.assert_not_called()
        assert result is True

    def test_falls_back_to_audio_when_captions_fail(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / 'recording.ogg').write_bytes(b'audio')
        with patch.object(transcript, 'get_captions', return_value=False), \
             patch.object(transcript, 'transcribe_audio', return_value='text') as mock_ta:
            result = archiver._ensure_transcript(MEETING, folder)
        mock_ta.assert_called_once()
        assert result is True

    def test_falls_back_to_recording_when_captions_fail_and_no_audio(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        rec = folder / '2024-03-15_1830_recording.mp4'
        rec.write_bytes(b'video')
        with patch.object(transcript, 'get_captions', return_value=False), \
             patch.object(transcript, 'find_recording_file', return_value=rec), \
             patch.object(transcript, 'transcribe_audio', return_value='text') as mock_ta:
            result = archiver._ensure_transcript(MEETING, folder)
        mock_ta.assert_called_once_with(rec, folder / '2024-03-15_1830_transcript.txt')
        assert result is True

    def test_uses_youtube_captions_when_no_audio(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch.object(transcript, 'get_captions', return_value=True) as mock_gc:
            result = archiver._ensure_transcript(MEETING, folder)
        mock_gc.assert_called_once()
        assert result is True

    def test_returns_false_when_all_sources_fail(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch.object(transcript, 'get_captions', return_value=False):
            assert archiver._ensure_transcript(MEETING, folder) is False

    def test_returns_false_when_no_source(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meeting = {**MEETING, 'youtube_id': None}
        assert archiver._ensure_transcript(meeting, folder) is False


class TestEnsureRecording:
    def test_returns_false_when_recording_exists(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_recording.mp4').write_bytes(b'fake')
        assert archiver._ensure_recording(MEETING, folder) is False

    def test_returns_false_when_no_youtube_id(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meeting = {**MEETING, 'youtube_id': None}
        assert archiver._ensure_recording(meeting, folder) is False

    def test_downloads_video_and_returns_true(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch.object(transcript, 'download_recording') as mock_dl:
            result = archiver._ensure_recording(MEETING, folder)
        mock_dl.assert_called_once()
        assert result is True

    def test_passes_audio_only_flag(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch.object(transcript, 'download_recording') as mock_dl:
            archiver._ensure_recording(MEETING, folder, audio_only=True)
        _, kwargs = mock_dl.call_args
        assert kwargs.get('audio_only') is True

    def test_returns_false_on_download_failure(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch.object(transcript, 'download_recording',
                          side_effect=Exception('yt-dlp error')):
            result = archiver._ensure_recording(MEETING, folder)
        assert result is False

    def test_dest_uses_mp4_for_video(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch.object(transcript, 'download_recording') as mock_dl:
            archiver._ensure_recording(MEETING, folder, audio_only=False)
        dest = mock_dl.call_args[0][1]
        assert dest.suffix == '.mp4'

    def test_dest_uses_m4a_for_audio_only(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch.object(transcript, 'download_recording') as mock_dl:
            archiver._ensure_recording(MEETING, folder, audio_only=True)
        dest = mock_dl.call_args[0][1]
        assert dest.suffix == '.m4a'


class TestSaveMeetingPageData:
    def test_writes_json_file_and_returns_data(self, tmp_path):
        import json as _json
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        page_data = {'scheduled_by': 'Alice', 'documents': [{'filename': 'a.pdf'}], 'revisions': []}
        with patch.object(mytowngovernment, 'fetch_meeting_page_data', return_value=page_data):
            result = archiver._save_meeting_page_data(MEETING, folder)
        out = folder / '2024-03-15_1830_page_data.json'
        assert out.exists()
        assert _json.loads(out.read_text())['scheduled_by'] == 'Alice'
        assert result == page_data

    def test_returns_empty_when_no_meeting_url(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meeting = {**MEETING, 'meeting_url': None}
        with patch.object(mytowngovernment, 'fetch_meeting_page_data') as mock_fetch:
            result = archiver._save_meeting_page_data(meeting, folder)
        mock_fetch.assert_not_called()
        assert result == {}

    def test_returns_empty_when_fetch_fails(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch.object(mytowngovernment, 'fetch_meeting_page_data', return_value={}):
            result = archiver._save_meeting_page_data(MEETING, folder)
        assert result == {}
        assert not (folder / '2024-03-15_1830_page_data.json').exists()


class TestArchiveMeeting:
    def test_saves_page_docs_and_transcript(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        docs = [{'filename': 'Minutes.pdf', 'url': 'http://x.com/d/1'}]
        with patch.object(archiver, '_download_from_page_data', return_value=1), \
             patch.object(archiver, '_save_meeting_page_data', return_value={'documents': docs}), \
             patch.object(archiver, '_ensure_agenda', return_value=True), \
             patch.object(archiver, '_ensure_transcript', return_value=True):
            summary = archiver.archive_meeting(MEETING, folder)
        assert summary['docs_saved'] == 1
        assert summary['agenda_saved'] == 1
        assert summary['transcript_saved'] == 1

    def test_saves_meeting_metadata_json(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch.object(archiver, '_download_from_page_data', return_value=0), \
             patch.object(archiver, '_save_meeting_page_data', return_value={'documents': []}), \
             patch.object(archiver, '_ensure_agenda', return_value=False), \
             patch.object(archiver, '_ensure_transcript', return_value=False):
            archiver.archive_meeting(MEETING, folder)
        assert data_store.load_meeting_metadata(folder) == {**MEETING, 'posted_meeting_files': []}

    def test_counts_docs_from_page_data(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        docs = [
            {'filename': 'Minutes.pdf', 'url': 'http://x.com/d/1'},
            {'filename': 'Agenda.pdf', 'url': 'http://x.com/d/2'},
        ]
        with patch.object(archiver, '_download_from_page_data', return_value=2), \
             patch.object(archiver, '_save_meeting_page_data', return_value={'documents': docs}), \
             patch.object(archiver, '_ensure_agenda', return_value=False), \
             patch.object(archiver, '_ensure_transcript', return_value=False):
            summary = archiver.archive_meeting(MEETING, folder)
        assert summary['docs_saved'] == 2

    def test_counts_only_saved_docs(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        with patch.object(archiver, '_download_from_page_data', return_value=0), \
             patch.object(archiver, '_save_meeting_page_data', return_value={'documents': []}), \
             patch.object(archiver, '_ensure_agenda', return_value=False), \
             patch.object(archiver, '_ensure_transcript', return_value=False):
            summary = archiver.archive_meeting(MEETING, folder)
        assert summary['docs_saved'] == 0
        assert summary['agenda_saved'] == 0
        assert summary['transcript_saved'] == 0

    def test_cancelled_meeting_skips_downloads(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meeting = {**MEETING, 'status': 'cancelled'}
        with patch.object(archiver, '_save_meeting_page_data', return_value={'documents': []}), \
             patch.object(archiver, '_download_from_page_data') as mock_dl:
            summary = archiver.archive_meeting(meeting, folder)
        mock_dl.assert_not_called()
        assert summary['docs_saved'] == 0
        assert summary['transcript_saved'] == 0

    def test_cleanup_runs_for_cancelled_meeting(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        old = folder / '2024-03-15_1830_download.pdf'
        old.write_bytes(b'stale')
        meeting = {**MEETING, 'status': 'cancelled'}
        with patch.object(archiver, '_save_meeting_page_data', return_value={'documents': []}):
            archiver.archive_meeting(meeting, folder)
        assert not old.exists()


class TestLogStart:
    def test_prints_date_and_position(self, capsys):
        archiver._log_start(3, 677, MEETING)
        out = capsys.readouterr().out
        assert '2024-03-15' in out
        assert '3' in out
        assert '677' in out

    def test_right_aligns_number(self, capsys):
        archiver._log_start(1, 100, MEETING)
        out = capsys.readouterr().out
        assert '[  1/100]' in out

    def test_shows_status_when_cancelled(self, capsys):
        meeting = {**MEETING, 'status': 'cancelled'}
        archiver._log_start(1, 10, meeting)
        assert '[cancelled]' in capsys.readouterr().out

    def test_no_status_suffix_when_held(self, capsys):
        archiver._log_start(1, 10, MEETING)
        assert '[held]' not in capsys.readouterr().out

    def test_shows_status_when_upcoming(self, capsys):
        meeting = {**MEETING, 'status': 'upcoming'}
        archiver._log_start(1, 10, meeting)
        assert '[upcoming]' in capsys.readouterr().out

    def test_shows_cancelled_when_location_is_cancelled(self, capsys):
        meeting = {**MEETING, 'status': 'held', 'location': 'Cancelled'}
        archiver._log_start(1, 10, meeting)
        assert '[cancelled]' in capsys.readouterr().out


class TestStatusMark:
    def test_plus_when_saved(self):
        assert archiver._status_mark(1, True) == '+'
        assert archiver._status_mark(1, False) == '+'

    def test_equals_when_exists_not_saved(self):
        assert archiver._status_mark(0, True) == '='

    def test_minus_when_absent(self):
        assert archiver._status_mark(0, False) == '-'


class TestIsCancelled:
    def test_true_when_status_is_cancelled(self):
        assert archiver._is_cancelled({'status': 'cancelled'}) is True

    def test_true_when_location_is_cancelled(self):
        assert archiver._is_cancelled({'status': 'held', 'location': 'Cancelled'}) is True

    def test_false_when_held_normal_location(self):
        assert archiver._is_cancelled({'status': 'held', 'location': 'Town Hall'}) is False

    def test_false_when_upcoming(self):
        assert archiver._is_cancelled({'status': 'upcoming'}) is False


class TestLogProgress:
    def test_always_prints(self, capsys):
        archiver._log_progress(self._summary())
        assert capsys.readouterr().out != ''

    def test_unknown_official_docs_shows_question_mark(self, capsys):
        archiver._log_progress(self._summary(official_docs=-1))
        assert 'docs:?' in capsys.readouterr().out

    def test_zero_official_docs_shows_zero(self, capsys):
        archiver._log_progress(self._summary(official_docs=0))
        assert 'docs:0' in capsys.readouterr().out

    def test_official_docs_shows_count(self, capsys):
        archiver._log_progress(self._summary(official_docs=2))
        assert 'docs:2' in capsys.readouterr().out

    def test_new_downloads_shown_in_parentheses(self, capsys):
        archiver._log_progress(self._summary(official_docs=2, docs_saved=1))
        out = capsys.readouterr().out
        assert 'docs:2(+1)' in out

    def test_plus_when_newly_saved(self, capsys):
        archiver._log_progress(self._summary(agenda_saved=1, agenda_exists=True))
        assert 'agenda:+' in capsys.readouterr().out

    def test_equals_when_cached(self, capsys):
        archiver._log_progress(self._summary(agenda_exists=True))
        assert 'agenda:=' in capsys.readouterr().out

    def test_minus_when_absent(self, capsys):
        archiver._log_progress(self._summary())
        assert 'agenda:-' in capsys.readouterr().out

    def test_output_contains_indented_fields(self, capsys):
        archiver._log_progress(self._summary())
        assert '    docs:' in capsys.readouterr().out

    def test_cancelled_shows_dim_line(self, capsys):
        archiver._log_progress(self._summary(), cancelled=True)
        out = capsys.readouterr().out
        assert 'docs:0' in out
        assert 'agenda:-' in out
        assert 'trans:-' in out

    def _summary(self, **overrides):
        base = {
            'docs_saved': 0, 'official_docs': -1,
            'agenda_saved': 0, 'agenda_exists': False,
            'transcript_saved': 0, 'transcript_exists': False,
            'recording_saved': 0, 'recording_exists': False,
        }
        base.update(overrides)
        return base


class TestArchiveAll:
    def test_skips_meetings_without_folder(self):
        meetings = [{**MEETING, 'folder': None}]
        with patch.object(archiver, 'archive_meeting') as mock_am, \
             patch.object(archiver, '_log_start'):
            archiver.archive_all(meetings)
        mock_am.assert_not_called()

    def test_aggregates_counts(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meetings = [{**MEETING, 'folder': str(folder)}]
        with patch.object(archiver, 'archive_meeting',
                          return_value=self._full_summary(docs_saved=2, agenda_saved=1, transcript_saved=1)), \
             patch.object(archiver, '_log_start'), \
             patch.object(archiver, '_log_progress'):
            totals = archiver.archive_all(meetings)
        assert totals['docs_saved'] == 2
        assert totals['agendas_saved'] == 1
        assert totals['transcripts_saved'] == 1

    def test_sums_across_multiple_meetings(self, tmp_path):
        folder_a = tmp_path / 'a'
        folder_b = tmp_path / 'b'
        folder_a.mkdir()
        folder_b.mkdir()
        meetings = [
            {**MEETING, 'folder': str(folder_a)},
            {**MEETING, 'date': '2024-04-10', 'folder': str(folder_b)},
        ]
        with patch.object(archiver, 'archive_meeting',
                          return_value=self._full_summary(docs_saved=1, agenda_saved=1)), \
             patch.object(archiver, '_log_start'), \
             patch.object(archiver, '_log_progress'):
            totals = archiver.archive_all(meetings)
        assert totals['docs_saved'] == 2
        assert totals['agendas_saved'] == 2
        assert totals['transcripts_saved'] == 0

    def _full_summary(self, **overrides):
        base = {
            'docs_saved': 0, 'official_docs': 0,
            'agenda_saved': 0, 'agenda_exists': False,
            'transcript_saved': 0, 'transcript_exists': False,
            'recording_saved': 0, 'recording_exists': False,
        }
        base.update(overrides)
        return base


class TestCol:
    def test_returns_plain_text_when_not_tty(self, capsys):
        result = archiver._col('hello', 'red')
        assert result == 'hello'

    def test_applies_color_when_tty(self, monkeypatch):
        monkeypatch.delenv('NO_COLOR', raising=False)
        import io as _io
        tty_stdout = _io.StringIO()
        tty_stdout.isatty = lambda: True
        monkeypatch.setattr(archiver.sys, 'stdout', tty_stdout)
        result = archiver._col('hello', 'red')
        assert 'hello' in result
        assert result != 'hello'
