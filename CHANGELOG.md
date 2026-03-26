# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [1.0.1] - 2026-03-26

### Added

- **Update checker** — `m4bmaker/gui/updater.py` (`UpdateChecker(QThread)`) queries
  the GitHub Releases API on startup via stdlib `urllib` (no new runtime dependency).
  A dismissible blue info bar appears at the top of the main window when a newer
  release is found; the bar is hidden by default and includes a Download link.
- **Privacy disclosure** — About dialog and README now document the single outbound
  network call made by the update checker (IP address + User-Agent sent to GitHub API).
- **Dark mode persistence** — `m4bmaker/gui/prefs.py` stores user preferences in
  `platformdirs.user_config_dir('m4bmaker')/prefs.json`. The dark mode toggle state
  is saved on change and restored on startup, surviving application restarts.
- **`platformdirs>=4.0`** added to `requirements.txt` and `pyproject.toml`
  (was a transitive dependency; now made explicit).
- **`PySide6>=6.6`** added to `requirements.txt` so that
  `pip install -r requirements.txt` is self-contained for GUI users.

### Fixed

- Paths containing an apostrophe in a *parent directory* (e.g. `/Dad's Books/`)
  now escape correctly in the ffmpeg concat list. The existing `replace("'", "\\'")
  ` logic already operated on the full path; five new tests document and verify this
  for both filename and directory-level apostrophes.

---

### Added

- **`m4bmaker/utils.py`** — `find_ffmpeg()` / `find_ffprobe()` with Homebrew/apt
  install hints on failure; `log()` helper for consistent progress output.
- **`m4bmaker/scanner.py`** — `scan_audio_files()` scans a directory for supported
  audio formats (`.mp3`, `.m4a`, `.aac`, `.flac`, `.wav`, `.ogg`) using natural sort
  via `natsort`; exits with a clear message on empty directories.
- **`m4bmaker/cover.py`** — `find_cover()` auto-selects the highest-resolution image
  in the directory via Pillow; accepts a `--cover` CLI override.
- **`m4bmaker/metadata.py`** — `extract_metadata()` reads title/author from audio tags
  via `mutagen`; `prompt_missing()` fills gaps interactively or via CLI flags.
- **`m4bmaker/chapters.py`** — `get_duration()` probes files with `ffprobe`;
  `build_chapters()` accumulates millisecond timestamps; `write_ffmetadata()` emits
  a valid `FFMETADATA1` chapter file with stripped track-number prefixes.
- **`m4bmaker/encoder.py`** — `write_concat_list()` generates an ffmpeg concat
  demuxer list with properly escaped paths; `encode()` drives the full ffmpeg
  command (AAC codec, configurable bitrate/channels, cover art, chapter metadata).
- **`m4bmaker/cli.py`** — `argparse` parser with flags: `directory`, `--output`,
  `--title`, `--author`, `--narrator`, `--cover`, `--bitrate`, `--stereo`,
  `--no-prompt`.
- **`m4bmaker/__main__.py`** — thin entry point wiring all modules with progress logging.
  Enables both `m4bmaker` (installed command) and `python -m m4bmaker`.
- **`tests/`** — comprehensive `pytest` suite (143 tests, 99% coverage) covering all
  eight modules and a full integration pipeline with mocked subprocess calls.
- **`man/m4bmaker.1`** — troff/groff man page with NAME, SYNOPSIS, DESCRIPTION,
  OPTIONS, EXAMPLES, FILES, REQUIREMENTS, EXIT STATUS, BUGS, AUTHOR, SEE ALSO.
- **`README.md`** — installation guide, quick-start examples, full CLI reference table,
  chapter-title stripping rules, Docker pointer.
- **`LICENSE`** — GPL-3.0 2026 sageframe-no-kaji.
- **`CONTRIBUTING.md`** — virtualenv setup, linting commands, test commands, PR guide.
- **`docs/architecture.md`** — module dependency map, data-flow diagram, design decisions.
- **`docs/docker.md`** — sample `Dockerfile` and `docker run` examples.
- **`pyproject.toml`** — build system (`setuptools.build_meta`), project metadata,
  `black` config, pytest `pythonpath = ["."]`.
- **`setup.cfg`** — `flake8` (max-line-length = 88) and `mypy` (strict) settings.
- **`requirements.txt`** — `mutagen>=1.47`, `natsort>=8.4`.
- **`requirements-dev.txt`** — `pytest`, `pytest-cov`, `mypy`, `black`, `flake8`,
  `Pillow`.

[Unreleased]: https://github.com/sageframe-no-kaji/m4bmaker/compare/HEAD...HEAD
