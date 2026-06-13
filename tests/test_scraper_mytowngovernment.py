from unittest.mock import MagicMock, patch

import pytest

from towncommoniq.scraper import mytowngovernment


SAMPLE_HTML = """
<html><body>
<a name="Upcoming"></a>
<table>
  <tr><th>col</th><th>Date/Time</th><th>Location</th><th>Action</th></tr>
  <tr>
    <td></td>
    <td>May 01, 2024 6:30 PM</td>
    <td>Town Hall</td>
    <td><a href="/meeting?meeting=upcoming123">Details and Agenda...</a></td>
  </tr>
</table>

<a name="Past"></a>
<table>
  <tr><th>Date/Time</th><th>Location</th><th>Status</th><th></th><th>Action</th></tr>
  <tr>
    <td>March 15, 2024 6:30 PM EDT</td>
    <td><a href="/location?location=loc1">Town Hall</a></td>
    <td>Not Available</td>
    <td></td>
    <td><a href="/meeting?meeting=past456">Details and Agenda...</a></td>
  </tr>
  <tr>
    <td>April 10, 2024 6:30 PM EDT</td>
    <td><a href="/location?location=loc1">Town Hall</a></td>
    <td>Not Available</td>
    <td></td>
    <td><a href="/meeting?meeting=past789">Details and Agenda...</a></td>
  </tr>
</table>

<a name="Docs"></a>
<table>
  <tr><th>Documents</th><th></th></tr>
  <tr>
    <td>Select Board Agenda - March 15, 2024</td>
    <td><a href="/download/111">Download</a></td>
  </tr>
  <tr>
    <td>Meeting Minutes - March 15, 2024</td>
    <td><a href="/download/456">Download</a></td>
  </tr>
</table>
</body></html>
"""

MEETING_PAGE_HTML = """
<html><body>
<table>
  <tr><td>Agenda:</td><td>1. Call to Order\n2. Executive Session\n3. Adjournment</td></tr>
</table>
</body></html>
"""


@pytest.fixture()
def mock_response():
    resp = MagicMock()
    resp.text = SAMPLE_HTML
    resp.raise_for_status = MagicMock()
    return resp


BOARD_HTML = """
<html><body>
<table>
  <tr><td>Chair:</td><td>Alice Smith</td></tr>
  <tr><td>Clerk:</td><td>Bob Jones</td></tr>
  <tr><td>Members:</td><td>Alice Smith\nBob Jones\nCarol Lee</td></tr>
  <tr><td>Other:</td><td>ignored</td></tr>
</table>
</body></html>
"""


class TestAbsolute:
    def test_relative_url_gets_prefixed(self):
        result = mytowngovernment._absolute('/meeting?meeting=abc')
        assert result.startswith('http')
        assert '/meeting?meeting=abc' in result

    def test_absolute_url_unchanged(self):
        url = 'https://example.com/meeting?meeting=abc'
        assert mytowngovernment._absolute(url) == url


