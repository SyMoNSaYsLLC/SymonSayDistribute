# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""The tool registry — what an agent is permitted to do, declared before it runs.

A tool is not "a function the model may call". It is a capability granted to one run, named
and bounded at the moment the run is composed. Nothing is ambient: a tool absent from the
grant is not refused at call time, it is never offered, so the model is never told it exists.

That ordering matters. A model that knows a capability exists and is refused will work around
the refusal. A model never told is simply working with a smaller set.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


class ToolError(Exception):
    """A tool refused, or could not run. Returned to the model as a result, never raised at it."""


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    schema: dict                       # JSON Schema for the arguments
    run: Callable[[dict], Any]
    # A tool that changes something is marked, so a run can be granted read-only capability
    # without every tool having to be audited by hand.
    mutates: bool = False

    def declare(self) -> dict:
        """The shape the dialect puts on the wire."""
        return {"name": self.name, "description": self.description, "input_schema": self.schema}


class Registry:
    """The tools that exist. A grant selects from these; it can never add to them."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        if not tool.name.replace("_", "").isalnum():
            raise ValueError(f"tool name {tool.name!r} must be alphanumeric with underscores")
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def grant(self, names: list[str]) -> "Grant":
        missing = [n for n in names if n not in self._tools]
        if missing:
            raise ValueError(f"cannot grant tools that do not exist: {missing}")
        return Grant({n: self._tools[n] for n in names})


class Grant:
    """One run's capabilities, fixed at composition.

    There is deliberately no method to add a tool after construction. A run that needs a
    capability it was not granted ends and is composed again with it — the same discipline as
    a sealed envelope, for the same reason: a grant that can grow mid-run is not a bound.
    """

    def __init__(self, tools: dict[str, Tool]) -> None:
        self._tools = dict(tools)

    def declare(self) -> list[dict]:
        return [t.declare() for t in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def read_only(self) -> bool:
        return not any(t.mutates for t in self._tools.values())

    def execute(self, name: str, arguments: dict) -> tuple[str, bool]:
        """Run one tool. Returns (result text, is_error).

        A failure comes back as a RESULT, not an exception. The model asked a question and
        deserves an answer it can act on; raising past it turns a recoverable step into a
        dead run, and the transcript then contains a call with no result, which is a shape
        the model was never trained on.
        """
        t = self._tools.get(name)
        if t is None:
            # Unreachable through a well-formed transcript: an ungranted tool was never
            # declared. It happens when a model invents a name, and the honest answer is
            # that it does not exist rather than a guess at what was meant.
            return (f"no such tool: {name}. Granted: {', '.join(self.names()) or '(none)'}", True)
        try:
            out = t.run(arguments or {})
        except ToolError as e:
            return (str(e), True)
        except Exception as e:                      # a tool's bug is not the run's failure
            return (f"{type(e).__name__}: {e}", True)
        if isinstance(out, (dict, list)):
            return (json.dumps(out, indent=1, sort_keys=True, default=str), False)
        return (str(out), False)
