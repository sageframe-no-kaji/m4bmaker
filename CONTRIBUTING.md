# Contributing to m4bmaker

Thank you for your interest in contributing! This document explains how to set up
your development environment, run tests and linters, and submit changes.

---

## Prerequisites

- **Python >= 3.11**
- **ffmpeg >= 6.0** (and `ffprobe`, bundled with ffmpeg) on `PATH`
  - macOS: `brew install ffmpeg`
  - Debian/Ubuntu: `apt-get install -y ffmpeg`
- **git**

---

## Local Setup

```bash
# 1. Fork and clone
git clone https://github.com/sageframe-no-kaji/m4bmaker.git
cd m4bmaker

# 2. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install runtime + dev dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

---

## Running Tests

```bash
# All tests with coverage report
pytest tests/ --cov=m4bmaker --cov-report=term-missing

# A single test file
pytest tests/test_chapters.py -v

# A single test
pytest tests/test_chapters.py::TestGetDuration::test_parses_duration_from_ffprobe -v
```

Coverage target: **> 90%** across all modules.

---

## Linting and Formatting

All three tools must pass cleanly before opening a pull request.

```bash
# Auto-format (writes changes in-place)
black .

# Check formatting without changing files
black --check .

# Lint
flake8 m4bmaker/ tests/

# Type check (strict)
mypy m4bmaker/
```

Configuration lives in `pyproject.toml` (black) and `setup.cfg` (flake8, mypy).
No separate `.mypy.ini` or `.flake8` files.

---

## Man Page

To verify the man page renders correctly:

```bash
man ./man/m4bmaker.1
```

---

## Commit Message Format

```
<type>(<scope>): <short summary>

- <file>: <what and why>
- <file>: <what and why>

Decisions: <any trade-offs or design choices>
```

**Types:** `feat`, `fix`, `test`, `docs`, `chore`, `refactor`

Examples:
- `feat(encoder): add --mono flag as explicit default`
- `fix(tests): remove unused width/height params in test_cover.py`
- `docs(phase-4): README, man page, CONTRIBUTING, CHANGELOG`

---

## Pull Request Guidelines

1. **One concern per PR.** Keep PRs focused — a bug fix should not also refactor
   unrelated code.
2. **Pass all checks.** `black --check`, `flake8`, `mypy`, and `pytest` must all
   pass cleanly.
3. **Write tests.** New behaviour must be covered by a test. Bug fixes should
   include a regression test.
4. **Reference issues.** If a PR closes an issue, include `Closes #N` in the
   PR description.
5. **Update CHANGELOG.md.** Add a bullet under `## [Unreleased]` describing
   your change.

---

## Project Structure

```
m4bmaker/          # production source package
tests/             # pytest test suite (mirrors package 1:1)
docs/              # long-form documentation
man/               # troff/groff man page
devlog/            # original prompt spec and living plan (not imported)
m4bmaker/          # production source package (includes __main__.py entry point)
pyproject.toml     # build system + tool config (black, pytest)
setup.cfg          # flake8 + mypy config
requirements.txt   # runtime deps
requirements-dev.txt  # dev/test deps
```

For a detailed module dependency map, see [docs/architecture.md](docs/architecture.md).
