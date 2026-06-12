from municipaliq import correlator


MEETING_A = {'date': '2024-03-15', 'status': 'held', 'youtube_id': None}
MEETING_B = {'date': '2024-04-10', 'status': 'held', 'youtube_id': None}

VIDEO_SAME_DAY = {'video_id': 'v1', 'date': '2024-03-15', 'title': 'Select Board 3/15'}
VIDEO_NEXT_DAY = {'video_id': 'v2', 'date': '2024-03-16', 'title': 'Select Board 3/16'}
VIDEO_FAR = {'video_id': 'v3', 'date': '2024-06-01', 'title': 'Other'}


class TestDatesWithin:
    def test_same_date_matches(self):
        assert correlator._dates_within('2024-03-15', '2024-03-15')

    def test_one_day_apart_matches(self):
        assert correlator._dates_within('2024-03-15', '2024-03-16')

    def test_two_days_apart_no_match(self):
        assert not correlator._dates_within('2024-03-15', '2024-03-17')

    def test_none_date_no_match(self):
        assert not correlator._dates_within(None, '2024-03-15')
        assert not correlator._dates_within('2024-03-15', None)

    def test_invalid_date_no_match(self):
        assert not correlator._dates_within('not-a-date', '2024-03-15')


class TestCorrelate:
    def test_matches_same_day(self):
        result = correlator.correlate([MEETING_A], [VIDEO_SAME_DAY])
        assert result[0]['youtube_id'] == 'v1'

    def test_matches_adjacent_day(self):
        result = correlator.correlate([MEETING_A], [VIDEO_NEXT_DAY])
        assert result[0]['youtube_id'] == 'v2'

    def test_no_match_when_far(self):
        result = correlator.correlate([MEETING_A], [VIDEO_FAR])
        assert result[0]['youtube_id'] is None

    def test_prefers_closer_date(self):
        videos = [VIDEO_NEXT_DAY, VIDEO_SAME_DAY]
        result = correlator.correlate([MEETING_A], videos)
        assert result[0]['youtube_id'] == 'v1'

    def test_each_video_matched_once(self):
        meetings = [MEETING_A, {'date': '2024-03-15', 'status': 'held', 'youtube_id': None}]
        result = correlator.correlate(meetings, [VIDEO_SAME_DAY])
        matched = [m for m in result if m.get('youtube_id')]
        assert len(matched) == 1

    def test_preserves_existing_youtube_id(self):
        meeting = {'date': '2024-03-15', 'status': 'held', 'youtube_id': 'existing'}
        result = correlator.correlate([meeting], [VIDEO_SAME_DAY])
        assert result[0]['youtube_id'] == 'existing'

    def test_empty_inputs(self):
        assert correlator.correlate([], []) == []
        assert correlator.correlate([MEETING_A], []) == [MEETING_A]
