"""NexusUI shortcut-surface whitelist helpers."""

import sys
from collections.abc import Iterator

from ..platforms import native as platform_api


_NEXUS_SERVICE_MODULE = "nexus._runtime.service.ssot"
_NEXUS_SERVICE_SUFFIX = ".nexus._runtime.service.ssot"


def is_nexusui_surface_hit(hit: object) -> bool:
    """Return True when a mouse hit belongs to a visible NexusUI surface."""
    try:
        host = _nexusui_host_for_hit(hit)
        if host is None:
            return False
        point = _hit_area_point(hit)
        if point is None:
            return False
        return _host_contains_point(host, point[0], point[1])
    except Exception:
        return False


def _nexusui_host_for_hit(hit: object) -> object | None:
    area_key = _hit_area_key(hit)
    if area_key is None:
        return None

    for service_module in _iter_nexus_service_modules():
        get_service = getattr(service_module, "get_service", None)
        service = get_service() if callable(get_service) else None
        if service is None:
            continue

        area_hosts = getattr(service, "area_hosts", None)
        get_host = getattr(area_hosts, "get", None)
        if not callable(get_host):
            continue

        host = get_host(area_key)
        if host is not None:
            return host
    return None


def _iter_nexus_service_modules() -> Iterator[object]:
    for name, module in tuple(sys.modules.items()):
        if module is None:
            continue
        if name == _NEXUS_SERVICE_MODULE or name.endswith(_NEXUS_SERVICE_SUFFIX):
            yield module


def _host_contains_point(host: object, x: float, y: float) -> bool:
    hit_test = getattr(host, "hit_test", None)
    if callable(hit_test) and bool(hit_test(x, y)):
        return True

    interaction = getattr(host, "interaction", None)
    if interaction is None:
        interaction = getattr(host, "_interaction", None)
    layers = getattr(interaction, "layers", None)
    layer_hit_test = getattr(layers, "hit_test", None)
    if callable(layer_hit_test):
        return layer_hit_test(x, y) is not None
    return False


def _hit_area_key(hit: object) -> tuple[int, int] | None:
    window = getattr(hit, "window", None)
    area = getattr(hit, "area", None)
    if window is None or area is None:
        return None
    window_pointer = _as_pointer(window)
    area_pointer = _as_pointer(area)
    if window_pointer is None or area_pointer is None:
        return None
    return (window_pointer, area_pointer)


def _hit_area_point(hit: object) -> tuple[float, float] | None:
    area_x = getattr(hit, "area_x", None)
    area_y = getattr(hit, "area_y", None)
    if area_x is None or area_y is None:
        return None
    return (float(area_x), float(area_y))


def _as_pointer(value: object) -> int | None:
    as_pointer = getattr(value, "as_pointer", None)
    if not callable(as_pointer):
        return None
    return platform_api.ptr_value(as_pointer())
