"""Pipeline configuration for agent execution.

Parses YAML/dict pipeline configs with mode, steps,
tools_allowed/denied, max_steps, and on_failure strategy.
"""

from __future__ import annotations

from typing import Any

_VALID_MODES = ("strict", "flexible", "batch")
_VALID_ON_FAILURE = ("abort", "skip", "retry")
_VALID_AGENT_MODES = ("process", "analyze", "preview")


class PipelineConfig:
    """Immutable pipeline configuration parsed from YAML or dict."""

    def __init__(
        self,
        *,
        name: str,
        mode: str,
        steps: list[dict[str, Any]],
        max_steps: int,
        on_failure: str,
        tools_allowed: list[str] | None = None,
        tools_denied: list[str] | None = None,
        system_prompt: str | None = None,
        max_tokens_budget: int | None = None,
        agent_mode: str = "process",
    ) -> None:
        self._name = name
        self._mode = mode
        self._steps = steps
        self._max_steps = max_steps
        self._on_failure = on_failure
        self._tools_allowed = tools_allowed or []
        self._tools_denied = tools_denied or []
        self._system_prompt = system_prompt
        self._max_tokens_budget = max_tokens_budget
        self._agent_mode = agent_mode

    # -- properties --------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def steps(self) -> list[dict[str, Any]]:
        return self._steps

    @property
    def max_steps(self) -> int:
        return self._max_steps

    @property
    def on_failure(self) -> str:
        return self._on_failure

    @property
    def tools_allowed(self) -> list[str]:
        return self._tools_allowed

    @property
    def tools_denied(self) -> list[str]:
        return self._tools_denied

    @property
    def system_prompt(self) -> str | None:
        return self._system_prompt

    @property
    def max_tokens_budget(self) -> int | None:
        return self._max_tokens_budget

    @property
    def agent_mode(self) -> str:
        return self._agent_mode

    # -- factory methods ---------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineConfig:
        """Create a PipelineConfig from a dictionary."""
        name = data["name"]
        mode = data["mode"]
        steps = data["steps"]
        max_steps = data.get("max_steps", 50)
        on_failure = data.get("on_failure", "abort")

        agent_mode = data.get("agent_mode", "process")

        if mode not in _VALID_MODES:
            raise ValueError(f"Invalid mode '{mode}'. Must be one of {_VALID_MODES}")
        if on_failure not in _VALID_ON_FAILURE:
            raise ValueError(
                f"Invalid on_failure '{on_failure}'. Must be one of {_VALID_ON_FAILURE}"
            )
        if agent_mode not in _VALID_AGENT_MODES:
            raise ValueError(
                f"Invalid agent_mode '{agent_mode}'. "
                f"Must be one of {_VALID_AGENT_MODES}"
            )

        return cls(
            name=name,
            mode=mode,
            steps=steps,
            max_steps=max_steps,
            on_failure=on_failure,
            tools_allowed=data.get("tools_allowed"),
            tools_denied=data.get("tools_denied"),
            system_prompt=data.get("system_prompt"),
            max_tokens_budget=data.get("max_tokens_budget"),
            agent_mode=agent_mode,
        )

    @classmethod
    def from_yaml(cls, path: str) -> PipelineConfig:
        """Create a PipelineConfig from a YAML file."""
        import yaml  # noqa: WPS433

        with open(path, encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh)
        return cls.from_dict(data)
