import requests
from unittest.mock import MagicMock, patch

from youtube_transcript_api._errors import IpBlocked, NoTranscriptFound, TranscriptsDisabled, VideoUnplayable

from towncommoniq import transcript


def _make_snippet(text: str):
    snippet = MagicMock()
    snippet.text = text
    return snippet


SAMPLE_SNIPPETS = [_make_snippet('Hello everyone.'), _make_snippet('Welcome to the meeting.')]


class TestFormatTranscript:
    def test_joins_lines(self):
        result = transcript._format_transcript(SAMPLE_SNIPPETS)
        assert 'Hello everyone.' in result
        assert 'Welcome to the meeting.' in result

    def test_strips_whitespace(self):
        snippet = _make_snippet('  Hello  ')
        result = transcript._format_transcript([snippet])
        assert result == 'Hello'

    def test_empty_entries(self):
        assert transcript._format_transcript([]) == ''


class TestConfigureCookies:
    def setup_method(self, _method):
        transcript._cfg.http_client = None
        transcript._cfg.cookies_file = None

    def teardown_method(self, _method):
        transcript._cfg.http_client = None
        transcript._cfg.cookies_file = None

    def test_sets_session(self, tmp_path):
        cookies_file = tmp_path / 'cookies.txt'
        cookies_file.write_text('')
        with patch('http.cookiejar.MozillaCookieJar.load'):
            transcript.configure_cookies(str(cookies_file))
        assert isinstance(transcript._cfg.http_client, requests.Session)

    def test_sets_cookies_file_path(self, tmp_path):
        cookies_file = tmp_path / 'cookies.txt'
        cookies_file.write_text('')
        with patch('http.cookiejar.MozillaCookieJar.load'):
            transcript.configure_cookies(str(cookies_file))
        assert transcript._cfg.cookies_file == str(cookies_file)

    def test_cookies_session_inherits_existing_proxy(self, tmp_path):
        transcript._cfg.proxy_url = 'socks5://127.0.0.1:1080'
        cookies_file = tmp_path / 'cookies.txt'
        cookies_file.write_text('')
        with patch('http.cookiejar.MozillaCookieJar.load'):
            transcript.configure_cookies(str(cookies_file))
        assert transcript._cfg.http_client.proxies.get('https') == 'socks5://127.0.0.1:1080'


class TestConfigureProxy:
    def setup_method(self, _method):
        transcript._cfg.http_client = None
        transcript._cfg.proxy_url = None

    def teardown_method(self, _method):
        transcript._cfg.http_client = None
        transcript._cfg.proxy_url = None

    def test_sets_proxy_url(self):
        transcript.configure_proxy('socks5://127.0.0.1:1080')
        assert transcript._cfg.proxy_url == 'socks5://127.0.0.1:1080'

    def test_creates_session_when_no_http_client(self):
        transcript.configure_proxy('socks5://127.0.0.1:1080')
        assert isinstance(transcript._cfg.http_client, requests.Session)
        assert transcript._cfg.http_client.proxies.get('https') == 'socks5://127.0.0.1:1080'

    def test_updates_existing_session_proxies(self):
        transcript._cfg.http_client = requests.Session()
        transcript.configure_proxy('socks5://127.0.0.1:1080')
        assert transcript._cfg.http_client.proxies.get('http') == 'socks5://127.0.0.1:1080'

    def test_ytdlp_captions_passes_proxy_flag(self):
        transcript._cfg.proxy_url = 'socks5://127.0.0.1:1080'
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        with patch('subprocess.run', return_value=mock_proc) as mock_run:
            transcript._fetch_ytdlp_captions('abc123')
        cmd = mock_run.call_args[0][0]
        assert '--proxy' in cmd
        assert 'socks5://127.0.0.1:1080' in cmd

    def test_do_fetch_passes_client_to_api(self):
        mock_instance = MagicMock()
        mock_instance.fetch.return_value = SAMPLE_SNIPPETS
        with patch('towncommoniq.transcript.YouTubeTranscriptApi', return_value=mock_instance) as mock_cls:
            transcript._do_fetch('abc123')
        mock_cls.assert_called_once_with(http_client=transcript._cfg.http_client)


