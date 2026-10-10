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
    e = session().find(eid)              # by id or qualified name
    if e is None:
        return err("not found", 404)
    return ok(summarize(e))

register_kind("VariantComponent", VariantComponent)   # creatable via POST /api/element
register_summary_hook(lambda e, d: d.update(variant=...))   # extra fields in element JSON
register_prop_hook(lambda e, key, value: ...)          # return True if it handled a PATCH prop
```

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
  studio.registerToolbarButton({ id: "add-variant", label: "Variant", group: "Arch",
                                 title: "Add variant component", onClick() { ... } });
  studio.registerInspectorSection({ id: "variant", title: "Variant", order: 20,
                                    render(el, container) { /* return false to hide */ } });
  studio.registerTreeBadge(node => node.variant ? "V" : null);
  studio.registerShortcut({ key: "k", ctrl: true, handler() { ... } });

  studio.on("select", el => ...);          // full element JSON
  studio.on("model-changed", tree => ...); // after every tree refresh
  studio.on("tab-shown", id => ...);
  studio.emit("my-event", payload);        // plugins can talk to each other

  await studio.api("GET", "/api/...");      // throws on non-2xx and logs the error
  studio.log("done", "ok");                 // severities: info, ok, warning, error
  studio.modal(title, formHtml, async values => { ... });
  await studio.refreshTree(); await studio.selectElement(id);
}
```

Tailwind utility classes (v4, vendored) and the component classes in
`styles.css` (`btn-primary`, `btn-action`, `input`, ...) are available.
No build step: write plain browser JavaScript.

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
