from towncommoniq import reporter


_MTG_WITH_MINUTES = {
    'date': '2026-03-30',
    'status': 'held',
    'minutes_url': 'http://mytowngovernment.org/minutes/abc',
}
_MTG_WITHOUT_MINUTES = {
    'date': '2025-09-15',
    'status': 'held',
    'minutes_url': None,
}
_TOWN_RECORD = {
    'date': '2026-03-30',
    'title': 'Selectboard Meeting Minutes - March 30, 2026',
    'file_url': 'http://town.example.com/file.pdf',
    'downloaded': False,
}
_TOWN_ONLY_RECORD = {
    'date': '2026-04-14',
    'title': 'Selectboard Meeting Minutes - April 14, 2026',
    'file_url': 'http://town.example.com/apr14.pdf',
    'downloaded': False,
}


class TestHasOfficialMinutes:
    def test_true_when_minutes_url_set(self):
        assert reporter._has_official_minutes(_MTG_WITH_MINUTES) is True

    def test_false_when_minutes_url_none(self):
        assert reporter._has_official_minutes(_MTG_WITHOUT_MINUTES) is False

    def test_false_for_empty_dict(self):
        assert reporter._has_official_minutes({}) is False


class TestLabelByDate:
    def test_indexes_meetings_by_date(self):
        meetings = [_MTG_WITH_MINUTES, _MTG_WITHOUT_MINUTES]
        result = reporter._label_by_date(meetings)
        assert '2026-03-30' in result
        assert '2025-09-15' in result

    def test_skips_meetings_without_date(self):
        result = reporter._label_by_date([{'status': 'held'}])
        assert result == {}


class TestCompareReport:
    def test_report_has_title(self):
        report = reporter.compare_report([], [])
        assert 'Hardwick Select Board' in report

    def test_report_has_generated_date(self):
        import re
        report = reporter.compare_report([], [])
        assert re.search(r'Generated: \d{4}-\d{2}-\d{2}', report)

    def test_both_section_shows_shared_date(self):
        report = reporter.compare_report([_MTG_WITH_MINUTES], [_TOWN_RECORD])
        assert '2026-03-30' in report
        assert 'BOTH' in report.upper()

    def test_only_mtg_section_shows_mtg_only_date(self):
        report = reporter.compare_report([_MTG_WITH_MINUTES], [])
        assert '2026-03-30' in report
        assert 'MyTownGovernment' in report

    def test_only_town_section_shows_town_only_date(self):
        report = reporter.compare_report([], [_TOWN_ONLY_RECORD])
        assert '2026-04-14' in report
        assert 'hardwick-ma.gov' in report

    def test_summary_counts_correctly(self):
        meetings = [_MTG_WITH_MINUTES]
        town = [_TOWN_RECORD, _TOWN_ONLY_RECORD]
        report = reporter.compare_report(meetings, town)
        assert 'SUMMARY' in report

    def test_meetings_without_minutes_url_excluded_from_mtg_set(self):
        report = reporter.compare_report([_MTG_WITHOUT_MINUTES], [])
        assert '2025-09-15' not in report

    def test_empty_section_shows_none_marker(self):
        report = reporter.compare_report([], [])
        assert '(none)' in report
