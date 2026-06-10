"""Minimal ctypes bindings needed by the Windows IME bridge."""

import ctypes
from ctypes import wintypes
import os

from ..core import runtime


def ptr_value(value: object) -> int:
    """Normalize ctypes handles and pointer-sized values to int."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if hasattr(value, "value"):
        return value.value or 0
    return int(value)


class IMECHARPOSITION(ctypes.Structure):
    """Caret geometry returned to IMEs during IMR_QUERYCHARPOSITION."""

    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("dwCharPos", wintypes.DWORD),
        ("pt", wintypes.POINT),
        ("cLineHeight", wintypes.UINT),
        ("rcDocument", wintypes.RECT),
    ]


class COMPOSITIONFORM(ctypes.Structure):
    """Composition-window placement for IMM32."""

    _fields_ = [
        ("dwStyle", wintypes.DWORD),
        ("ptCurrentPos", wintypes.POINT),
        ("rcArea", wintypes.RECT),
    ]


class CANDIDATEFORM(ctypes.Structure):
    """Candidate-window placement for IMM32."""

    _fields_ = [
        ("dwIndex", wintypes.DWORD),
        ("dwStyle", wintypes.DWORD),
        ("ptCurrentPos", wintypes.POINT),
        ("rcArea", wintypes.RECT),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    """Header shared by Win32 raw-input packets."""

    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWKEYBOARD(ctypes.Structure):
    """Keyboard payload inside a raw-input packet."""

    _fields_ = [
        ("MakeCode", wintypes.USHORT),
        ("Flags", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("VKey", wintypes.USHORT),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


class RAWINPUTDATA(ctypes.Union):
    """Raw input can carry several payload shapes; we only read keyboard data."""

    _fields_ = [("keyboard", RAWKEYBOARD)]


class RAWINPUT(ctypes.Structure):
    """Full raw-input packet passed through WM_INPUT."""

    _fields_ = [("header", RAWINPUTHEADER), ("data", RAWINPUTDATA)]


class Win32Api:
    """Loaded Win32 DLLs plus the signatures this bridge relies on."""

    GWL_WNDPROC = -4

    IACE_DEFAULT = 0x0010
    RID_INPUT = 0x10000003
    RIM_TYPEKEYBOARD = 1
    CFS_POINT = 0x0002
    CFS_EXCLUDE = 0x0080

    WM_SETFOCUS = 0x0007
    WM_KILLFOCUS = 0x0008
    WM_ACTIVATEAPP = 0x001C
    WM_INPUT = 0x00FF
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONDOWN = 0x0204
    WM_RBUTTONDBLCLK = 0x0206
    WM_MBUTTONDOWN = 0x0207
    WM_MBUTTONDBLCLK = 0x0209
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_CHAR = 0x0102
    WM_IME_STARTCOMPOSITION = 0x010D
    WM_IME_ENDCOMPOSITION = 0x010E
    WM_IME_COMPOSITION = 0x010F
    WM_IME_CHAR = 0x0286
    WM_IME_REQUEST = 0x0288
    WM_IME_KEYDOWN = 0x0290
    WM_IME_KEYUP = 0x0291

    VK_BACK = 0x08
    VK_RETURN = 0x0D
    VK_ESCAPE = 0x1B
    VK_CONTROL = 0x11
    VK_MENU = 0x12
    VK_PRIOR = 0x21
    VK_NEXT = 0x22
    VK_END = 0x23
    VK_HOME = 0x24
    VK_LEFT = 0x25
    VK_UP = 0x26
    VK_RIGHT = 0x27
    VK_DOWN = 0x28
    VK_DELETE = 0x2E
    VK_F2 = 0x71
    VK_F3 = 0x72
    VK_SPACE = 0x20

    GCS_COMPSTR = 0x0008
    GCS_RESULTSTR = 0x0800

    IME_CMODE_NATIVE = 0x0001
    IME_CMODE_NOCONVERSION = 0x0100

    IMR_QUERYCHARPOSITION = 0x0006
    NI_CLOSECANDIDATE = 0x0011
    NI_COMPOSITIONSTR = 0x0015
    CPS_CANCEL = 0x0004

    def __init__(self) -> None:
        """Load the DLLs once and wire up ctypes signatures immediately."""
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.imm32 = ctypes.WinDLL("imm32", use_last_error=True)

        self.LRESULT = ctypes.c_ssize_t
        self.WNDPROC = ctypes.WINFUNCTYPE(
            self.LRESULT,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        self.EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        self.EnumChildProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        self._configure_functions()

    def _declare(self, func: object, argtypes: list[object], restype: object) -> None:
        """Keep ctypes declarations compact and consistent."""
        func.argtypes = argtypes
        func.restype = restype

    def _configure_functions(self) -> None:
        """Group declarations by the Windows subsystem they belong to."""
        self._configure_user32_functions()
        self._configure_window_proc_functions()
        self._configure_imm32_functions()

    def _configure_user32_functions(self) -> None:
        """user32 covers windows, coordinates, and raw keyboard packets."""
        self._declare(
            self.user32.EnumWindows,
            [self.EnumWindowsProc, wintypes.LPARAM],
            wintypes.BOOL,
        )
        self._declare(
            self.user32.EnumChildWindows,
            [wintypes.HWND, self.EnumChildProc, wintypes.LPARAM],
            wintypes.BOOL,
        )
        self._declare(
            self.user32.GetWindowThreadProcessId,
            [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)],
            wintypes.DWORD,
        )
        self._declare(self.user32.IsWindow, [wintypes.HWND], wintypes.BOOL)
        self._declare(
            self.user32.IsWindowVisible,
            [wintypes.HWND],
            wintypes.BOOL,
        )
        self._declare(
            self.user32.GetClassNameW,
            [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int],
            ctypes.c_int,
        )
        self._declare(self.user32.GetForegroundWindow, [], wintypes.HWND)
        self._declare(self.user32.GetKeyState, [ctypes.c_int], ctypes.c_short)
        self._declare(
            self.user32.GetClientRect,
            [wintypes.HWND, ctypes.POINTER(wintypes.RECT)],
            wintypes.BOOL,
        )
        self._declare(
            self.user32.ClientToScreen,
            [wintypes.HWND, ctypes.POINTER(wintypes.POINT)],
            wintypes.BOOL,
        )
        self._declare(
            self.user32.ScreenToClient,
            [wintypes.HWND, ctypes.POINTER(wintypes.POINT)],
            wintypes.BOOL,
        )
        self._declare(
            self.user32.CallWindowProcW,
            [
                ctypes.c_void_p,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ],
            self.LRESULT,
        )
        self._declare(
            self.user32.GetRawInputData,
            [
                wintypes.HANDLE,
                wintypes.UINT,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.UINT),
                wintypes.UINT,
            ],
            wintypes.UINT,
        )

    def _configure_window_proc_functions(self) -> None:
        """Pick the pointer-sized window-procedure APIs when available."""
        if hasattr(self.user32, "SetWindowLongPtrW"):
            self.GetWindowLongPtrW = self.user32.GetWindowLongPtrW
            self.SetWindowLongPtrW = self.user32.SetWindowLongPtrW
            ptr_type = ctypes.c_void_p
        else:
            self.GetWindowLongPtrW = self.user32.GetWindowLongW
            self.SetWindowLongPtrW = self.user32.SetWindowLongW
            ptr_type = wintypes.LONG

        self._declare(
            self.GetWindowLongPtrW,
            [wintypes.HWND, ctypes.c_int],
            ctypes.c_void_p,
        )
        self._declare(
            self.SetWindowLongPtrW,
            [wintypes.HWND, ctypes.c_int, ptr_type],
            ctypes.c_void_p,
        )

    def _configure_imm32_functions(self) -> None:
        """IMM32 is the old but still practical API for this bridge."""
        self._declare(self.imm32.ImmGetContext, [wintypes.HWND], wintypes.HANDLE)
        self._declare(
            self.imm32.ImmReleaseContext,
            [wintypes.HWND, wintypes.HANDLE],
            wintypes.BOOL,
        )
        self._declare(
            self.imm32.ImmAssociateContextEx,
            [wintypes.HWND, wintypes.HANDLE, wintypes.DWORD],
            wintypes.BOOL,
        )
        self._declare(
            self.imm32.ImmGetCompositionStringW,
            [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD],
            ctypes.c_long,
        )
        self._declare(
            self.imm32.ImmGetOpenStatus,
            [wintypes.HANDLE],
            wintypes.BOOL,
        )
        self._declare(
            self.imm32.ImmGetConversionStatus,
            [
                wintypes.HANDLE,
                ctypes.POINTER(wintypes.DWORD),
                ctypes.POINTER(wintypes.DWORD),
            ],
            wintypes.BOOL,
        )
        self._declare(
            self.imm32.ImmSetConversionStatus,
            [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.DWORD,
            ],
            wintypes.BOOL,
        )
        self._declare(
            self.imm32.ImmSetOpenStatus,
            [wintypes.HANDLE, wintypes.BOOL],
            wintypes.BOOL,
        )
        self._declare(
            self.imm32.ImmNotifyIME,
            [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
            ],
            wintypes.BOOL,
        )
        self._declare(
            self.imm32.ImmIsUIMessageW,
            [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM],
            wintypes.BOOL,
        )
        self._declare(
            self.imm32.ImmSetCompositionWindow,
            [wintypes.HANDLE, ctypes.POINTER(COMPOSITIONFORM)],
            wintypes.BOOL,
        )
        self._declare(
            self.imm32.ImmSetCandidateWindow,
            [wintypes.HANDLE, ctypes.POINTER(CANDIDATEFORM)],
            wintypes.BOOL,
        )


def ensure_windows() -> Win32Api | None:
    """Create the Win32 table lazily; non-Windows builds get a clean no-op."""
    if os.name != "nt":
        return None
    if runtime.state.win is None:
        runtime.state.win = Win32Api()
    return runtime.state.win


def class_name(win: Win32Api, hwnd: object) -> str:
    """Read a window class name into a small stack buffer."""
    buffer = ctypes.create_unicode_buffer(256)
    win.user32.GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value


def window_process_id(win: Win32Api, hwnd: object) -> int:
    """Return the owning process id for a window handle."""
    pid = wintypes.DWORD()
    win.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def is_current_process_window(win: Win32Api, hwnd: object) -> bool:
    """Check whether hwnd belongs to this Blender process."""
    return bool(hwnd) and window_process_id(win, hwnd) == os.getpid()


def enum_process_windows(include_children: bool = True) -> list[dict[str, object]]:
    """Collect only windows owned by Blender's current process."""
    win = ensure_windows()
    if win is None:
        return []

    current_pid = os.getpid()
    windows = []
    seen = set()
    top_level_hwnds = []

    def add_window(hwnd: object, top_level: bool = False) -> None:
        """Deduplicate hwnds while preserving the fields the hook layer needs."""
        hwnd_value = ptr_value(hwnd)
        if hwnd_value in seen:
            return
        if window_process_id(win, hwnd) != current_pid:
            return
        seen.add(hwnd_value)
        visible = bool(win.user32.IsWindowVisible(hwnd))
        info = {
            "hwnd": hwnd,
            "hwnd_value": hwnd_value,
            "visible": visible,
            "class": class_name(win, hwnd),
        }
        windows.append(info)
        if top_level:
            top_level_hwnds.append(hwnd)

    def enum_window(hwnd: object, _lparam: object) -> bool:
        """EnumWindows callback."""
        add_window(hwnd, True)
        return True

    enum_cb = win.EnumWindowsProc(enum_window)
    win.user32.EnumWindows(enum_cb, 0)

    if include_children:
        def enum_child(hwnd: object, _lparam: object) -> bool:
            """EnumChildWindows callback."""
            add_window(hwnd)
            return True

        child_cb = win.EnumChildProc(enum_child)
        for top_hwnd in top_level_hwnds:
            win.user32.EnumChildWindows(top_hwnd, child_cb, ptr_value(top_hwnd))

    return windows


