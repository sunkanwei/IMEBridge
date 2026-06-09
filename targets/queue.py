"""Main-thread queue for committed IME text."""

import bpy

from ..core import models
from ..core import runtime
from ..core import safe_ops
from . import detect as targets
from . import font as font_target
from . import text as text_target


PENDING_INSERT_TIMER_INTERVAL = 0.01


def flush() -> None:
    """Blender operators are safer from the timer than from WndProc."""
    try:
        while runtime.state.pending_inserts:
            item = runtime.state.pending_inserts.popleft()
            inserted = False

            if models.is_text_editor_target(item.target):
                inserted = text_target.insert(
                    item.text,
                    item.target,
                    item.text_session,
                )
            elif models.is_font_edit_target(item.target):
                inserted = font_target.insert(item.text, item.target)

            if (
                not inserted
                and models.is_font_edit_target(item.target)
                and targets.active_font_edit_object() is not None
            ):
                fallback_target = targets.find_font_edit_target()
                font_target.insert(item.text, fallback_target)
    finally:
        runtime.state.insert_timer_registered = False
    return None


def queue(text: str, target: object, text_session: object = None) -> None:
    """Defer an IME commit until Blender operators are safe to call."""
    if not text:
        return
    if target is None:
        target = targets.find_font_edit_target()
    if target is None:
        return

    runtime.state.pending_inserts.append(
        models.PendingInsert(text, target, text_session)
    )
    if not runtime.state.insert_timer_registered:
        runtime.state.insert_timer_registered = True
        bpy.app.timers.register(
            flush,
            first_interval=PENDING_INSERT_TIMER_INTERVAL,
        )


def cancel() -> None:
    """Drop pending commits during unregister or hook shutdown."""
    runtime.state.pending_inserts.clear()
    runtime.state.insert_timer_registered = False
    safe_ops.unregister_timer(flush)