class TestFetchYoutubeTranscript:
    def test_returns_text_on_success(self):
        mock_instance = MagicMock()
        mock_instance.fetch.return_value = SAMPLE_SNIPPETS
        with patch('towncommoniq.transcript.YouTubeTranscriptApi', return_value=mock_instance):
            result = transcript._fetch_youtube_transcript('abc123')
        assert result is not None
        assert 'Hello everyone.' in result

    def test_returns_none_on_no_transcript(self):
        mock_instance = MagicMock()
        mock_instance.fetch.side_effect = NoTranscriptFound('abc123', [], {})
        with patch('towncommoniq.transcript.YouTubeTranscriptApi', return_value=mock_instance):
            result = transcript._fetch_youtube_transcript('abc123')
        assert result is None

    def test_returns_none_on_disabled(self):
        mock_instance = MagicMock()
        mock_instance.fetch.side_effect = TranscriptsDisabled('abc123')
        with patch('towncommoniq.transcript.YouTubeTranscriptApi', return_value=mock_instance):
            result = transcript._fetch_youtube_transcript('abc123')
        assert result is None

    def test_returns_none_on_ip_blocked(self):
        mock_instance = MagicMock()
        mock_instance.fetch.side_effect = IpBlocked('abc123')
        with patch('towncommoniq.transcript.YouTubeTranscriptApi', return_value=mock_instance):
            result = transcript._fetch_youtube_transcript('abc123')
        assert result is None

    def test_returns_none_on_video_unplayable(self):
        mock_instance = MagicMock()
        mock_instance.fetch.side_effect = VideoUnplayable('abc123', 'processing', [])
        with patch('towncommoniq.transcript.YouTubeTranscriptApi', return_value=mock_instance):
            result = transcript._fetch_youtube_transcript('abc123')
        assert result is None


class TestParseSrt:
    def test_strips_indices_and_timestamps(self):
        srt = '1\n00:00:00,000 --> 00:00:02,000\nHello everyone.\n\n2\n00:00:02,000 --> 00:00:04,000\nWelcome.\n'
        assert transcript._parse_srt(srt) == 'Hello everyone.\nWelcome.'

    def test_deduplicates_adjacent_identical_lines(self):
        srt = '1\n00:00:00,000 --> 00:00:02,000\nHello.\n\n2\n00:00:02,000 --> 00:00:04,000\nHello.\n\n3\n00:00:04,000 --> 00:00:06,000\nWorld.\n'
        assert transcript._parse_srt(srt) == 'Hello.\nWorld.'

    def test_returns_empty_for_blank_input(self):
        assert transcript._parse_srt('') == ''


