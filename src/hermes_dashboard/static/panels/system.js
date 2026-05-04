// System metrics panel — subscribes to /api/system/stream (SSE) and rerenders
// on every push. Falls back to polling if EventSource isn't available.

function fmtBytes(n) {
  if (n == null) return "—";
  const u = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(1)} ${u[i]}`;
}

function pct(v) { return `${Number(v ?? 0).toFixed(1)}%`; }

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);
}

function bar(percent) {
  const safe = Math.max(0, Math.min(100, Number(percent || 0)));
  const cls = safe > 90 ? "bad" : safe > 75 ? "warn" : "";
  return `<div class="bar ${cls}"><div class="fill" style="width:${safe}%"></div></div>`;
}

function storageCard(disks) {
  const rows = (disks || []).slice(0, 6);
  if (!rows.length) {
    return `
      <div class="metric storage-card">
        <div class="metric-label">Storage</div>
        <div class="metric-value">No mounted disks</div>
      </div>`;
  }
  const worst = rows.reduce((a, b) => Number(a.percent || 0) >= Number(b.percent || 0) ? a : b);
  return `
    <div class="metric storage-card">
      <div class="storage-head">
        <div>
          <div class="metric-label">Storage</div>
          <div class="metric-value">${escapeHtml(worst.mount)} · ${pct(worst.percent)}</div>
        </div>
        <div class="storage-free">${fmtBytes(worst.free)} free</div>
      </div>
      <div class="storage-list">
        ${rows.map(p => `
          <div class="storage-row">
            <div class="storage-row-top"><span>${escapeHtml(p.mount)}</span><span>${fmtBytes(p.used)} / ${fmtBytes(p.total)}</span></div>
            ${bar(p.percent)}
          </div>`).join("")}
      </div>
    </div>`;
}

export async function mountSystemPanel(root) {
  root.innerHTML = `
    <div class="metric-grid" id="sys-grid"></div>
  `;
  const grid = root.querySelector("#sys-grid");

  function render(snap) {
    const d = snap.data || snap;
    const cells = [
      { label: "CPU",      value: pct(d.cpu_percent),                              barv: d.cpu_percent },
      { label: "Memory",   value: `${fmtBytes(d.memory.used)} / ${fmtBytes(d.memory.total)}`, barv: d.memory.percent },
      { label: "Swap",     value: pct(d.swap.percent),                             barv: d.swap.percent },
      { label: "Load",     value: d.load.map(x => x.toFixed(2)).join(" ") },
      { label: "Net up",   value: fmtBytes(d.network.bytes_sent) },
      { label: "Net down", value: fmtBytes(d.network.bytes_recv) },
    ];
    grid.innerHTML = cells.map(c => `
      <div class="metric">
        <div class="metric-label">${c.label}</div>
        <div class="metric-value">${c.value}</div>
        ${c.barv != null ? bar(c.barv) : ""}
      </div>`).join("") + storageCard(d.disk);
  }

  // Prime with a single fetch so the panel isn't blank for the first second.
  try {
    const r = await fetch("/api/system/metrics");
    if (r.ok) render(await r.json());
  } catch (err) {
    console.warn("initial metrics fetch failed", err);
  }

  const es = new EventSource("/api/system/stream");
  es.onmessage = (e) => {
    try { render(JSON.parse(e.data)); }
    catch (err) { console.warn("system stream parse", err); }
  };
  es.onerror = () => { /* browser auto-reconnects; nothing to do */ };
}
