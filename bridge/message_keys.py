"""Win32 keyboard and message predicates used by the router."""

from ..platforms import native as platform_api


def ctrl_is_down(win: object) -> bool:
    """Check Ctrl without importing the keyboard guards into routing policy."""
    return bool(win.user32.GetKeyState(win.VK_CONTROL) & 0x8000)


def alt_is_down(win: object) -> bool:
    """Alt usually belongs to menus, so Ctrl+Alt+F is not treated as find."""
    return bool(win.user32.GetKeyState(win.VK_MENU) & 0x8000)


def shift_is_down(win: object) -> bool:
    """Shift+Tab still belongs to Blender's unindent shortcut."""
    return bool(win.user32.GetKeyState(win.VK_SHIFT) & 0x8000)


def opens_native_text_ui(win: object, msg_value: int, wparam: object) -> bool:
    """Public shortcuts that hand focus to Blender's own text fields."""
    if msg_value != win.WM_KEYDOWN:
        return False

    key = platform_api.ptr_value(wparam)
    if key in {win.VK_F2, win.VK_F3}:
        return True
    return key == ord("F") and ctrl_is_down(win) and not alt_is_down(win)


def is_supported_message(win: object, msg_value: int) -> bool:
    """Ignore the native message noise the bridge never handles."""
    return msg_value in {
        win.WM_SETFOCUS,
        win.WM_KILLFOCUS,
        win.WM_ACTIVATEAPP,
        win.WM_INPUT,
        win.WM_LBUTTONDOWN,
        win.WM_LBUTTONDBLCLK,
        win.WM_RBUTTONDOWN,
        win.WM_RBUTTONDBLCLK,
        win.WM_MBUTTONDOWN,
        win.WM_MBUTTONDBLCLK,
        win.WM_KEYDOWN,
        win.WM_KEYUP,
        win.WM_CHAR,
        win.WM_IME_CHAR,
        win.WM_IME_KEYDOWN,
        win.WM_IME_KEYUP,
        win.WM_IME_REQUEST,
        win.WM_IME_STARTCOMPOSITION,
        win.WM_IME_COMPOSITION,
        win.WM_IME_ENDCOMPOSITION,
    }


def is_bridge_ime_message(win: object, msg_value: int) -> bool:
    """Messages that can otherwise leak into stale bridge targets."""
    return msg_value in {
        win.WM_IME_CHAR,
        win.WM_IME_KEYDOWN,
        win.WM_IME_KEYUP,
        win.WM_IME_REQUEST,
        win.WM_IME_STARTCOMPOSITION,
        win.WM_IME_COMPOSITION,
        win.WM_IME_ENDCOMPOSITION,
    }
