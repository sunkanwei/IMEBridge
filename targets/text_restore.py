"""Restore guards for Text Editor IME edit-key leaks."""

from ..core import models
from ..core import runtime
from ..core import safe_ops
from . import text_positions as positions
from . import text_state


TEXT_RESTORE_TIMER_INTERVAL = 0.02


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
