"""Tests for project dependency declarations — closes #9.

Covers three concerns:
1. requirements.txt lists all expected runtime + GUI packages.
2. Every package in requirements.txt is importable in the current environment.
3. pyproject.toml [project.dependencies] and [project.optional-dependencies.gui]
   are consistent with requirements.txt — no silent drift between the two files.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_TXT = REPO_ROOT / "requirements.txt"
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"

# ---------------------------------------------------------------------------
# Map pip package name (lowercase, normalised) → Python import name.
# Only needed where the two differ.
# ---------------------------------------------------------------------------
_IMPORT_NAME: dict[str, str] = {
    "pyside6": "PySide6",
    "pillow": "PIL",
    "pyinstaller": "PyInstaller",
    "pytest-cov": "pytest_cov",
    "static-ffmpeg": "static_ffmpeg",
    # packages whose import name matches their pip name (lower-cased):
    # mutagen, natsort, pytest, mypy, black, flake8
}


def _pkg_name(raw: str) -> str:
    """Strip version specifier and return the normalised package name."""
    # PEP 508 extras ([extra]) and version constraints (>=, ==, …) stripped.
    name = re.split(r"[><=!;\[\s]", raw.strip())[0]
    return name.lower().replace("_", "-")


def _import_name(pip_name: str) -> str:
    """Return the importable module name for a pip package name."""
    normalised = pip_name.lower().replace("-", "_").replace(".", "_")
    return _IMPORT_NAME.get(pip_name, normalised)


def _requirements_packages() -> list[str]:
    """Parse requirements.txt and return normalised package names."""
    pkgs: list[str] = []
    for line in REQUIREMENTS_TXT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        pkgs.append(_pkg_name(line))
    return pkgs


def _pyproject_packages() -> tuple[list[str], list[str]]:
    """Return (runtime_deps, gui_deps) from pyproject.toml as normalised names."""
    data = tomllib.loads(PYPROJECT_TOML.read_text(encoding="utf-8"))
    project = data.get("project", {})
    runtime = [_pkg_name(d) for d in project.get("dependencies", [])]
    gui = [
        _pkg_name(d) for d in project.get("optional-dependencies", {}).get("gui", [])
    ]
    return runtime, gui


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRequirementsTxtContents:
    """requirements.txt must declare every runtime and GUI dependency."""

    def test_mutagen_listed(self) -> None:
        assert (
            "mutagen" in _requirements_packages()
        ), "mutagen missing from requirements.txt"

    def test_natsort_listed(self) -> None:
        assert (
            "natsort" in _requirements_packages()
        ), "natsort missing from requirements.txt"

    def test_pyside6_listed(self) -> None:
        """Regression test for issue #9 — PySide6 was missing."""
        assert "pyside6" in _requirements_packages(), (
            "PySide6 missing from requirements.txt — GUI cannot launch after "
            "'pip install -e .' without it (issue #9)"
        )


class TestAllDepsImportable:
    """Every package declared in requirements.txt must be importable."""

    @pytest.mark.parametrize("pkg", _requirements_packages())
    def test_importable(self, pkg: str) -> None:
        mod = _import_name(pkg)
        spec = importlib.util.find_spec(mod)
        assert spec is not None, (
            f"Package '{pkg}' listed in requirements.txt is not importable as "
            f"'{mod}' — run 'pip install -r requirements.txt'"
        )


class TestPyprojectConsistency:
    """pyproject.toml and requirements.txt must agree on package declarations."""

    def test_pyproject_runtime_deps_in_requirements(self) -> None:
        """Every pyproject runtime dep must appear in requirements.txt."""
        req_pkgs = set(_requirements_packages())
        runtime, _ = _pyproject_packages()
        missing = [d for d in runtime if d not in req_pkgs]
        assert not missing, (
            f"Packages in pyproject.toml [project.dependencies] missing from "
            f"requirements.txt: {missing}"
        )

    def test_pyproject_gui_deps_in_requirements(self) -> None:
        """Every pyproject gui optional dep must appear in requirements.txt."""
        req_pkgs = set(_requirements_packages())
        _, gui = _pyproject_packages()
        missing = [d for d in gui if d not in req_pkgs]
        assert not missing, (
            f"Packages in pyproject.toml [project.optional-dependencies.gui] "
            f"missing from requirements.txt: {missing}"
        )

    def test_requirements_runtime_pkgs_in_pyproject(self) -> None:
        """Core runtime packages in requirements.txt must be declared in pyproject."""
        # Only check the non-GUI runtime packages (mutagen, natsort) — PySide6
        # lives correctly under optional-dependencies.gui in pyproject.
        runtime, gui = _pyproject_packages()
        all_pyproject = set(runtime) | set(gui)
        req_pkgs = _requirements_packages()
        # Exclude PySide6 from this direction — it's in gui extras intentionally.
        missing = [p for p in req_pkgs if p not in all_pyproject]
        assert (
            not missing
        ), f"Packages in requirements.txt not declared in pyproject.toml: {missing}"
