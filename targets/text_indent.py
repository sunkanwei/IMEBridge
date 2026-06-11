"""Deferred Text Editor indentation after IME-related Tab suppression."""

import bpy

from ..core import models
from ..core import runtime
from ..core import safe_ops
from . import detect as targets
from . import text_state


TEXT_TAB_INDENT_TIMER_INTERVAL = 0.0


def indent_once(target: object) -> bool:
    """Run Blender's plain Text indent operator for one suppressed Tab."""
    if not models.is_text_editor_target(target):
        return False

    context = targets.target_context(target)
    if context is None or context["space"] is None:
        return False
    if getattr(context["space"], "text", None) != text_state.text_data_from_target(
        target,
    ):
        return False

    try:
        with bpy.context.temp_override(
            window=context["window"],
            screen=context["screen"],
            area=context["area"],
            region=context["region"],
            space_data=context["space"],
        ):
            if bpy.ops.text.indent.poll():
                bpy.ops.text.indent()
                return True
    except (AttributeError, ReferenceError, RuntimeError):
        return False
    return False


def flush_tab_indent_queue() -> None:
    """Apply any Tab presses that were diverted away from autocomplete."""
    state = runtime.state.tab_indent
    state.timer_registered = False
    target = state.target
    count = state.count
    state.target = None
    state.count = 0

    for _index in range(count):
        if not indent_once(target):
            break
    return None


def schedule_tab_indent(target: object) -> bool:
    """Queue one plain indent action after suppressing Unicode autocomplete."""
    state = runtime.state.tab_indent
    state.target = target
    state.count += 1
    if state.timer_registered:
        return True

    if safe_ops.register_timer(
        flush_tab_indent_queue,
        first_interval=TEXT_TAB_INDENT_TIMER_INTERVAL,
    ):
        state.timer_registered = True
        return True

    state.count = max(0, state.count - 1)
    if state.count == 0:
        state.target = None
    return False


def cancel_tab_indent() -> None:
    """Drop pending autocomplete-safe Tab indentation."""
    runtime.state.tab_indent.clear()
    safe_ops.unregister_timer(flush_tab_indent_queue)
