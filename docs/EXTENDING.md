# Extending the studio

Features plug in through registries instead of editing the core files, so
several can be developed side by side without merge conflicts. A typical
feature adds:

| Layer | Where | Registered by |
|-------|-------|---------------|
| Metamodel + logic | `engine/<feature>.py` (or `sysmlv2/<feature>.py`) | plain Python |
| Persistence | same module | `engine.register_codec` / `register_repo_codec` |
| Validation | same module | `engine.register_rule` / `register_repo_rule` |
| Knowledge graph | same module | `engine.register_edge_source` |
| Link kinds | same module | `engine.register_link_kind` |
| Web API | `webapp/routes/<feature>.py` | `webapp.core.route` |
| Web UI | `webapp/static/plugins/<NN>-<feature>.js` | `studio.register*` |
| MCP tools | `mcp_server/tools/<feature>.py` | module-level `TOOLS` list |
| Tests | `tests/test_<feature>.py`, `tests/ui/scenarios/<NN>_<feature>.mjs` | discovered automatically |

Import a feature's engine module from its route/tool modules so its
registrations run; serializer codecs are also re-imported automatically when
a saved project uses them.

## Engine

```python
from engine import (register_codec, register_repo_codec, register_rule,
                    register_repo_rule, register_edge_source, register_link_kind,
                    ValidationIssue, Severity, LinkKind)

# Per-element state. encode returns None when there is nothing to save.
register_codec("variants",
               encode=lambda e: getattr(e, "active_choice_id", None),
               decode=lambda e, data, by_id: setattr(e, "active_choice_id", data))

# Project-level state (e.g. allocation sets that are not model elements).
register_repo_codec("allocations", encode=lambda repo: ..., decode=lambda repo, data, by_id: ...)

def check(e):                       # runs for every element on validate
    if ...: yield ValidationIssue(Severity.ERROR, "variants.active", "No active choice", e)
register_rule(check)

register_edge_source(lambda e: [("allocatedTo", e, tgt, {})] if ... else [])
```

`Element.tool_data` (a dict) is persisted automatically when its values are
JSON-serializable. UI-only state such as canvas layout belongs there.
New element classes persist automatically (by class path) as long as their
extra attributes are covered by a codec.

## Web API (`webapp/core.py`)

```python
from webapp.core import route, ok, err, session, summarize, register_kind, \
    register_summary_hook, register_prop_hook

@route("GET", r"^/api/variants/(?P<eid>[^/]+)$")
def get_variants(req, eid):              # req = {"body": dict|None, "query": dict}
    e = session().find(eid)              # id or qualified name, with or without the project root
    if e is None:
        return err("not found", 404)
    return ok(summarize(e))

register_kind("VariantComponent", VariantComponent)   # creatable via POST /api/element
register_summary_hook(lambda e, d: d.update(variant=...))   # extra fields in element JSON
register_prop_hook(lambda e, key, value: ...)          # return True if it handled a PATCH prop
```

**Undo step labels.** Every non-GET request that changes the model becomes
one undo step automatically. Name it for users (the Undo / Redo tooltips and
the Output log show it) next to the route; no label ever shows an HTTP
method, a route or an id:

```python
from webapp.core import register_undo_label

register_undo_label("POST", r"^/api/variants/(?P<vid>[^/]+)/activate$",
                    lambda c: f"Activate {c.name(c.body.get('choice'))} in {c.name(c.args['vid'])}")
```

The function runs after the handler and gets a `LabelContext`: `c.body`,
`c.payload` (the answer; `c.pid()` is its `id`), `c.args` (URL-decoded named
groups), `c.name(ref)` (display name now, or before the request for deleted
elements; requirements by their id such as SYS-3), `c.old_name(ref)`,
`c.names(refs)` and `c.port(ref)` ("ADIRU.airData"). Unlabelled routes get a
generic label ("Edit variants"). The labels of the wave-1 features are in
`webapp/routes/labels.py`.

