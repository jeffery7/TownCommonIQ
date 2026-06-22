"""Retrieves or generates a plain-text transcript for a meeting.

Sources tried in this priority order:
  1. Cached transcript.txt on disk — returned immediately if present.
  2. Local audio file (.ogg or .m4a) in the meeting folder — run through
     Whisper locally.  Use this for meetings recorded in person but not
     streamed to YouTube.
  3. YouTube auto-generated captions via youtube-transcript-api (fast,
     no audio download needed).
  4. Download audio from YouTube with yt-dlp and run Whisper locally
     (slow fallback when YouTube has no captions).
"""
import logging
import subprocess
import tempfile
import time
from http import cookiejar
from pathlib import Path
from typing import Optional

import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import CouldNotRetrieveTranscript

_logger = logging.getLogger(__name__)

_CAPTION_DELAY: float = 1.5  # seconds between live YouTube caption requests

_YTDLP = 'yt-dlp'
_OPT_OUTPUT = '--output'
_OPT_NO_PLAYLIST = '--no-playlist'


class _Config:
    """Mutable transport configuration shared across YouTube requests."""

    http_client: Optional[requests.Session] = None
    cookies_file: Optional[str] = None
    proxy_url: Optional[str] = None


_cfg = _Config()


def configure_cookies(cookies_file: str) -> None:
    """Load a Netscape-format cookies file to bypass YouTube IP blocks.

    Export cookies from your browser while logged in to YouTube (e.g. via the
    'Get cookies.txt LOCALLY' extension) and pass the file path here.  The
    same format is accepted by yt-dlp's --cookies option, so one file works
    for both the Transcript API session and yt-dlp subtitle downloads.
    """
    jar = cookiejar.MozillaCookieJar()
    jar.load(cookies_file, ignore_discard=True, ignore_expires=True)
    session = requests.Session()
    session.cookies = jar  # type: ignore[assignment]
    if _cfg.proxy_url:
        session.proxies = {'http': _cfg.proxy_url, 'https': _cfg.proxy_url}
    _cfg.http_client = session
    _cfg.cookies_file = cookies_file


def configure_proxy(proxy_url: str) -> None:
    """Set a proxy for all YouTube requests to bypass hard IP blocks.

    Accepts any format supported by requests and yt-dlp, e.g.:
      socks5://127.0.0.1:1080   (SSH tunnel: ssh -D 1080 user@host)
      http://proxy.example.com:8080

    Both the Transcript API requests session and yt-dlp subtitle downloads
    will route through this proxy.  Call before archive_all() is invoked.
    """
    _cfg.proxy_url = proxy_url
    if _cfg.http_client is None:
        session = requests.Session()
        session.proxies = {'http': proxy_url, 'https': proxy_url}
        _cfg.http_client = session
    else:
        _cfg.http_client.proxies = {'http': proxy_url, 'https': proxy_url}


_DOWNLOAD_TIMEOUT = 600
_RECORDING_TIMEOUT = 7200  # 2 hours — large video files take time
_AUDIO_EXTENSIONS = ('.ogg', '.m4a')
_RECORDING_EXTENSIONS = ('.mp4', '.webm', '.mkv', '.m4a')


def _format_transcript(fetched) -> str:
    """Join a list of caption snippet objects into a single plain-text string."""
    return '\n'.join(snippet.text for snippet in fetched).strip()


def _do_fetch(video_id: str):
    """Call the YouTube Transcript API for a given video ID.

    Separated from _fetch_youtube_transcript so tests can mock the API call
    without patching the entire module.  Uses the module-level session when
    one has been configured via configure_cookies().
    """
    return YouTubeTranscriptApi(http_client=_cfg.http_client).fetch(video_id)


def _fetch_youtube_transcript(video_id: str) -> Optional[str]:
    """Try to download YouTube's auto-generated captions; return None on failure.

    Returns None (rather than raising) when captions are unavailable so the
    caller can fall back to Whisper without extra error handling.
    """
    try:
        return _format_transcript(_do_fetch(video_id))
    except CouldNotRetrieveTranscript as exc:
        _logger.info('YouTube Transcript API has no captions for %s: %s', video_id, exc)
        return None


