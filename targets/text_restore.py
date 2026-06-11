"""Restore guards for Text Editor IME edit-key leaks."""

import time

from ..core import models
from ..core import runtime
from ..core import safe_ops
from . import text_positions as positions
from . import text_state


TEXT_RESTORE_TIMER_INTERVAL = 0.02
TEXT_CONFIRM_SPACE_LEAK_SECONDS = 0.5


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


def restore_text_cursor(snapshot: models.TextRestoreSnapshot) -> bool:
    """Move only the selection when the text body stayed intact."""
    if snapshot.text is None:
        return False
    return text_state.set_text_selection(
        snapshot.text,
        snapshot.line,
        snapshot.column,
        snapshot.select_line,
        snapshot.select_column,
    )


def restore_text_after_ime_edit_key() -> None:
    """Repair the Text Editor after the short guard window expires."""
    runtime.state.text_restore_timer_registered = False
    snapshot = runtime.state.text_restore_guard
    runtime.state.text_restore_guard = None
    if snapshot is None or snapshot.text is None:
        return None
    if not restore_snapshot_is_current(snapshot):
        return None

    current_body = safe_ops.maybe_get_text_body(snapshot.text)
    if current_body is None:
        return None

    selection = positions.text_selection_position(snapshot.text)
    if selection is None:
        return None

    if current_body != snapshot.body:
        text_state.restore_text_state(snapshot)
        return None

    snapshot_selection = (
        snapshot.line,
        snapshot.column,
        snapshot.select_line,
        snapshot.select_column,
    )
    if selection != snapshot_selection:
        restore_text_cursor(snapshot)
    return None


def schedule_restore_guard(target: object) -> None:
    """Arm the guard while the IME owns keys such as Backspace."""
    if runtime.state.text_restore_timer_registered:
        return

    snapshot = text_state.capture_restore_snapshot(target)
    if snapshot is None:
        return

    runtime.state.text_restore_guard = snapshot
    if safe_ops.register_timer(
        restore_text_after_ime_edit_key,
        first_interval=TEXT_RESTORE_TIMER_INTERVAL,
    ):
        runtime.state.text_restore_timer_registered = True
    else:
        runtime.state.text_restore_guard = None


def cancel_restore_guard() -> None:
    """Drop the Text Editor guard during shutdown or target changes."""
    runtime.state.text_restore_timer_registered = False
    runtime.state.text_restore_guard = None
    safe_ops.unregister_timer(restore_text_after_ime_edit_key)


def restore_snapshot_is_current(snapshot: models.TextRestoreSnapshot) -> bool:
    """Reject stale or committed guards before they can roll text back."""
    if snapshot.commit_generation != runtime.state.text_ime_session.commit_generation:
        return False
    if (
        isinstance(snapshot.session, models.TextImeSession)
        and snapshot.session.committed
    ):
        return False
    current_session = text_state.active_text_session(snapshot.text)
    if current_session is not None and snapshot.session is not current_session:
        return False
    return True


def clear_matching_restore_guard(
    text_data: object,
    session: object,
    *,
    unregister_timer: bool = True,
) -> None:
    """Drop a restore guard once the same IME session has a real commit."""
    guard = runtime.state.text_restore_guard
    if (
        isinstance(guard, models.TextRestoreSnapshot)
        and text_state.same_text_data(guard.text, text_data)
        and (guard.session is None or guard.session is session)
    ):
        runtime.state.text_restore_guard = None
        runtime.state.text_restore_timer_registered = False
        if unregister_timer:
            safe_ops.unregister_timer(restore_text_after_ime_edit_key)


def mark_composition_committed(
    text_session: object,
    *,
    unregister_timer: bool = True,
) -> None:
    """Make stale preedit guards harmless as soon as IME confirms text."""
    if not isinstance(text_session, models.TextImeSession):
        return
    runtime.state.text_ime_session.mark_committed(text_session)
    clear_matching_restore_guard(
        text_session.text,
        text_session,
        unregister_timer=unregister_timer,
    )


