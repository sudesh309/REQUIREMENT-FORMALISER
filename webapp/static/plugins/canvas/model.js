// "New model…" (name + System/Software architecture type + root architecture) and the
// model-type switch shown in the toolstrip.
import { esc, openForm, reload } from "./common.js";

const TYPE_LABEL = { system: "System architecture", software: "Software architecture" };

export function installModel(studio) {
  studio.registerToolbarButton({
    id: "new-model", label: "New model…", group: "Model",
    title: "New architecture model (System or Software)", onClick: newModel,
  });
  const typeBtn = studio.registerToolbarButton({
    id: "model-type", label: "System", group: "Model",
    title: "Architecture model type", onClick: changeType,
  });

  async function refreshType() {
    try {
      const t = await studio.api("GET", "/api/arch/model-type");
      typeBtn.textContent = t.type === "software" ? "Software" : "System";
      typeBtn.dataset.type = t.type;
      typeBtn.title = `${TYPE_LABEL[t.type]} — ports: ${t.allowed_port_kinds.join(", ")} (click to change)`;
    } catch { /* logged */ }
  }
  studio.on("model-changed", refreshType);

  function newModel() {
    openForm(studio, "New architecture model", `
      <label class="block text-sm">Model name
        <input class="input" name="name" value="AvionicsSystem" required /></label>
      <fieldset class="text-sm">
        <legend class="mb-1">Architecture type</legend>
        <label class="inline-flex items-center gap-1 mr-4">
          <input type="radio" name="type" value="system" checked /> System (data + physical ports)</label>
        <label class="inline-flex items-center gap-1">
          <input type="radio" name="type" value="software" /> Software (data + client/server ports)</label>
      </fieldset>
      <label class="block text-sm">Root architecture
        <input class="input" name="arch" value="System" placeholder="leave empty for none" /></label>
      <p class="text-xs text-slate-500">The current project is replaced (save it first).</p>
    `, async (v) => {
      const name = (v.name || "").trim() || "UntitledProject";
      await studio.api("POST", "/api/new", { name, type: v.type || "system" });
      let arch = null;
      if ((v.arch || "").trim()) arch = await studio.api("POST", "/api/arch/architecture", { name: v.arch.trim() });
      studio.log(`New ${v.type || "system"} model ${name}`, "ok");
      await reload(studio, arch?.id || null);
    });
  }

  function changeType() {
    const current = typeBtn.dataset.type || "system";
    openForm(studio, "Architecture model type", `
      <label class="block text-sm">Type
        <select class="input" name="type">
          <option value="system"${current === "system" ? " selected" : ""}>${esc(TYPE_LABEL.system)} — data, physical ports</option>
          <option value="software"${current === "software" ? " selected" : ""}>${esc(TYPE_LABEL.software)} — data, client/server ports</option>
        </select></label>
      <label class="inline-flex items-center gap-1 text-sm">
        <input type="checkbox" name="force" /> Change even if existing ports use kinds the new type does not allow
        (the validator will report them)</label>
    `, async (v) => {
      const r = await studio.api("POST", "/api/arch/model-type", { type: v.type, force: v.force === "on" });
      studio.log(`Model type: ${r.type}`, "ok");
      await reload(studio);
    });
  }

  return { refreshType };
}
