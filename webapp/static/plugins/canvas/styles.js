// Styles for the architecture canvas tab (injected once; no build step).
let done = false;

export function injectCanvasStyles() {
  if (done) return;
  done = true;
  const st = document.createElement("style");
  st.dataset.plugin = "architecture-canvas";
  st.textContent = `
  .arch-pane { background:#f1f5f9; min-height:0; }
  /* toolstrip */
  .arch-toolstrip { display:flex; flex-wrap:wrap; align-items:stretch; gap:0; background:#fff; border-bottom:1px solid #e2e8f0;
                    padding:2px 4px 0; font-size:11px; color:#334155; }
  .arch-tsec { display:flex; flex-direction:column; border-right:1px solid #e2e8f0; padding:0 6px; }
  .arch-tsec:last-child { border-right:0; }
  .arch-tsec-body { display:flex; align-items:center; gap:2px; flex:1; }
  .arch-tsec-label { text-align:center; font-size:9.5px; letter-spacing:.06em; text-transform:uppercase; color:#94a3b8; padding:1px 0 2px; }
  .arch-tcol { display:flex; flex-direction:column; gap:1px; }
  .arch-tgrid { display:grid; grid-template-columns:repeat(3, auto); gap:1px 2px; }
  .arch-tbtn { display:inline-flex; align-items:center; gap:4px; padding:2px 6px; border-radius:4px; border:1px solid transparent;
               background:transparent; color:#334155; white-space:nowrap; line-height:1.25; }
  .arch-tbtn:hover:not([disabled]) { background:#eff6ff; border-color:#bfdbfe; }
  .arch-tbtn[disabled] { opacity:.38; cursor:default; }
  .arch-tbtn[aria-pressed="true"] { background:#dbeafe; border-color:#93c5fd; color:#1d4ed8; }
  .arch-tbtn.big { flex-direction:column; gap:1px; padding:3px 7px; min-width:52px; }
  .arch-tbtn.big .arch-ico { width:22px; height:22px; }
  .arch-tbtn[hidden] { display:none; }
  .arch-zoom { min-width:44px; justify-content:center; font-variant-numeric:tabular-nums; }
  .arch-ico { width:15px; height:15px; fill:none; stroke:currentColor; stroke-width:1.3; stroke-linecap:round; stroke-linejoin:round; flex:none; }
  /* bar */
  .arch-bar { display:flex; align-items:center; gap:8px; padding:3px 8px; background:#f8fafc; border-bottom:1px solid #e2e8f0;
              font-size:12px; min-height:30px; flex-wrap:wrap; }
  .arch-path { display:flex; align-items:center; gap:3px; flex-wrap:wrap; }
  .arch-path button { color:#1d4ed8; padding:0 3px; border-radius:3px; }
  .arch-path button:hover { background:#dbeafe; }
  .arch-path .arch-up { color:#475569; display:inline-flex; }
  .arch-crumb-sep { color:#94a3b8; }
  .arch-spacer { flex:1; }
  .arch-open { display:flex; align-items:center; gap:4px; color:#64748b; }
  .arch-open .input { width:auto; max-width:220px; padding:1px 4px; font-size:12px; }
  .arch-newarch { font-size:12px; color:#1d4ed8; padding:1px 6px; border-radius:4px; white-space:nowrap; }
  .arch-newarch:hover { background:#eff6ff; }
  .arch-banners { display:flex; gap:6px; flex-wrap:wrap; }
  .arch-banner { display:inline-flex; align-items:center; gap:6px; background:#fef9c3; border:1px solid #fde68a; color:#713f12;
                 padding:1px 4px 1px 8px; border-radius:999px; }
  .arch-banner.hl { background:#fff7ed; border-color:#fed7aa; }
  .arch-banner.hl i { width:9px; height:9px; border-radius:999px; background:var(--hl); display:inline-block; }
  .arch-banner label { display:inline-flex; gap:3px; align-items:center; }
  /* main */
  .arch-main { flex:1; display:flex; min-height:0; }
  .arch-host { position:relative; flex:1; min-width:0; overflow:hidden; outline:none; background:#fbfcfe; }
  .arch-host:focus-visible { box-shadow:inset 0 0 0 2px #93c5fd; }
  .arch-svg { width:100%; height:100%; display:block; user-select:none; -webkit-user-select:none; touch-action:none;
              font-family:ui-sans-serif, system-ui, sans-serif; }
  .arch-svg.is-empty { visibility:hidden; }
  .arch-host.space, .arch-host.mode-pan { cursor:grab; }
  .arch-host.panning { cursor:grabbing; }
  .arch-host.dragging { cursor:move; }
  .arch-host.connecting, .arch-host.mode-connect { cursor:crosshair; }
  .arch-host.resizing { cursor:nwse-resize; }
  /* frame */
  .arch-frame-box { fill:#ffffff; stroke:#94a3b8; stroke-width:1.2; }
  .arch-frame-head { stroke:#e2e8f0; }
  .arch-frame-title { font-size:13px; font-weight:600; fill:#0f172a; cursor:text; }
  .arch-frame-sub { font-size:11px; font-weight:400; fill:#64748b; }
  .arch-stereo { font-size:10px; fill:#7c3aed; font-weight:400; }
  /* blocks */
  .arch-block { cursor:pointer; }
  .arch-body { stroke-width:1.4; filter:drop-shadow(0 1px 1.5px rgb(15 23 42 / .12)); }
  .arch-block:hover .arch-body { stroke:#2563eb; }
  .arch-block.sel .arch-body { stroke:#2563eb; stroke-width:2.6; }
  .arch-block.ref .arch-body { stroke-width:1.8; }
  .arch-name { font-size:12.5px; font-weight:600; cursor:text; }
  .arch-def { font-size:10.5px; fill:#475569; font-style:italic; }
  .arch-refmark rect { fill:none; stroke:#2563eb; stroke-width:1.4; }
  .arch-compmark rect { fill:none; stroke:#64748b; stroke-width:1; }
  .arch-compmark rect + rect { fill:#94a3b8; stroke:none; }
  .arch-pill rect { fill:#e0e7ff; }
  .arch-pill text { font-size:8.5px; fill:#3730a3; }
  .arch-icon { font-size:12px; }
  .arch-resize { stroke:#94a3b8; stroke-width:1.2; opacity:0; pointer-events:none; }
  .arch-resize-hit { fill:transparent; cursor:nwse-resize; }
  .arch-block:hover .arch-resize, .arch-block.sel .arch-resize { opacity:1; }
  .arch-hl-ring { fill:none; stroke:none; }
  .arch-block.hl .arch-hl-ring { stroke:var(--hl); stroke-width:5; stroke-opacity:.55; filter:url(#arch-glow); }
  .arch-block.hl .arch-body { stroke:var(--hl); stroke-width:2.4; }
  .arch-block.f-dim, .arch-conn.f-dim { opacity:.14; }
  .arch-block.f-hidden, .arch-conn.f-hidden { display:none; }
  .arch-block.drop-target .arch-body { stroke:#16a34a; stroke-width:3; }
  .arch-block.hover-target .arch-body { stroke:#16a34a; stroke-dasharray:5 3; stroke-width:2.2; }
  /* ports */
  .arch-port { cursor:crosshair; }
  .arch-port-hit { fill:transparent; }
  .arch-port-ring { fill:none; stroke:none; }
  .arch-port-glyph { stroke-width:1.2; }
  .arch-port-label { font-size:11.5px; fill:#334155; cursor:text; }
  .arch-port:hover .arch-port-ring { stroke:#2563eb; stroke-width:1.5; fill:rgb(219 234 254 / .6); }
  .arch-port.sel .arch-port-ring { stroke:#2563eb; stroke-width:2; fill:rgb(191 219 254 / .7); }
  .arch-port.sel .arch-port-label { fill:#1d4ed8; font-weight:600; }
  .arch-port.hl .arch-port-ring { stroke:var(--hl); stroke-width:3; fill:none; filter:url(#arch-glow); }
  .arch-port.source .arch-port-ring { stroke:#2563eb; stroke-width:2.5; fill:rgb(191 219 254 / .8); }
  .arch-port.can .arch-port-ring { stroke:#16a34a; stroke-width:1.6; fill:rgb(220 252 231 / .8); }
  .arch-port.cannot { opacity:.25; }
  .arch-port.can.hover-target .arch-port-ring { stroke-width:3; }
  .arch-port.drop-target .arch-port-ring { stroke:#16a34a; stroke-width:3; }
  /* connectors */
  .arch-conn { cursor:pointer; }
  .arch-conn-hit { fill:none; stroke:transparent; stroke-width:11; stroke-linejoin:round; }
  .arch-conn-line { fill:none; stroke-width:1.6; stroke-linejoin:round; }
  .arch-conn.k-physical .arch-conn-line { stroke-width:2.4; }
  .arch-conn.k-client-server .arch-conn-line { stroke-dasharray:7 3; }
  .arch-conn.bad .arch-conn-line { stroke-dasharray:4 3; }
  .arch-conn:hover .arch-conn-hit { stroke:rgb(147 197 253 / .35); }
  .arch-conn.sel .arch-conn-hit { stroke:rgb(59 130 246 / .35); }
  .arch-conn.sel .arch-conn-line { stroke-width:2.4; }
  .arch-conn.hl .arch-conn-hit { stroke:var(--hl); stroke-opacity:.45; }
  .arch-conn.drop-target .arch-conn-hit { stroke:rgb(22 163 74 / .45); }
  .arch-conn-label { font-size:10.5px; fill:#1e293b; paint-order:stroke; stroke:#fff; stroke-width:3.5px; stroke-linejoin:round; cursor:text; }
  .arch-clabel { cursor:pointer; }
  .arch-clabel.sel .arch-conn-label { fill:#1d4ed8; font-weight:600; }
  .arch-clabel.hl .arch-conn-label { fill:var(--hl); font-weight:600; }
  .arch-clabel.bad .arch-conn-label { fill:#b91c1c; }
  .arch-clabel.f-dim { opacity:.14; }
  .arch-clabel.f-hidden { display:none; }
  /* overlay */
  .arch-l-over { pointer-events:none; }
  .arch-seg { fill:#fff; stroke:#2563eb; stroke-width:1.4; pointer-events:all; }
  .arch-band { fill:rgb(59 130 246 / .08); stroke:#3b82f6; stroke-width:1; stroke-dasharray:4 3; vector-effect:non-scaling-stroke; }
  .arch-rubber { fill:none; stroke:#64748b; stroke-width:1.6; stroke-dasharray:5 4; vector-effect:non-scaling-stroke; }
  .arch-rubber.ok, .arch-rubber.new { stroke:#16a34a; }
  .arch-rubber.bad { stroke:#dc2626; }
  /* empty state, status, toasts, menu, inline edit */
  .arch-empty { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; }
  .arch-empty[hidden] { display:none; }
  .arch-empty-card { background:#fff; border:1px dashed #94a3b8; border-radius:10px; padding:22px 26px; max-width:380px; text-align:center;
                     color:#475569; font-size:13px; display:flex; flex-direction:column; gap:10px; align-items:center; }
  .arch-empty-title { font-size:15px; font-weight:600; color:#0f172a; }
  .arch-status { position:absolute; left:8px; bottom:6px; right:8px; font-size:11px; color:#64748b; pointer-events:none;
                 white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .arch-toasts { position:absolute; left:50%; bottom:28px; transform:translateX(-50%); display:flex; flex-direction:column; gap:6px;
                 align-items:center; z-index:20; max-width:min(560px, 90%); }
  .arch-toast { background:#1e293b; color:#f8fafc; padding:7px 12px; border-radius:6px; font-size:12.5px; cursor:pointer;
                box-shadow:0 6px 20px rgb(15 23 42 / .25); }
  .arch-toast.error { background:#991b1b; }
  .arch-toast.warning { background:#92400e; }
  .arch-toast.ok { background:#166534; }
  .arch-menu { position:absolute; z-index:30; min-width:200px; background:#fff; border:1px solid #cbd5e1; border-radius:6px;
               box-shadow:0 12px 30px rgb(15 23 42 / .2); padding:4px; font-size:12.5px; }
  .arch-menu[hidden] { display:none; }
  .arch-menu-item { display:flex; width:100%; justify-content:space-between; gap:16px; padding:4px 10px; border-radius:4px;
                    text-align:left; color:#0f172a; }
  .arch-menu-item:hover:not([disabled]), .arch-menu-item:focus { background:#eff6ff; outline:none; }
  .arch-menu-item[disabled], .arch-menu-chip[disabled] { color:#94a3b8; }
  .arch-menu-item.danger { color:#b91c1c; }
  .arch-menu-item kbd { color:#94a3b8; font-size:11px; font-family:inherit; }
  .arch-menu-sep { height:1px; background:#e2e8f0; margin:3px 2px; }
  .arch-menu-row { display:flex; flex-wrap:wrap; align-items:center; gap:3px; padding:3px 8px; }
  .arch-menu-glabel { color:#64748b; margin-right:4px; }
  .arch-menu-chip { padding:1px 7px; border:1px solid #cbd5e1; border-radius:999px; }
  .arch-menu-chip:hover:not([disabled]), .arch-menu-chip:focus { background:#dbeafe; border-color:#93c5fd; outline:none; }
  .arch-inline-edit { position:absolute; z-index:25; font-size:13px; padding:2px 6px; border:2px solid #2563eb; border-radius:4px;
                      background:#fff; box-shadow:0 4px 12px rgb(15 23 42 / .2); }
  .arch-inline-edit[hidden] { display:none; }
  /* dock */
  .arch-dock { width:272px; flex:none; border-left:1px solid #e2e8f0; background:#fff; overflow:auto; font-size:12px; }
  .arch-dock[hidden] { display:none; }
  .arch-dock-head { display:flex; justify-content:space-between; align-items:center; padding:6px 10px; font-size:11px;
                    letter-spacing:.06em; text-transform:uppercase; color:#64748b; border-bottom:1px solid #e2e8f0; background:#f8fafc;
                    position:sticky; top:0; z-index:1; }
  .arch-dock-body { padding:8px 10px; display:flex; flex-direction:column; gap:6px; }
  .arch-dock-kind { display:flex; align-items:center; gap:6px; font-weight:600; color:#0f172a; font-size:12.5px; }
  .arch-dock-sub { font-size:10.5px; text-transform:uppercase; letter-spacing:.05em; color:#64748b; margin-top:6px; }
  .arch-dock-muted { color:#94a3b8; }
  .arch-dock-btns { display:flex; flex-wrap:wrap; gap:4px; }
  .arch-field { display:grid; grid-template-columns:72px 1fr; align-items:center; gap:6px; }
  .arch-field > span { color:#475569; }
  .arch-field .input { padding:2px 5px; font-size:12px; }
  .arch-dock-ports { display:flex; flex-direction:column; gap:3px; }
  .arch-prow { display:grid; grid-template-columns:minmax(0,1fr) 62px 74px 18px; gap:3px; align-items:center; }
  .arch-prow .input { padding:1px 3px; font-size:11.5px; min-width:0; }
  .arch-prow.usage-only input[data-dock-port="name"] { border-style:dashed; }
  .arch-kv { display:flex; justify-content:space-between; gap:8px; }
  .arch-kv > span { color:#64748b; }
  .arch-kv > b { font-weight:500; text-align:right; word-break:break-word; }
  .arch-stereo-row { color:#7c3aed; }
  .arch-stereo-row .arch-kv { color:#334155; padding-left:8px; }
  .arch-dock-part { display:contents; }
  .arch-dock-stereo { display:flex; flex-direction:column; gap:6px; }
  .arch-dock-stereo[hidden] { display:none; }
  .arch-st-bar select { width:100%; padding:2px 5px; font-size:12px; }
  .arch-st-partial { display:flex; align-items:center; justify-content:space-between; gap:6px; color:#6d28d9; }
  .arch-st-partial .btn-action { padding:0 6px; font-size:11px; }
  .arch-dock .pf-app { margin-bottom:0; }
  .arch-dock .pf-app > summary { font-size:12px; padding:3px 6px; gap:5px; }
  .arch-dock .pf-props { grid-template-columns:minmax(0, 40%) minmax(0, 1fr) auto; gap:3px 5px; padding:6px; font-size:12px; }
  .arch-dock .pf-props .input { padding:2px 5px; font-size:12px; min-width:0; width:100%; }
  .arch-dock .pf-props .pf-unit { max-width:46px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .arch-dock .pf-msg { margin:0; min-height:0; word-break:break-word; }
  .arch-dock .pf-msg:empty { display:none; }
  .arch-tips { margin:0; padding-left:16px; list-style:disc; color:#64748b; display:flex; flex-direction:column; gap:2px; }
  `;
  document.head.appendChild(st);
}
