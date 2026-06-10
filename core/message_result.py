"""Return values used by native message routers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MessageResult:
    """Whether a message was consumed, plus the value the native hook should receive."""

    handled: bool = False
    value: int = 0

    @classmethod
    def pass_through(cls) -> "MessageResult":
        """Let Blender's original native procedure see the message."""
        return cls(False, 0)

    @classmethod
    def handled_value(cls, value: int = 0) -> "MessageResult":
        """Return a value to the native hook without forwarding the message."""
        return cls(True, value)

    @property
    def as_window_result(self) -> int | None:
        """Use None as the hook-side sentinel for pass-through messages."""
        if self.handled:
            return self.value
        return None
