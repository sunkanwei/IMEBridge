from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
import importlib
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_PARENT = PROJECT_ROOT.parent


class FakeTimers:
    def __init__(self) -> None:
        self.registered: list[tuple[object, float]] = []

    def register(self, callback: object, *, first_interval: float = 0.0) -> None:
        self.registered.append((callback, first_interval))

    def is_registered(self, callback: object) -> bool:
        return any(item[0] is callback for item in self.registered)

    def unregister(self, callback: object) -> None:
        self.registered = [item for item in self.registered if item[0] is not callback]


class FakeSpaceTextEditor:
    draw_handlers: list[tuple[object, tuple[object, ...], str, str]] = []

    @classmethod
    def draw_handler_add(
        cls,
        callback: object,
        args: tuple[object, ...],
        region_type: str,
        draw_type: str,
    ) -> object:
        token = (callback, args, region_type, draw_type)
        cls.draw_handlers.append(token)
        return token

    @classmethod
    def draw_handler_remove(cls, handler: object, _region_type: str) -> None:
        cls.draw_handlers.remove(handler)


class FakeOperator:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.poll_result = True

    def poll(self) -> bool:
        return self.poll_result

    def __call__(self, *args: object, **kwargs: object) -> set[str]:
        self.calls.append((args, kwargs))
        return {"FINISHED"}


class FakeContext(SimpleNamespace):
    @contextmanager
    def temp_override(self, **kwargs: object):
        previous = {key: getattr(self, key, None) for key in kwargs}
        for key, value in kwargs.items():
            setattr(self, key, value)
        try:
            yield self
        finally:
            for key, value in previous.items():
                setattr(self, key, value)


def install_fake_bpy() -> ModuleType:
    existing = sys.modules.get("bpy")
    if existing is not None:
        return existing

    bpy = ModuleType("bpy")
    bpy.context = FakeContext(
        window=None,
        screen=None,
        area=None,
        region=None,
        space_data=None,
        window_manager=SimpleNamespace(windows=()),
        preferences=SimpleNamespace(addons={}),
        object=None,
        active_object=None,
        edit_object=None,
        selected_objects=(),
        view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),
    )
    bpy.app = SimpleNamespace(
        background=False,
        timers=FakeTimers(),
        translations=SimpleNamespace(
            register=lambda *_args, **_kwargs: None,
            unregister=lambda *_args, **_kwargs: None,
        ),
    )
    bpy.props = SimpleNamespace(
        BoolProperty=lambda **_kwargs: None,
        EnumProperty=lambda **_kwargs: None,
        IntProperty=lambda **_kwargs: None,
    )
    bpy.types = SimpleNamespace(
        AddonPreferences=object,
        SpaceTextEditor=FakeSpaceTextEditor,
    )
    bpy.ops = SimpleNamespace(
        text=SimpleNamespace(
            insert=FakeOperator(),
            indent=FakeOperator(),
        ),
        font=SimpleNamespace(
            text_insert=FakeOperator(),
            delete=FakeOperator(),
        ),
    )
    bpy.utils = SimpleNamespace(
        register_class=lambda _cls: None,
        unregister_class=lambda _cls: None,
    )
    sys.modules["bpy"] = bpy
    return bpy


def import_bridge_module(name: str) -> ModuleType:
    install_fake_bpy()
    package_parent = str(PACKAGE_PARENT)
    if package_parent not in sys.path:
        sys.path.insert(0, package_parent)
    return importlib.import_module(f"IMEBridge.{name}")


def reset_runtime() -> None:
    runtime = import_bridge_module("core.runtime")
    runtime.state.win = None
    runtime.state.hooks.clear()
    runtime.state.detached_hooks.clear()
    runtime.state.auto_enable_timer_registered = False
    runtime.state.auto_enable_attempts = 0
    runtime.state.clear_input_state()
    runtime.state.clear_pending_inserts()


@contextmanager
def patched(obj: object, name: str, value: object):
    sentinel = object()
    old_value = getattr(obj, name, sentinel)
    setattr(obj, name, value)
    try:
        yield
    finally:
        if old_value is sentinel:
            delattr(obj, name)
        else:
            setattr(obj, name, old_value)
