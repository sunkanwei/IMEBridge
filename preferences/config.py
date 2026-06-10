"""AddonPreferences plus safe accessors for runtime code."""

import bpy

from . import i18n


def _addon_id() -> str:
    """Return the top-level add-on package for legacy and Extension installs."""
    package = __package__ or __name__
    preferences_suffix = ".preferences"
    if preferences_suffix in package:
        return package.rsplit(preferences_suffix, 1)[0]
    return package.rpartition(".")[0] or package


ADDON_ID = _addon_id()

DEFAULT_X_OFFSET = -30
DEFAULT_Y_OFFSET = -30
DEFAULT_ADD_REQUESTED_CHAR_OFFSET = False
DEFAULT_PREPOSITION_CANDIDATE = True
DEFAULT_AUTO_ENGLISH_ON_SHORTCUTS = True


class IMEBridgePreferences(bpy.types.AddonPreferences):
    """Settings Blender stores for IMEBridge."""

    bl_idname = ADDON_ID

    ime_bridge_language: bpy.props.EnumProperty(
        name="Language",
        description="Display language for IMEBridge preferences",
        items=i18n.LANGUAGE_ITEMS,
        default=i18n.LANGUAGE_AUTO,
    )
    ime_bridge_x_offset: bpy.props.IntProperty(
        name="X Offset",
        description="Candidate box X offset in screen pixels",
        default=DEFAULT_X_OFFSET,
        min=-800,
        max=800,
        step=10,
    )
    ime_bridge_y_offset: bpy.props.IntProperty(
        name="Y Offset",
        description="Candidate box Y offset in screen pixels",
        default=DEFAULT_Y_OFFSET,
        min=-800,
        max=800,
        step=10,
    )
    ime_bridge_add_requested_char_offset: bpy.props.BoolProperty(
        name="Add Composition Character Offset",
        description=(
            "Use IME requested composition character position as extra "
            "candidate offset"
        ),
        default=DEFAULT_ADD_REQUESTED_CHAR_OFFSET,
    )
    ime_bridge_preposition_candidate: bpy.props.BoolProperty(
        name="Pre-position Candidate Box",
        description="Move candidate box near the text cursor before composition",
        default=DEFAULT_PREPOSITION_CANDIDATE,
    )
    ime_bridge_auto_english_on_shortcuts: bpy.props.BoolProperty(
        name="Automatic English on Shortcut Surfaces",
        description="Close IME on shortcut-heavy editor canvases",
        default=DEFAULT_AUTO_ENGLISH_ON_SHORTCUTS,
    )

    def draw(self, _context: object) -> None:
        """Blender calls this when it renders the add-on preferences panel."""
        layout = self.layout
        col = layout.column(align=True)
        col.prop(self, "ime_bridge_language", text=i18n.text("Language", self))

        col.separator()
        col.label(text=i18n.text("Candidate Box Position", self))
        col.prop(
            self,
            "ime_bridge_preposition_candidate",
            text=i18n.text("Pre-position Candidate Box", self),
        )
        col.prop(
            self,
            "ime_bridge_add_requested_char_offset",
            text=i18n.text("Add Composition Character Offset", self),
        )
        col.prop(self, "ime_bridge_x_offset", text=i18n.text("X Offset", self))
        col.prop(self, "ime_bridge_y_offset", text=i18n.text("Y Offset", self))

        col.separator()
        col.label(text=i18n.text("Input Mode", self))
        col.prop(
            self,
            "ime_bridge_auto_english_on_shortcuts",
            text=i18n.text("Automatic English on Shortcut Surfaces", self),
        )


def get_preferences(context: object = None) -> object | None:
    """Preferences are absent during early registration and background runs."""
    context = context or bpy.context
    preferences = getattr(context, "preferences", None)
    if preferences is None:
        return None
    addon = preferences.addons.get(ADDON_ID)
    if addon is None:
        return None
    return addon.preferences


def get_setting(name: str, default: object, context: object = None) -> object:
    """Read a setting without assuming the add-on is fully registered."""
    preferences = get_preferences(context)
    if preferences is None or not hasattr(preferences, name):
        return default
    return getattr(preferences, name)


def preposition_candidate(context: object = None) -> bool:
    """Whether to nudge the native IME before composition starts."""
    return bool(
        get_setting(
            "ime_bridge_preposition_candidate",
            DEFAULT_PREPOSITION_CANDIDATE,
            context,
        )
    )


def auto_english_on_shortcuts(context: object = None) -> bool:
    """Whether shortcut-heavy canvases should close the window IME."""
    return bool(
        get_setting(
            "ime_bridge_auto_english_on_shortcuts",
            DEFAULT_AUTO_ENGLISH_ON_SHORTCUTS,
            context,
        )
    )


def add_requested_char_offset(context: object = None) -> bool:
    """Some IMEs report useful per-character offsets; some do not."""
    return bool(
        get_setting(
            "ime_bridge_add_requested_char_offset",
            DEFAULT_ADD_REQUESTED_CHAR_OFFSET,
            context,
        )
    )


def x_offset(context: object = None) -> int:
    """Manual candidate-window X offset, in physical screen pixels."""
    return int(get_setting("ime_bridge_x_offset", DEFAULT_X_OFFSET, context))


def y_offset(context: object = None) -> int:
    """Manual candidate-window Y offset, in physical screen pixels."""
    return int(get_setting("ime_bridge_y_offset", DEFAULT_Y_OFFSET, context))
