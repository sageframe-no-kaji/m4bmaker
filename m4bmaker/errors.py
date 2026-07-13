"""Shared exception types for user-facing failures.

Library modules never call ``sys.exit`` — they raise :class:`M4BError` (or
its subclass :class:`EncodeCancelled`) instead, so the same code can be
driven by both the CLI and the GUI. ``m4bmaker.__main__`` is the only place
that translates these exceptions into process exit codes.
"""

from __future__ import annotations


class M4BError(Exception):
    """A user-facing failure. The message is the full text to show the user."""


class EncodeCancelled(M4BError):
    """Raised when an in-progress encode is cancelled by the user."""
