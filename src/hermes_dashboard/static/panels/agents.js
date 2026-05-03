// Agents panel — polls /api/hermes/status every 5s and renders gateway,
// session count, cron count, and the most recent sessions.

function fmtTime(unix) {
  if (!unix) return "—";
  const d = new Date(unix * 1000);
  return d.toLocaleString();
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

export async function mountAgentsPanel(root) {
  root.innerHTML = `
    <div id="ag-summary"></div>
    <div id="ag-sessions" style="margin-top:0.75rem"></div>
  `;
  const summary = root.querySelector("#ag-summary");
  const sessions = root.querySelector("#ag-sessions");

  async function tick() {
    try {
      const r = await fetch("/api/hermes/status");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = await r.json();
      const d = body.data || body;
      const gw = d.gateway || {};
      summary.innerHTML = `
        <dl class="kv">
          <dt>Gateway</dt>
          <dd>${gw.running ? `✓ running (pid ${gw.pid ?? "?"})` : "✗ stopped"}</dd>
          <dt>Active sessions</dt>
          <dd>${d.sessions_count ?? 0}</dd>
          <dt>Cron jobs (active)</dt>
          <dd>${d.cron_active ?? 0}</dd>
        </dl>`;

      const recent = d.recent_sessions || [];
      if (recent.length) {
        sessions.innerHTML =
          `<h3 style="margin:0.75rem 0 0.5rem 0; font-size:0.75rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:0.05em;">Recent sessions</h3>` +
          recent.slice(0, 5).map(s => {
            const label = escapeHtml(s.source || s.platform || "session");
            const title = escapeHtml(s.title || s.session_id || "—");
            const when = fmtTime(s.last_updated || s.updated_at);
            return `
              <div class="metric" style="margin-bottom:0.5rem;">
                <div class="metric-label">${label}</div>
                <div style="font-size:0.95rem; margin-top:0.25rem;">${title}</div>
                <div style="font-size:0.8rem; color:var(--text-dim); margin-top:0.25rem;">${when}</div>
              </div>`;
          }).join("");
      } else {
        sessions.innerHTML = "";
      }
    } catch (e) {
      summary.innerHTML = `<div class="bubble error">failed to fetch /api/hermes/status: ${escapeHtml(e.message || e)}</div>`;
      sessions.innerHTML = "";
    }
  }

  await tick();
  setInterval(tick, 5000);
}
