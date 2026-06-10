"""Lifecycle helpers for automatically enabling the IME bridge."""

import bpy

from . import arming
from . import hook
from . import ime_context
from ..core import runtime
from ..core import safe_ops
from ..platforms import native as platform_api
from ..targets import detect as targets
from ..targets import queue as insert_queue
from ..targets import state as target_state
from ..targets import text as text_target


AUTO_ENABLE_RETRY_LIMIT = 20
AUTO_ENABLE_RETRY_INTERVAL = 0.5


def initialize_input_bridge(context: object = None) -> tuple[int, int]:
    """Bring the bridge online for the current Blender UI state."""
    context = context or bpy.context
    target = targets.make_input_target_from_context(context)
    if target is None:
        target = targets.find_font_edit_target(context)
    if target is None and platform_api.backend_name() == "macos":
        target = targets.find_text_editor_target(context)
    if target is not None:
        target_state.set_active_target(target)

    if platform_api.backend_name() == "macos":
        from . import macos_event_bridge

        started = macos_event_bridge.start(insert_on_commit=True)
        if target is not None:
            ime_context.update_ime_candidate_position(target=target)
        return 0, started

    restored = ime_context.restore_ime_contexts()
    hooked = hook.start_hooks(insert_on_commit=True)
    if target is not None:
        ime_context.update_ime_candidate_position(target=target)
    return restored, hooked


def _auto_enable_timer() -> float | None:
    """Blender may not have its native windows ready on the first tick."""
    if not runtime.state.auto_enable_timer_registered:
        return None
    runtime.state.auto_enable_timer_registered = False
    if bpy.app.background or not platform_api.supports_native_bridge():
        runtime.state.auto_enable_attempts = 0
        return None

    initialize_input_bridge()
    if runtime.state.hooks or _macos_bridge_running():
        runtime.state.auto_enable_attempts = 0
        return None

    runtime.state.auto_enable_attempts += 1
    if runtime.state.auto_enable_attempts <= AUTO_ENABLE_RETRY_LIMIT:
        runtime.state.auto_enable_timer_registered = True
        return AUTO_ENABLE_RETRY_INTERVAL

    runtime.state.auto_enable_attempts = 0
    return None


def schedule_auto_enable(first_interval: float = 0.1) -> None:
    """Start the bridge lazily after Blender finishes building the UI."""
    if (
        bpy.app.background
        or not platform_api.supports_native_bridge()
        or runtime.state.auto_enable_timer_registered
    ):
        return
    if safe_ops.register_timer(_auto_enable_timer, first_interval=first_interval):
        runtime.state.auto_enable_timer_registered = True


def cancel_auto_enable() -> None:
    """Stop pending auto-enable work during reload or shutdown."""
    runtime.state.auto_enable_timer_registered = False
    runtime.state.auto_enable_attempts = 0
    safe_ops.unregister_timer(_auto_enable_timer)
    arming.cancel_auto_arm()


def _macos_bridge_running() -> bool:
    """Check the macOS bridge only when that backend is selected."""
    if platform_api.backend_name() != "macos":
        return False
    from . import macos_event_bridge

    return macos_event_bridge.is_running()


def stop_hooks() -> int:
    """Public lifecycle exit for hooks and deferred text work."""
    arming.cancel_auto_arm()
    from . import message_router

    stopped_macos = 0
    if platform_api.backend_name() == "macos":
        from . import macos_event_bridge

        stopped_macos = macos_event_bridge.stop()

    message_router.cancel_pending_input_scope()
    insert_queue.cancel()
    text_target.cancel_restore_guard()
    return stopped_macos + hook.stop_hooks()
