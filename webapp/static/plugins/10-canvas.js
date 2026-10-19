// Architecture modeling plugin (System Composer style).
//
// This entry module installs the pieces under ./canvas/:
//   editor.js     the Architecture tab: interactive SVG canvas (blocks, ports, connectors,
//                 drag/resize/connect, rubber band, zoom/pan, drill-down, context menu,
//                 Property Inspector dock); shown at start-up
//   geometry.js / render.js / toolstrip.js / dock.js / ui.js / styles.js   its parts
//   undo.js       Undo / Redo toolstrip buttons + Ctrl+Z, Ctrl+Y, Ctrl+Shift+Z (all model edits)
//   model.js      "New model…" (System / Software architecture) and the model-type switch
//   inspector.js  "Architecture" inspector section in the Properties tab (tables)
// Everything goes through /api/arch/* (see docs/features/architecture.md).
import { installUndo } from "./canvas/undo.js";
import { installModel } from "./canvas/model.js";
import { installInspector } from "./canvas/inspector.js";
import { installCanvas } from "./canvas/editor.js";

export default async function install(studio) {
  const undo = installUndo(studio);
  const model = installModel(studio);
  installInspector(studio);
  const canvas = installCanvas(studio, { undo });
  studio.architecture = { undo, model, canvas };
  studio.switchTab("architecture");      // the canvas is the start-up view
}
