"""Mode labelling in MainWindow — closes #13.

The mode badge and the first tab both name the current mode. They were set at
separate call sites and the tab was never updated, so opening an M4B produced
a window whose badge read "Edit" beside a tab still reading "Build". These
tests pin both labels to the mode together.
"""

from __future__ import annotations

import pytest

from m4bmaker.gui.window import _MODE_TAB_INDEX, MainWindow


@pytest.fixture
def window(qapp):
    w = MainWindow()
    yield w
    w.close()


def test_starts_in_build_mode(window):
    assert window._mode == "build"
    assert window._mode_badge.text() == "Build"
    assert window._tabs.tabText(_MODE_TAB_INDEX) == "Build"


def test_edit_mode_relabels_both_badge_and_tab(window):
    window._set_mode("edit")
    assert window._mode == "edit"
    assert window._mode_badge.text() == "Edit"
    assert window._tabs.tabText(_MODE_TAB_INDEX) == "Edit"


def test_returning_to_build_restores_both_labels(window):
    window._set_mode("edit")
    window._set_mode("build")
    assert window._mode == "build"
    assert window._mode_badge.text() == "Build"
    assert window._tabs.tabText(_MODE_TAB_INDEX) == "Build"


@pytest.mark.parametrize("mode", ["build", "edit"])
def test_badge_and_tab_never_disagree(window, mode):
    """The defect in #13 was precisely these two drifting apart."""
    window._set_mode(mode)
    assert window._mode_badge.text() == window._tabs.tabText(_MODE_TAB_INDEX)


def test_clearing_the_folder_returns_to_build(window):
    window._set_mode("edit")
    window._on_folder_cleared()
    assert window._mode == "build"
    assert window._mode_badge.text() == "Build"
    assert window._tabs.tabText(_MODE_TAB_INDEX) == "Build"


def test_mode_tab_index_points_at_the_mode_tab(window):
    """A reordered tab bar must not silently relabel the wrong tab."""
    assert window._tabs.tabText(_MODE_TAB_INDEX) in {"Build", "Edit"}
    assert window._tabs.tabText(1) == "Chapters"
