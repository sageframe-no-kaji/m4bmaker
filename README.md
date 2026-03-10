# m4bmaker

**Build beautiful audiobooks from folders of audio files — in seconds.**

m4bmaker converts a directory of audio files into a clean, chapterized **.m4b audiobook** with metadata, cover art, and proper chapter markers. It works as a desktop GUI app, a command-line tool, and a scriptable pipeline.

Free and open source. Available on macOS.

---

⭐ **Star this repo if m4bmaker saves you time.**  
☕ **Buy me a coffee:** https://buymeacoffee.com/sageframe

---

## Features

### 📚 Automatic Chapter Creation
Drop a folder of audio files and m4bmaker generates chapters automatically — one per file, with titles cleaned from track numbers and prefixes.

```
01 - Prologue.mp3       →  Prologue
02 - The Journey.mp3    →  The Journey
03 - Arrival.mp3        →  Arrival
```

### ✏️ Chapter Editor
Rename chapters, adjust timestamps, and reorder — all inline, before encoding. No nested menus.

### 🎧 Built-in Audio Preview Player
A lightweight playback player lets you scrub through the source audio anA lightweight playback player lets you scrub through the source audio aseeksA lightweight playback player lets you scrub through the source audio anA lightweight playback player lets you scrub through the source audio aseeksA lightweight playback player lets you scrub through the source audio anurce.

### 🔄 Rechaptering (Edit Mode)
Load an existing `.m4b` to rename chapters, adjust timestamps, and write the changes back — without re-encoding the audio.

### 🖼 Automatic Cover Art
The largest image in the source directory is automatically used as the audiobook cover. Override with `--cover` if needed.

### 🛡 Robust Audio Repair
Many audiobook downloads contain damaged files. m4bmaker automatically detects and repairs:
- corrupted MP3 frames
- missing or invalid VBR/Xing headers
- embedded artwork in source tracks
- inconsistent audio stream layouts

Files are normalized before encoding so the final `.m4b` is clean and stable.

### 🔍 Preflight Audio Analysis
Before encoding, m4bmaker analyzes all input files and reports sample rate consistency, channel layout (mono/stereo), and bitrate distribution. Encoding settings are automatically matched to the source material.

### 📋 Batch Queue
Stage multiple audiobook jobs and process them sequentially — HandBrake-style. Add jobs to the queue, start the queue, and walk away.

### 🚀 Multiple Windows
Press `⌘N` to open a new independent window. Each window runs its own encode in parallel with no shared state.

### ⚙️ Full CLI Support
Everything available in the GUI is also scriptable:

```bash
m4bmaker ./Dune \
  --title "Dune" \
  --author "Frank Herbert" \
  --narrator "Scott Brick"
```

---

## Installation

### macOS (App Store)
Download **m4bmaker** from the Mac App Store. ffmpeg is bundled — no additional setup required.

### From Source

**Requirements:** Python 3.11+, ffmpeg

```bash
# Install ffmpeg
brew install ffmpeg

# Clone and install
git clone https://github.cgit clone https://github.cgit cit
cd m4bmaker
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

---

## Quick Start

```bash
# Convert a folder of audio files
m4bmaker ./MyBook

# With metadata
m4bmaker ./MyBook \
  --title "My Book" \
  --author "Author Name" \
  --narrator "Narrator Name"

# Custom cover art
m4bmaker ./MyBook --cover cover.jpg
```

---

## Supported Input Formats

`mp3` · `m4a` · `aac` · `flac` · `wav` · `ogg`

Formats can be mixed in the same directory.

---

## Contributing

Contributions are wContributions are wBUTING.mdContributions are wContributions are wBUTING.mdConyleContrilines.

Areas where Areas where Aciated:
- testing on large or unusual audiobook collections
- - tadata edge cases
- GUI improvements
- documentation

---

## License

MIT License · © 2026 Andrew T. Marcus
