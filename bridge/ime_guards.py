"""Keyboard guards that keep IME composition from editing Blender text directly."""

from .direct_ascii_guard import (
    DIRECT_ASCII_STALE_SECONDS,
    caps_lock_is_on,
    clear_ime_direct_ascii,
    consume_direct_ascii_char,
    direct_ascii_has_key,
    direct_ascii_has_pending_char,
    direct_ascii_pending_target,
    direct_ascii_state_is_active,
    direct_ascii_target,
    finish_direct_ascii_if_idle,
    handle_direct_ascii_char,
    handle_direct_ascii_guard,
    handle_direct_ascii_key_message,
    handle_direct_ascii_raw_input,
    is_direct_ascii_char,
    is_direct_ascii_vkey,
    refresh_direct_ascii_state,
    release_direct_ascii_key,
    remember_direct_ascii_key,
)
from .ime_confirm_space import (
    SPACE_CONFIRM_STALE_SECONDS,
    SPACE_EVENT_CHAR,
    SPACE_EVENT_DOWN,
    SPACE_EVENT_UP,
    clear_hidden_text_ime_activity,
    clear_ime_confirm_space,
    feed_ime_keyboard_message,
    handle_active_ime_confirm_space,
    handle_ime_confirm_space_guard,
    ime_confirm_space_is_active,
    remember_hidden_text_ime_activity,
    refresh_ime_confirm_space,
    space_event_kind,
)
from .ime_guard_common import (
    CompositionReader,
    active_target_for_ime_guard,
    ime_edit_guard_target,
    ime_edit_guard_vkeys,
    ime_is_composing,
    is_keyboard_message,
    modifier_shortcut_is_down,
    protect_text_target_from_ime_edit,
)
from .preedit_guard import (
    handle_ime_edit_key_guard,
    handle_preedit_text_guard,
    handle_raw_input_guard,
    ime_can_accept_preedit_text,
    is_preedit_char,
    is_preedit_vkey,
)

__all__ = (
    "SPACE_CONFIRM_STALE_SECONDS",
    "DIRECT_ASCII_STALE_SECONDS",
    "SPACE_EVENT_DOWN",
    "SPACE_EVENT_UP",
    "SPACE_EVENT_CHAR",
    "CompositionReader",
    "clear_ime_confirm_space",
    "clear_hidden_text_ime_activity",
    "clear_ime_direct_ascii",
    "refresh_ime_confirm_space",
    "ime_confirm_space_is_active",
    "space_event_kind",
    "feed_ime_keyboard_message",
    "handle_active_ime_confirm_space",
    "handle_ime_confirm_space_guard",
    "remember_hidden_text_ime_activity",
    "caps_lock_is_on",
    "direct_ascii_state_is_active",
    "refresh_direct_ascii_state",
    "finish_direct_ascii_if_idle",
    "remember_direct_ascii_key",
    "release_direct_ascii_key",
    "consume_direct_ascii_char",
    "direct_ascii_has_key",
    "direct_ascii_has_pending_char",
    "direct_ascii_pending_target",
    "is_direct_ascii_vkey",
    "is_direct_ascii_char",
    "direct_ascii_target",
    "handle_direct_ascii_raw_input",
    "handle_direct_ascii_key_message",
    "handle_direct_ascii_char",
    "handle_direct_ascii_guard",
    "is_keyboard_message",
    "modifier_shortcut_is_down",
    "is_preedit_vkey",
    "is_preedit_char",
    "ime_can_accept_preedit_text",
    "ime_edit_guard_vkeys",
    "active_target_for_ime_guard",
    "ime_is_composing",
    "ime_edit_guard_target",
    "protect_text_target_from_ime_edit",
    "handle_preedit_text_guard",
    "handle_raw_input_guard",
    "handle_ime_edit_key_guard",
    "handle_message_guards",
)


def handle_message_guards(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    comp_string_reader: CompositionReader,
) -> int | None:
    """Run the keyboard shields before normal IME dispatch."""
    remember_hidden_text_ime_activity(win, hwnd, msg_value, wparam)

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

    direct_ascii_result = handle_direct_ascii_guard(
        win,
        hwnd,
        msg_value,
        wparam,
        lparam,
        comp_string_reader,
    )
    if direct_ascii_result is not None:
        return direct_ascii_result

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
