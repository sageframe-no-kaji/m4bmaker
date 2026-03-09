# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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
- **`make_m4b.py`** — thin entry point wiring all modules with progress logging.
- **`tests/`** — comprehensive `pytest` suite (143 tests, 99% coverage) covering all
  eight modules and a full integration pipeline with mocked subprocess calls.
- **`man/m4bmaker.1`** — troff/groff man page with NAME, SYNOPSIS, DESCRIPTION,
  OPTIONS, EXAMPLES, FILES, REQUIREMENTS, EXIT STATUS, BUGS, AUTHOR, SEE ALSO.
- **`README.md`** — installation guide, quick-start examples, full CLI reference table,
  chapter-title stripping rules, Docker pointer.
- **`LICENSE`** — MIT 2026 sageframe-no-kaji.
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
