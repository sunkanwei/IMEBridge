"""No-op native backend used before a platform has a real bridge."""

from dataclasses import dataclass


SUPPORTS_NATIVE_BRIDGE = False


@dataclass
class Point:
    """Small point object matching the attributes used by bridge geometry code."""

    x: int = 0
    y: int = 0


@dataclass
class Rect:
    """Small rect object matching the attributes used by bridge geometry code."""

    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0


RECT = Rect
POINT = Point


class DWord:
    """Tiny value holder matching the attribute shape of a DWORD."""

    def __init__(self, value: int = 0) -> None:
        self.value = int(value)


DWORD = DWord


class IMECHARPOSITION:
    """Placeholder type for backend-specific IME request data."""


class COMPOSITIONFORM:
    """Placeholder type for backend-specific composition positioning."""


class CANDIDATEFORM:
    """Placeholder type for backend-specific candidate positioning."""


def ensure() -> None:
    """Unsupported backends intentionally keep the bridge inactive."""
    return None


def ptr_value(value: object) -> int:
    """Normalize pointer-like values without relying on platform APIs."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if hasattr(value, "value"):
        return int(value.value or 0)
    return int(value)


def enum_process_windows(include_children: bool = True) -> list[dict[str, object]]:
    """No windows are hookable until a real backend exists."""
    return []


def class_name(_api: object, _window: object) -> str:
    """Unsupported backends have no native window class names."""
    return ""


def is_current_process_window(_api: object, _window: object) -> bool:
    """Unsupported backends cannot verify native window ownership."""
    return False


def window_region(area: object) -> object | None:
    """Return Blender's main WINDOW region; this helper is platform-independent."""
    for region in area.regions:
        if region.type == "WINDOW":
            return region
    return None


def client_height(_api: object, _window: object) -> int | None:
    """No native client rectangle is available on the no-op backend."""
    return None


def client_rect(_api: object, _window: object) -> Rect | None:
    """No native client rectangle is available on the no-op backend."""
    return None


def client_to_screen(
    _api: object,
    _window: object,
    _x: float,
    _y: float,
) -> Point | None:
    """No native coordinate conversion is available on the no-op backend."""
    return None


def screen_to_client(
    _api: object,
    _window: object,
    _x: float,
    _y: float,
) -> Point | None:
    """No native coordinate conversion is available on the no-op backend."""
    return None


def region_point_to_screen(
    _api: object,
    _window: object,
    _region: object,
    _x: float,
    _y: float,
) -> Point | None:
    """No native coordinate conversion is available on the no-op backend."""
    return None


def region_rect_to_screen(
    _api: object,
    _window: object,
    _region: object,
) -> Rect | None:
    """No native coordinate conversion is available on the no-op backend."""
    return None


def read_raw_keyboard(_api: object, _payload: object) -> dict[str, int] | None:
    """Unsupported backends do not expose raw keyboard packets."""
    return None
