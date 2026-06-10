"""Install and restore native message hooks for Blender windows."""

import ctypes

from . import ime_guards
from . import message_router
from ..core import runtime
from ..platforms import native as platform_api


def is_hook_target(item: dict[str, object]) -> bool:
    """Only Blender's GHOST window should be subclassed."""
    return item["class"] == "GHOST_WindowClass"


def call_previous_window_proc(
    win: object,
    old_proc: int,
    hwnd: object,
    msg: object,
    wparam: object,
    lparam: object,
) -> object:
    """Keep the original window chain intact."""
    return win.user32.CallWindowProcW(
        ctypes.c_void_p(old_proc),
        hwnd,
        msg,
        wparam,
        lparam,
    )


def make_window_proc(win: object, old_proc: int, control: dict[str, bool]) -> object:
    """Wrap Blender's native message procedure without letting Python leaks escape."""
    def wndproc(hwnd_arg: object, msg: object, wparam: object, lparam: object) -> object:
        """Handle one message, then hand it back to Blender when untouched."""
        handled_result = None
        if control.get("active", True):
            try:
                result = message_router.handle_window_message(
                    hwnd_arg,
                    msg,
                    wparam,
                    lparam,
                )
                handled_result = result.as_window_result
            # A Python exception must never escape a native message hook.
            except Exception:
                handled_result = None

        if handled_result is not None:
            return handled_result
        return call_previous_window_proc(win, old_proc, hwnd_arg, msg, wparam, lparam)

    return win.WNDPROC(wndproc)


def keep_detached_hook(record: dict[str, object]) -> None:
    """Keep callbacks alive if another add-on still owns the top of the chain."""
    record["control"]["active"] = False
    if record not in runtime.state.detached_hooks:
        runtime.state.detached_hooks.append(record)


def hook_window(win: object, item: dict[str, object]) -> bool:
    """Subclass a single GHOST window if it has not been hooked yet."""
    hwnd = item["hwnd"]
    hwnd_value = item["hwnd_value"]
    if hwnd_value in runtime.state.hooks:
        record = runtime.state.hooks[hwnd_value]
        if current_window_proc(win, hwnd) == record["callback_ptr"]:
            record["control"]["active"] = True
            return False
        keep_detached_hook(record)
        runtime.state.hooks.pop(hwnd_value, None)
    if not item["visible"] or not is_hook_target(item):
        return False

    old_proc = platform_api.ptr_value(win.GetWindowLongPtrW(hwnd, win.GWL_WNDPROC))
    if not old_proc:
        return False

    control = {"active": True}
    callback = make_window_proc(win, old_proc, control)
    ctypes.set_last_error(0)
    previous = platform_api.ptr_value(
        win.SetWindowLongPtrW(
            hwnd,
            win.GWL_WNDPROC,
            ctypes.cast(callback, ctypes.c_void_p),
        )
    )
    err = ctypes.get_last_error()
    if previous == 0 and err:
        return False

    runtime.state.hooks[hwnd_value] = {
        "hwnd": hwnd,
        "old_proc": old_proc,
        "callback": callback,
        "control": control,
        "callback_ptr": platform_api.ptr_value(ctypes.cast(callback, ctypes.c_void_p)),
        "class": item["class"],
    }
    return True


def start_hooks(insert_on_commit: bool = False) -> int:
    """Install hooks for the current Blender process."""
    win = platform_api.ensure()
    if win is None:
        return 0

    runtime.state.insert_on_commit = bool(insert_on_commit)
    hooked = 0
    for item in platform_api.enum_process_windows(include_children=True):
        if hook_window(win, item):
            hooked += 1
    return hooked


def current_window_proc(win: object, hwnd: object) -> int:
    """Read the native procedure currently installed on hwnd."""
    return platform_api.ptr_value(win.GetWindowLongPtrW(hwnd, win.GWL_WNDPROC))


def restore_hook(win: object, record: dict[str, object]) -> bool:
    """Restore only our own hook; later hooks from other add-ons are left alone."""
    hwnd = record["hwnd"]
    if not win.user32.IsWindow(hwnd):
        return True

    if current_window_proc(win, hwnd) != record["callback_ptr"]:
        keep_detached_hook(record)
        return False

    ctypes.set_last_error(0)
    previous = platform_api.ptr_value(
        win.SetWindowLongPtrW(
            hwnd,
            win.GWL_WNDPROC,
            ctypes.c_void_p(record["old_proc"]),
        )
    )
    err = ctypes.get_last_error()
    return previous != 0 or not err


def stop_hooks() -> int:
    """Tear down hook state as far as the current hook chain allows."""
    from . import ime_switch

    ime_switch.restore_all_managed()
    win = runtime.state.win
    if win is None:
        runtime.state.hooks.clear()
        runtime.clear_input_state()
        runtime.clear_pending_inserts()
        return 0

    stopped = 0
    for hwnd_value, record in list(runtime.state.hooks.items()):
        if restore_hook(win, record):
            runtime.state.hooks.pop(hwnd_value, None)
            stopped += 1
        else:
            runtime.state.hooks.pop(hwnd_value, None)

    runtime.clear_input_state()
    runtime.clear_pending_inserts()
    ime_guards.clear_ime_activity()
    ime_guards.clear_space_suppression()
    return stopped
