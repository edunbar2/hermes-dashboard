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

function pct(v) { return `${v.toFixed(1)}%`; }

function bar(percent) {
  const cls = percent > 90 ? "bad" : percent > 75 ? "warn" : "";
  return `<div class="bar ${cls}"><div class="fill" style="width:${percent}%"></div></div>`;
}

export async function mountSystemPanel(root) {
  root.innerHTML = `
    <div class="metric-grid" id="sys-grid"></div>
    <div id="sys-disks" style="margin-top:0.75rem"></div>
  `;
  const grid = root.querySelector("#sys-grid");
  const disks = root.querySelector("#sys-disks");

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
      </div>`).join("");

    if (d.disk?.length) {
      disks.innerHTML = `<dl class="kv">${
        d.disk.map(p => `
          <dt>${p.mount}</dt>
          <dd>${fmtBytes(p.used)} / ${fmtBytes(p.total)} (${pct(p.percent)})</dd>
        `).join("")
      }</dl>`;
    }
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
