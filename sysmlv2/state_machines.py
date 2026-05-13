"""State machine capability for SysML v2 Parts.

Each PartDefinition can own one or more *state machines*. A state machine
is a `StateMachineDefinition` (a kind of StateDefinition) containing:

- *states* (`StateUsage`) with optional entry / do / exit actions,
- a designated *initial* state and (optionally) *final* states,
- *transitions* (`TransitionUsage`) carrying trigger, guard and effect,
- *events* (`EventDefinition` / `EventUsage`) that trigger transitions.

A `StateMachineRunner` provides execution: feed events with
``runner.fire(event_name, **payload)``; the runner runs guards, fires
exit/transition-effect/entry hooks, and updates the current state.

Example
-------

    part_def = PartDefinition(name="Vehicle")
    sm = attach_state_machine(part_def, "VehicleSM")
    parked   = sm.add_state("Parked",  entry="lock()",   is_initial=True)
    driving  = sm.add_state("Driving", entry="unlock()", do="monitor()")
    sm.add_transition(parked, driving, trigger="start", effect="releaseBrake()")
    sm.add_transition(driving, parked, trigger="park",
                      guard=lambda ctx: ctx.get("speed", 0) == 0)

    runner = sm.runner()
    runner.fire("start")             # → Driving
    runner.fire("park", speed=0)     # → Parked
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from kerml.elements import Element
from kerml.features import Feature

from .definitions import (
    ActionUsage,
    Definition,
    PartDefinition,
    StateDefinition,
    StateUsage,
    TransitionUsage,
    Usage,
)


# --- new metamodel elements --------------------------------------------------

class StateMachineDefinition(StateDefinition):
    """A StateDefinition acting as a top-level state-machine container.

    Owns its states, events and transitions. The ``is_parallel`` flag
    (inherited from StateDefinition) enables AND-state semantics.
    """
    kind = "StateMachineDefinition"

    def __init__(self, name: Optional[str] = None, **kwargs):
        super().__init__(name=name, **kwargs)
        self.initial_state: Optional[StateUsage] = None
        self.final_states: list[StateUsage] = []
        self.events: list["EventDefinition"] = []

    # --- authoring helpers -----------------------------------------------
    def add_state(self, name: str, *,
                  entry: Any = None, do: Any = None, exit: Any = None,
                  is_initial: bool = False, is_final: bool = False
                  ) -> StateUsage:
        s = StateUsage(name=name)
        if entry is not None: s.entry_action = entry
        if do is not None:    s.do_action    = do
        if exit is not None:  s.exit_action  = exit
        s.is_final = is_final
        self.own(s)
        if is_initial:
            self.initial_state = s
        if is_final:
            self.final_states.append(s)
        return s

    def add_transition(self, source: StateUsage, target: StateUsage, *,
                       trigger: Optional[str] = None,
                       guard: Any = None, effect: Any = None,
                       name: Optional[str] = None) -> TransitionUsage:
        t = TransitionUsage(name=name or f"{source.name}→{target.name}")
        t.transition_source = source
        t.transition_target = target
        t.trigger_event = trigger
        t.guard = guard
        t.effect = effect
        self.own(t)
        return t

    def add_event(self, name: str) -> "EventDefinition":
        e = EventDefinition(name=name)
        self.own(e)
        self.events.append(e)
        return e

    # --- queries ---------------------------------------------------------
    @property
    def states(self) -> list[StateUsage]:
        return [s for s in self.owned_elements
                if isinstance(s, StateUsage) and not isinstance(s, TransitionUsage)]

    @property
    def transitions(self) -> list[TransitionUsage]:
        return [t for t in self.owned_elements if isinstance(t, TransitionUsage)]

    def transitions_from(self, state: StateUsage) -> list[TransitionUsage]:
        return [t for t in self.transitions if t.transition_source is state]

    # --- execution -------------------------------------------------------
    def runner(self) -> "StateMachineRunner":
        return StateMachineRunner(self)


class EventDefinition(Definition):
    """A signal / event that can trigger transitions."""
    kind = "EventDefinition"


class EventUsage(Usage):
    """A usage of an EventDefinition (e.g. a typed slot on a port)."""
    kind = "EventUsage"


# --- execution engine --------------------------------------------------------

@dataclass
class StateMachineRunner:
    """Runtime that steps a StateMachineDefinition under incoming events.

    Multiple runners can coexist (one per Part *instance*). The runner is
    deliberately small: it evaluates guards, fires effects, and updates
    the current state, raising for invalid events. All callables receive
    the context dict (filled with the event payload).
    """
    sm: StateMachineDefinition
    current: Optional[StateUsage] = None
    history: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.current is None:
            self.current = self.sm.initial_state
        if self.current is not None:
            self._record(f"enter:{self.current.name}")
            self._call(getattr(self.current, "entry_action", None), {})

    # --- introspection ---------------------------------------------------
    def is_in_final(self) -> bool:
        return self.current in self.sm.final_states

    # --- step ------------------------------------------------------------
    def fire(self, event: str, **payload: Any) -> Optional[StateUsage]:
        """Process a single event; return the new state (or None if no transition)."""
        if self.current is None:
            raise RuntimeError("State machine has no current state (set is_initial=True somewhere).")
        for t in self.sm.transitions_from(self.current):
            if t.trigger_event != event:
                continue
            if not self._guard_ok(t.guard, payload):
                continue
            self._call(getattr(self.current, "exit_action", None), payload)
            self._call(getattr(t, "effect", None), payload)
            self.current = t.transition_target
            self._record(f"{event}→{self.current.name if self.current else '?'}")
            if self.current is not None:
                self._call(getattr(self.current, "entry_action", None), payload)
            return self.current
        # No matching transition.
        self._record(f"unhandled:{event}")
        return None

    def trace(self) -> list[str]:
        return list(self.history)

    # --- internals -------------------------------------------------------
    def _guard_ok(self, guard: Any, payload: dict) -> bool:
        if guard is None:
            return True
        if callable(guard):
            return bool(guard(payload))
        if isinstance(guard, str):
            try:
                return bool(eval(guard, {"__builtins__": {}}, payload))  # noqa: S307
            except Exception:  # pragma: no cover
                return False
        return bool(guard)

    def _call(self, action: Any, payload: dict) -> None:
        if action is None:
            return
        if callable(action):
            action(payload); return
        # Strings are recorded as opaque "action descriptors" — useful for
        # validation, codegen, and visualization without an interpreter.
        self._record(f"action:{action}")

    def _record(self, line: str) -> None:
        self.history.append(line)


# --- attach to PartDefinition -----------------------------------------------

def attach_state_machine(part: PartDefinition, name: str,
                         **kwargs) -> StateMachineDefinition:
    """Create and own a fresh state machine on `part`. Returns the SM."""
    sm = StateMachineDefinition(name=name, **kwargs)
    part.own(sm)
    return sm


def state_machines_of(part: PartDefinition) -> list[StateMachineDefinition]:
    """Return every state machine owned (directly) by `part`."""
    return [e for e in part.owned_elements if isinstance(e, StateMachineDefinition)]


# Patch PartDefinition with convenience methods so callers can write
# `vehicle.attach_state_machine("VehicleSM")`. Doing this here keeps
# the SM module optional — until imported, PartDefinition is unchanged.
PartDefinition.attach_state_machine = (   # type: ignore[attr-defined]
    lambda self, name, **kw: attach_state_machine(self, name, **kw)
)
PartDefinition.state_machines = (        # type: ignore[attr-defined]
    property(lambda self: state_machines_of(self))
)


# --- patch StateUsage / TransitionUsage with the new attributes -------------
# These attributes are optional; tests/users may set them directly.
def _ensure_attr(cls: type, name: str, default: Any = None) -> None:
    if not hasattr(cls, name):
        setattr(cls, name, default)


for attr in ("entry_action", "do_action", "exit_action", "is_final"):
    _ensure_attr(StateUsage, attr, None if attr != "is_final" else False)
for attr in ("trigger_event", "guard", "effect"):
    _ensure_attr(TransitionUsage, attr, None)
