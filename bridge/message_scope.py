"""Mouse-driven input scope state transitions for the native message router."""

import bpy

from . import arming
from . import font_commit
from . import ime_context
from . import ime_guards
from . import ime_switch
from . import input_scope
from ..core import models
from ..core import runtime
from ..core import safe_ops
from ..preferences import config
from ..targets import detect as targets
from ..targets import state as target_state
from ..targets import text as text_target


INPUT_SCOPE_TIMER_INTERVAL = 0.01


def set_current_scope(scope: input_scope.InputScope) -> None:
    """Store the last resolved Blender editor scope in one place."""
    runtime.state.input_scope.current_kind = scope.kind
    runtime.state.input_scope.current_area_type = input_scope.scope_area_type(scope)


def set_neutral_scope() -> None:
    """Leave bridge-owned input without making a new Blender area claim."""
    runtime.state.input_scope.current_kind = input_scope.SCOPE_NEUTRAL
    runtime.state.input_scope.current_area_type = ""


def clear_native_text_ui_handoff() -> None:
    """Release the temporary handoff to Blender's own text fields."""
    runtime.state.input_scope.native_text_ui_handoff = False


def target_area_type(target: object) -> str:
    """Read the editor type from a resolved bridge target."""
    area = getattr(target, "area", None)
    return str(getattr(area, "type", "") or "")


def recent_font_target_from_state() -> object | None:
    """Keep a just-committed 3D Text target through late IME messages."""
    target = runtime.state.composition_target or runtime.state.active_target
    if not models.is_font_edit_target(target):
        return None
    if not font_commit.is_recent_font_target(target):
        return None
    if targets.active_font_edit_object() != getattr(target, "obj", None):
        return None
    return target


def clear_bridge_target_state() -> None:
    """Forget only the target state owned by IMEBridge."""
    target_state.clear_active_target()
    runtime.state.composition_target = None
    runtime.state.text_ime_session.clear()
    ime_guards.clear_ime_confirm_space()
    ime_guards.clear_hidden_text_ime_activity()
    ime_guards.clear_ime_direct_ascii()
    text_target.cancel_restore_guard()
    text_target.clear_confirm_space_leak()
    text_target.cancel_tab_indent()
    runtime.state.font_result_dedup.clear()


def apply_enabled_scope(scope: input_scope.InputScope) -> None:
    """Restore IMEBridge input for a supported Text or 3D Text target."""
    if not targets.is_usable_input_target(scope.target):
        return
    target_state.set_active_target(scope.target)
    ime_switch.restore_if_managed(scope.hwnd)
    arming.request_auto_arm()
    ime_context.update_ime_candidate_position(hwnd=scope.hwnd, target=scope.target)


def apply_shortcut_scope(scope: input_scope.InputScope) -> None:
    """Close the IME where Blender expects direct shortcut keystrokes."""
    if refresh_scope_from_context(scope.hwnd):
        return

    clear_bridge_target_state()
    if config.auto_english_on_shortcuts():
        ime_switch.close_for_shortcut_surface(scope.hwnd)


def apply_neutral_scope(scope: input_scope.InputScope) -> None:
    """Step away from bridge-owned targets without touching native UI fields."""
    clear_bridge_target_state()
    ime_switch.restore_if_managed(scope.hwnd)


def apply_input_scope(scope: input_scope.InputScope) -> None:
    """Apply the latest click scope after Blender focus has settled."""
    set_current_scope(scope)
    if scope.kind == input_scope.SCOPE_ENABLED_TARGET:
        apply_enabled_scope(scope)
    elif scope.kind == input_scope.SCOPE_SHORTCUT_SURFACE:
        apply_shortcut_scope(scope)
    else:
        apply_neutral_scope(scope)


def _apply_pending_input_scope() -> None:
    """Timer callback used to keep native hooks out of heavier Blender work."""
    if not runtime.state.input_scope.scope_timer_registered:
        return None
    runtime.state.input_scope.scope_timer_registered = False

    scope = runtime.state.input_scope.pending_scope
    runtime.state.input_scope.pending_scope = None
    if scope is not None:
        apply_input_scope(scope)
    return None


def schedule_input_scope_application(scope: input_scope.InputScope) -> None:
    """Apply only the newest click when several arrive in quick succession."""
    runtime.state.input_scope.pending_scope = scope
    if runtime.state.input_scope.scope_timer_registered:
        return
    if safe_ops.register_timer(
        _apply_pending_input_scope,
        first_interval=INPUT_SCOPE_TIMER_INTERVAL,
    ):
        runtime.state.input_scope.scope_timer_registered = True


def cancel_pending_scope_application() -> None:
    """Drop delayed click-scope work without touching other timers."""
    runtime.state.input_scope.pending_scope = None
    runtime.state.input_scope.scope_timer_registered = False
    safe_ops.unregister_timer(_apply_pending_input_scope)


def scope_target_from_context() -> object | None:
    """Catch mode changes such as Tab entering 3D Text edit mode."""
    current_kind = runtime.state.input_scope.current_kind
    current_area_type = runtime.state.input_scope.current_area_type

    if (
        current_kind == input_scope.SCOPE_SHORTCUT_SURFACE
        and current_area_type == "VIEW_3D"
    ):
        return targets.find_font_edit_target(bpy.context)

    if current_kind != input_scope.SCOPE_SHORTCUT_SURFACE:
        return targets.make_input_target_from_context(bpy.context)

    return None


def refresh_scope_from_context(hwnd: object) -> bool:
    """Promote a stale shortcut scope when Blender now has a text target."""
    if runtime.state.input_scope.native_text_ui_handoff:
        return False

    target = scope_target_from_context()
    if target is None:
        target = recent_font_target_from_state()
    if not targets.is_usable_input_target(target):
        return False

    runtime.state.input_scope.current_kind = input_scope.SCOPE_ENABLED_TARGET
    runtime.state.input_scope.current_area_type = target_area_type(target)
    target_state.set_active_target(target)
    ime_switch.restore_if_managed(hwnd)
    return True
