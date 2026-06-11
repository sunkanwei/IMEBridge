from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from .env import import_bridge_module


@dataclass
class FakeLine:
    body: str


class FakeText:
    _next_pointer = 1000

    def __init__(
        self,
        body: str,
        *,
        line: int = 0,
        column: int = 0,
        select_line: int | None = None,
        select_column: int | None = None,
    ) -> None:
        FakeText._next_pointer += 1
        self._pointer = FakeText._next_pointer
        self.current_line_index = line
        self.current_character = column
        self.select_end_line_index = line if select_line is None else select_line
        self.select_end_character = column if select_column is None else select_column
        self._body = ""
        self.lines: list[FakeLine] = []
        self.write(body)

    def as_pointer(self) -> int:
        return self._pointer

    def as_string(self) -> str:
        return self._body

    def clear(self) -> None:
        self._body = ""
        self.lines = [FakeLine("")]

    def write(self, body: str) -> None:
        self._body = body
        self.lines = [FakeLine(item) for item in body.split("\n")]
        if not self.lines:
            self.lines = [FakeLine("")]

    def select_set(
        self,
        line: int,
        column: int,
        select_line: int,
        select_column: int,
    ) -> None:
        self.current_line_index = line
        self.current_character = column
        self.select_end_line_index = select_line
        self.select_end_character = select_column


class PointerObject:
    def __init__(self, pointer: int) -> None:
        self._pointer = pointer

    def as_pointer(self) -> int:
        return self._pointer


class FakeObj(PointerObject):
    def __init__(
        self,
        pointer: int = 2000,
        *,
        obj_type: str = "FONT",
        body: str = "",
    ) -> None:
        super().__init__(pointer)
        self.type = obj_type
        self.mode = "EDIT"
        self.data = SimpleNamespace(body=body)


def text_editor_target(text: FakeText | None = None):
    models = import_bridge_module("core.models")
    text_data = text or FakeText("")
    window = SimpleNamespace(screen=None)
    screen = SimpleNamespace()
    window.screen = screen
    area = SimpleNamespace(type="TEXT_EDITOR", regions=[])
    region = SimpleNamespace(type="WINDOW", x=0, y=0, width=640, height=480)
    space = SimpleNamespace(text=text_data)
    return models.TextEditorTarget(window, screen, area, region, space, text_data)


def font_target(pointer: int = 3000, *, body: str = ""):
    models = import_bridge_module("core.models")
    window = SimpleNamespace(screen=None)
    screen = SimpleNamespace()
    window.screen = screen
    area = SimpleNamespace(type="VIEW_3D", regions=[])
    region = SimpleNamespace(type="WINDOW", x=0, y=0, width=640, height=480)
    space = SimpleNamespace()
    obj = FakeObj(pointer, body=body)
    return models.FontEditTarget(window, screen, area, region, space, obj)


class FakeUser32:
    def __init__(self) -> None:
        self.key_state: dict[int, int] = {}

    def GetKeyState(self, key: int) -> int:
        return self.key_state.get(int(key), 0)


class FakeImm32:
    def __init__(self) -> None:
        self.ui_messages: list[tuple[object, int, object, object]] = []
        self.open_status = True
        self.conversion = 0x0001
        self.sentence = 0
        self.set_open_calls: list[bool] = []
        self.set_conversion_calls: list[tuple[int, int]] = []
        self.notifications: list[tuple[object, int, int, int]] = []
        self.context = object()
        self.context_available = True
        self.composition_windows: list[object] = []
        self.candidate_windows: list[object] = []

    def ImmIsUIMessageW(
        self,
        hwnd: object,
        msg: int,
        wparam: object,
        lparam: object,
    ) -> bool:
        self.ui_messages.append((hwnd, msg, wparam, lparam))
        return True

    def ImmGetContext(self, _hwnd: object) -> object | None:
        return self.context if self.context_available else None

    def ImmReleaseContext(self, _hwnd: object, _himc: object) -> bool:
        return True

    def ImmGetOpenStatus(self, _himc: object) -> bool:
        return self.open_status

    def ImmSetOpenStatus(self, _himc: object, status: bool) -> bool:
        self.set_open_calls.append(bool(status))
        self.open_status = bool(status)
        return True

    def ImmGetConversionStatus(self, _himc: object, conversion: object, sentence: object) -> bool:
        conversion._obj.value = self.conversion
        sentence._obj.value = self.sentence
        return True

    def ImmSetConversionStatus(self, _himc: object, conversion: int, sentence: int) -> bool:
        self.set_conversion_calls.append((int(conversion), int(sentence)))
        self.conversion = int(conversion)
        self.sentence = int(sentence)
        return True

    def ImmNotifyIME(self, himc: object, action: int, index: int, value: int) -> bool:
        self.notifications.append((himc, action, index, value))
        return True

    def ImmSetCompositionWindow(self, _himc: object, form: object) -> bool:
        self.composition_windows.append(form._obj)
        return True

    def ImmSetCandidateWindow(self, _himc: object, form: object) -> bool:
        self.candidate_windows.append(form._obj)
        return True


class FakeWin:
    WM_SETFOCUS = 0x0007
    WM_KILLFOCUS = 0x0008
    WM_ACTIVATEAPP = 0x001C
    WM_INPUT = 0x00FF
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_CHAR = 0x0102
    WM_SYSKEYUP = 0x0105
    WM_IME_STARTCOMPOSITION = 0x010D
    WM_IME_ENDCOMPOSITION = 0x010E
    WM_IME_COMPOSITION = 0x010F
    WM_IME_CHAR = 0x0286
    WM_IME_REQUEST = 0x0288
    WM_IME_KEYDOWN = 0x0290
    WM_IME_KEYUP = 0x0291
    VK_BACK = 0x08
    VK_TAB = 0x09
    VK_RETURN = 0x0D
    VK_SHIFT = 0x10
    VK_CAPITAL = 0x14
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
    VK_PROCESSKEY = 0xE5
    VK_OEM_102 = 0xE2
    VK_SPACE = 0x20
    GCS_COMPSTR = 0x0008
    GCS_RESULTSTR = 0x0800
    IME_CMODE_NATIVE = 0x0001
    IME_CMODE_NOCONVERSION = 0x0100
    CFS_DEFAULT = 0x0000
    CFS_POINT = 0x0002
    CFS_EXCLUDE = 0x0080
    NI_CLOSECANDIDATE = 0x0011
    NI_COMPOSITIONSTR = 0x0015
    CPS_CANCEL = 0x0004

    def __init__(self) -> None:
        self.user32 = FakeUser32()
        self.imm32 = FakeImm32()
