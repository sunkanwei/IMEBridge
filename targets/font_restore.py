"""Restore guards for 3D Text confirmation-space leaks."""

import time

from ..core import models
from ..core import runtime
from . import font as font_target


FONT_CONFIRM_SPACE_LEAK_SECONDS = 0.5


def _ptr_value(value: object) -> int:
    """Normalize pointer-like values without importing a platform backend."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    try:
        raw = getattr(value, "value", value)
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def remember_hidden_ime_activity(hwnd: object, target: object) -> None:
    """Remember hidden pre-composition IME activity for a 3D Text target."""
    key = font_target.target_key(target)
    if not key:
        return

    state = runtime.state.font_hidden_ime_activity
    state.hwnd = _ptr_value(hwnd)
    state.target_key = key
    state.until = time.monotonic() + runtime.TEXT_HIDDEN_IME_ACTIVITY_SECONDS


def hidden_ime_activity_is_active(hwnd: object, target: object) -> bool:
    """Return whether hidden pre-composition activity recently hit this Font."""
    state = runtime.state.font_hidden_ime_activity
    if not state.target_key:
        return False
    if state.hwnd and state.hwnd != _ptr_value(hwnd):
        return False
    if time.monotonic() > state.until:
        state.clear()
        return False
    return state.target_key == font_target.target_key(target)


def remember_possible_confirm_space_leak(hwnd: object, target: object) -> None:
    """Snapshot 3D Text before a Space that may belong to IME confirmation."""
    key = font_target.target_key(target)
    body = font_target.body_from_target(target)
    if not key or body is None:
        return

    state = runtime.state.font_confirm_space_leak
    snapshot = state.snapshot
    if (
        isinstance(snapshot, models.FontBodySnapshot)
        and snapshot.target_key == key
        and snapshot.body == body
        and (not state.hwnd or state.hwnd == _ptr_value(hwnd))
        and time.monotonic() <= state.until
    ):
        return

    state.hwnd = _ptr_value(hwnd)
    state.snapshot = models.FontBodySnapshot(key, body)
    state.until = time.monotonic() + FONT_CONFIRM_SPACE_LEAK_SECONDS


def clear_confirm_space_leak() -> None:
    """Drop the suspected 3D Text confirmation-space snapshot."""
    runtime.state.font_confirm_space_leak.clear()


def _ime_result_needs_space_leak_guard(text: str | None) -> bool:
    """Only committed IME text should be allowed to erase a leaked Space."""
    if not text:
        return False
    candidate = text[1:] if text.startswith(" ") else text
    return bool(candidate) and not candidate.isascii()


def _confirm_space_leak_snapshot_is_active(
    hwnd: object,
    target: object,
) -> bool:
    """Keep the Font leak snapshot only while it still matches this target."""
    state = runtime.state.font_confirm_space_leak
    snapshot = state.snapshot
    if not isinstance(snapshot, models.FontBodySnapshot):
        return False
    if state.hwnd and state.hwnd != _ptr_value(hwnd):
        return False
    if time.monotonic() > state.until:
        clear_confirm_space_leak()
        return False
    return snapshot.target_key == font_target.target_key(target)


def preview_confirm_space_leak_snapshot(
    hwnd: object,
    target: object,
    text: str | None,
) -> tuple[models.FontBodySnapshot | None, str | None]:
    """Return the valid leaked-Space repair without mutating runtime state."""
    if not _confirm_space_leak_snapshot_is_active(hwnd, target):
        return None, text
    if not _ime_result_needs_space_leak_guard(text):
        return None, text

    snapshot = runtime.state.font_confirm_space_leak.snapshot
    if not isinstance(snapshot, models.FontBodySnapshot):
        return None, text
    if font_target.confirm_space_leak_index(target, snapshot) is None:
        return None, text

    normalized = text[1:] if text.startswith(" ") else text
    return snapshot, normalized


def consume_confirm_space_leak_snapshot(
    hwnd: object,
    target: object,
    text: str | None,
) -> tuple[models.FontBodySnapshot | None, str | None]:
    """Attach a valid leaked-Space snapshot to the next 3D Text commit."""
    snapshot, normalized = preview_confirm_space_leak_snapshot(hwnd, target, text)
    if snapshot is not None:
        clear_confirm_space_leak()
        return snapshot, normalized
    if _confirm_space_leak_snapshot_is_active(hwnd, target):
        clear_confirm_space_leak()
    return None, text


def finish_confirm_space_leak_snapshot(hwnd: object, target: object) -> None:
    """Commit the preview decision once the deferred insert is safely queued."""
    if _confirm_space_leak_snapshot_is_active(hwnd, target):
        clear_confirm_space_leak()