class TestParseUpcomingTable:
    def test_skips_rows_with_few_cells(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><th>h</th></tr><tr><td>only one</td></tr></table>'
        table = BeautifulSoup(html, 'html.parser').find('table')
        assert mytowngovernment._parse_upcoming_table(table) == []

    def test_skips_rows_with_unparseable_date(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><th>h</th></tr><tr><td>col</td><td>not a date</td></tr></table>'
        table = BeautifulSoup(html, 'html.parser').find('table')
        assert mytowngovernment._parse_upcoming_table(table) == []


class TestBlankMeetingDictMeetingUrl:
    def test_meeting_url_extracted_from_row(self):
        from bs4 import BeautifulSoup
        html = '<tr><td><a href="/meeting?meeting=123">detail</a></td></tr>'
        row = BeautifulSoup(html, 'html.parser').find('tr')
        result = mytowngovernment._blank_meeting_dict('2024-03-15', '6:30 PM', 'Town Hall', 'held', row)
        assert result['meeting_url'] == 'https://www.mytowngovernment.org/meeting?meeting=123'

    def test_meeting_url_is_none_when_no_meeting_link(self):
        from bs4 import BeautifulSoup
        row = BeautifulSoup('<tr><td><a href="/other">link</a></td></tr>', 'html.parser').find('tr')
        result = mytowngovernment._blank_meeting_dict('2024-03-15', '6:30 PM', 'Town Hall', 'held', row)
        assert result['meeting_url'] is None


class TestParsePastTable:
    def test_skips_rows_with_few_cells(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><th>h</th></tr><tr><td>only one</td></tr></table>'
        table = BeautifulSoup(html, 'html.parser').find('table')
        assert mytowngovernment._parse_past_table(table) == []

    def test_skips_rows_with_unparseable_date(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><th>h</th></tr><tr><td>not a date</td><td>loc</td></tr></table>'
        table = BeautifulSoup(html, 'html.parser').find('table')
        assert mytowngovernment._parse_past_table(table) == []

    def test_location_falls_back_to_text_when_no_link(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><th>h</th></tr><tr><td>March 15, 2024 6:30 PM</td><td>Town Hall</td></tr></table>'
        table = BeautifulSoup(html, 'html.parser').find('table')
        meetings = mytowngovernment._parse_past_table(table)
        assert meetings[0]['location'] == 'Town Hall'

    def test_cancelled_location_sets_cancelled_status(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><th>h</th></tr><tr><td>February 14, 2022 6:30 PM</td><td>Cancelled</td></tr></table>'
        table = BeautifulSoup(html, 'html.parser').find('table')
        meetings = mytowngovernment._parse_past_table(table)
        assert meetings[0]['status'] == 'cancelled'

    def test_normal_location_sets_held_status(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><th>h</th></tr><tr><td>March 15, 2024 6:30 PM</td><td>Town Hall</td></tr></table>'
        table = BeautifulSoup(html, 'html.parser').find('table')
        meetings = mytowngovernment._parse_past_table(table)
        assert meetings[0]['status'] == 'held'


class TestMeetingPageData:
    def test_scrape_label_value_finds_match(self):
        soup = self._make_soup('<table><tr><td>Posted At:</td><td>Jan 05, 2023</td></tr></table>')
        assert mytowngovernment._scrape_label_value(soup, 'Posted At:') == 'Jan 05, 2023'

    def test_scrape_label_value_returns_empty_when_not_found(self):
        soup = self._make_soup('<table><tr><td>Other:</td><td>value</td></tr></table>')
        assert mytowngovernment._scrape_label_value(soup, 'Posted At:') == ''

    def test_scrape_documents_extracts_filename_size_created(self):
        # Real page structure: viewer link (bold, has filename) + download link
        html = (
            '<b>Minutes and Associated Documents</b>'
            '<table><tr><th>Document</th><th>Size</th><th>Created</th></tr>'
            '<tr><td>'
            '<a href="/viewer?document=abc" style="font-weight:bold">1-9-2023.pdf</a>'
            ' (<a href="/download?document=abc">download</a>)'
            '</td>'
            '<td>90 Kb</td><td>Nov 01, 2023</td></tr></table>'
        )
        soup = self._make_soup(html)
        docs = mytowngovernment._scrape_documents(soup)
        assert len(docs) == 1
        assert docs[0]['filename'] == '1-9-2023.pdf'
        assert docs[0]['size'] == '90 Kb'
        assert docs[0]['created'] == 'Nov 01, 2023'
        assert 'download' in docs[0]['url']

    def test_scrape_documents_skips_rows_without_download_link(self):
        html = (
            '<b>Minutes and Associated Documents</b>'
            '<table><tr><th>Document</th><th>Size</th><th>Created</th></tr>'
            '<tr><td><a href="/view/1">View</a></td><td>90 Kb</td><td>Nov 01, 2023</td></tr></table>'
        )
        soup = self._make_soup(html)
        assert mytowngovernment._scrape_documents(soup) == []

    def test_scrape_documents_returns_empty_when_no_section(self):
        soup = self._make_soup('<p>No documents here</p>')
        assert mytowngovernment._scrape_documents(soup) == []

    def test_scrape_revisions_extracts_entries(self):
        html = (
            '<b>Meeting Revision History</b>'
            '<table><tr><th>Date</th><th>Changes</th><th></th></tr>'
            '<tr><td>Jan 08, 2023</td><td>Agenda</td>'
            '<td><a href="/change?change=abc">Details...</a></td></tr></table>'
        )
        soup = self._make_soup(html)
        revisions = mytowngovernment._scrape_revisions(soup)
        assert len(revisions) == 1
        assert revisions[0]['date'] == 'Jan 08, 2023'
        assert revisions[0]['changes'] == 'Agenda'
        assert 'abc' in revisions[0]['detail_url']

    def test_scrape_revisions_returns_empty_when_no_section(self):
        soup = self._make_soup('<p>No history</p>')
        assert mytowngovernment._scrape_revisions(soup) == []

    def test_fetch_meeting_page_data_returns_empty_on_failed_fetch(self):
        with patch.object(mytowngovernment, '_fetch_soup', return_value=None):
            assert mytowngovernment.fetch_meeting_page_data('http://x.com/m') == {}

    def test_fetch_meeting_page_data_returns_all_fields(self):
        from bs4 import BeautifulSoup
        html = (
            '<table><tr><td>Scheduled By:</td><td>Jane Smith</td></tr>'
            '<tr><td>Posted At:</td><td>Jan 05, 2023</td></tr>'
            '<tr><td>Last Modified:</td><td>Jan 09, 2023</td></tr></table>'
            '<b>Minutes and Associated Documents</b>'
            '<table><tr><th>D</th><th>S</th><th>C</th></tr></table>'
            '<b>Meeting Revision History</b>'
            '<table><tr><th>Date</th><th>Changes</th><th></th></tr></table>'
        )
        soup = BeautifulSoup(html, 'html.parser')
        with patch.object(mytowngovernment, '_fetch_soup', return_value=soup):
            data = mytowngovernment.fetch_meeting_page_data('http://x.com/m')
        assert data['scheduled_by'] == 'Jane Smith'
        assert data['posted_at'] == 'Jan 05, 2023'
        assert data['last_modified'] == 'Jan 09, 2023'
        assert isinstance(data['documents'], list)
        assert isinstance(data['revisions'], list)

    def _make_soup(self, html: str):
        from bs4 import BeautifulSoup
        return BeautifulSoup(html, 'html.parser')


class TestParseDocsTable:
    def test_skips_rows_without_date_match(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><th>h</th></tr><tr><td>No date here</td><td><a href="/download/1">Download</a></td></tr></table>'
        table = BeautifulSoup(html, 'html.parser').find('table')
        assert mytowngovernment._parse_docs_table(table) == {}

    def test_unlabeled_link_used_as_minutes(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><th>h</th></tr><tr><td>Document March 15, 2024</td><td><a href="/download/1">Download</a></td></tr></table>'
        table = BeautifulSoup(html, 'html.parser').find('table')
        docs = mytowngovernment._parse_docs_table(table)
        assert docs['2024-03-15']['minutes_url'] is not None

    def test_skips_links_without_download(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><th>h</th></tr><tr><td>Minutes March 15, 2024</td><td><a href="/view/1">View</a></td></tr></table>'
        table = BeautifulSoup(html, 'html.parser').find('table')
        docs = mytowngovernment._parse_docs_table(table)
        assert docs.get('2024-03-15', {}).get('minutes_url') is None

    def test_skips_rows_with_invalid_date(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><th>h</th></tr><tr><td>Minutes February 30, 2024</td><td><a href="/download/1">Download</a></td></tr></table>'
        table = BeautifulSoup(html, 'html.parser').find('table')
        docs = mytowngovernment._parse_docs_table(table)
        assert docs == {}


class TestFetchBoardMembers:
    def test_extracts_chair(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(BOARD_HTML, 'html.parser')
        info = mytowngovernment.fetch_board_members(soup)
        assert info['chair'] == 'Alice Smith'

    def test_extracts_clerk(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(BOARD_HTML, 'html.parser')
        info = mytowngovernment.fetch_board_members(soup)
        assert info['clerk'] == 'Bob Jones'

    def test_extracts_members(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(BOARD_HTML, 'html.parser')
        info = mytowngovernment.fetch_board_members(soup)
        assert 'Alice Smith' in info['members']
        assert 'Carol Lee' in info['members']

    def test_returns_empty_for_no_table(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
        info = mytowngovernment.fetch_board_members(soup)
        assert info == {'chair': None, 'clerk': None, 'members': []}

    def test_strips_role_titles_from_members(self):
        from bs4 import BeautifulSoup
        html = """<html><body><table>
          <tr><td>Chair:</td><td>Alice Smith</td></tr>
          <tr><td>Clerk:</td><td>Bob Jones</td></tr>
          <tr><td>Members:</td><td>Alice Smith\nChair\nBob Jones\nVice Chair\nCarol Lee\nClerk</td></tr>
        </table></body></html>"""
        soup = BeautifulSoup(html, 'html.parser')
        info = mytowngovernment.fetch_board_members(soup)
        assert 'Chair' not in info['members']
        assert 'Vice Chair' not in info['members']
        assert 'Clerk' not in info['members']
        assert info['members'] == ['Alice Smith', 'Bob Jones', 'Carol Lee']


class TestParseDate:
    def test_long_month_name(self):
        assert mytowngovernment._parse_date('March 15, 2024') == '2024-03-15'

    def test_abbreviated_month(self):
        assert mytowngovernment._parse_date('Mar 15, 2024') == '2024-03-15'

    def test_numeric_format(self):
        assert mytowngovernment._parse_date('03/15/2024') == '2024-03-15'

    def test_invalid_returns_none(self):
        assert mytowngovernment._parse_date('not a date') is None

    def test_empty_returns_none(self):
        assert mytowngovernment._parse_date('') is None


class TestFetchAgendaText:
    def test_extracts_agenda_from_meeting_page(self):
        mock_resp = MagicMock()
        mock_resp.text = MEETING_PAGE_HTML
        mock_resp.raise_for_status = MagicMock()
        with patch('requests.get', return_value=mock_resp):
            text = mytowngovernment.fetch_agenda_text('http://example.com/meeting?meeting=abc')
        assert 'Call to Order' in text
        assert 'Executive Session' in text

    def test_returns_empty_when_no_agenda_td(self):
        mock_resp = MagicMock()
        mock_resp.text = '<html><body><p>No agenda here</p></body></html>'
        mock_resp.raise_for_status = MagicMock()
        with patch('requests.get', return_value=mock_resp):
            text = mytowngovernment.fetch_agenda_text('http://example.com/meeting?meeting=abc')
        assert text == ''

    def test_returns_empty_on_request_error(self):
        with patch('requests.get', side_effect=Exception('timeout')):
            text = mytowngovernment.fetch_agenda_text('http://example.com/meeting?meeting=abc')
        assert text == ''

    def test_returns_empty_when_no_sibling_td(self):
        mock_resp = MagicMock()
        mock_resp.text = '<html><body><table><tr><td>Agenda:</td></tr></table></body></html>'
        mock_resp.raise_for_status = MagicMock()
        with patch('requests.get', return_value=mock_resp):
            text = mytowngovernment.fetch_agenda_text('http://example.com/meeting?meeting=abc')
        assert text == ''


class TestFetchMeetings:
    def test_returns_tuple(self, mock_response):
        with patch('requests.get', return_value=mock_response):
            result = mytowngovernment.fetch_meetings()
        assert isinstance(result, tuple) and len(result) == 2

    def test_returns_meetings(self, mock_response):
        with patch('requests.get', return_value=mock_response):
            meetings, _ = mytowngovernment.fetch_meetings()
        assert len(meetings) >= 1

    def test_parses_past_dates(self, mock_response):
        with patch('requests.get', return_value=mock_response):
            meetings, _ = mytowngovernment.fetch_meetings()
        dates = [m['date'] for m in meetings]
        assert '2024-03-15' in dates

    def test_captures_meeting_url(self, mock_response):
        with patch('requests.get', return_value=mock_response):
            meetings, _ = mytowngovernment.fetch_meetings()
        meeting = next(m for m in meetings if m['date'] == '2024-03-15')
        assert meeting['meeting_url'] is not None
        assert '/meeting?' in meeting['meeting_url']

    def test_past_meeting_has_held_status(self, mock_response):
        with patch('requests.get', return_value=mock_response):
            meetings, _ = mytowngovernment.fetch_meetings()
        meeting = next(m for m in meetings if m['date'] == '2024-03-15')
        assert meeting['status'] == 'held'

    def test_upcoming_meeting_has_upcoming_status(self, mock_response):
        with patch('requests.get', return_value=mock_response):
            meetings, _ = mytowngovernment.fetch_meetings()
        meeting = next(m for m in meetings if m['date'] == '2024-05-01')
        assert meeting['status'] == 'upcoming'

    def test_docs_table_supplements_minutes_url(self, mock_response):
        with patch('requests.get', return_value=mock_response):
            meetings, _ = mytowngovernment.fetch_meetings()
        meeting = next(m for m in meetings if m['date'] == '2024-03-15')
        assert meeting['minutes_url'] is not None

    def test_docs_table_supplements_agenda_url(self, mock_response):
        with patch('requests.get', return_value=mock_response):
            meetings, _ = mytowngovernment.fetch_meetings()
        meeting = next(m for m in meetings if m['date'] == '2024-03-15')
        assert meeting['agenda_url'] is not None

    def test_meeting_without_docs_has_none_urls(self, mock_response):
        with patch('requests.get', return_value=mock_response):
            meetings, _ = mytowngovernment.fetch_meetings()
        meeting = next(m for m in meetings if m['date'] == '2024-04-10')
        assert meeting['minutes_url'] is None
        assert meeting['agenda_url'] is None

    def test_docs_anchor_without_table_is_skipped(self):
        html = """
        <html><body>
        <a name="Past"></a>
        <table>
          <tr><th>Date/Time</th><th>Location</th></tr>
          <tr>
            <td>March 15, 2024 6:30 PM</td>
            <td>Town Hall</td>
          </tr>
        </table>
        <a name="Docs"></a>
        </body></html>
        """
        resp = MagicMock()
        resp.text = html
        resp.raise_for_status = MagicMock()
        with patch('requests.get', return_value=resp):
            meetings, _ = mytowngovernment.fetch_meetings()
        assert meetings[0]['minutes_url'] is None

    def test_docs_for_unknown_date_are_skipped(self):
        html = """
        <html><body>
        <a name="Past"></a>
        <table>
          <tr><th>Date/Time</th><th>Location</th></tr>
          <tr>
            <td>March 15, 2024 6:30 PM</td>
            <td>Town Hall</td>
          </tr>
        </table>
        <a name="Docs"></a>
        <table>
          <tr><th>Documents</th><th></th></tr>
          <tr>
            <td>Meeting Minutes - January 01, 2000</td>
            <td><a href="/download/999">Download</a></td>
          </tr>
        </table>
        </body></html>
        """
        resp = MagicMock()
        resp.text = html
        resp.raise_for_status = MagicMock()
        with patch('requests.get', return_value=resp):
            meetings, _ = mytowngovernment.fetch_meetings()
        assert meetings[0]['minutes_url'] is None


class TestScrapeLabelValue:
    def test_returns_matching_cell(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><td>Scheduled By:</td><td>Town Clerk</td></tr></table>'
        soup = BeautifulSoup(html, 'html.parser')
        result = mytowngovernment._scrape_label_value(soup, 'Scheduled By:')
        assert result == 'Town Clerk'

    def test_returns_empty_when_no_match(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><td>Other:</td><td>value</td></tr></table>'
        soup = BeautifulSoup(html, 'html.parser')
        result = mytowngovernment._scrape_label_value(soup, 'Scheduled By:')
        assert result == ''


class TestScrapeDocuments:
    def test_uses_viewer_link_for_filename(self):
        from bs4 import BeautifulSoup
        html = '''<table>
          <tr><th>File</th><th>Size</th><th>Created</th></tr>
          <tr>
            <td>
              <a href="/viewer?f=agenda.pdf">agenda.pdf</a>
              <a href="/download?f=agenda.pdf"> ( download ) </a>
            </td>
            <td>100 KB</td><td>2024-03-01</td>
          </tr>
        </table>'''
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        with patch.object(mytowngovernment, '_find_section_table', return_value=table):
            docs = mytowngovernment._scrape_documents(soup)
        assert len(docs) == 1
        assert docs[0]['filename'] == 'agenda.pdf'

    def test_falls_back_to_cell_text_when_no_viewer(self):
        from bs4 import BeautifulSoup
        html = '''<table>
          <tr><th>File</th><th>Size</th><th>Created</th></tr>
          <tr>
            <td>
              <a href="/download?f=report.pdf">report.pdf ( download )</a>
            </td>
            <td>50 KB</td><td>2024-03-01</td>
          </tr>
        </table>'''
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        with patch.object(mytowngovernment, '_find_section_table', return_value=table):
            docs = mytowngovernment._scrape_documents(soup)
        assert len(docs) == 1
        assert '( download )' not in docs[0]['filename']


class TestScrapeRevisions:
    def test_extracts_detail_url(self):
        from bs4 import BeautifulSoup
        html = '''<table>
          <tr><th>Date</th><th>Changes</th><th>Detail</th></tr>
          <tr>
            <td>2024-03-01</td><td>Agenda</td>
            <td><a href="/revision?id=1">View</a></td>
          </tr>
        </table>'''
        soup = BeautifulSoup(html, 'html.parser')
        table = soup.find('table')
        with patch.object(mytowngovernment, '_find_section_table', return_value=table):
            revs = mytowngovernment._scrape_revisions(soup)
        assert len(revs) == 1
        assert revs[0]['detail_url'] is not None


class TestScrapeEdgeCases:
    def test_scrape_label_value_skips_single_cell_rows(self):
        from bs4 import BeautifulSoup
        html = '<table><tr><td>just one cell</td></tr></table>'
        soup = BeautifulSoup(html, 'html.parser')
        assert mytowngovernment._scrape_label_value(soup, 'anything') == ''

    def test_scrape_documents_skips_rows_with_few_cells(self):
        from bs4 import BeautifulSoup
        html = '<b>Minutes and Associated Documents</b><table><tr><th>h</th></tr><tr><td>only one</td></tr></table>'
        soup = BeautifulSoup(html, 'html.parser')
        docs = mytowngovernment._scrape_documents(soup)
        assert docs == []

    def test_scrape_revisions_skips_rows_with_few_cells(self):
        from bs4 import BeautifulSoup
        html = '<b>Meeting Revision History</b><table><tr><th>h</th></tr><tr><td>only one</td></tr></table>'
        soup = BeautifulSoup(html, 'html.parser')
        revs = mytowngovernment._scrape_revisions(soup)
        assert revs == []
