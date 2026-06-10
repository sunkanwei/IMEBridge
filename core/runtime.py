"""Runtime state that should not live on Blender RNA objects."""

from collections import deque
from dataclasses import dataclass, field

from . import models


@dataclass
class ImeActivityState:
    """Recent IME activity, kept only long enough to guard leaked keys."""

    hwnd: int = 0
    until: float = 0.0

    def clear(self) -> None:
        """Forget the active IME window."""
        self.hwnd = 0
        self.until = 0.0


@dataclass
class SpaceSuppressionState:
    """A narrow guard for confirmation spaces that escape some IMEs."""

    hwnd: int = 0
    until: float = 0.0

    def clear(self) -> None:
        """Drop any pending space suppression window."""
        self.hwnd = 0
        self.until = 0.0


@dataclass
class SpaceConfirmState:
    """A recent Space key sequence that belongs to IME confirmation."""

    hwnd: int = 0
    until: float = 0.0

    def clear(self) -> None:
        """Forget the recent Space confirmation marker."""
        self.hwnd = 0
        self.until = 0.0


@dataclass
class FontResultDedupState:
    """Last 3D Text commit seen through the character-message fallback."""

    target_key: int = 0
    text: str = ""
    echo_index: int = 0
    until: float = 0.0

    def clear(self) -> None:
        """Forget the last fallback commit."""
        self.target_key = 0
        self.clear_echo()
        self.until = 0.0

    def clear_echo(self) -> None:
        """Stop duplicate-character suppression but keep target trust intact."""
        self.text = ""
        self.echo_index = 0


@dataclass
class ManagedImeState:
    """The IME state before IMEBridge temporarily closed a window."""

    hwnd: object
    was_open: bool
    conversion: int | None = None
    sentence: int | None = None


@dataclass
class InputScopeState:
    """Mouse-driven IME scope, separate from Blender text insertion state."""

    current_kind: str = "neutral"
    current_area_type: str = ""
    native_text_ui_handoff: bool = False
    pending_scope: object = None
    scope_timer_registered: bool = False
    managed_open_status: dict[int, ManagedImeState] = field(default_factory=dict)

    def clear(self) -> None:
        """Drop delayed scope work and remembered IME state."""
        self.current_kind = "neutral"
        self.current_area_type = ""
        self.native_text_ui_handoff = False
        self.pending_scope = None
        self.scope_timer_registered = False
        self.managed_open_status.clear()


@dataclass
class TextImeSessionState:
    """Current Text Editor IME session and commit generation."""

    current: models.TextImeSession | None = None
    commit_generation: int = 0

    def clear(self) -> None:
        """Forget all Text Editor IME session bookkeeping."""
        self.current = None
        self.commit_generation = 0

    def begin(
        self,
        *,
        text: object,
        body: str,
        line: int,
        column: int,
        select_line: int,
        select_column: int,
        replace_start: int,
        replace_end: int,
    ) -> models.TextImeSession:
        """Create and remember a new Text Editor IME session."""
        self.current = models.TextImeSession(
            text=text,
            body=body,
            line=line,
            column=column,
            select_line=select_line,
            select_column=select_column,
            replace_start=replace_start,
            replace_end=replace_end,
        )
        return self.current

    def active_for_text(self, text_data: object) -> models.TextImeSession | None:
        """Return the active session only when it owns the Text datablock."""
        if self.current is not None and self.current.owns_text(text_data):
            return self.current
        return None

    def mark_committed(self, session: object) -> None:
        """Record a legal IME commit and invalidate older restore snapshots."""
        if isinstance(session, models.TextImeSession) and session.mark_committed():
            self.commit_generation += 1

    def end_current(self) -> None:
        """Release the active composition without losing snapshot history."""
        self.current = None


@dataclass
class RuntimeState:
    """The bridge's per-session state."""

    win: object = None
    hooks: dict = field(default_factory=dict)
    detached_hooks: list = field(default_factory=list)

    insert_on_commit: bool = False
    pending_inserts: deque = field(default_factory=deque)
    insert_timer_registered: bool = False

    auto_enable_timer_registered: bool = False
    auto_enable_attempts: int = 0
    auto_arm_timer_registered: bool = False

    text_restore_timer_registered: bool = False
    text_restore_guard: object = None
    text_ime_session: TextImeSessionState = field(
        default_factory=TextImeSessionState
    )
    text_draw_handler: object = None
    last_preposition_at: float = 0.0

    active_target: object = None
    composition_target: object = None

    ime_activity: ImeActivityState = field(default_factory=ImeActivityState)
    space_suppression: SpaceSuppressionState = field(
        default_factory=SpaceSuppressionState
    )
    space_confirm: SpaceConfirmState = field(default_factory=SpaceConfirmState)
    font_result_dedup: FontResultDedupState = field(
        default_factory=FontResultDedupState
    )
    input_scope: InputScopeState = field(default_factory=InputScopeState)

    def clear_input_state(self) -> None:
        """Reset input bookkeeping while leaving installed hooks alone."""
        self.insert_on_commit = False
        self.auto_arm_timer_registered = False
        self.text_restore_timer_registered = False
        self.text_restore_guard = None
        self.text_ime_session.clear()
        self.last_preposition_at = 0.0
        self.active_target = None
        self.composition_target = None
        self.ime_activity.clear()
        self.space_suppression.clear()
        self.space_confirm.clear()
        self.font_result_dedup.clear()
        self.input_scope.clear()

    def clear_pending_inserts(self) -> None:
        """Drop queued commits after shutdown or failed setup."""
        self.pending_inserts.clear()
        self.insert_timer_registered = False


# One runtime object is enough here. Blender's add-on reload is the lifecycle
# boundary, and transient Win32 handles do not belong in RNA data.
state = RuntimeState()


def clear_input_state() -> None:
    """Module-level convenience for lifecycle code."""
    state.clear_input_state()


def clear_pending_inserts() -> None:
    """Module-level convenience for lifecycle code."""
    state.clear_pending_inserts()
