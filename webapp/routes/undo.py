"""Undo / redo for every model mutation made through the web API.

A mutation hook (``webapp.core.register_mutation_hook``) snapshots the model
before every non-GET request and records an undo step afterwards when the
model actually changed, so plugins get undo for free. Undo/redo, save,
export, new and load requests are not recorded; new/load clear the history.
Steps are named by ``webapp.core.register_undo_label`` (the labels of every
feature are in ``webapp/routes/labels.py``).

    POST /api/undo          -> {ok, ...state}   (ok false when there is nothing to undo)
    POST /api/redo          -> {ok, ...state}
    GET  /api/undo/state    -> {can_undo, can_redo, undo_label, redo_label, undo_depth, redo_depth, limit}
"""
from __future__ import annotations

import re
from typing import Any, Callable, Optional

from engine.undo import history_for, redo, undo
from webapp.core import (
    Mutation, current_mutation, ok, register_mutation_hook, route, session, undo_label,
)

_UNTRACKED = re.compile(r"^/api/(undo|redo|new|load|save|export|plugins|state|tree|validate)(/|$)")


def label_for(method: str, path: str, body: Any = None, payload: Any = None) -> str:
    """The undo label of a request (see ``webapp.core.register_undo_label``)."""
    m = Mutation(method, path, body)
    m.payload = payload
    return undo_label(m)[0]


def _before_mutation(method: str, path: str, body: Any) -> Optional[Callable[[int], None]]:
    if _UNTRACKED.match(path):
        return None
    s = session()
    before = history_for(s).begin(s.repo)

    def finish(status: int) -> None:
        m = current_mutation() or Mutation(method, path, body)
        label, relabel = undo_label(m, before)
        # Naming an element in place right after creating it (the studio sends
        # X-Undo-Merge: <element id>) joins the creation step: one undo removes both.
        merge = m.headers.get("x-undo-merge") or None
        # A handler that switched projects clears the history; recording the old
        # snapshot in the fresh one makes that switch undoable too.
        if history_for(s).commit(s.repo, before, label, merge_into=merge, relabel=relabel):
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
