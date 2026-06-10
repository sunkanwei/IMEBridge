"""Keyboard guards that keep IME composition from editing Blender text directly."""

from collections.abc import Callable
import time

from . import ime_switch
from ..core import models
from ..core import runtime
from ..targets import text as text_target
from ..win32 import api as win32_api


SPACE_SUPPRESSION_SECONDS = 0.75
IME_ACTIVITY_SECONDS = 2.0


CompositionReader = Callable[[object, object, int], str | None]


def clear_space_suppression() -> None:
    """Forget any pending confirmation-space swallow."""
    runtime.state.space_suppression.clear()


def mark_space_suppression(hwnd: object) -> None:
    """Give the commit path a short grace period to eat Blender's stray space."""
    runtime.state.space_suppression.hwnd = win32_api.ptr_value(hwnd)
    runtime.state.space_suppression.until = time.monotonic() + SPACE_SUPPRESSION_SECONDS


def handle_space_suppression(
    win: object,
    hwnd: object,
    msg_value: int,
    w_value: int,
) -> int | None:
    """Catch the space that Windows sends after some IME commits."""
    state = runtime.state.space_suppression
    if not state.hwnd:
        return None
    if time.monotonic() > state.until:
        clear_space_suppression()
        return None
    if state.hwnd != win32_api.ptr_value(hwnd):
        return None

    if msg_value == win.WM_KEYDOWN and w_value == win.VK_SPACE:
        clear_space_suppression()
        return None

    if msg_value == win.WM_CHAR and w_value == win.VK_SPACE:
        return 0

    if msg_value == win.WM_KEYUP and w_value == win.VK_SPACE:
        clear_space_suppression()
        return 0

    return None


def mark_ime_activity(hwnd: object, seconds: float = IME_ACTIVITY_SECONDS) -> None:
    """Keep guards awake briefly after composition flags disappear."""
    runtime.state.ime_activity.hwnd = win32_api.ptr_value(hwnd)
    runtime.state.ime_activity.until = time.monotonic() + seconds


def clear_ime_activity() -> None:
    """Forget the recent IME activity marker."""
    runtime.state.ime_activity.clear()


def has_recent_ime_activity(hwnd: object) -> bool:
    """Some IMEs clear composition state before their final key messages arrive."""
    state = runtime.state.ime_activity
    if not state.hwnd or state.hwnd != win32_api.ptr_value(hwnd):
        return False
    if time.monotonic() > state.until:
        clear_ime_activity()
        return False
    return True


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
    """Ctrl and Alt chords belong to Blender or Windows, not to this guard."""
    control_down = bool(win.user32.GetKeyState(win.VK_CONTROL) & 0x8000)
    alt_down = bool(win.user32.GetKeyState(win.VK_MENU) & 0x8000)
    return control_down or alt_down


def is_preedit_vkey(value: int) -> bool:
    """Letters, digits, and common punctuation keys can feed IME preedit."""
    if 0x30 <= value <= 0x5A:
        return True
    if 0xBA <= value <= 0xC0:
        return True
    return 0xDB <= value <= 0xDF


def is_preedit_char(value: int) -> bool:
    """Printable ASCII chars are the usual leaked pinyin payload."""
    return 0x20 <= value <= 0x7E


def ime_can_accept_preedit_text(win: object, hwnd: object) -> bool:
    """Allow ASCII preedit guards only in an IME conversion mode that needs them."""
    if not ime_switch.is_open(win, hwnd):
        return False

    native_mode = ime_switch.is_native_conversion_mode(win, hwnd)
    if native_mode is None:
        return True
    return native_mode


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
    if not (models.is_text_editor_target(target) or models.is_font_edit_target(target)):
        return None
    return target


def ime_is_composing(
    win: object,
    hwnd: object,
    comp_string_reader: CompositionReader,
) -> bool:
    """Treat very recent IME traffic as still composing."""
    comp = comp_string_reader(win, hwnd, win.GCS_COMPSTR)
    recent = has_recent_ime_activity(hwnd)
    return bool(runtime.state.composition_target) or bool(comp) or recent


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


