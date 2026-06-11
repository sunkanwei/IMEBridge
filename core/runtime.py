"""Runtime state that should not live on Blender RNA objects."""

from collections import deque
from dataclasses import dataclass, field
import time

from . import models


TEXT_IME_RECENT_SESSION_SECONDS = 0.5
TEXT_HIDDEN_IME_ACTIVITY_SECONDS = 2.0


@dataclass
class ImeConfirmSpaceState:
    """The physical Space key sequence currently owned by IME confirmation."""

    hwnd: int = 0
    until: float = 0.0
    released: bool = False
    char_seen: bool = False

    def clear(self) -> None:
        """Drop any pending IME confirmation Space sequence."""
        self.hwnd = 0
        self.until = 0.0
        self.released = False
        self.char_seen = False


@dataclass
class ImeDirectAsciiState:
    """Printable ASCII keys diverted from raw input until their WM_CHAR arrives."""

    hwnd: int = 0
    target: object = None
    active_vkeys: set[int] = field(default_factory=set)
    pending_chars: int = 0
    until: float = 0.0

    def clear(self) -> None:
        """Drop pending direct ASCII input."""
        self.hwnd = 0
        self.target = None
        self.active_vkeys.clear()
        self.pending_chars = 0
        self.until = 0.0


@dataclass
class TabIndentState:
    """Deferred Text Editor indentation after suppressing Unicode autocomplete."""

    target: object = None
    count: int = 0
    timer_registered: bool = False

    def clear(self) -> None:
        """Drop pending indentation."""
        self.target = None
        self.count = 0
        self.timer_registered = False


@dataclass
class TextAreaActivationState:
    """Pending Text Editor activation after a header action changes text."""

    hwnd: object = None
    hit: object = None
    previous_text_key: int = 0
    attempts: int = 0
    timer_registered: bool = False

    def clear(self) -> None:
        """Drop pending Text Editor activation."""
        self.hwnd = None
        self.hit = None
        self.previous_text_key = 0
        self.attempts = 0
        self.timer_registered = False


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
    recent: models.TextImeSession | None = None
    recent_until: float = 0.0
    commit_generation: int = 0

    def clear(self) -> None:
        """Forget all Text Editor IME session bookkeeping."""
        self.current = None
        self.recent = None
        self.recent_until = 0.0
        self.commit_generation = 0

    def clear_recent(self) -> None:
        """Forget the short grace-period session after composition end."""
        self.recent = None
        self.recent_until = 0.0

    def recent_is_active(self) -> bool:
        """Return whether an ended session can still accept late IME messages."""
        if self.recent is None:
            return False
        if time.monotonic() > self.recent_until:
            self.clear_recent()
            return False
        return True

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
        self.clear_recent()
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
        if (
            self.recent_is_active()
            and self.recent is not None
            and not self.recent.committed
            and self.recent.owns_text(text_data)
        ):
            return self.recent
        return None

    def mark_committed(self, session: object) -> None:
        """Record a legal IME commit and invalidate older restore snapshots."""
        if isinstance(session, models.TextImeSession) and session.mark_committed():
            self.commit_generation += 1

    def end_current(self) -> None:
        """Release the active composition while keeping a short late-result window."""
        if self.current is not None and not self.current.committed:
            self.recent = self.current
            self.recent_until = time.monotonic() + TEXT_IME_RECENT_SESSION_SECONDS
        self.current = None


@dataclass
class TextConfirmSpaceLeakState:
    """Snapshot before a Space that may be an IME confirmation key."""

    hwnd: int = 0
    snapshot: object = None
    until: float = 0.0

    def clear(self) -> None:
        """Drop the suspected confirmation-space snapshot."""
        self.hwnd = 0
        self.snapshot = None
        self.until = 0.0


@dataclass
class TextHiddenImeActivityState:
    """Recent IME key activity before Windows exposes composition state."""

    hwnd: int = 0
    text: object = None
    until: float = 0.0

    def clear(self) -> None:
        """Forget hidden pre-composition activity."""
        self.hwnd = 0
        self.text = None
        self.until = 0.0


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
    text_confirm_space_leak: TextConfirmSpaceLeakState = field(
        default_factory=TextConfirmSpaceLeakState
    )
    text_hidden_ime_activity: TextHiddenImeActivityState = field(
        default_factory=TextHiddenImeActivityState
    )
    text_draw_handler: object = None
    last_preposition_at: float = 0.0

    active_target: object = None
    composition_target: object = None

    ime_confirm_space: ImeConfirmSpaceState = field(
        default_factory=ImeConfirmSpaceState
    )
    ime_direct_ascii: ImeDirectAsciiState = field(
        default_factory=ImeDirectAsciiState
    )
    tab_indent: TabIndentState = field(default_factory=TabIndentState)
    text_area_activation: TextAreaActivationState = field(
        default_factory=TextAreaActivationState
    )
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
        self.text_confirm_space_leak.clear()
        self.text_hidden_ime_activity.clear()
        self.last_preposition_at = 0.0
        self.active_target = None
        self.composition_target = None
        self.ime_confirm_space.clear()
        self.ime_direct_ascii.clear()
        self.tab_indent.clear()
        self.text_area_activation.clear()
        self.font_result_dedup.clear()
        self.input_scope.clear()

    def clear_pending_inserts(self) -> None:
        """Drop queued commits after shutdown or failed setup."""
        self.pending_inserts.clear()
        self.insert_timer_registered = False


# One runtime object is enough here. Blender's add-on reload is the lifecycle
# boundary, and transient native handles do not belong in RNA data.
state = RuntimeState()


def clear_input_state() -> None:
    """Module-level convenience for lifecycle code."""
    state.clear_input_state()


def clear_pending_inserts() -> None:
    """Module-level convenience for lifecycle code."""
    state.clear_pending_inserts()
