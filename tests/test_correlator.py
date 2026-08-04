from towncommoniq import correlator


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

    def test_flags_other_board_match(self):
        other_board_video = {
            'video_id': 'v4', 'date': '2024-03-15',
            'title': 'Board of Health Meeting 3/15',
        }
        result = correlator.correlate([MEETING_A], [other_board_video])
        assert result[0]['youtube_id'] == 'v4'
        assert result[0]['video_board_mismatch'] is True

    def test_no_mismatch_flag_for_select_board_match(self):
        result = correlator.correlate([MEETING_A], [VIDEO_SAME_DAY])
        assert 'video_board_mismatch' not in result[0]

    def test_expected_board_changes_what_counts_as_mismatch(self):
        board_of_health_video = {
            'video_id': 'v5', 'date': '2024-03-15',
            'title': 'Board of Health Meeting 3/15',
        }
        result = correlator.correlate(
            [MEETING_A], [board_of_health_video], expected_board='Board of Health',
        )
        assert 'video_board_mismatch' not in result[0]

        result = correlator.correlate(
            [MEETING_A], [VIDEO_SAME_DAY], expected_board='Board of Health',
        )
        assert result[0]['video_board_mismatch'] is True


class TestLooksLikeWrongBoard:
    def test_flags_board_of_health(self):
        title = 'Board of Health Meeting 3/15'
        assert correlator.looks_like_wrong_board(title, 'Select Board')

    def test_flags_finance_committee(self):
        title = 'Finance Committee Meeting 5/21'
        assert correlator.looks_like_wrong_board(title, 'Select Board')

    def test_does_not_flag_select_board(self):
        assert not correlator.looks_like_wrong_board('Select Board 3/15', 'Select Board')

    def test_does_not_flag_joint_meeting(self):
        title = 'Select Board & Finance Committee Meeting'
        assert not correlator.looks_like_wrong_board(title, 'Select Board')

    def test_does_not_flag_bare_finance_committee_title_if_joint_worded(self):
        title = 'Joint Meeting with the Finance Committee'
        assert not correlator.looks_like_wrong_board(title, 'Select Board')

    def test_unrelated_title_not_flagged(self):
        title = 'Gaming Commission Public Hearing'
        assert not correlator.looks_like_wrong_board(title, 'Select Board')

    def test_select_board_title_flagged_when_expecting_board_of_health(self):
        assert correlator.looks_like_wrong_board('Select Board 3/15', 'Board of Health')

    def test_board_of_health_title_not_flagged_when_expecting_itself(self):
        title = 'Board of Health Meeting 3/15'
        assert not correlator.looks_like_wrong_board(title, 'Board of Health')

    def test_unknown_expected_board_falls_back_to_no_self_keywords(self):
        # A board with no entry in BOARD_TITLE_KEYWORDS has nothing that
        # counts as "its own" title, so any other tracked board's keyword
        # still flags — but an unrelated title still doesn't.
        assert correlator.looks_like_wrong_board('Select Board 3/15', 'Planning Board')
        assert not correlator.looks_like_wrong_board('Planning Board 3/15', 'Planning Board')