def handle_preedit_text_guard(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
) -> int | None:
    """Stop pinyin preedit keystrokes from becoming real Blender text."""
    if not is_keyboard_message(win, msg_value):
        return None
    if modifier_shortcut_is_down(win) or not ime_can_accept_preedit_text(win, hwnd):
        return None

    target = active_target_for_ime_guard()
    if not models.is_text_editor_target(target):
        return None

    value = win32_api.ptr_value(wparam)
    if msg_value == win.WM_CHAR and not is_preedit_char(value):
        return None
    if msg_value != win.WM_CHAR and not is_preedit_vkey(value):
        return None

    protect_text_target_from_ime_edit(target)
    win.imm32.ImmIsUIMessageW(hwnd, msg_value, wparam, lparam)
    return 0


def handle_font_space_confirm_guard(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    comp_string_reader: CompositionReader,
) -> int | None:
    """For 3D Text, space belongs to the IME until composition is finished."""
    if msg_value == win.WM_INPUT:
        raw = win32_api.read_raw_keyboard(win, lparam)
        if raw is None or raw["vkey"] != win.VK_SPACE:
            return None
        target = ime_edit_guard_target(win, hwnd, comp_string_reader)
        if models.is_font_edit_target(target):
            return 0
        return None

    if not is_keyboard_message(win, msg_value):
        return None

    if win32_api.ptr_value(wparam) != win.VK_SPACE:
        return None

    target = ime_edit_guard_target(win, hwnd, comp_string_reader)
    if not models.is_font_edit_target(target):
        return None

    win.imm32.ImmIsUIMessageW(hwnd, msg_value, wparam, lparam)
    return 0


def handle_raw_input_guard(
    win: object,
    hwnd: object,
    lparam: object,
    comp_string_reader: CompositionReader,
) -> int | None:
    """Raw input can reach Blender before translated IME messages do."""
    raw = win32_api.read_raw_keyboard(win, lparam)
    if raw is None:
        return None

    if raw["vkey"] not in ime_edit_guard_vkeys(win):
        return None

    target = ime_edit_guard_target(win, hwnd, comp_string_reader)
    if target is None:
        return None

    protect_text_target_from_ime_edit(target)
    return 0


def handle_ime_edit_key_guard(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    comp_string_reader: CompositionReader,
) -> int | None:
    """Let IMM32 consume navigation and deletion keys during composition."""
    w_value = win32_api.ptr_value(wparam)
    is_guarded_char = msg_value == win.WM_CHAR and w_value in {
        win.VK_BACK,
        win.VK_ESCAPE,
        0x7F,
    }
    if w_value not in ime_edit_guard_vkeys(win) and not is_guarded_char:
        return None

    target = ime_edit_guard_target(win, hwnd, comp_string_reader)
    if target is None:
        return None

    if msg_value in {
        win.WM_IME_KEYDOWN,
        win.WM_IME_KEYUP,
        win.WM_KEYDOWN,
        win.WM_KEYUP,
        win.WM_CHAR,
    }:
        protect_text_target_from_ime_edit(target)
        win.imm32.ImmIsUIMessageW(hwnd, msg_value, wparam, lparam)
        return 0

    return None


def handle_message_guards(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    comp_string_reader: CompositionReader,
) -> int | None:
    """Run the keyboard shields before normal IME dispatch."""
    font_space_result = handle_font_space_confirm_guard(
        win,
        hwnd,
        msg_value,
        wparam,
        lparam,
        comp_string_reader,
    )
    if font_space_result is not None:
        return font_space_result

    if msg_value == win.WM_INPUT:
        raw_result = handle_raw_input_guard(win, hwnd, lparam, comp_string_reader)
        if raw_result is not None:
            return raw_result

    edit_result = handle_ime_edit_key_guard(
        win,
        hwnd,
        msg_value,
        wparam,
        lparam,
        comp_string_reader,
    )
    if edit_result is not None:
        return edit_result

    preedit_result = handle_preedit_text_guard(
        win,
        hwnd,
        msg_value,
        wparam,
        lparam,
    )
    if preedit_result is not None:
        return preedit_result

    return handle_space_suppression(
        win,
        hwnd,
        msg_value,
        win32_api.ptr_value(wparam),
    )
