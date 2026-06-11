"""Install and remove native message hooks for Blender windows."""

from . import message_router
from ..core import runtime
from ..platforms import native as platform_api


SUBCLASS_ID = 0x494D4542


def _item_field(item: dict[str, object], name: str) -> object:
    """Read enum metadata without trusting every backend to provide it."""
    try:
        return item.get(name)
    except Exception:
        return None


def hook_skip_reason(item: dict[str, object]) -> str:
    """Return why a window should not receive a subclass callback."""
    if not _item_field(item, "visible"):
        return "hidden"
    if _item_field(item, "class") != "GHOST_WindowClass":
        return "class"
    current_thread = _item_field(item, "current_thread")
    if current_thread is not None and not bool(current_thread):
        return "cross_thread"
    return ""


def is_hook_target(item: dict[str, object]) -> bool:
    """Only Blender's GHOST window should be subclassed."""
    return hook_skip_reason(item) == ""


def call_def_subclass_proc(
    win: object,
    hwnd: object,
    msg: object,
    wparam: object,
    lparam: object,
) -> object:
    """Continue the system-managed subclass chain."""
    try:
        return win.DefSubclassProc(hwnd, msg, wparam, lparam)
    except Exception:
        return 0


def make_subclass_proc(win: object, control: dict[str, bool]) -> object:
    """Wrap Blender's native message procedure without letting Python leaks escape."""
    holder: dict[str, object] = {}

    def subclass_proc(
        hwnd_arg: object,
        msg: int,
        wparam: object,
        lparam: object,
        subclass_id: object,
        _ref_data: object,
    ) -> object:
        """Handle one message, then hand it back to Blender when untouched."""
        try:
            if int(msg) == win.WM_NCDESTROY:
                hwnd_value = platform_api.ptr_value(hwnd_arg)
                record = runtime.state.hooks.get(hwnd_value)
                removed = remove_subclass(
                    win,
                    hwnd_arg,
                    holder["callback"],
                    subclass_id,
                )
                if removed:
                    runtime.state.hooks.pop(hwnd_value, None)
                elif record is not None:
                    record["control"]["active"] = False
                return call_def_subclass_proc(win, hwnd_arg, msg, wparam, lparam)

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
            return call_def_subclass_proc(win, hwnd_arg, msg, wparam, lparam)
        except Exception:
            return call_def_subclass_proc(win, hwnd_arg, msg, wparam, lparam)

    callback = win.SUBCLASSPROC(subclass_proc)
    holder["callback"] = callback
    return callback


def install_subclass(
    win: object,
    hwnd: object,
    callback: object,
    hwnd_value: int,
) -> bool:
    """Install or refresh this add-on's system-managed subclass callback."""
    try:
        installed = bool(win.SetWindowSubclass(hwnd, callback, SUBCLASS_ID, hwnd_value))
    except Exception:
        return False
    return installed


def remove_subclass(
    win: object,
    hwnd: object,
    callback: object,
    subclass_id: object = SUBCLASS_ID,
) -> bool:
    """Remove only this add-on's subclass layer."""
    try:
        removed = bool(win.RemoveWindowSubclass(hwnd, callback, subclass_id))
    except Exception:
        return False
    return removed


def is_window_alive(win: object, hwnd: object) -> bool:
    """Treat uncertain native state as alive so callbacks stay safely rooted."""
    try:
        return bool(win.user32.IsWindow(hwnd))
    except Exception:
        return True


def prune_stale_hooks(win: object) -> int:
    """Forget callback records for windows that no longer exist."""
    removed = 0
    for hwnd_value, record in list(runtime.state.hooks.items()):
        if not is_window_alive(win, record["hwnd"]):
            runtime.state.hooks.pop(hwnd_value, None)
            removed += 1
    return removed


def hook_window(win: object, item: dict[str, object]) -> bool:
    """Subclass a single GHOST window if it has not been hooked yet."""
    hwnd = _item_field(item, "hwnd")
    hwnd_value = platform_api.ptr_value(_item_field(item, "hwnd_value"))
    if not hwnd or not hwnd_value:
        return False

    if hwnd_value in runtime.state.hooks:
        reason = hook_skip_reason(item)
        if reason:
            return False
        record = runtime.state.hooks[hwnd_value]
        if record["control"].get("active", True):
            return False
        if not install_subclass(win, hwnd, record["callback"], hwnd_value):
            return False
        record["control"]["active"] = True
        return True

    reason = hook_skip_reason(item)
    if reason:
        return False

    control = {"active": True}
    callback = make_subclass_proc(win, control)
    if not install_subclass(win, hwnd, callback, hwnd_value):
        return False

    runtime.state.hooks[hwnd_value] = {
        "hwnd": hwnd,
        "callback": callback,
        "control": control,
        "class": _item_field(item, "class"),
    }
    return True


def start_hooks(insert_on_commit: bool = False) -> int:
    """Install hooks for the current Blender process."""
    win = platform_api.ensure()
    if win is None:
        return 0

    runtime.state.insert_on_commit = bool(insert_on_commit)
    prune_stale_hooks(win)
    hooked = 0
    for item in platform_api.enum_process_windows(include_children=True):
        if hook_window(win, item):
            hooked += 1
    return hooked


def has_active_hooks() -> bool:
    """Return whether at least one Windows subclass is actively handling messages."""
    return any(
        record["control"].get("active", False)
        for record in runtime.state.hooks.values()
    )


def restore_hook(win: object, record: dict[str, object]) -> bool:
    """Remove a system-managed subclass while keeping failed callbacks alive."""
    hwnd = record["hwnd"]
    if not is_window_alive(win, hwnd):
        return True

    if remove_subclass(win, hwnd, record["callback"]):
        return True

    record["control"]["active"] = False
    return False


def stop_hooks() -> int:
    """Tear down hook state and keep failed callbacks inert but alive."""
    from . import ime_switch

    ime_switch.restore_all_managed()
    win = runtime.state.win
    if win is None:
        for record in runtime.state.hooks.values():
            record["control"]["active"] = False
        runtime.clear_input_state()
        runtime.clear_pending_inserts()
        return 0

    stopped = 0
    for hwnd_value, record in list(runtime.state.hooks.items()):
        if restore_hook(win, record):
            runtime.state.hooks.pop(hwnd_value, None)
            stopped += 1

    runtime.clear_input_state()
    runtime.clear_pending_inserts()
    return stopped
