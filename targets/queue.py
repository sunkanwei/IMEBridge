"""Main-thread queue for committed IME text."""

from ..core import models
from ..core import runtime
from ..core import safe_ops
from . import font as font_target
from . import text as text_target


PENDING_INSERT_TIMER_INTERVAL = 0.01
SOURCE_IME_RESULT = "ime_result"
SOURCE_FONT_CHAR = "font_char"


def flush() -> None:
    """Blender operators are safer from the timer than from WndProc."""
    try:
        while runtime.state.pending_inserts:
            item = runtime.state.pending_inserts.popleft()
            try:
                flush_one(item)
            except (AttributeError, ReferenceError, RuntimeError, ValueError):
                continue
    finally:
        runtime.state.insert_timer_registered = False
    return None


def flush_one(item: models.PendingInsert) -> None:
    """Commit one queued item while keeping the outer queue alive."""
    inserted = False

    if models.is_text_editor_target(item.target):
        inserted = text_target.insert(
            item.text,
            item.target,
            item.text_session,
        )
    elif models.is_font_edit_target(item.target):
        if item.source == SOURCE_FONT_CHAR:
            from ..bridge import font_commit

            if font_commit.is_recent_font_result_char(item.target, item.text):
                return
        inserted = font_target.insert(item.text, item.target)

    if not inserted:
        return

    if models.is_font_edit_target(item.target):
        from ..bridge import font_commit

        font_commit.mark_recent_font_result(item.target, item.text)

    if item.suppress_space and item.hwnd:
        from ..bridge import ime_guards

        ime_guards.mark_space_suppression(item.hwnd)


def queue(
    text: str,
    target: object,
    text_session: object = None,
    *,
    hwnd: object = None,
    source: str = "",
    suppress_space: bool = False,
) -> None:
    """Defer an IME commit until Blender operators are safe to call."""
    if not text:
        return
    if target is None:
        return

    runtime.state.pending_inserts.append(
        models.PendingInsert(
            text,
            target,
            text_session,
            hwnd=hwnd,
            source=source,
            suppress_space=suppress_space,
        )
    )
    if not runtime.state.insert_timer_registered:
        if safe_ops.register_timer(
            flush,
            first_interval=PENDING_INSERT_TIMER_INTERVAL,
        ):
            runtime.state.insert_timer_registered = True


def cancel() -> None:
    """Drop pending commits during unregister or hook shutdown."""
    runtime.state.pending_inserts.clear()
    runtime.state.insert_timer_registered = False
    safe_ops.unregister_timer(flush)
