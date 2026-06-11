"""Keyboard guards that keep IME composition from editing Blender text directly."""

from collections.abc import Callable
import time

from . import ime_switch
from ..core import models
from ..core import runtime
from ..targets import detect as targets
from ..targets import text as text_target
from ..platforms import native as platform_api


SPACE_CONFIRM_STALE_SECONDS = 2.0
SPACE_EVENT_DOWN = "down"
SPACE_EVENT_UP = "up"
SPACE_EVENT_CHAR = "char"


CompositionReader = Callable[[object, object, int], str | None]


def clear_ime_confirm_space() -> None:
    """Forget any pending IME-owned Space key sequence."""
    runtime.state.ime_confirm_space.clear()


def refresh_ime_confirm_space(hwnd: object) -> None:
    """Keep the current confirmation Space sequence alive briefly."""
    state = runtime.state.ime_confirm_space
    state.hwnd = platform_api.ptr_value(hwnd)
    state.until = time.monotonic() + SPACE_CONFIRM_STALE_SECONDS


def ime_confirm_space_is_active(hwnd: object) -> bool:
    """Return whether this window still owns a confirmation Space sequence."""
    state = runtime.state.ime_confirm_space
    if not state.hwnd:
        return False
    if time.monotonic() > state.until:
        clear_ime_confirm_space()
        return False
    return state.hwnd == platform_api.ptr_value(hwnd)


def space_event_kind(
    win: object,
    msg_value: int,
    wparam: object,
    lparam: object,
) -> str:
    """Classify Space messages without treating time as the source of truth."""
    if msg_value == win.WM_INPUT:
        raw = platform_api.read_raw_keyboard(win, lparam)
        if raw is None or raw["vkey"] != win.VK_SPACE:
            return ""
        return SPACE_EVENT_DOWN if raw["key_down"] else SPACE_EVENT_UP

    if not is_keyboard_message(win, msg_value):
        return ""
    if platform_api.ptr_value(wparam) != win.VK_SPACE:
        return ""
    if msg_value in {win.WM_KEYUP, win.WM_IME_KEYUP}:
        return SPACE_EVENT_UP
    if msg_value == win.WM_CHAR:
        return SPACE_EVENT_CHAR
    return SPACE_EVENT_DOWN


def feed_ime_keyboard_message(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
) -> None:
    """Forward translated Space messages to IMM while raw input stays local."""
    if msg_value != win.WM_INPUT:
        win.imm32.ImmIsUIMessageW(hwnd, msg_value, wparam, lparam)


def handle_active_ime_confirm_space(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    event_kind: str,
) -> int | None:
    """Swallow only messages that belong to the remembered physical Space key."""
    feed_ime_keyboard_message(win, hwnd, msg_value, wparam, lparam)
    if event_kind == SPACE_EVENT_UP:
        clear_ime_confirm_space()
    else:
        refresh_ime_confirm_space(hwnd)
    return 0


def handle_ime_confirm_space_guard(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    comp_string_reader: CompositionReader,
) -> int | None:
    """Consume the physical Space key used to confirm an active IME composition."""
    event_kind = space_event_kind(win, msg_value, wparam, lparam)
    if not event_kind:
        return None

    if ime_confirm_space_is_active(hwnd):
        result = handle_active_ime_confirm_space(
            win,
            hwnd,
            msg_value,
            wparam,
            lparam,
            event_kind,
        )
        if result is not None:
            return result

    if event_kind == SPACE_EVENT_UP:
        return None

    target = ime_edit_guard_target(win, hwnd, comp_string_reader)
    if target is None:
        return None

    refresh_ime_confirm_space(hwnd)
    feed_ime_keyboard_message(win, hwnd, msg_value, wparam, lparam)
    return 0


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

    value = platform_api.ptr_value(wparam)
    if msg_value == win.WM_CHAR and not is_preedit_char(value):
        return None
    if msg_value != win.WM_CHAR and not is_preedit_vkey(value):
        return None

    protect_text_target_from_ime_edit(target)
    win.imm32.ImmIsUIMessageW(hwnd, msg_value, wparam, lparam)
    return 0


def handle_raw_input_guard(
    win: object,
    hwnd: object,
    lparam: object,
    comp_string_reader: CompositionReader,
) -> int | None:
    """Raw input can reach Blender before translated IME messages do."""
    raw = platform_api.read_raw_keyboard(win, lparam)
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
    """Let the native IME consume navigation and deletion keys during composition."""
    w_value = platform_api.ptr_value(wparam)
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
    space_result = handle_ime_confirm_space_guard(
        win,
        hwnd,
        msg_value,
        wparam,
        lparam,
        comp_string_reader,
    )
    if space_result is not None:
        return space_result

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

    return None
