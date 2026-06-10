"""Delayed re-arming after Blender focus and area changes."""

from ..core import runtime
from ..core import safe_ops
from ..platforms import native as platform_api
from ..targets import detect as targets


def request_auto_arm() -> None:
    """Re-arm on the next timer tick, after Blender has settled focus."""
    if runtime.state.auto_arm_timer_registered:
        return
    if safe_ops.register_timer(_auto_arm_input, first_interval=0.0):
        runtime.state.auto_arm_timer_registered = True


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
    if not targets.is_usable_input_target(target):
        return None

    from . import hook
    from . import ime_context

    if platform_api.backend_name() == "macos":
        from . import macos_event_bridge

        macos_event_bridge.start(insert_on_commit=True)
        ime_context.update_ime_candidate_position(target=target)
        return None

    ime_context.restore_ime_contexts()
    hook.start_hooks(insert_on_commit=True)
    ime_context.update_ime_candidate_position(target=target)
    return None
