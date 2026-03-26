<div align="center">

<img src="https://m4bookmaker.sageframe.net/assets/icons/app-icon.png" width="96" alt="m4Bookmaker icon" />

# m4Bookmaker

Convert a folder of audio files into a clean M4B audiobook — in seconds.

[![PyPI](https://img.shields.io/pypi/v/m4bmaker?color=blue)](https://pypi.org/project/m4bmaker/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![macOS](https://img.shields.io/badge/macOS-13%2B-black?logo=apple&logoColor=white)](#installation)
[![Windows](https://img.shields.io/badge/Windows-10%2B-0078D4?logo=windows&logoColor=white)](#installation)
[![Linux](https://img.shields.io/badge/Linux-supported-FCC624?logo=linux&logoColor=black)](#from-pypi)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](#from-source)

⭐ [Watch this repo (Releases only)](https://github.com/sageframe-no-kaji/m4bmaker/subscription) to get notified when a new version drops.

**[Website](https://m4bookmaker.sageframe.net) · [Help & Docs](https://m4bookmaker.sageframe.net/help.html) · [Report a Bug](https://github.com/sageframe-no-kaji/m4bmaker/issues/new)**

</div>

Drag in a folder, adjust your chapters, hit Convert. m4Bookmaker handles the rest — chapters, cover art, metadata, and even repairs broken audio files automatically.

<div align="center">
<img src="https://m4bookmaker.sageframe.net/assets/img/convert.png" width="640" alt="m4Bookmaker — main window" />
</div>

**[Website](https://m4bookmaker.sageframe.net)** · **[Help & Docs](https://m4bookmaker.sageframe.net/help.html)** · **[Report a Bug](https://github.com/sageframe-no-kaji/m4bmaker/issues)**

**Development Process:** This project was built using the [Ho System](https://atmarcus.net/work/ho-system), a structured methodology for human-AI collaborative development. The human makes every design decision. The AI implements under direction. There is verification at every step.

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

<div align="center">
<img src="https://m4bookmaker.sageframe.net/assets/img/chapter.png" width="640" alt="m4Bookmaker — chapter editor" />
</div>

---

## Installation

### Download

Get the signed, notarized macOS app or the Windows installer:

**[m4bookmaker.sageframe.net](https://m4bookmaker.sageframe.net)**

ffmpeg is bundled — nothing else to install.

### From PyPI

Works on macOS, Windows, and Linux. Requires Python 3.11+ and ffmpeg.

```bash
pip install m4bmaker
```

Or with the optional GUI:

```bash
pip install m4bmaker[gui]
```

Install ffmpeg if you don't have it:

```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Windows (winget)
winget install ffmpeg
```

### From source

Requires Python 3.11+ and ffmpeg.

```bash
git clone https://github.com/sageframe-no-kaji/m4bmaker.git
cd m4bmaker
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

## Privacy & network activity

m4Bookmaker is fully local — it never uploads your audio files or metadata.

**Update checker:** On startup, the GUI makes a single outbound request to the GitHub Releases API to check whether a newer version is available:

```
GET https://api.github.com/repos/sageframe-no-kaji/m4bmaker/releases/latest
User-Agent: m4bmaker/<version>
```

This sends your IP address and the installed version number to GitHub's API. No other data is transmitted. The check runs silently in the background and fails silently if you are offline. The CLI (`m4bmaker` command) makes no network calls at all.

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
