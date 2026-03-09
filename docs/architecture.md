# Architecture

## Module Dependency Map

```
make_m4b.py → m4bmaker/__main__.py
    ├── m4bmaker/cli.py          parse_args()          → argparse.Namespace
    ├── m4bmaker/utils.py        find_ffmpeg()         → str (path)
    │                            find_ffprobe()        → str (path)
    │                            log()                 → None
    ├── m4bmaker/scanner.py      scan_audio_files()    → list[Path]
    ├── m4bmaker/cover.py        find_cover()          → Path | None
    ├── m4bmaker/metadata.py     extract_metadata()    → dict[str, str]
    │                            prompt_missing()      → dict[str, str]
    ├── m4bmaker/chapters.py     get_duration()        → float
    │                            build_chapters()      → list[Chapter]
    │                            write_ffmetadata()    → None
    └── m4bmaker/encoder.py      write_concat_list()   → None
                                 encode()              → None
```

No module imports from another module — all cross-module communication happens
through `m4bmaker/__main__.py`. This keeps each module independently testable.

---

## Data Flow

```
 DIRECTORY
     │
     ▼
 scanner.py ──────────────────────── list[Path] (natural-sorted audio files)
     │
     ├──▶ cover.py ─────────────────── Path | None  (cover image)
     │
     ├──▶ metadata.py ──────────────── dict[str, str]  (title, author, narrator)
     │         │
     │         └── mutagen (reads tags from first file)
     │         └── builtins.input() (fills gaps interactively)
     │
     ├──▶ chapters.py
     │         │
     │         ├── ffprobe (subprocess) ── float (duration per file)
     │         ├── build_chapters() ────── list[Chapter] (ms timestamps)
     │         └── write_ffmetadata() ──── ffmetadata.txt
     │
     └──▶ encoder.py
               │
               ├── write_concat_list() ─── concat.txt
               └── ffmpeg (subprocess) ─── <Title> - <Author>.m4b
```

---

## Design Decisions

### One module, one responsibility
Each module in `m4bmaker/` has a single, well-defined job. `scanner.py` finds
files; `chapters.py` computes timestamps; `encoder.py` calls ffmpeg. There are
no circular imports and no shared global state.

### Subprocess calls are isolated
`ffprobe` is called only in `chapters.py` (`get_duration`). `ffmpeg` is called
only in `encoder.py` (`encode`). This makes mocking straightforward: tests
patch `m4bmaker.chapters.get_duration` directly (returns a `float`) and
`m4bmaker.encoder.subprocess.run` (returns a `CompletedProcess` stub).

### Chapter title stripping
The regex `r'^[\d]+[\s\.\-_]+'` strips leading track-number prefixes
(`01 - `, `1.`, `01_`) from filenames before using them as chapter titles.
If the stripped result is empty the original filename stem is kept.

### Pillow is optional
`cover.py` uses Pillow only for resolution comparison inside `_image_area()`.
If Pillow is not installed (or the import fails), `_image_area` returns `0`
for all candidates and the tie is broken alphabetically by filename. The tool
remains fully functional without Pillow.

### Mono by default
Audiobooks are primarily speech. Mono at 96 kbps produces files roughly half
the size of stereo at the same perceived quality. Users who need stereo pass
`--stereo`.

### Temporary directory for intermediate files
`m4bmaker/__main__.py` creates one `tempfile.TemporaryDirectory()` for the session and
writes both `ffmetadata.txt` and `concat.txt` inside it. The directory is
automatically deleted when the `with` block exits, even on failure.

### Single entry point
`m4bmaker/__main__.py` is intentionally thin — it contains only wiring and logging, no
business logic. This keeps each module independently importable and testable
without invoking the full pipeline.
