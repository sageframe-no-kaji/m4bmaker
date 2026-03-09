# m4bmaker

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)

Convert a directory of audio files into a single `.m4b` audiobook with chapters,
cover art, and embedded metadata — powered by **ffmpeg**.

---

## Features

- **Auto-chapters** — probes each file with `ffprobe` and writes `[CHAPTER]` markers
- **Metadata** — reads title/author from tags via `mutagen`; prompts for anything missing
- **Cover art** — auto-selects the largest-resolution image in the directory; override with `--cover`
- **Natural sort** — `01`, `02`, `10` ordered correctly, not lexicographically
- **Batch-friendly** — `--no-prompt` + CLI flags for fully non-interactive pipelines and Docker

---

## Requirements

| Dependency | Version | Notes |
|---|---|---|
| Python | >= 3.11 | |
| ffmpeg | >= 6.0 | must be on `PATH` |
| ffprobe | >= 6.0 | bundled with ffmpeg |
| mutagen | >= 1.47 | installed automatically |
| natsort | >= 8.4 | installed automatically |
| Pillow | any | optional; enables cover resolution comparison |

### macOS (Homebrew)

```bash
brew install ffmpeg
```

### Debian / Ubuntu

```bash
apt-get install -y ffmpeg
```

---

## Installation

```bash
# Clone the repo
git clone https://github.com/sageframe-no-kaji/m4bmaker.git
cd m4bmaker

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install runtime dependencies
pip install -r requirements.txt

# Optional: install as a command
pip install -e .
```

---

## Quick Start

```bash
# Interactive — prompts for any missing metadata
make_m4b /path/to/audiobook/Dune

# Supply all metadata up front
make_m4b /path/to/audiobook/Dune \
  --title "Dune" \
  --author "Frank Herbert" \
  --narrator "Scott Brick"

# Stereo, higher bitrate, custom output path
make_m4b /path/to/audiobook/Dune \
  --bitrate 128k \
  --stereo \
  --output ~/Desktop/Dune.m4b

# Fully non-interactive (scripts, CI, Docker)
make_m4b /books/Dune \
  --title "Dune" \
  --author "Frank Herbert" \
  --narrator "Scott Brick" \
  --no-prompt
```

The output file is placed inside the input directory and named
**`<Title> - <Author>.m4b`** (or `audiobook.m4b` if metadata is unavailable).

---

## CLI Reference

```
make_m4b [DIRECTORY] [options]
```

| Flag | Short | Default | Description |
|---|---|---|---|
| `DIRECTORY` | | cwd | Directory containing the audio files |
| `--output PATH` | `-o` | auto | Output `.m4b` path |
| `--title TITLE` | `-t` | from tags | Book title |
| `--author AUTHOR` | `-a` | from tags | Author name |
| `--narrator NAME` | `-n` | prompted | Narrator name |
| `--cover IMAGE` | `-c` | auto | Cover image path (`.jpg`/`.png`) |
| `--bitrate RATE` | `-b` | `96k` | Audio bitrate (e.g. `128k`) |
| `--stereo` | | mono | Encode in stereo (2 channels) |
| `--no-prompt` | | off | Fail instead of prompting for missing fields |

---

## Chapter Timestamps

Each audio file in the directory becomes one chapter. The chapter title is derived
from the filename with leading track-number prefixes stripped:

| Filename | Chapter title |
|---|---|
| `01 - Prologue.mp3` | `Prologue` |
| `02_Part_One.flac` | `Part One` |
| `03. The Desert.m4a` | `The Desert` |
| `Introduction.mp3` | `Introduction` |

---

## Supported Audio Formats

`.mp3` `.m4a` `.aac` `.flac` `.wav` `.ogg`

---

## Docker

See [docs/docker.md](docs/docker.md) for a ready-to-use `Dockerfile` and
`docker run` examples that mount your audiobook directory.

---

## Architecture

See [docs/architecture.md](docs/architecture.md) for the module dependency map
and design decisions.

---

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, linting, and testing instructions.

---

## License

[MIT](LICENSE) © 2026 sageframe-no-kaji