def window_region(area: object) -> object | None:
    """Blender areas can have headers and sidebars; hooks need the main region."""
    for region in area.regions:
        if region.type == "WINDOW":
            return region
    return None


def client_height(win: Win32Api, hwnd: object) -> int | None:
    """Needed because Blender's region Y axis is opposite Win32 client Y."""
    rect = wintypes.RECT()
    if not win.user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.bottom - rect.top


def client_rect(win: Win32Api, hwnd: object) -> object | None:
    """Read the client rect, returning None if the hwnd is already stale."""
    rect = wintypes.RECT()
    if not win.user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    return rect


def client_to_screen(win: Win32Api, hwnd: object, x: float, y: float) -> object | None:
    """Win32 helper with None for failed conversions."""
    point = wintypes.POINT(int(round(x)), int(round(y)))
    if not win.user32.ClientToScreen(hwnd, ctypes.byref(point)):
        return None
    return point


def screen_to_client(win: Win32Api, hwnd: object, x: float, y: float) -> object | None:
    """Win32 helper with None for failed conversions."""
    point = wintypes.POINT(int(round(x)), int(round(y)))
    if not win.user32.ScreenToClient(hwnd, ctypes.byref(point)):
        return None
    return point


def region_point_to_screen(
    win: Win32Api,
    hwnd: object,
    region: object,
    x: float,
    y: float,
) -> object | None:
    """Convert Blender region coordinates into the screen space IMEs expect."""
    height = client_height(win, hwnd)
    if height is None:
        return None
    client_x = region.x + int(round(x))
    client_y = height - (region.y + int(round(y)))
    return client_to_screen(win, hwnd, client_x, client_y)


