"""Undo / redo for every model mutation made through the web API.

A mutation hook (``webapp.core.register_mutation_hook``) snapshots the model
before every non-GET request and records an undo step afterwards when the
model actually changed, so plugins get undo for free. Undo/redo, save,
export, new and load requests are not recorded; new/load clear the history.

    POST /api/undo          -> {ok, ...state}   (ok false when there is nothing to undo)
    POST /api/redo          -> {ok, ...state}
    GET  /api/undo/state    -> {can_undo, can_redo, undo_label, redo_label, undo_depth, redo_depth, limit}
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

from engine.undo import history_for, redo, undo
from webapp.core import ok, register_mutation_hook, route, session

_UNTRACKED = re.compile(r"^/api/(undo|redo|new|load|save|export|plugins|state|tree|validate)(/|$)")

_LABELS: list[tuple[str, str, str]] = [
    ("POST", r"^/api/element$", "Create element"),
    ("PATCH", r"^/api/element/", "Edit properties"),
    ("DELETE", r"^/api/element/", "Delete element"),
    ("POST", r"^/api/link$", "Create link"),
    ("POST", r"^/api/parse$", "Import SysML text"),
    ("POST", r"^/api/stereotype/", "Stereotype"),
    ("POST", r"^/api/sm/", "State machine edit"),
    ("POST", r"^/api/arch/component$", "Add component"),
    ("PATCH", r"^/api/arch/component/", "Edit component"),
    ("POST", r"^/api/arch/port$", "Add port"),
    ("PATCH", r"^/api/arch/port/", "Edit port"),
    ("POST", r"^/api/arch/connector$", "Connect"),
    ("PATCH", r"^/api/arch/connector/", "Edit connector"),
    ("POST", r"^/api/arch/delete$", "Delete"),
    ("POST", r"^/api/arch/duplicate$", "Duplicate"),
    ("POST", r"^/api/arch/group$", "Create component from selection"),
    ("POST", r"^/api/arch/expand$", "Expand component"),
    ("POST", r"^/api/arch/save-as-reference$", "Save as reference"),
    ("POST", r"^/api/arch/inline$", "Inline component"),
    ("POST", r"^/api/arch/auto-layout$", "Arrange"),
    ("POST", r"^/api/arch/layout$", "Move"),
    ("POST", r"^/api/arch/model-type$", "Change model type"),
    ("POST", r"^/api/arch/architecture$", "New architecture"),
]


def label_for(method: str, path: str) -> str:
    for verb, pattern, label in _LABELS:
        if verb == method and re.match(pattern, path):
            return label
    return f"{method} {path}"


def _before_mutation(method: str, path: str, body: Any) -> Optional[Callable[[int], None]]:
    if _UNTRACKED.match(path):
        return None
    s = session()
    before = history_for(s).begin(s.repo)
    label = label_for(method, path)

    def finish(status: int) -> None:
        # A handler that switched projects clears the history; recording the old
        # snapshot in the fresh one makes that switch undoable too.
        if history_for(s).commit(s.repo, before, label):
            s.touch()            # every view in the browser learns the model moved
    return finish


register_mutation_hook(_before_mutation)


def _state(done: bool, reason: Optional[str] = None) -> dict:
    out = {"ok": done, **history_for(session()).state()}
    if reason:
        out["reason"] = reason
    return out


@route("POST", r"^/api/undo$")
def api_undo(_req: dict):
    done = undo(session())
    return ok(_state(done, None if done else "nothing to undo"))


@route("POST", r"^/api/redo$")
def api_redo(_req: dict):
    done = redo(session())
    return ok(_state(done, None if done else "nothing to redo"))


@route("GET", r"^/api/undo/state$")
def api_undo_state(_req: dict):
    return ok(history_for(session()).state())