def _generate_with_whisper(video_id: str) -> str:
    """Download audio and run Whisper locally to produce a transcript.

    Uses a temporary directory so the downloaded audio file is automatically
    deleted when transcription finishes, regardless of success or failure.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        audio_path = Path(tmp_dir) / 'audio.mp3'
        _download_audio(video_id, audio_path)
        return _run_whisper(audio_path)


def _download_audio(video_id: str, dest: Path) -> None:
    """Use yt-dlp to download only the audio track of a YouTube video as MP3.

    Raises subprocess.CalledProcessError if yt-dlp exits with a non-zero
    status (e.g. the video is private or geo-blocked).
    """
    url = f'https://www.youtube.com/watch?v={video_id}'
    cmd = [
        _YTDLP,
        '--extract-audio',
        '--audio-format', 'mp3',
        _OPT_OUTPUT, str(dest.with_suffix('')),  # yt-dlp appends extension
        _OPT_NO_PLAYLIST,
        url,
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_DOWNLOAD_TIMEOUT,
    )
    proc.check_returncode()


def _run_whisper(audio_path: Path) -> str:
    """Run OpenAI Whisper on a local audio file and return the transcript text.

    Whisper is imported inside the function because it is a heavy dependency
    (it downloads model weights on first use) and is only needed as a fallback.
    """
    import whisper  # local import — heavy dependency only loaded when needed
    model = whisper.load_model('base')
    # fp16=False avoids NaN logits on GPUs with limited float16 support (e.g. MX550)
    transcription = model.transcribe(str(audio_path), fp16=False)
    return transcription['text'].strip()


def find_audio_file(folder: Path) -> Optional[Path]:
    """Return the first .ogg or .m4a file found in folder, or None.

    Returns None (rather than raising) if the folder does not exist yet,
    so callers can safely check before a meeting folder has been created.
    """
    if not folder.is_dir():
        return None
    for path in sorted(folder.iterdir()):
        if path.suffix in _AUDIO_EXTENSIONS:
            return path
    return None


def transcribe_audio(audio_path: Path, dest_path: Path) -> str:
    """Transcribe a local audio file with Whisper and cache the result.

    If a cached transcript already exists at dest_path it is returned
    immediately without re-running Whisper (which is slow).
    """
    if dest_path.exists():
        return dest_path.read_text()
    text = _run_whisper(audio_path)
    dest_path.write_text(text)
    return text


def _parse_srt(srt_text: str) -> str:
    """Convert SRT subtitle text to a plain-text transcript.

    Strips sequence indices, timestamps, and deduplicates adjacent identical
    lines (YouTube auto-captions often repeat the same line across cues).
    """
    lines = []
    for line in srt_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.isdigit() or ' --> ' in stripped:
            continue
        lines.append(stripped)
    parsed_lines = []
    prev = None
    for line in lines:
        if line != prev:
            parsed_lines.append(line)
            prev = line
    return '\n'.join(parsed_lines).strip()


def _fetch_ytdlp_captions(video_id: str) -> Optional[str]:
    """Download English auto-captions via yt-dlp as fallback for API IP blocks.

    yt-dlp accesses YouTube's subtitle endpoint through the video player API,
    which is a different path than the Transcript API and supports cookie-based
    authentication.  When a cookies file has been configured via
    configure_cookies(), it is passed to yt-dlp automatically.
    Returns None if captions are unavailable, rate-limited, or yt-dlp fails.
    """
    url = f'https://www.youtube.com/watch?v={video_id}'
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_template = str(Path(tmp_dir) / '%(id)s.%(ext)s')
        cmd = [
            _YTDLP,
            '--write-auto-subs', '--skip-download',
            '--sub-lang', 'en', '--sub-format', 'srt',
            _OPT_OUTPUT, out_template,
            _OPT_NO_PLAYLIST,
        ]
        if _cfg.cookies_file:
            cmd += ['--cookies', _cfg.cookies_file]
        if _cfg.proxy_url:
            cmd += ['--proxy', _cfg.proxy_url]
        cmd.append(url)
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_DOWNLOAD_TIMEOUT,
        )
        if proc.returncode != 0:
            _logger.info(
                'yt-dlp caption fetch failed for %s (exit %s): %s',
                video_id, proc.returncode, proc.stderr.strip(),
            )
            return None
        srt_files = sorted(Path(tmp_dir).glob('*.srt'))
        if not srt_files:
            _logger.info('No auto-captions available via yt-dlp for %s', video_id)
            return None
        return _parse_srt(srt_files[0].read_text()) or None


def get_captions(video_id: str, dest_path: Path) -> bool:
    """Fetch YouTube auto-captions; return True if a transcript was saved.

    Tries the Transcript API first (fast).  If the IP is blocked, falls back
    to yt-dlp subtitle download (which uses a different YouTube endpoint and
    supports cookie-based auth when configured via configure_cookies()).
    A small delay (_CAPTION_DELAY seconds) is applied before each live fetch
    to avoid triggering YouTube's per-IP rate limit.
    Does NOT fall back to Whisper.  Returns False only when no captions can
    be obtained by any means.
    """
    if dest_path.exists():
        return True
    time.sleep(_CAPTION_DELAY)
    text = _fetch_youtube_transcript(video_id)
    if not text:
        text = _fetch_ytdlp_captions(video_id)
    if not text:
        return False
    dest_path.write_text(text)
    return True


def find_recording_file(folder: Path) -> Optional[Path]:
    """Return the first video/audio recording file in folder, or None.

    Looks for any file whose suffix matches a known recording extension
    (.mp4, .webm, .mkv, .m4a) and whose name contains '_recording'.
    Returns None when the folder does not exist or has no recording.
    """
    if not folder.is_dir():
        return None
    for path in sorted(folder.iterdir()):
        if '_recording' in path.name and path.suffix in _RECORDING_EXTENSIONS:
            return path
    return None


def download_recording(video_id: str, dest_path: Path, audio_only: bool = False) -> None:
    """Download a YouTube meeting recording via yt-dlp.

    When audio_only is False (the default) the best available MP4 is saved.
    When audio_only is True only the audio track is saved as M4A, which is
    roughly one-tenth the size of a full video and sufficient for archival.
    Raises subprocess.CalledProcessError if yt-dlp fails (private video,
    geo-block, etc.).
    """
    url = f'https://www.youtube.com/watch?v={video_id}'
    if audio_only:
        cmd = [
            _YTDLP,
            '--extract-audio', '--audio-format', 'm4a',
            _OPT_OUTPUT, str(dest_path.with_suffix('')),
            _OPT_NO_PLAYLIST, url,
        ]
    else:
        cmd = [
            _YTDLP,
            '--format', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
            '--merge-output-format', 'mp4',
            _OPT_OUTPUT, str(dest_path),
            _OPT_NO_PLAYLIST, url,
        ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=_RECORDING_TIMEOUT,
    )
    proc.check_returncode()


def get_transcript(video_id: str, dest_path: Path) -> str:
    """Return the transcript for a YouTube video, writing it to dest_path.

    Tries YouTube's built-in captions first; falls back to Whisper if none
    are available.
    """
    if dest_path.exists():
        return dest_path.read_text()

    text = _fetch_youtube_transcript(video_id)
    if text is None:
        text = _generate_with_whisper(video_id)

    dest_path.write_text(text)
    return text