**Create, then name in place = one step.** When the UI names an element in
place right after creating it (canvas Add Component / Group / ports, a new
interface or element, a new requirement's summary), it sends the rename with
`studio.api(method, path, body, { undoMerge: <new element id> })`. The server
folds that edit into the creation step (only if the creation is the latest
step), so one Ctrl+Z removes the element and the step is labelled with its
final name ("Group ADIRU, FMS into CPM_Pair").

**Request notices (tell the user now).** A request can succeed and still deserve a
word: an interface assignment that leaves a connector incompatible. The handler reports it with `warn_user(payload, messages)`
(`webapp.core`): the messages become `payload["warnings"]` (what scripts and HTTP tests
read) and notices, which the server sends in the `X-Studio-Notices` header (percent-encoded
JSON `[{message, severity}]`, at most 6 per request). `studio.api` shows each one through
`studio.notify(message, severity)` — an Output log line, plus a toast on the architecture
canvas via the `notice` event — whichever view or feature sent the request, so the callers
need no code of their own. Use `add_notice(text, severity)` when there is no JSON object to
put `warnings` in. Messages are readable sentences that name the element and the reason.

Never import `webapp.server` from a plugin: under `python -m webapp.server`
it is `__main__`, and a second import would create a second session. Use
`session().plugin_state["<feature>"]` for runtime state; it is cleared when
the project changes. `PATCH /api/element/<id>` with
`{"props": {"tool_data": {...}}}` merges into `tool_data`.

## Web UI (`window.studio`)

Plugins are ES modules in `webapp/static/plugins/`, loaded in file-name order
(use a numeric prefix, e.g. `20-canvas.js`). Each default-exports an install
function (it may be async; it is awaited before the next plugin loads):

```js
export default async function install(studio) {
  const pane = studio.registerTab({ id: "variants", title: "Variants", order: 30,
                                    mount(pane) { ... }, onShow(selected) { ... } });
  // The toolstrip is organised by task: section "modeling" | "views" | "requirements" |
  // "analysis" | "interop" (default: from the group, see RIBBON_SECTION_OF_GROUP in app.js,
  // else "modeling"); each group is a cluster inside its section.
  studio.registerToolbarButton({ id: "add-variant", label: "Variant", group: "Variants",
                                 section: "modeling", title: "Add variant component", onClick() { ... } });
  studio.registerInspectorSection({ id: "variant", title: "Variant", order: 20,
                                    render(el, container) { /* return false to hide */ } });
  studio.registerTreeBadge(node => node.variant ? "V" : null);
  studio.registerShortcut({ key: "k", ctrl: true, handler() { ... } });

  studio.on("select", el => ...);          // full element JSON
  studio.on("model-changed", tree => ...); // after every tree refresh
  studio.on("tab-shown", id => ...);
  studio.emit("my-event", payload);        // plugins can talk to each other

  await studio.api("GET", "/api/...");      // throws on non-2xx and logs the error (in words:
                                            // no HTTP method, route or ids)
  await studio.api("PATCH", url, body, { undoMerge: newId });   // see "Create, then name"
  studio.log("done", "ok");                 // severities: info, ok, warning, error
  studio.notify("Connector A → B: …", "warning");   // log line + canvas toast (see "Request notices")
  studio.modal(title, formHtml, async values => { ... });
  const v = await studio.dialog(title, formHtml, { ok: "Add" });  // values or null (no window.prompt/confirm)
  studio.registerUnsavedCheck({ check: async () => reason || null, saved: async () => {} });  // New / Load warn
  await studio.refreshTree(); await studio.selectElement(id);
}
```

Tailwind utility classes (v4, vendored) and the component classes in
`styles.css` (`btn-primary`, `btn-action`, `input`, ...) are available.
No build step: write plain browser JavaScript.

Studio chrome rules: dialogs are `studio.modal` (never `window.prompt`,
`confirm` or `alert`; `tests/test_studio_chrome.py` checks it). A feature's
editor is a tab; add a button that opens it to the toolstrip section of its
task (`RIBBON_EDITORS` in `app.js`). Generic SysML element commands, legacy
dialogs and rarely used tabs (Links, Parser) belong in the **Advanced ▾**
menu at the end of the tab bar.

## MCP (`mcp_server/core.py`)

```python
from mcp_server.core import SESSION, _ok, _err, register_kind, register_summary_hook

def tool_set_active_choice(variant: str, choice: str) -> dict:
    v = SESSION.find(variant)
    ...
    return _ok(SESSION.element_summary(v))

TOOLS = [{"name": "sysml_set_active_choice", "description": "...",
          "inputSchema": {"type": "object", "properties": {...}, "required": [...]},
          "handler": tool_set_active_choice}]
```

## Tests

- `tests/webapp_harness.py`: subclass `WebAppTestCase`, call
  `self.call(method, path, body, expect=200)`; each class gets its own server
  on a free port and a fresh session.
- `tests/ui/scenarios/*.mjs`: headless Chromium scenarios, run by
  `tests/test_ui_browser.py` (skipped without Node + Playwright). Each
  default-exports `async ({page, api, fresh, waitReady, expect}) => {...}`;
  any browser console error fails the scenario. Run one with
  `UI_FILTER=<name> python -m unittest tests.test_ui_browser`.

### Wave gate (mandatory before a wave closes)

`tests/ui/scenarios/99_avionics_e2e.mjs` builds a small avionics model the way
an engineer does, with **GUI gestures only**: New model, functional and
physical architectures drawn on the canvas, an ARINC 429 interface dragged
from the Interface Editor onto a port, a profile with mass / power / DAL
values, a requirement set whose rows are dragged onto blocks, an allocation
matrix, a Model Check finding fixed in the editors, a report, and Save JSON /
New / Load JSON. Along the way it checks the canvas Property Inspector, the
block badges, the undo labels and the Model Check count, and at the end that
no request failed, no native dialog opened and the Output log holds no error.

- A wave is closed only when `UI_GATE=1 python -m unittest tests.test_ui_browser`
  passes (with `UI_GATE` set, a missing Node.js / Playwright fails instead of
  skipping) together with the rest of `python -m unittest discover -s tests`.
- Each wave **extends** the scenario with its features, through their real
  gestures (a drag is a drag, not `studio.emit`). `tests/test_wave_gate.py`
  rejects API writes (`api("POST" | "PATCH" | "DELETE")`), `fresh()` and
  `window.studio` calls in it, and lists the features it must cover.
- `UI_E2E_SHOTS=1` keeps a screenshot of every stage in `UI_ARTIFACT_DIR`
  for the acceptance review.

## Cross-feature contracts

These keep independently built features consistent.

**Architecture structure** (`engine/structure.py`): an architecture is a
`PartDefinition`; a component is a `PartUsage` (reference component when
typed by a `PartDefinition`, inline component otherwise); a port is a
`PortUsage` (direction = `Feature.direction`, interface = its type); a
connector is a `ConnectionUsage` owned by the composition it wires, with
`ends[0]` = source port and `ends[1]` = destination port. Use
`components_of`, `ports_of`, `connectors_of`, `component_tree`,
`definition_of` instead of walking `owned_elements` yourself.

**Connector warnings** (`engine/structure.py`): a connector can be valid for the
architecture rules and still worth a warning. A feature supplies readable findings with
`register_connector_warning_source(fn(connector) -> list[str])` (the interfaces feature: the
interfaces of the two ports are incompatible). `connector_warnings(conn)` gathers them; the canvas
view puts them after the structural problems in the connector's `issues` (red, dashed line, ⚠ on
the label, tooltip, *Problems* in the Property Inspector), and the routes that edit a port report
the ones an edit just caused (`connector_warning_snapshot(repo, port)` before,
`new_connector_warnings(repo, port, before)` after → `warn_user`). They are warnings, never errors:
the edit still succeeds, as in System Composer.

