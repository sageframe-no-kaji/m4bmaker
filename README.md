# m4Bookmaker

Convert a folder of audio files into a clean M4B audiobook — in seconds.

Drag in a folder, adjust your chapters, hit Convert. m4Bookmaker handles the rest — chapters, cover art, metadata, and even repairs broken audio files automatically.

**[Website](https://m4bookmaker.sageframe.net)** · **[Help & Docs](https://m4bookmaker.sageframe.net/help.html)** · **[Report a Bug](https://github.com/sageframe-no-kaji/m4bmaker/issues)**

---

## What it does

- **Automatic chapters** from filenames — track numbers and prefixes stripped
- **Chapter editor** — rename, reorder, merge, split, adjust timestamps inline
- **Built-in audio player** — scrub through source audio, seek to any chapter boundary
- **Edit existing M4Bs** — rename chapters and adjust timestamps without re-encoding
- **Batch queue** — stage multiple books and process them sequentially
- **Audio repair** — fixes corrupted MP3 frames, missing headers, inconsistent streams
- **Automatic cover art** — largest image in the directory is used
- **Multiple windows** — each encoding in parallel
- **Full CLI** — everything in the GUI is scriptable from the command line

---

## Installation

### Download

Get the signed, notarized macOS app or the Windows installer:

**[m4bookmaker.sageframe.net](https://m4bookmaker.sageframe.net)**

ffmpeg is bundled — nothing else to install.

### From source

Requires Python 3.11+ and ffmpeg.

```bash
brew install ffmpeg
git clone https://github.com/sageframe-no-kaji/m4bmaker.git
cd m4bmaker
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Launch the GUI:

```bash
python -m m4bmaker.gui.app
```

Or use the CLI:

```bash
m4bmaker ./MyBook --title "Dune" --author "Frank Herbert"
```

---

## CLI reference

```bash
m4bmaker <folder> [options]
```

| Flag | Description |
|------|-------------|
| `--title` | Book title |
| `--author` | Author name |
| `--narrator` | Narrator name |
| `--cover` | Path to cover image |
| `--output` | Output directory |
| `--bitrate` | AAC bitrate (default: matches source) |
| `--stereo` | Force stereo output |
| `--no-prompt` | Skip interactive prompts |

---

## Supported formats

**Input:** mp3 · m4a · aac · flac · wav · ogg — formats can be mixed in the same folder.

**Output:** `.m4b` (AAC in MP4 container with chapter metadata)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

GPL-3.0 · © 2026 Andrew T. Marcus

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE) for details.

---

<div align="center">

**[Website](https://m4bookmaker.sageframe.net)** · **[Help Docs](https://m4bookmaker.sageframe.net/help.html)** · **[Report a Bug](https://github.com/sageframe-no-kaji/m4bmaker/issues)**

Made by [Sageframe](https://github.com/sageframe-no-kaji)

</div>