def remember_possible_confirm_space_leak(hwnd: object, target: object) -> None:
    """Remember Text state before a Space that may belong to IME confirmation."""
    state = runtime.state.text_confirm_space_leak
    snapshot = state.snapshot
    target_text = text_state.text_data_from_target(target)
    if (
        isinstance(snapshot, models.TextRestoreSnapshot)
        and target_text is not None
        and text_state.same_text_data(snapshot.text, target_text)
        and (not state.hwnd or state.hwnd == _ptr_value(hwnd))
        and time.monotonic() <= state.until
    ):
        return

    snapshot = text_state.capture_restore_snapshot(target)
    if snapshot is None:
        return

    state.hwnd = _ptr_value(hwnd)
    state.snapshot = snapshot
    state.until = time.monotonic() + TEXT_CONFIRM_SPACE_LEAK_SECONDS


def clear_confirm_space_leak() -> None:
    """Drop the suspected confirmation-space snapshot."""
    runtime.state.text_confirm_space_leak.clear()


def ime_result_needs_space_leak_guard(text: str | None) -> bool:
    """Only committed IME text should be allowed to erase a leaked Space."""
    if not text:
        return False
    candidate = text[1:] if text.startswith(" ") else text
    return bool(candidate) and not candidate.isascii()


def _space_leak_snapshot_is_active(hwnd: object, target: object) -> bool:
    state = runtime.state.text_confirm_space_leak
    snapshot = state.snapshot
    if not isinstance(snapshot, models.TextRestoreSnapshot):
        return False
    if state.hwnd and state.hwnd != _ptr_value(hwnd):
        return False
    if time.monotonic() > state.until:
        clear_confirm_space_leak()
        return False
    target_text = text_state.text_data_from_target(target)
    active = target_text is not None and text_state.same_text_data(
        snapshot.text,
        target_text,
    )
    return active


def _body_after_single_space(snapshot: models.TextRestoreSnapshot) -> str | None:
    offsets = positions.text_selection_offsets(
        snapshot.body,
        snapshot.line,
        snapshot.column,
        snapshot.select_line,
        snapshot.select_column,
    )
    if offsets is None:
        return None
    start, end = offsets
    return snapshot.body[:start] + " " + snapshot.body[end:]


def _session_from_space_leak_snapshot(
    snapshot: models.TextRestoreSnapshot,
) -> models.TextImeSession | None:
    offsets = positions.text_selection_offsets(
        snapshot.body,
        snapshot.line,
        snapshot.column,
        snapshot.select_line,
        snapshot.select_column,
    )
    if offsets is None:
        return None
    start, end = offsets
    return models.TextImeSession(
        text=snapshot.text,
        body=snapshot.body,
        line=snapshot.line,
        column=snapshot.column,
        select_line=snapshot.select_line,
        select_column=snapshot.select_column,
        replace_start=start,
        replace_end=end,
    )


def consume_confirm_space_leak_session(
    hwnd: object,
    target: object,
    text: str | None,
) -> tuple[models.TextImeSession | None, str | None]:
    """Convert a just-leaked confirmation Space into a normal Text IME session."""
    if not _space_leak_snapshot_is_active(hwnd, target):
        return None, text
    if not ime_result_needs_space_leak_guard(text):
        clear_confirm_space_leak()
        return None, text

    state = runtime.state.text_confirm_space_leak
    snapshot = state.snapshot
    if not isinstance(snapshot, models.TextRestoreSnapshot):
        return None, text

    current_body = safe_ops.maybe_get_text_body(snapshot.text)
    expected_body = _body_after_single_space(snapshot)
    if current_body != expected_body:
        clear_confirm_space_leak()
        return None, text

    session = _session_from_space_leak_snapshot(snapshot)
    if session is None:
        clear_confirm_space_leak()
        return None, text

    clear_confirm_space_leak()
    normalized = text[1:] if text.startswith(" ") else text
    return session, normalized
