<div align="center">

<img src="https://m4bookmaker.sageframe.net/assets/icons/app-icon.png" width="128" alt="m4Bookmaker icon" />

# m4Bookmaker

**Convert a folder of audio files into a clean M4B audiobook — in seconds.**

Automatic chapters · cover art · metadata · audio repair · no ffmpeg setup required.

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-13%2B-black?logo=apple&logoColor=white)](#installation)
[![Website](https://img.shields.io/badge/Website-m4bookmaker.sageframe.net-c45a2d)](https://m4bookmaker.sageframe.net)

<br />

<a href="https://m4bookmaker.sageframe.net">
  <img src="https://m4bookmaker.sageframe.net/assets/img/m4Bookmaker.png" width="720" alt="m4Bookmaker — main window" />
</a>

</div>

<br />

## Why m4Bookmaker?

Most audiobook tools expect perfect input. Real audiobook files are messy — inconsistent formats, corrupted frames, missing headers, numbered filenames. m4Bookmaker handles all of it automatically so you get a clean `.m4b` without touching a terminal or configuring ffmpeg.

**Free and open source.** A [$4.99 direct download](https://m4bookmaker.sageframe.net) is available if you want to support development.

---

## Features

<table>
<tr>
<td width="50%">

### Automatic Chapters
Drop a folder and chapters are created from filenames — track numbers and prefixes stripped automatically.

```
01 - Prologue.mp3    →  Prologue
02 - The Journey.mp3 →  The Journey
03 - Arrival.mp3     →  Arrival
```

</td>
<td width="50%">

### Chapter Editor
Rename, reorder, merge, split, and adjust chapter timestamps inline. No nested dialogs — everything edits in place.

<img src="https://m4bookmaker.sageframe.net/assets/img/chapter.png" width="360" alt="Chapter editor" />

</td>
</tr>
<tr>
<td>

### Built-in Audio Player
Scrub through source audio, seek to any chapter boundary, and preview before encoding.

<img src="https://m4bookmaker.sageframe.net/assets/img/player.png" width="360" alt="Audio player" />

</td>
<td>

### Rechaptering (Edit Mode)
Load an existing `.m4b` to rename chapters, adjust timestamps, and write changes back — **without re-encoding** the audio.

<img src="https://m4bookmaker.sageframe.net/assets/img/edit.png" width="360" alt="Edit mode" />

</td>
</tr>
<tr>
<td>

### Batch Queue
Stage multiple audiobooks and process them sequentially — HandBrake-style. Start the queue and walk away.

<img src="https://m4bookmaker.sageframe.net/assets/img/queue.png" width="360" alt="Batch queue" />

</td>
<td>

### Audio Repair
Automatically detects and repairs corrupted MP3 frames, missing VBR/Xing headers, embedded artwork, and inconsistent stream layouts before encoding.

</td>
</tr>
</table>

**Also includes:**
- **Automatic cover art** — largest image in the directory is used automatically
- **Preflight analysis** — sample rate, channel layout, and bitrate are matched to source material
- **Multiple windows** — `⌘N` opens independent windows, each encoding in parallel
- **Full CLI** — everything in the GUI is scriptable from the command line

---

## Installation

### Download (recommended)

Get the signed, notarized macOS app from the website:

**[m4bookmaker.sageframe.net](https://m4bookmaker.sageframe.net)**

ffmpeg is bundled — nothing else to install.

### From Source

Requires **Python 3.11+** and **ffmpeg**.

```bash
brew install ffmpeg

git clone https://github.com/sageframe-no-kaji/m4bmaker.git
cd m4bmaker
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Launch the GUI
python -m m4bmaker.gui.app

# Or use the CLI
m4bmaker ./MyBook --title "My Book" --author "Author Name"
```

---

## CLI Usage

```bash
# Basic conversion
m4bmaker ./MyBook

# With metadata
m4bmaker ./MyBook \
  --title "Dune" \
  --author "Frank Herbert" \
  --narrator "Scott Brick"

# Custom cover and output
m4bmaker ./MyBook --cover cover.jpg --output ~/Audiobooks/
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

## Supported Formats

**Input:** `mp3` · `m4a` · `aac` · `flac` · `wav` · `ogg` — formats can be mixed in the same directory.

**Output:** `.m4b` (AAC in MP4 container with chapter metadata)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and guidelines.

---

## License

**GPL-3.0** · © 2026 Andrew T. Marcus

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE) for details.

---

<div align="center">

**[Website](https://m4bookmaker.sageframe.net)** · **[Help Docs](https://m4bookmaker.sageframe.net/help.html)** · **[Report a Bug](https://github.com/sageframe-no-kaji/m4bmaker/issues)**

Made by [Sageframe](https://github.com/sageframe-no-kaji)

</div>
