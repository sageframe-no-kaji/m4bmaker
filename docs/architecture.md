# Architecture

> This document is a stub. Full content will be added in Phase 4.

## Module Dependency Map

```
make_m4b.py
    └── m4bmaker/cli.py          (argparse, all flags)
    └── m4bmaker/utils.py        (find_ffmpeg, find_ffprobe, log)
    └── m4bmaker/scanner.py      (scan_audio_files)
    └── m4bmaker/cover.py        (find_cover)
    └── m4bmaker/metadata.py     (extract_metadata, prompt_missing)
    └── m4bmaker/chapters.py     (get_duration, build_chapters, write_ffmetadata)
    └── m4bmaker/encoder.py      (write_concat_list, encode)
```

## Design Decisions

_To be filled in Phase 4._
