"""Guard preedit, navigation, and deletion keys owned by the IME."""

from . import ime_guard_common as common
from . import ime_switch
from ..core import models
from ..platforms import native as platform_api


def is_preedit_vkey(value: int) -> bool:
    """Letters, digits, and common punctuation keys can feed IME preedit."""
    if 0x30 <= value <= 0x5A:
        return True
    if 0xBA <= value <= 0xC0:
        return True
    return 0xDB <= value <= 0xDF


def is_preedit_char(value: int) -> bool:
    """Printable non-space ASCII chars are the usual leaked pinyin payload."""
    return 0x21 <= value <= 0x7E


def ime_can_accept_preedit_text(win: object, hwnd: object) -> bool:
    """Allow ASCII preedit guards only in an IME conversion mode that needs them."""
    if not ime_switch.is_open(win, hwnd):
        return False

    native_mode = ime_switch.is_native_conversion_mode(win, hwnd)
    if native_mode is None:
        return True
    return native_mode


def handle_preedit_text_guard(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
) -> int | None:
    """Stop pinyin preedit keystrokes from becoming real Blender text."""
    if not common.is_keyboard_message(win, msg_value):
        return None
    if common.modifier_shortcut_is_down(win) or not ime_can_accept_preedit_text(
        win,
        hwnd,
    ):
        return None

    target = common.active_target_for_ime_guard()
    if not models.is_text_editor_target(target):
        return None

    value = platform_api.ptr_value(wparam)
    if msg_value == win.WM_CHAR and not is_preedit_char(value):
        return None
    if msg_value != win.WM_CHAR and not is_preedit_vkey(value):
        return None

    common.protect_text_target_from_ime_edit(target)
    win.imm32.ImmIsUIMessageW(hwnd, msg_value, wparam, lparam)
    return 0


def handle_raw_input_guard(
    win: object,
    hwnd: object,
    lparam: object,
    comp_string_reader: common.CompositionReader,
) -> int | None:
    """Raw input can reach Blender before translated IME messages do."""
    raw = platform_api.read_raw_keyboard(win, lparam)
    if raw is None:
        return None

    if raw["vkey"] not in common.ime_edit_guard_vkeys(win):
        return None

    target = common.ime_edit_guard_target(win, hwnd, comp_string_reader)
    if target is None:
        return None

    common.protect_text_target_from_ime_edit(target)
    return 0


def handle_ime_edit_key_guard(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    comp_string_reader: common.CompositionReader,
) -> int | None:
    """Let the native IME consume navigation and deletion keys during composition."""
    w_value = platform_api.ptr_value(wparam)
    is_guarded_char = msg_value == win.WM_CHAR and w_value in {
        win.VK_BACK,
        win.VK_ESCAPE,
        0x7F,
    }
    if w_value not in common.ime_edit_guard_vkeys(win) and not is_guarded_char:
        return None

    target = common.ime_edit_guard_target(win, hwnd, comp_string_reader)
    if target is None:
        return None

    if msg_value in {
        win.WM_IME_KEYDOWN,
        win.WM_IME_KEYUP,
        win.WM_KEYDOWN,
        win.WM_KEYUP,
        win.WM_CHAR,
    }:
        common.protect_text_target_from_ime_edit(target)
        win.imm32.ImmIsUIMessageW(hwnd, msg_value, wparam, lparam)
        return 0

    return None
