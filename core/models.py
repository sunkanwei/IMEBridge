"""Small records passed between the bridge and Blender target code."""

from dataclasses import dataclass


TARGET_TEXT_EDITOR = "TEXT_EDITOR"
TARGET_FONT_EDIT = "FONT_EDIT"


@dataclass(frozen=True)
class TextEditorTarget:
    """Enough Blender context to re-enter a Text Editor safely."""

    window: object
    screen: object
    area: object
    region: object
    space: object
    text: object

    @property
    def type(self) -> str:
        """Keep routing independent of reload-sensitive class identity."""
        return TARGET_TEXT_EDITOR


@dataclass(frozen=True)
class FontEditTarget:
    """Enough Blender context to insert into 3D Text edit mode."""

    window: object
    screen: object
    area: object
    region: object
    space: object
    obj: object
    data: object

    @property
    def type(self) -> str:
        """Keep routing independent of reload-sensitive class identity."""
        return TARGET_FONT_EDIT


@dataclass(frozen=True)
class TextCompositionStart:
    """Text Editor cursor captured before an IME composition mutates the buffer."""

    text: object
    body: str
    line: int
    column: int
    session_id: int


@dataclass(frozen=True)
class TextRestoreSnapshot:
    """Text Editor state kept briefly while edit-key guards settle."""

    target: TextEditorTarget
    text: object
    body: str
    line: int
    column: int
    session_id: int


@dataclass(frozen=True)
class PendingInsert:
    """Committed IME text waiting for Blender's main-thread timer."""

    text: str
    target: object
    composition_start: object = None


@dataclass(frozen=True)
class CandidateInfo:
    """Raw target geometry before user offsets and IME quirks are applied."""

    area: object
    region: object
    space: object
    screen_x: int
    screen_y: int
    line_height: int
    rect: object
    text: object = None
    obj: object = None
    line: int = 0
    column: int = 0
    region_x: int = 0
    region_y: int = 0


@dataclass(frozen=True)
class CandidatePosition:
    """Final screen-space position sent to IMM32."""

    screen_x: int
    screen_y: int
    char_width: int = 0
    requested_x_offset: int = 0
    manual_x_offset: int = 0
    manual_y_offset: int = 0


def target_type(target: object) -> object:
    """Accept stale or missing targets without raising during message routing."""
    return getattr(target, "type", None)


def is_text_editor_target(target: object) -> bool:
    """Check the string discriminator used across module reloads."""
    return target_type(target) == TARGET_TEXT_EDITOR


def is_font_edit_target(target: object) -> bool:
    """Check the string discriminator used across module reloads."""
    return target_type(target) == TARGET_FONT_EDIT
