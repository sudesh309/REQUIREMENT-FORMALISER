"""Model change hooks shared by every front end.

Any code path that creates an element (web API, canvas routes, MCP tools,
table import, templates) calls ``notify_created(element, repo)`` after the
element is owned and registered. Features react with
``register_created_hook(fn)``, e.g. profiles applying default stereotypes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from kerml.elements import Element

if TYPE_CHECKING:
    from .repository import Repository

_CREATED_HOOKS: list[Callable[[Element, "Repository"], None]] = []


def register_created_hook(fn: Callable[[Element, "Repository"], None]) -> None:
    _CREATED_HOOKS.append(fn)


def notify_created(element: Element, repo: "Repository") -> None:
    for hook in _CREATED_HOOKS:
        hook(element, repo)
    repo.registry.register_tree(element)
