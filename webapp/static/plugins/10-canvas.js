// Architecture modeling plugin (System Composer style).
//
// This entry module installs the pieces under ./canvas/:
//   undo.js       Undo / Redo toolstrip buttons + Ctrl+Z, Ctrl+Y, Ctrl+Shift+Z (all model edits)
//   model.js      "New model…" (System / Software architecture) and the model-type switch
//   inspector.js  "Architecture" inspector section: components, ports, connectors, duplicate,
//                 create-component-from-selection, expand, save as reference, inline, arrange
// The graphical canvas editor builds on the same /api/arch/* endpoints (view model:
// GET /api/arch/view/<id>; see docs/features/architecture.md) and is added as
// further modules under ./canvas/.
import { installUndo } from "./canvas/undo.js";
import { installModel } from "./canvas/model.js";
import { installInspector } from "./canvas/inspector.js";

export default async function install(studio) {
  const undo = installUndo(studio);
  const model = installModel(studio);
  installInspector(studio);
  studio.architecture = { undo, model };
}
