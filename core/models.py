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

    @property
    def type(self) -> str:
        """Keep routing independent of reload-sensitive class identity."""
        return TARGET_FONT_EDIT


@dataclass
class TextImeSession:
    """One Text Editor IME composition session."""

    text: object
    body: str
    line: int
    column: int
    select_line: int
    select_column: int
    replace_start: int
    replace_end: int
    committed: bool = False

    def owns_text(self, text_data: object) -> bool:
        """Check whether this session still belongs to the given Text datablock."""
        try:
            return self.text == text_data
        except (ReferenceError, RuntimeError):
            return False

    def mark_committed(self) -> bool:
        """Mark the session as committed, returning whether this changed state."""
        if self.committed:
            return False
        self.committed = True
        return True


@dataclass(frozen=True)
class TextRestoreSnapshot:
    """Text Editor state kept briefly while edit-key guards settle."""

    text: object
    body: str
    line: int
    column: int
    select_line: int
    select_column: int
    session: object = None
    commit_generation: int = 0


@dataclass(frozen=True)
class FontBodySnapshot:
    """3D Text body state kept briefly while a confirm Space may leak."""

    target_key: int
    body: str


@dataclass(frozen=True)
class PendingInsert:
    """Committed IME text waiting for Blender's main-thread timer."""

    text: str
    target: object
    text_session: object = None
    hwnd: object = None
    source: str = ""
    font_space_leak: object = None


@dataclass(frozen=True)
class CandidateInfo:
    """Raw target geometry before user offsets and IME quirks are applied."""

    space: object
    screen_x: int
    screen_y: int
    line_height: int
    rect: object
    line: int = 0
    column: int = 0


@dataclass(frozen=True)
class CandidatePosition:
    """Final screen-space position sent to the native IME backend."""

    screen_x: int
    screen_y: int


def target_type(target: object) -> object:
    """Accept stale or missing targets without raising during message routing."""
    return getattr(target, "type", None)


def is_text_editor_target(target: object) -> bool:
    """Check the string discriminator used across module reloads."""
    return target_type(target) == TARGET_TEXT_EDITOR


def is_font_edit_target(target: object) -> bool:
    """Check the string discriminator used across module reloads."""
    return target_type(target) == TARGET_FONT_EDIT
