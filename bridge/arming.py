"""Delayed re-arming after Blender focus and area changes."""

import bpy

from ..core import runtime
from ..core import safe_ops
from ..targets import detect as targets


def request_auto_arm() -> None:
    """Re-arm on the next timer tick, after Blender has settled focus."""
    if runtime.state.auto_arm_timer_registered:
        return
    runtime.state.auto_arm_timer_registered = True
    bpy.app.timers.register(_auto_arm_input, first_interval=0.0)


def cancel_auto_arm() -> None:
    """Drop pending re-arm work during reload or shutdown."""
    runtime.state.auto_arm_timer_registered = False
    safe_ops.unregister_timer(_auto_arm_input)


def _auto_arm_input() -> None:
    """Refresh IME state for the target Blender just focused."""
    if not runtime.state.auto_arm_timer_registered:
        return None
    runtime.state.auto_arm_timer_registered = False

    target = runtime.state.active_target
    if not targets.is_supported_input_target(target):
        return None

    from . import hook
    from . import ime_context

    ime_context.restore_ime_contexts()
    hook.start_hooks(insert_on_commit=True)
    ime_context.update_ime_candidate_position(target=target)
    return None