class TestFetchYtdlpCaptions:
    def test_returns_text_when_srt_downloaded(self, tmp_path):
        srt_content = '1\n00:00:00,000 --> 00:00:02,000\nHello board.\n'
        mock_proc = MagicMock()
        mock_proc.returncode = 0

        def fake_run(cmd, **kwargs):
            # Find the output template from cmd and write a fake SRT file
            out_idx = cmd.index('--output') + 1
            template = cmd[out_idx].replace('%(id)s', 'abc123').replace('%(ext)s', 'en.srt')
            import os
            os.makedirs(os.path.dirname(template), exist_ok=True)
            with open(template, 'w') as f:
                f.write(srt_content)
            return mock_proc

        with patch('subprocess.run', side_effect=fake_run):
            result = transcript._fetch_ytdlp_captions('abc123')
        assert result == 'Hello board.'

    def test_returns_none_on_yt_dlp_failure(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        with patch('subprocess.run', return_value=mock_proc):
            assert transcript._fetch_ytdlp_captions('abc123') is None

    def test_returns_none_when_no_srt_file(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        with patch('subprocess.run', return_value=mock_proc):
            assert transcript._fetch_ytdlp_captions('abc123') is None

    def test_passes_cookies_file_when_configured(self, monkeypatch):
        monkeypatch.setattr(transcript._cfg, 'cookies_file', '/tmp/cookies.txt')
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        with patch('subprocess.run', return_value=mock_proc) as mock_run:
            transcript._fetch_ytdlp_captions('abc123')
        cmd = mock_run.call_args[0][0]
        assert '--cookies' in cmd
        assert '/tmp/cookies.txt' in cmd

    def test_no_cookies_flag_without_configuration(self):
        transcript._cfg.cookies_file = None
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        with patch('subprocess.run', return_value=mock_proc) as mock_run:
            transcript._fetch_ytdlp_captions('abc123')
        cmd = mock_run.call_args[0][0]
        assert '--cookies' not in cmd


class TestGetCaptionsFallback:
    def setup_method(self, _method):
        self._orig_delay = transcript._CAPTION_DELAY
        transcript._CAPTION_DELAY = 0

    def teardown_method(self, _method):
        transcript._CAPTION_DELAY = self._orig_delay

    def test_falls_back_to_ytdlp_when_api_blocked(self, tmp_path):
        dest = tmp_path / 'transcript.txt'
        with patch.object(transcript, '_fetch_youtube_transcript', return_value=None), \
             patch.object(transcript, '_fetch_ytdlp_captions', return_value='Hello.') as mock_yt:
            result = transcript.get_captions('abc123', dest)
        mock_yt.assert_called_once_with('abc123')
        assert result is True
        assert dest.read_text() == 'Hello.'

    def test_returns_false_when_both_sources_fail(self, tmp_path):
        dest = tmp_path / 'transcript.txt'
        with patch.object(transcript, '_fetch_youtube_transcript', return_value=None), \
             patch.object(transcript, '_fetch_ytdlp_captions', return_value=None):
            assert transcript.get_captions('abc123', dest) is False

    def test_skips_ytdlp_when_api_succeeds(self, tmp_path):
        dest = tmp_path / 'transcript.txt'
        with patch.object(transcript, '_fetch_youtube_transcript', return_value='text'), \
             patch.object(transcript, '_fetch_ytdlp_captions') as mock_yt:
            transcript.get_captions('abc123', dest)
        mock_yt.assert_not_called()


class TestDownloadAudio:
    def test_calls_yt_dlp(self, tmp_path):
        dest = tmp_path / 'audio.mp3'
        mock_result = MagicMock()
        mock_result.check_returncode = MagicMock()
        with patch('subprocess.run', return_value=mock_result) as mock_run:
            transcript._download_audio('abc123', dest)
        cmd = mock_run.call_args[0][0]
        assert 'yt-dlp' in cmd
        assert 'abc123' in ' '.join(cmd)


class TestRunWhisper:
    def test_calls_whisper_and_returns_text(self, tmp_path):
        audio = tmp_path / 'audio.mp3'
        audio.write_text('fake')
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {'text': '  whisper output  '}
        mock_whisper = MagicMock()
        mock_whisper.load_model.return_value = mock_model
        with patch.dict('sys.modules', {'whisper': mock_whisper}):
            result = transcript._run_whisper(audio)
        assert result == 'whisper output'


class TestGenerateWithWhisper:
    def test_returns_transcript_text(self, tmp_path):
        with patch.object(transcript, '_download_audio'), \
             patch.object(transcript, '_run_whisper', return_value='local text'):
            result = transcript._generate_with_whisper('abc123')
        assert result == 'local text'


class TestFindAudioFile:
    def test_finds_ogg_file(self, tmp_path):
        (tmp_path / 'meeting.ogg').write_bytes(b'audio')
        assert transcript.find_audio_file(tmp_path) == tmp_path / 'meeting.ogg'

    def test_finds_m4a_file(self, tmp_path):
        (tmp_path / 'meeting.m4a').write_bytes(b'audio')
        assert transcript.find_audio_file(tmp_path) == tmp_path / 'meeting.m4a'

    def test_returns_none_when_no_audio(self, tmp_path):
        (tmp_path / 'transcript.txt').write_text('text')
        assert transcript.find_audio_file(tmp_path) is None

    def test_returns_none_for_missing_folder(self, tmp_path):
        assert transcript.find_audio_file(tmp_path / 'nonexistent') is None


class TestTranscribeAudio:
    def test_returns_cached_when_transcript_exists(self, tmp_path):
        audio = tmp_path / 'meeting.ogg'
        audio.write_bytes(b'audio')
        dest = tmp_path / 'transcript.txt'
        dest.write_text('cached')
        assert transcript.transcribe_audio(audio, dest) == 'cached'

    def test_runs_whisper_and_caches(self, tmp_path):
        audio = tmp_path / 'meeting.ogg'
        audio.write_bytes(b'audio')
        dest = tmp_path / 'transcript.txt'
        with patch.object(transcript, '_run_whisper', return_value='whisper text'):
            result = transcript.transcribe_audio(audio, dest)
        assert result == 'whisper text'
        assert dest.read_text() == 'whisper text'


class TestGetCaptions:
    def setup_method(self, _method):
        self._orig_delay = transcript._CAPTION_DELAY
        transcript._CAPTION_DELAY = 0

    def teardown_method(self, _method):
        transcript._CAPTION_DELAY = self._orig_delay

    def test_returns_true_when_cached(self, tmp_path):
        dest = tmp_path / 'transcript.txt'
        dest.write_text('cached')
        assert transcript.get_captions('abc123', dest) is True

    def test_saves_and_returns_true_when_captions_available(self, tmp_path):
        dest = tmp_path / 'transcript.txt'
        with patch.object(transcript, '_fetch_youtube_transcript', return_value='captions text'), \
             patch.object(transcript, '_fetch_ytdlp_captions', return_value=None):
            result = transcript.get_captions('abc123', dest)
        assert result is True
        assert dest.read_text() == 'captions text'

    def test_returns_false_when_captions_unavailable(self, tmp_path):
        dest = tmp_path / 'transcript.txt'
        with patch.object(transcript, '_fetch_youtube_transcript', return_value=None), \
             patch.object(transcript, '_fetch_ytdlp_captions', return_value=None):
            result = transcript.get_captions('abc123', dest)
        assert result is False
        assert not dest.exists()

    def test_does_not_fall_back_to_whisper(self, tmp_path):
        dest = tmp_path / 'transcript.txt'
        with patch.object(transcript, '_fetch_youtube_transcript', return_value=None), \
             patch.object(transcript, '_fetch_ytdlp_captions', return_value=None), \
             patch.object(transcript, '_generate_with_whisper') as mock_whisper:
            transcript.get_captions('abc123', dest)
        mock_whisper.assert_not_called()


class TestGetTranscript:
    def test_returns_cached_when_file_exists(self, tmp_path):
        dest = tmp_path / 'transcript.txt'
        dest.write_text('cached transcript')
        result = transcript.get_transcript('abc123', dest)
        assert result == 'cached transcript'

    def test_fetches_from_youtube_when_no_cache(self, tmp_path):
        dest = tmp_path / 'transcript.txt'
        with patch.object(transcript, '_fetch_youtube_transcript', return_value='yt text'):
            result = transcript.get_transcript('abc123', dest)
        assert result == 'yt text'
        assert dest.read_text() == 'yt text'

    def test_falls_back_to_whisper_when_youtube_unavailable(self, tmp_path):
        dest = tmp_path / 'transcript.txt'
        with patch.object(transcript, '_fetch_youtube_transcript', return_value=None), \
             patch.object(transcript, '_generate_with_whisper', return_value='whisper text'):
            result = transcript.get_transcript('abc123', dest)
        assert result == 'whisper text'
        assert dest.read_text() == 'whisper text'


class TestFindRecordingFile:
    def test_finds_recording_file(self, tmp_path):
        rec = tmp_path / 'meeting_recording.mp4'
        rec.write_bytes(b'fake')
        result = transcript.find_recording_file(tmp_path)
        assert result == rec

    def test_returns_none_when_no_recording(self, tmp_path):
        assert transcript.find_recording_file(tmp_path) is None

    def test_returns_none_when_folder_missing(self, tmp_path):
        assert transcript.find_recording_file(tmp_path / 'nonexistent') is None


class TestDownloadRecording:
    def test_audio_only_uses_m4a_format(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        with patch('subprocess.run', return_value=mock_proc) as mock_run:
            transcript.download_recording('abc123', MagicMock(), audio_only=True)
        cmd = mock_run.call_args[0][0]
        assert '--extract-audio' in cmd
        assert 'm4a' in cmd

    def test_video_uses_mp4_format(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        with patch('subprocess.run', return_value=mock_proc) as mock_run:
            transcript.download_recording('abc123', MagicMock(), audio_only=False)
        cmd = mock_run.call_args[0][0]
        assert 'mp4' in ' '.join(cmd)
