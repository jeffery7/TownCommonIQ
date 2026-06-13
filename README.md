# TownCommonIQ

TownCommonIQ builds a searchable archive of local government meeting records —
agendas, recordings, transcripts, and minutes — and can generate draft minutes
for meetings where none have been posted.

It was created to support oversight of the **Town of Hardwick, Massachusetts
Select Board**, but is designed to be adaptable to other Massachusetts towns.

## What it does

- **Scrapes** meeting listings and agendas from
  [MyTownGovernment.org](https://www.mytowngovernment.org/) and the town
  website, and pulls stream metadata from the town's YouTube channel.
- **Correlates** meetings with their corresponding YouTube recordings by
  date.
- **Archives** agendas, posted documents, and (optionally) recordings or
  audio for each meeting into a local per-meeting folder.
- **Transcribes** recordings via the YouTube transcript API, falling back to
  Whisper when no transcript is available.
- **Generates** draft `.docx` minutes from agendas and transcripts using the
  Claude API, aiming for compliance with Massachusetts Open Meeting Law
  (MGL Chapter 30A §22/§23).
- **Compares** minutes availability between the official posting site and the
  town website to flag gaps.

## Quick start

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
export TOWNCOMMONIQ_TOWN=Hardwick   # defaults to Hardwick if not set

python -m towncommoniq sync       # refresh meeting and video listings
python -m towncommoniq list       # see what's known
python -m towncommoniq archive --all
python -m towncommoniq generate --all
```

## Documentation

Full CLI reference, architecture, data layout, coding style, and test
instructions live in [AGENTS.md](AGENTS.md) — this is the canonical
documentation source for both human contributors and AI coding agents
(Claude Code, ChatGPT/Codex, Gemini CLI).

## License

No license has been chosen yet; all rights reserved.
