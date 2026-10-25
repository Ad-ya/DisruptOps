from __future__ import annotations

from collections.abc import Iterable, Mapping, Iterator
from supply_chain_poc.models import Tool


class ToolRegistry(Mapping[str, Tool]):
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        name = tool.__name__
        if name in self._tools:
            raise ValueError(f'Tool already registered: {name}')
        if not tool.__doc__:
            raise ValueError(f'Tool needs a docstring: {name}')
        self._tools[name] = tool

    def resolve(self, names: tuple[str, ...]) -> list[Tool]:
        if len(names) != len(set(names)):
            raise ValueError('Duplicate tool names')
        unknown = set(names) - self._tools.keys()
        if unknown:
            raise ValueError(f'Unregistered tools: {sorted(unknown)}')
        return [self._tools[name] for name in names]


    def __getitem__(self, name: str) -> Tool:
        return self._tools[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._tools)

    def __len__(self) -> int:
        return len(self._tools)
