"""Snapshot-based undo / redo for whole-model edits.

Every tracked mutation stores the JSON snapshot (``engine.to_dict``) taken
before it; undo swaps the session's repository for the restored snapshot and
keeps the replaced state for redo. Element ids survive the round trip, so a
UI can keep its selection.

Front ends wrap each mutating call::

    hist = history_for(session)
    before = hist.begin(session.repo)
    ...mutate...
    hist.commit(session.repo, before, "Add component")

``commit`` only records a step when the model really changed, so read-only
calls and rejected edits leave no empty undo steps. Changes made outside
tracked calls (e.g. by a tool that is not wrapped) are detected at the next
``begin`` / ``undo`` by comparing with the last committed state and become
their own undo step.

The history lives in ``session.plugin_state["undo"]``: loading or creating a
project (``Session.set_repo``) clears it; undo/redo themselves use
:func:`swap_repo`, which keeps it.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from .serializer import from_dict, to_dict

MAX_SNAPSHOTS = 50
EXTERNAL = "external change"


class UndoHistory:
    def __init__(self, limit: int = MAX_SNAPSHOTS) -> None:
        self.limit = limit
        self.undo_stack: list[tuple[str, dict]] = []
        self.redo_stack: list[tuple[str, dict]] = []
        self.baseline: Optional[dict] = None
        # Every recorded change, undo and redo bumps the revision; ``dirty`` compares it
        # with the revision of the last save (a new or loaded project starts clean).
        self.revision = 0
        self.saved_revision = 0
        self._lock = threading.RLock()

    # --- recording -------------------------------------------------------
    def _push(self, label: str, snapshot: dict) -> None:
        self.undo_stack.append((label, snapshot))
        del self.undo_stack[:-self.limit]
        self.revision += 1

    def _catch_up(self, current: dict) -> bool:
        """Record an untracked change since the last commit; True if there was one."""
        if self.baseline is not None and current != self.baseline:
            self._push(EXTERNAL, self.baseline)
            self.redo_stack.clear()
            self.baseline = current
            return True
        return False

    def begin(self, repo) -> dict:
        snapshot = to_dict(repo)
        with self._lock:
            self._catch_up(snapshot)
        return snapshot

    def commit(self, repo, before: dict, label: str = "") -> bool:
        """Record `before` as an undo step if the model changed since it was taken."""
        after = to_dict(repo)
        with self._lock:
            self.baseline = after
            if after == before:
                return False
            self._push(label or "edit", before)
            self.redo_stack.clear()
            return True

    # --- undo / redo -----------------------------------------------------
    def undo(self, repo) -> Optional[Any]:
        """The repository to switch to, or None when there is nothing to undo."""
        with self._lock:
            current = to_dict(repo)
            self._catch_up(current)
            if not self.undo_stack:
                return None
            label, snapshot = self.undo_stack.pop()
            self.redo_stack.append((label, current))
            self.revision += 1
            restored = from_dict(snapshot)
            self.baseline = to_dict(restored)
            return restored

    def redo(self, repo) -> Optional[Any]:
        with self._lock:
            current = to_dict(repo)
            if self._catch_up(current) or not self.redo_stack:
                return None
            label, snapshot = self.redo_stack.pop()
            self._push(label, current)
            restored = from_dict(snapshot)
            self.baseline = to_dict(restored)
            return restored

    def clear(self) -> None:
        with self._lock:
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.baseline = None
            self.saved_revision = self.revision

    def mark_saved(self, repo) -> None:
        """The model as it is now has been saved (``dirty`` becomes False)."""
        with self._lock:
            self._catch_up(to_dict(repo))
            self.saved_revision = self.revision

    def state(self) -> dict:
        with self._lock:
            return {
                "dirty": self.revision != self.saved_revision,
                "revision": self.revision,
                "can_undo": bool(self.undo_stack),
                "can_redo": bool(self.redo_stack),
                "undo_label": self.undo_stack[-1][0] if self.undo_stack else None,
                "redo_label": self.redo_stack[-1][0] if self.redo_stack else None,
                "undo_depth": len(self.undo_stack),
                "redo_depth": len(self.redo_stack),
                "limit": self.limit,
            }


# --- session helpers ------------------------------------------------------

def history_for(session) -> UndoHistory:
    """The undo history of a web or MCP session (created on first use)."""
    hist = session.plugin_state.get("undo")
    if not isinstance(hist, UndoHistory):
        hist = session.plugin_state["undo"] = UndoHistory()
    return hist


def swap_repo(session, repo) -> None:
    """Switch the session's repository without losing the undo history."""
    hist = session.plugin_state.get("undo")
    session.set_repo(repo)
    if hist is not None:
        session.plugin_state["undo"] = hist


def undo(session) -> bool:
    restored = history_for(session).undo(session.repo)
    if restored is None:
        return False
    swap_repo(session, restored)
    return True


def redo(session) -> bool:
    restored = history_for(session).redo(session.repo)
    if restored is None:
        return False
    swap_repo(session, restored)
    return True


@contextmanager
def tracked(session, label: str = "") -> Iterator[None]:
    """Record whatever the body changes as one undo step."""
    hist = history_for(session)
    before = hist.begin(session.repo)
    try:
        yield
    finally:
        hist.commit(session.repo, before, label)
