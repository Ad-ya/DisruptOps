from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

type Tool = Callable[..., object]


@dataclass(frozen=True, slots=True)
class AgentContext:
    case_id: str
    facts: dict[str, object] = field(default_factory=dict)
    previous_results: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentRequest:
    role: str
    system_prompt: str
    user_message: str
    context: AgentContext
    tool_names: tuple[str, ...]
    middleware_names: tuple[str, ...]
    max_model_calls: int
    max_graph_steps: int


@dataclass(frozen=True, slots=True)
class AgentResult:
    role: str
    case_id: str
    finding: dict

    @property
    def text(self) -> str:
        """Human-readable summary, derived from the validated finding."""
        return self.finding['summary']
