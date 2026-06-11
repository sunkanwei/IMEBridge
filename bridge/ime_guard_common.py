"""Shared predicates for IME keyboard guard modules."""

from collections.abc import Callable

from ..core import models
from ..core import runtime
from ..targets import detect as targets
from ..targets import text as text_target


CompositionReader = Callable[[object, object, int], str | None]


def is_keyboard_message(win: object, msg_value: int) -> bool:
    """Small local predicate for the keyboard messages we care about."""
    return msg_value in {
        win.WM_IME_KEYDOWN,
        win.WM_IME_KEYUP,
        win.WM_KEYDOWN,
        win.WM_KEYUP,
        win.WM_CHAR,
    }


def modifier_shortcut_is_down(win: object) -> bool:
    """Ctrl and Alt chords belong to Blender or the system, not to this guard."""
    control_down = bool(win.user32.GetKeyState(win.VK_CONTROL) & 0x8000)
    alt_down = bool(win.user32.GetKeyState(win.VK_MENU) & 0x8000)
    return control_down or alt_down


def ime_edit_guard_vkeys(win: object) -> set[int]:
    """Keys that should edit the IME preedit string, not Blender's buffer."""
    return {
        win.VK_BACK,
        win.VK_DELETE,
        win.VK_LEFT,
        win.VK_RIGHT,
        win.VK_UP,
        win.VK_DOWN,
        win.VK_HOME,
        win.VK_END,
        win.VK_PRIOR,
        win.VK_NEXT,
        win.VK_ESCAPE,
    }


def active_target_for_ime_guard() -> object | None:
    """Pick the target currently at risk from IME edit keys."""
    target = runtime.state.composition_target or runtime.state.active_target
    if not targets.is_usable_input_target(target):
        return None
    return target


def ime_is_composing(
    win: object,
    hwnd: object,
    comp_string_reader: CompositionReader,
) -> bool:
    """Return whether the IME is currently composing."""
    comp = comp_string_reader(win, hwnd, win.GCS_COMPSTR)
    return bool(runtime.state.composition_target) or bool(comp)


def ime_edit_guard_target(
    win: object,
    hwnd: object,
    comp_string_reader: CompositionReader,
) -> object | None:
    """Expose a target to guards only while the IME owns the keystrokes."""
    target = active_target_for_ime_guard()
    if target is None or not ime_is_composing(win, hwnd, comp_string_reader):
        return None
    return target


def protect_text_target_from_ime_edit(target: object) -> None:
    """Snapshot the Text Editor before swallowing an edit key."""
    if models.is_text_editor_target(target):
        text_target.schedule_restore_guard(target)
