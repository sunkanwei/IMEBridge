"""Install and restore native message hooks for Blender windows."""

import ctypes

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


def record_hwnd_value(record: dict[str, object]) -> int:
    """Return the stable integer key used for one hook record."""
    return platform_api.ptr_value(record.get("hwnd"))


def forget_detached_hook(record: dict[str, object]) -> None:
    """Remove a hook from the detached keep-alive list if present."""
    try:
        runtime.state.detached_hooks.remove(record)
    except ValueError:
        pass


def keep_detached_hook(
    record: dict[str, object],
    covering_proc: int | None = None,
) -> None:
    """Keep callbacks alive if another add-on still owns the top of the chain."""
    record["control"]["active"] = False
    if covering_proc:
        record["covering_proc"] = covering_proc
    if record not in runtime.state.detached_hooks:
        runtime.state.detached_hooks.append(record)


def reactivate_detached_hook(record: dict[str, object]) -> bool:
    """Re-use an existing hook record instead of stacking a new callback."""
    hwnd_value = record_hwnd_value(record)
    if not hwnd_value:
        forget_detached_hook(record)
        return False
    record["control"]["active"] = True
    record.pop("covering_proc", None)
    runtime.state.hooks[hwnd_value] = record
    forget_detached_hook(record)
    return True


def sweep_detached_hooks(win: object, *, reactivate: bool = False) -> int:
    """Restore or re-use callbacks that were previously covered by another hook."""
    changed = 0
    for record in list(runtime.state.detached_hooks):
        hwnd = record["hwnd"]
        if not win.user32.IsWindow(hwnd):
            forget_detached_hook(record)
            continue

        current_proc = current_window_proc(win, hwnd)
        callback_ptr = record["callback_ptr"]
        covering_proc = record.get("covering_proc")
        if reactivate and current_proc in {callback_ptr, covering_proc}:
            if reactivate_detached_hook(record):
                changed += 1
            continue

        if current_proc == callback_ptr:
            if restore_hook(win, record):
                forget_detached_hook(record)
                changed += 1
        else:
            record["control"]["active"] = False
    return changed


def hook_window(win: object, item: dict[str, object]) -> bool:
    """Subclass a single GHOST window if it has not been hooked yet."""
    hwnd = item["hwnd"]
    hwnd_value = item["hwnd_value"]
    if hwnd_value in runtime.state.hooks:
        record = runtime.state.hooks[hwnd_value]
        current_proc = current_window_proc(win, hwnd)
        if current_proc != record["callback_ptr"]:
            record["covering_proc"] = current_proc
        record["control"]["active"] = True
        return False
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
    hooked = sweep_detached_hooks(win, reactivate=True)
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

    current_proc = current_window_proc(win, hwnd)
    if current_proc != record["callback_ptr"]:
        keep_detached_hook(record, current_proc)
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
    stopped += sweep_detached_hooks(win)

    runtime.clear_input_state()
    runtime.clear_pending_inserts()
    return stopped
