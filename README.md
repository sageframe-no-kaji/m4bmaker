# m4bmaker

**A fast, modern tool for building audiobooks (.m4b) from folders of audio files.**

m4bmaker converts a directory of audio files into a clean, chapterized **.m4b audiobook** with proper metadata and cover art — powered by ffmpeg and designed to be simple, reliable, and scriptable.

---

⭐ **If this tool helped you, please star the repository!**
☕ **Support development:** https://buymeacoffee.com/sageframe

---

# Why This Exists

Audiobook tools have historically been frustrating.

Many are:

• old GUI applications that are difficult to automate
• fragile tools that fail on imperfect audio files
• complicated ffmpeg command pipelines
• abandoned software

m4bmaker was created to provide a **modern, reliable audiobook builder** that works for both **command-line users and GUI users**.

The goal is simple:

> Turn a folder of audio files into a clean `.m4b` audiobook with minimal friction.

---

# Features

## 📚 Automatic Chapter Creation

Each audio file becomes a chapter automatically.

Example input files:

01 - Prologue.mp3
02 - The Journey.mp3
03 - Arrival.mp3

Chapters become:

Prologue
The Journey
Arrival

Track numbers and prefixes are cleaned automatically.

---

## ✏️ Simple Chapter Editing

Chapters are automatically generated, but **can be edited easily before encoding**.

Features include:

- rename chapters directly
- edit titles inline
- flatten the chapter list (no confusing nested menus)
- bulk rename chapters

The goal is **fast editing with minimal friction**.

---

## 🎧 Built-in Mini Chapter Player

The GUI includes a **small preview player** so you can quickly listen to chapter boundaries.

This helps users:

- verify chapter positions
- identify chapter names
- rename chapters without leaving the app

---

## 🖼 Automatic Cover Detection

The tool automatically selects the **largest image in the directory** as the audiobook cover.

You can override with:

–cover cover.jpg

---

## ⚙️ Clean, Scriptable CLI

The command line interface is designed for **automation and scripting**.

Example:

m4bmaker ./Dune
–title “Dune”
–author “Frank Herbert”
–narrator “Scott Brick”

Batch workflows, Docker, and pipelines work cleanly.

---

## 🧱 Robust Audio Handling

Many audiobook downloads contain messy files.

m4bmaker automatically handles:

- corrupted MP3 frames
- missing headers
- embedded artwork in tracks
- inconsistent metadata
- mixed audio formats

Files are normalized before encoding so the final audiobook is stable.

---

## 🖥 Simple Desktop GUI

For users who prefer a visual interface, the GUI provides:

• folder selection
• metadata editing
• chapter editing
• cover preview
• progress display

Everything happens in **one clean window**.

---

## 🚀 Multiple Encoding Jobs

Run multiple audiobook builds simultaneously.

You can simply open multiple windows and run separate encodes in parallel.

This makes it easy to process large audiobook collections.

---

# Installation

Clone the repository:

git clone https://github.com/sageframe-no-kaji/m4bmaker.git
cd m4bmaker

Create a virtual environment:

python3 -m venv .venv
source .venv/bin/activate

Install dependencies:

pip install -r requirements.txt

Install the command:

pip install -e .

---

# Quick Start

Convert a folder of audio files into an audiobook:

m4bmaker ./MyBook

Interactive prompts will guide you through metadata.

Or provide metadata directly:

m4bmaker ./MyBook
–title “My Book”
–author “Author Name”
–narrator “Narrator Name”

---

# Supported Audio Formats

mp3
m4a
aac
flac
wav
ogg

Formats can be mixed in the same directory.

---

# Requirements

- Python 3.11+
- ffmpeg

Install ffmpeg on macOS:

brew install ffmpeg

---

# Project Philosophy

m4bmaker is designed to be:

• simple
• reliable
• scriptable
• predictable

It should work equally well for:

- CLI users
- audiobook collectors
- automation workflows
- GUI users

---

# Support Development

If m4bmaker saves you time or helps manage your audiobook library, consider supporting the project.

☕ **Buy me a coffee:**
https://buymeacoffee.com/sageframe

Even small donations help keep development active.

---

# Contributing

Contributions are welcome.

Helpful areas include:

- testing on large audiobook collections
- metadata improvements
- GUI improvements
- documentation
- bug reports

---

# License

MIT License

© 2026 Andrew T. Marcus