**Stereotypes** (`engine/profiles.py` is the authority): a stereotype is named
`Stereotype.full_name` everywhere (`Profile.Stereotype`; a stereotype outside a
profile, e.g. in a plain package, is just its name), looked up with
`engine.profiles.find_stereotype` (id, qualified name, `Profile.Stereotype`, unique
bare name) and its values are set through the profiles API (`set_property_value(s)`,
`StereotypeApplication.set`), which checks types and ranges and converts units. Read
`StereotypeApplication.values` as a snapshot: it is a fresh dict, assigning into it
changes nothing. Do not re-derive names from owning packages or coerce values yourself.

**Element JSON display fields**: every summary has `badges` (list of short
strings) and `style` (dict with optional `fill`, `stroke`, `text`, `dash`,
`icon`). Summary hooks *append* badges and *set* style keys; the tree shows
badges, the canvas uses both.

**Element creation**: every code path that creates an element (web API,
canvas routes, MCP tools, table import, templates) must call
`engine.notify_created(element, repo)` once the element is owned;
features react with `engine.register_created_hook(fn(element, repo))`
(for example to apply default stereotypes). Deletion goes through
`Repository.remove`, which cascades and runs `register_removal_hook` hooks.

**Frontend events** (`studio.emit` / `studio.on`):

