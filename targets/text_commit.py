"""Text Editor IME commit transactions."""

import bpy

from ..core import models
from ..core import runtime
from ..core import safe_ops
from . import detect as targets
from . import text_positions as positions
from . import text_restore
from . import text_state


def restore_composition_baseline(
    target: object,
    text_session: object,
) -> bool:
    """Restore the pre-composition body and selection."""
    text_data = text_state.session_text_data(target, text_session)
    if text_data is None:
        return False

    current_body = safe_ops.maybe_get_text_body(text_data)
    if current_body is None:
        return False
    if current_body != text_session.body:
        return text_state.restore_text_body(
            text_data,
            text_session.body,
            text_session.line,
            text_session.column,
            text_session.select_line,
            text_session.select_column,
        )
    return text_state.set_text_selection(
        text_data,
        text_session.line,
        text_session.column,
        text_session.select_line,
        text_session.select_column,
    )


def _text_session_body_after_single_space(
    text_session: models.TextImeSession,
) -> str:
    """Return the body shape left by a leaked confirmation Space."""
    start, end = text_session_replacement_offsets(text_session)
    return text_session.body[:start] + " " + text_session.body[end:]


def _restore_guard_matches_session(text_session: models.TextImeSession) -> bool:
    """Return whether a dirty body is protected by the IME edit-key guard."""
    guard = runtime.state.text_restore_guard
    return (
        isinstance(guard, models.TextRestoreSnapshot)
        and guard.session is text_session
        and guard.body == text_session.body
        and guard.commit_generation == runtime.state.text_ime_session.commit_generation
    )


def _text_session_body_is_safe_to_restore(
    text_session: models.TextImeSession,
    current_body: str,
) -> bool:
    """Reject real edits that happened after the IME session was captured."""
    if current_body == text_session.body:
        return True
    if current_body == _text_session_body_after_single_space(text_session):
        return True
    return _restore_guard_matches_session(text_session)


def text_session_replacement_offsets(
    text_session: models.TextImeSession,
) -> tuple[int, int]:
    """Clamp a session replacement range to its saved body."""
    body_length = len(text_session.body)
    start = max(0, min(int(text_session.replace_start), body_length))
    end = max(0, min(int(text_session.replace_end), body_length))
    return min(start, end), max(start, end)


def text_session_commit_result(
    text_session: models.TextImeSession,
    text: str,
) -> tuple[str, int, int]:
    """Return the committed body and collapsed cursor for an IME session."""
    start, end = text_session_replacement_offsets(text_session)
    new_body = text_session.body[:start] + text + text_session.body[end:]
    line, column = positions.text_offset_to_position(new_body, start + len(text))
    return new_body, line, column


def insert_text_session_result(
    target: object,
    text: str,
    text_session: object,
    *,
    use_operator: bool,
) -> bool:
    """Commit text by applying the session's saved replacement range."""
    text_data = text_state.session_text_data(target, text_session)
    if text_data is None:
        return False
    current_body = safe_ops.maybe_get_text_body(text_data)
    if current_body is None:
        return False

    expected_body, cursor_line, cursor_column = text_session_commit_result(
        text_session,
        text,
    )
    safe_to_restore = _text_session_body_is_safe_to_restore(
        text_session,
        current_body,
    )
    text_restore.mark_composition_committed(text_session)

    if not safe_to_restore:
        if use_operator:
            try:
                if bpy.ops.text.insert.poll():
                    bpy.ops.text.insert(text=text)
                    if safe_ops.maybe_get_text_body(text_data) != current_body:
                        return True
            except (AttributeError, ReferenceError, RuntimeError):
                pass
        return text_state.insert_text_body_at_cursor(text_data, text)

    if use_operator and restore_composition_baseline(target, text_session):
        try:
            if bpy.ops.text.insert.poll():
                bpy.ops.text.insert(text=text)
                if safe_ops.maybe_get_text_body(text_data) == expected_body:
                    return text_state.set_text_cursor(
                        text_data,
                        cursor_line,
                        cursor_column,
                    )
        except (AttributeError, ReferenceError, RuntimeError):
            pass

    return text_state.restore_text_body(
        text_data,
        expected_body,
        cursor_line,
        cursor_column,
    )


def insert(text: str, target: object, text_session: object = None) -> bool:
    """Commit IME text through Blender's Text Editor operator."""
    text_data = text_state.text_data_from_target(target)
    if text_data is None:
        return False

    context = targets.target_context(target)
    if context is None or context["space"] is None:
        return False
    if getattr(context["space"], "text", None) != text_data:
        return False

    with bpy.context.temp_override(
        window=context["window"],
        screen=context["screen"],
        area=context["area"],
        region=context["region"],
        space_data=context["space"],
    ):
        if isinstance(text_session, models.TextImeSession):
            return insert_text_session_result(
                target,
                text,
                text_session,
                use_operator=True,
            )

        if bpy.ops.text.insert.poll():
            bpy.ops.text.insert(text=text)
            return True

    try:
        if isinstance(text_session, models.TextImeSession):
            return insert_text_session_result(
                target,
                text,
                text_session,
                use_operator=False,
            )
        return text_state.insert_text_body_at_cursor(text_data, text)
    except (AttributeError, ReferenceError, RuntimeError):
        return False
