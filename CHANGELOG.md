# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [1.1.0] - 2026-07-12

A hardening release: a full security, correctness, and performance review of
the entire codebase, with every finding fixed. 992 tests (up from ~630),
90% coverage.

### Fixed

- **Narrator edits to an existing M4B now stick.** The value was always
  written, but reading it back preferred the file's `comment` tag (store
  blurbs) over the saved atom, so the change looked lost. Narrator is now
  read from `©nrt`/`©wrt` directly, and saves also write `©nrt` — the atom
  Apple Books actually displays. Clearing a metadata field now clears it in
  the file instead of silently keeping the old value.
- **Edit mode: removing a chapter marker no longer corrupts the timeline.**
  Previously every later chapter shifted earlier by the removed chapter's
  length; the removed span now merges into the previous chapter. Reorder
  buttons are hidden in edit mode (time slices of one file can't be
  reordered).
- **Chapter time edits are honoured on Convert and Add to Queue** (previously
  only Save/Split applied them — edits were silently discarded).
- **A failed or cancelled encode can no longer destroy your audiobook.**
  Encoding stages to a temporary file and moves it into place only on
  success; a pre-existing good file at the destination survives.
- **Quitting mid-encode is now clean.** Cmd+Q / File→Quit cancels all
  background work and terminates ffmpeg instead of crashing and leaving an
  orphan process writing a half-finished file.
- **Queue Stop→Start race fixed** — stopping and immediately restarting the
  queue could strand remaining jobs and run two encodes at once. Failed queue
  jobs now show the actual error (tooltip / double-click).
- **Rapid folder switching can no longer mix up books** — a slow scan
  finishing late can't populate the UI for a different folder or carry the
  previous book's sample rate into the encode.
- **Special characters in tags and filenames no longer corrupt chapter
  metadata** — `#`, `=`, `;`, backslashes and newlines in titles/tags are
  escaped correctly (a filename like `Part #2.mp3` used to silently truncate
  its chapter title).
- **Chapter markers stay accurate when damaged files are repaired** (repair
  can shorten a file; markers are now recomputed afterwards). The repair scan
  also stopped flagging healthy files, reports files it could not repair
  honestly, and no longer collides same-named files from different discs.
- Mixed-codec source folders (e.g. a stray `.flac` among `.mp3`s) are
  rejected with a clear message before encoding — previously they produced
  corrupt output with drifting chapters.
- macOS `._*` AppleDouble files on USB/network drives no longer abort a
  build as "corrupt".
- GUI errors are real error dialogs again — library failures no longer kill
  the worker thread silently (frozen progress bar).
- Player: clicking chapters in quick succession no longer yanks playback
  back to the previous chapter; saving chapter edits no longer conflicts
  with the preview player holding the file open (Windows).
- macOS: the .m4b file picker no longer freezes the app while open, and a
  pick taking longer than two minutes is no longer lost.
- Output filenames derived from tags are sanitized for Windows-invalid
  characters (`Dune: Messiah` no longer fails at the end of a long encode)
  and can no longer escape the chosen output folder.
- Update check orders pre-release version tags correctly.

### Changed

- Find & Replace in the chapter table matches **literally** by default
  (typing `1.5` no longer matches `125`); a new **Regex** checkbox restores
  pattern matching.
- The Convert button becomes **Cancel** during a direct conversion;
  cancelling reports "Cancelled." instead of an ffmpeg error dump.
- Cover-by-URL requires `https://` and rejects images over 20 MB outright
  (previously silently truncated — corrupt covers).

### Security

- **macOS build: the third-party Intel ffmpeg binary is verified against a
  pinned SHA-256 before being bundled** into the signed, notarized app.
- Release builds (macOS script and Windows CI) install from a fully pinned,
  hash-verified dependency lock (`requirements-build.lock`) for reproducible
  builds.
- Metadata and chapter text are escaped before reaching ffmpeg's metadata
  files; output paths derived from untrusted tags are sanitized (traversal).
- Cover downloads are https-only, size-capped, and content-type-checked;
  hardened-runtime entitlements are documented with re-review criteria.

---

## [1.0.5] - 2026-05-08

### Fixed

- macOS Intel support actually works now — bundled ffmpeg/ffprobe are now
  universal2 fat binaries. 1.0.4 launched on Intel but crashed at first audio
  probe with "Bad CPU type in executable" because static_ffmpeg shipped
  arm64-only binaries.

---

## [1.0.4] - 2026-05-08

### Fixed

- macOS build now runs on both Intel and Apple Silicon (universal2 binary)

---

## [1.0.3] - 2026-04-03

### Fixed

- **Edit mode metadata strip** — Opening an `.m4b` to edit chapters no longer
  silently strips Title, Author, Narrator, and Genre on save. The ffmpeg command
  now uses `-map_metadata 0` (preserve all existing tags from the source) plus
  explicit `-metadata` flags to override only the fields edited in the GUI.
- **Edit mode metadata not saved** — Changes made to Title, Author, Narrator, or
  Genre in Edit mode are now written to the output file. Previously the GUI values
  were never threaded down to `save_m4b_chapters()`.
- **Narrator not persisting** — mutagen's EasyMP4 does not expose the `composer`
  key, so narrator always read back as empty after a save. `extract_metadata()`
  now falls back to reading the `©wrt` atom directly via the raw `MP4` interface
  when the easy path returns nothing.

---

## [1.0.2] - 2026-04-02

### Added

- **Edit mode** — `File > Open M4B File…` (⌘O) loads an existing `.m4b` into a new
  Edit mode. The app switches to an **Edit** mode badge and displays the chapter
  list for review and modification; cover art, metadata, and duration are pre-filled.
- **Add Chapter button** — In Edit mode a new "Add Chapter" button inserts a chapter
  at the current playhead position, automatically renaming subsequent chapters.
- **Millisecond precision** — Chapter timestamps in the table are now displayed and
  editable to millisecond precision (`HH:MM:SS.mmm`), preserving sub-second accuracy
  when editing and saving.
- **Direct timestamp editing** — Clicking any timestamp cell in the chapter table
  opens an in-place editor. Edited values are validated; invalid entries revert.
- **Native macOS file picker** — "Edit…" button uses `osascript choose file`
  (real NSOpenPanel) so all files are visible and selectable; extension is validated
  after selection.
- **Build… / Edit… button labels** — "Browse" renamed to "Build…" and "Open M4B"
  to "Edit…" with tooltips that match the mode badge names per macOS HIG convention.

### Fixed

- **macOS scanning hang** — `LoadM4bWorker` previously called `ffmpeg` via
  `subprocess` from a QThread. On macOS, Qt multimedia holds CoreAudio locks on
  the main thread; the forked child inherits them, causing a permanent deadlock.
  Cover art is now extracted via mutagen only (`MP4.covr`, then ID3 `APIC`
  fallback) — pure Python, no subprocess, fork-safe.

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