| Event | Payload | Meaning |
|-------|---------|---------|
| `navigate` | `{id}` | show an element (tree + inspector select it; canvas opens its parent) |
| `highlight` | `{ids, color?, reason?}` or `null` | emphasize elements on the canvas |
| `canvas-filter` | `{ids, label?}` or `null` | canvas shows only these components (views) |
| `selection-changed` | `[ids]` | multi-selection changed; read with `studio.getSelection()` |
| `project-changed` | `{reason: "new" \| "load"}` | the project is about to be replaced (emitted before the tree reloads); drop per-project UI state such as zoom |
| `project-saved` | `null` | *Save JSON* finished (after every `registerUnsavedCheck` `saved()` ran) |
| `drop-on-element` | `{dragged_id, target_id}` | an element was dragged (HTML5, see below) onto a canvas block, port or connector (`target_id` = its element id; dropped on the canvas background: the composition's id); handled by the dragged element's feature |
| `notice` | `{message, severity}` | `studio.notify()`: a warning to show now (the canvas toasts it; the log line is already written) |
| `element-changed` | `{revision, selected}` | the model changed but nobody refreshed the tree (see below); `selected` is the fresh summary of the selected element, if any |
| `select` / `model-changed` / `tab-shown` | see above | core events |

`studio.setSelection(ids)` sets the multi-selection (canvas rubber band,
table rows); `studio.getSelection()` falls back to the selected element.
The latest selection wins wherever it was made: a click in the containment tree
and a `navigate` replace the multi-selection (and emit `selection-changed`), so
`getSelection()` never returns an earlier canvas pick. `studio.selectElement(id)`
alone keeps the multi-selection (the canvas publishes its picks with
`setSelection` and then selects the primary one; editors re-select after a reload).

**Model changes reach every view** (the rule): every successful request that
changes the model results in `model-changed` or `element-changed`, whichever
feature sent it. The server stamps each API response with an
`X-Model-Revision` header (`Session.revision`, moved by `Session.touch()`: the
undo hook calls it whenever a request changed the model, and `set_repo` on
new / load / undo / redo). `studio.api` watches the header. A feature that
calls `studio.refreshTree()` after its edit gets `model-changed` (as before);
an editor that saves in place and keeps its focus (the Stereotypes section of
the Properties tab, table cells) need not do anything: once its request has
returned and the tree was not refreshed, the studio emits `element-changed`
and updates `studio.selected` without re-rendering the Properties tab.
"Returned" means no `studio.api` request is in flight any more: a command that
sends several requests before it refreshes the tree (New model: a new project,
then its architecture) gets one `model-changed` at the end and no
`element-changed` in between, so no view reloads from the old tree. So:

- Displays that mirror the model (canvas blocks, badges and Property Inspector,
  undo / redo buttons, Model Check results) listen to **both** events.
- Editors with keyboard focus (Profile Editor, requirement and interface
  tables) reload on `model-changed` only, or just mark themselves stale on
  `element-changed`, so typing is never interrupted.
- A route that changes the model outside a tracked request (rare) calls
  `session().touch()` itself.

**Dragging elements** (HTML5 drag and drop): a drag source puts the element id
in `dataTransfer` under the type `application/x-sysml-element` (and may set
`effectAllowed = "copyLink"`). The architecture canvas accepts such drops and
emits `drop-on-element`; it does not act on them itself (except a part
definition dropped on the canvas background, which becomes a reference
component). The feature that owns the dragged element reacts and ignores
payloads that are not its own: the requirements feature links a dropped
requirement, the interfaces feature assigns an interface or value type dropped
on a port. Drag sources: containment-tree rows, Interface Editor list rows,
requirement grips and Requirements Perspective rows. Holding a drag over the
Architecture tab opens the canvas, so a drag can start in another tab.

The canvas highlights any listed id it draws (components, ports, connectors);
`canvas-filter` may carry `hide: true` to hide instead of dim the other
components.
