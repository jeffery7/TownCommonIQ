import json

import pytest

from towncommoniq import document_index, data_store


MEETING = {
    'date': '2024-03-15',
    'time': '6:30 PM',
    'youtube_id': 'abc123',
    'folder': None,
}


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(data_store, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(document_index, '_INDEX_JSON', tmp_path / 'index.json')
    (tmp_path / 'meetings').mkdir()


def _write_meeting_json(folder, posted_files):
    """Helper: write a _meeting.json with the given posted_meeting_files list."""
    meta = {'date': '2024-03-15', 'posted_meeting_files': posted_files}
    (folder / f'{folder.name}_meeting.json').write_text(json.dumps(meta))


class TestTypedDocPresent:
    def test_returns_false_when_no_meeting_json(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        assert document_index._typed_doc_present(folder, 'minutes') is False

    def test_returns_false_when_posted_files_empty(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        _write_meeting_json(folder, [])
        assert document_index._typed_doc_present(folder, 'minutes') is False

    def test_returns_true_when_minutes_doc_downloaded(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        _write_meeting_json(folder, [{'type': 'minutes', 'downloaded': True}])
        assert document_index._typed_doc_present(folder, 'minutes') is True

    def test_returns_false_when_minutes_not_downloaded(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        _write_meeting_json(folder, [{'type': 'minutes', 'downloaded': False}])
        assert document_index._typed_doc_present(folder, 'minutes') is False

    def test_returns_false_when_type_mismatch(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        _write_meeting_json(folder, [{'type': 'agenda', 'downloaded': True}])
        assert document_index._typed_doc_present(folder, 'minutes') is False

    def test_returns_true_for_agenda_type(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        _write_meeting_json(folder, [{'type': 'agenda', 'downloaded': True}])
        assert document_index._typed_doc_present(folder, 'agenda') is True


class TestScanFolder:
    def test_all_false_for_missing_folder(self, tmp_path):
        result = document_index.scan_folder(tmp_path / 'nonexistent')
        assert all(not present for present in result.values())

    def test_detects_agenda_txt(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_agenda.txt').write_text('Agenda items')
        result = document_index.scan_folder(folder)
        assert result['agenda'] is True
        assert result['minutes'] is False

    def test_detects_agenda_pdf(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_agenda.pdf').write_bytes(b'%PDF')
        result = document_index.scan_folder(folder)
        assert result['agenda'] is True

    def test_detects_original_named_minutes(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '03-15-2024 Minutes.pdf').write_bytes(b'%PDF')
        result = document_index.scan_folder(folder)
        assert result['minutes'] is True

    def test_detects_canonical_minutes_pdf(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_minutes.pdf').write_bytes(b'%PDF')
        result = document_index.scan_folder(folder)
        assert result['minutes'] is True

    def test_draft_does_not_count_as_minutes(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_minutes_draft_generated.docx').write_bytes(b'PK')
        result = document_index.scan_folder(folder)
        assert result['minutes'] is False
        assert result['draft'] is True

    def test_detects_transcript(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_transcript.txt').write_text('text')
        result = document_index.scan_folder(folder)
        assert result['transcript'] is True

    def test_detects_draft(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_minutes_draft_generated.docx').write_bytes(b'PK')
        result = document_index.scan_folder(folder)
        assert result['draft'] is True

    def test_returns_all_false_for_empty_folder(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        result = document_index.scan_folder(folder)
        assert not any(result.values())

    def test_detects_minutes_from_metadata_when_filename_has_no_keyword(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '01272014.doc.docx.doc').write_bytes(b'data')
        _write_meeting_json(folder, [{'type': 'minutes', 'downloaded': True}])
        result = document_index.scan_folder(folder)
        assert result['minutes'] is True

    def test_detects_agenda_from_metadata_when_filename_has_no_keyword(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '01272014.doc.docx.doc').write_bytes(b'data')
        _write_meeting_json(folder, [{'type': 'agenda', 'downloaded': True}])
        result = document_index.scan_folder(folder)
        assert result['agenda'] is True

    def test_metadata_fallback_not_used_when_filename_already_matches(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '03-15-2024 Minutes.pdf').write_bytes(b'%PDF')
        result = document_index.scan_folder(folder)
        assert result['minutes'] is True


class TestBuildIndex:
    def test_skips_meetings_without_folder(self):
        meetings = [{**MEETING, 'folder': None}]
        assert document_index.build_index(meetings) == {}

    def test_skips_meetings_without_date(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meetings = [{'folder': str(folder)}]
        assert document_index.build_index(meetings) == {}

    def test_indexes_meeting_by_date(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        meetings = [{**MEETING, 'folder': str(folder)}]
        index = document_index.build_index(meetings)
        assert '2024-03-15' in index

    def test_index_reflects_present_files(self, tmp_path):
        folder = tmp_path / '2024-03-15_1830'
        folder.mkdir()
        (folder / '2024-03-15_1830_transcript.txt').write_text('text')
        meetings = [{**MEETING, 'folder': str(folder)}]
        index = document_index.build_index(meetings)
        assert index['2024-03-15']['transcript'] is True
        assert index['2024-03-15']['agenda'] is False


class TestSaveLoadIndex:
    def test_round_trip(self, tmp_path):
        index = {'2024-03-15': {'agenda': True, 'minutes': False}}
        document_index.save_index(index)
        assert document_index.load_index() == index

    def test_load_returns_empty_when_no_file(self):
        assert document_index.load_index() == {}

    def test_save_writes_valid_json(self, tmp_path):
        index = {'2024-03-15': {'agenda': True}}
        document_index.save_index(index)
        path = document_index._INDEX_JSON
        parsed = json.loads(path.read_text())
        assert parsed == index


class TestMissing:
    def test_returns_dates_missing_doc_type(self):
        index = {
            '2024-03-15': {'agenda': True, 'transcript': False},
            '2024-04-10': {'agenda': False, 'transcript': True},
        }
        result = document_index.missing(index, 'transcript')
        assert result == ['2024-03-15']

    def test_returns_empty_when_all_present(self):
        index = {'2024-03-15': {'agenda': True, 'transcript': True}}
        assert document_index.missing(index, 'transcript') == []

    def test_result_is_sorted(self):
        index = {
            '2024-04-10': {'agenda': False},
            '2024-03-15': {'agenda': False},
        }
        assert document_index.missing(index, 'agenda') == ['2024-03-15', '2024-04-10']


class TestFormatStatus:
    def test_y_for_present_n_for_absent(self):
        docs = {'agenda': True, 'minutes': False}
        status = document_index.format_status(docs)
        assert 'agenda:Y' in status
        assert 'minutes:N' in status

    def test_empty_dict_returns_empty_string(self):
        assert document_index.format_status({}) == ''