def region_rect_to_screen(win: Win32Api, hwnd: object, region: object) -> object | None:
    """Convert a Blender region box into a Win32 RECT."""
    height = client_height(win, hwnd)
    if height is None:
        return None

    left = region.x
    top = height - (region.y + region.height)
    right = region.x + region.width
    bottom = height - region.y

    top_left = client_to_screen(win, hwnd, left, top)
    bottom_right = client_to_screen(win, hwnd, right, bottom)
    if top_left is None or bottom_right is None:
        return None

    return wintypes.RECT(
        top_left.x,
        top_left.y,
        bottom_right.x,
        bottom_right.y,
    )


def read_raw_keyboard(win: Win32Api, lparam: object) -> dict[str, int] | None:
    """Read WM_INPUT just far enough to learn the virtual key."""
    size = wintypes.UINT(0)
    header_size = ctypes.sizeof(RAWINPUTHEADER)
    result = win.user32.GetRawInputData(
        wintypes.HANDLE(ptr_value(lparam)),
        win.RID_INPUT,
        None,
        ctypes.byref(size),
        header_size,
    )
    if result == 0xFFFFFFFF or size.value <= 0:
        return None

    buffer = ctypes.create_string_buffer(size.value)
    result = win.user32.GetRawInputData(
        wintypes.HANDLE(ptr_value(lparam)),
        win.RID_INPUT,
        ctypes.byref(buffer),
        ctypes.byref(size),
        header_size,
    )
    if result == 0xFFFFFFFF:
        return None

    raw = ctypes.cast(buffer, ctypes.POINTER(RAWINPUT)).contents
    if raw.header.dwType != win.RIM_TYPEKEYBOARD:
        return None

    keyboard = raw.data.keyboard
    return {
        "vkey": int(keyboard.VKey),
    }
