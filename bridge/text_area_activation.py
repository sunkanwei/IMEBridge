"""Delayed Text Editor target activation after header actions change text."""

from . import input_scope
from . import message_scope
from ..core import runtime
from ..core import safe_ops
from ..targets import detect as targets
from ..platforms import native as platform_api


TEXT_AREA_ACTIVATION_INTERVAL = 0.02
TEXT_AREA_ACTIVATION_RETRY_LIMIT = 20


def text_datablock_key(text_data: object) -> int:
    """Return a stable key for detecting Text Editor datablock changes."""
    if text_data is None:
        return 0
    try:
        return platform_api.ptr_value(text_data.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0


def text_target_from_area_hit(hit: input_scope.AreaHit) -> object | None:
    """Build a Text Editor target from a remembered area hit."""
    try:
        return targets.make_text_editor_target(
            hit.window,
            hit.area,
            hit.region,
            hit.space,
        )
    except (AttributeError, ReferenceError, RuntimeError):
        return None


def activate_text_area_hit(hit: input_scope.AreaHit, hwnd: object) -> bool:
    """Activate a Text Editor area after Blender finishes a header action."""
    target = text_target_from_area_hit(hit)
    if not targets.is_usable_input_target(target):
        return False

    message_scope.cancel_pending_scope_application()
    message_scope.apply_input_scope(
        input_scope.InputScope(
            input_scope.SCOPE_ENABLED_TARGET,
            hwnd=hwnd,
            target=target,
            hit=hit,
        )
    )
    return True


def pending_text_area_key() -> int:
    """Read the current text key for the pending Text Editor area."""
    hit = runtime.state.text_area_activation.hit
    if hit is None:
        return 0
    try:
        return text_datablock_key(getattr(hit.space, "text", None))
    except (AttributeError, ReferenceError, RuntimeError):
        return 0


def try_activate_pending_text_area(
    hwnd: object = None,
    *,
    unregister_timer: bool = True,
) -> bool:
    """Promote a header-created Text datablock into an active IME target."""
    state = runtime.state.text_area_activation
    hit = state.hit
    if hit is None:
        return False

    current_key = pending_text_area_key()
    if not current_key or current_key == state.previous_text_key:
        return False

    if not activate_text_area_hit(hit, hwnd or state.hwnd):
        return False

    state.clear()
    if unregister_timer:
        safe_ops.unregister_timer(_apply_pending_text_area_activation)
    return True


def _apply_pending_text_area_activation() -> float | None:
    """Wait briefly for Text Editor header actions to update space.text."""
    state = runtime.state.text_area_activation
    if not state.timer_registered:
        return None

    if try_activate_pending_text_area(unregister_timer=False):
        return None

    state.attempts += 1
    if state.attempts >= TEXT_AREA_ACTIVATION_RETRY_LIMIT:
        state.clear()
        return None
    return TEXT_AREA_ACTIVATION_INTERVAL


def schedule_text_area_activation(
    hwnd: object,
    hit: input_scope.AreaHit,
) -> bool:
    """Remember a Text Editor area while Blender creates or switches text."""
    previous_key = text_datablock_key(getattr(hit.space, "text", None))
    state = runtime.state.text_area_activation
    state.hwnd = hwnd
    state.hit = hit
    state.previous_text_key = previous_key
    state.attempts = 0

    if state.timer_registered:
        return True
    if safe_ops.register_timer(
        _apply_pending_text_area_activation,
        first_interval=TEXT_AREA_ACTIVATION_INTERVAL,
    ):
        state.timer_registered = True
        return True

    state.clear()
    return False


def maybe_schedule_text_area_activation(
    hwnd: object,
    lparam: object,
    scope: input_scope.InputScope,
    allow_activation: bool,
) -> bool:
    """Track Text Editor header clicks that may create a new text target."""
    if not allow_activation or scope.kind != input_scope.SCOPE_NEUTRAL:
        cancel_pending_text_area_activation()
        return False

    hit = input_scope.text_editor_area_from_mouse_lparam(hwnd, lparam)
    if hit is None:
        cancel_pending_text_area_activation()
        return False

    return schedule_text_area_activation(hwnd, hit)


def cancel_pending_text_area_activation() -> None:
    """Drop delayed Text Editor activation work."""
    runtime.state.text_area_activation.clear()
    safe_ops.unregister_timer(_apply_pending_text_area_activation)
