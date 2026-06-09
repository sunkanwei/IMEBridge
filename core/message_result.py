"""Return values used by the Win32 message router."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MessageResult:
    """Whether a message was consumed, plus the value Win32 should receive."""

    handled: bool = False
    value: int = 0

    @classmethod
    def pass_through(cls) -> "MessageResult":
        """Let Blender's original window procedure see the message."""
        return cls(False, 0)

    @classmethod
    def handled_value(cls, value: int = 0) -> "MessageResult":
        """Return a value to Win32 without forwarding the message."""
        return cls(True, value)

    @property
    def as_window_result(self) -> int | None:
        """Use None as the hook-side sentinel for pass-through messages."""
        if self.handled:
            return self.value
        return None
