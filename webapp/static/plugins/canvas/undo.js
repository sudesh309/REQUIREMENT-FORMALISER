// Undo / redo toolstrip buttons and Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z for every model edit.
import { reload } from "./common.js";

export function installUndo(studio) {
  let busy = false;
  const undoBtn = studio.registerToolbarButton({
    id: "undo", label: "↶ Undo", group: "Edit", title: "Undo (Ctrl+Z)", onClick: () => step("undo"),
  });
  const redoBtn = studio.registerToolbarButton({
    id: "redo", label: "↷ Redo", group: "Edit", title: "Redo (Ctrl+Y)", onClick: () => step("redo"),
  });
  undoBtn.disabled = redoBtn.disabled = true;

  function show(s) {
    undoBtn.disabled = !s.can_undo;
    redoBtn.disabled = !s.can_redo;
    undoBtn.title = s.can_undo ? `Undo ${s.undo_label} (Ctrl+Z)` : "Nothing to undo (Ctrl+Z)";
    redoBtn.title = s.can_redo ? `Redo ${s.redo_label} (Ctrl+Y)` : "Nothing to redo (Ctrl+Y)";
    studio.emit("undo-state", s);      // the canvas toolstrip mirrors these buttons
  }

  async function refreshState() {
    try { show(await studio.api("GET", "/api/undo/state")); } catch { /* logged by studio.api */ }
  }

  async function step(which) {
    if (busy) return;
    busy = true;
    try {
      const r = await studio.api("POST", `/api/${which}`);
      if (!r.ok) { studio.log(r.reason, "warning"); show(r); return; }
      studio.log(which === "undo" ? `Undo: ${r.redo_label}` : `Redo: ${r.undo_label}`, "ok");
      studio.emit(which, r);
      await reload(studio);           // emits model-changed, which refreshes the buttons
    } catch (e) {
      console.warn(e);
    } finally {
      busy = false;
    }
  }

  studio.registerShortcut({ key: "z", ctrl: true, handler: () => step("undo") });
  studio.registerShortcut({ key: "z", ctrl: true, shift: true, handler: () => step("redo") });
  studio.registerShortcut({ key: "y", ctrl: true, handler: () => step("redo") });
  studio.on("model-changed", refreshState);
  studio.on("element-changed", refreshState);     // edits saved in place (no tree refresh)
  return { undo: () => step("undo"), redo: () => step("redo"), refreshState };
}
