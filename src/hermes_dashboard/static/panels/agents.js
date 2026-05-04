// Agent Activity panel — seven roster cards with live kanban-derived status.

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);
}

function fmtRelTime(unix) {
  if (!unix) return "never";
  const d = Date.now() / 1000 - unix;
  if (d < 60) return `${Math.max(0, Math.floor(d))}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
}

function statusClass(agent) {
  if (agent.stale) return "stale";
  const s = String(agent.status || "idle").toLowerCase();
  if (s === "running") return "running";
  if (s === "blocked") return "blocked";
  if (["ready", "todo", "triage", "assigned"].includes(s)) return "assigned";
  if (s === "done") return "done";
  return "idle";
}

function renderAgent(agent) {
  const cls = statusClass(agent);
  const progress = Math.max(0, Math.min(100, Number(agent.progress_percent || 0)));
  return `
    <article class="agent-card ${cls}">
      <div class="agent-head">
        <div class="avatar-ring ${cls}"><img src="${escapeHtml(agent.avatar_url)}" alt="${escapeHtml(agent.name)}"></div>
        <div>
          <div class="agent-name">${escapeHtml(agent.name)}</div>
          <div class="agent-role">${escapeHtml(agent.role)}</div>
        </div>
        <span class="agent-pill ${cls}">${escapeHtml(agent.status || "idle")}</span>
      </div>
      <div class="agent-task">${escapeHtml(agent.current_task || "No active task")}</div>
      <div class="bar agent-progress ${cls}"><div class="fill" style="width:${progress}%"></div></div>
      <div class="agent-meta">
        <span>${escapeHtml(agent.progress_label || "idle")}</span>
        <span>${progress}%</span>
        <span>updated ${fmtRelTime(agent.last_update)}</span>
      </div>
      <div class="agent-counts">
        <span>${agent.active_count ?? 0} active</span>
        <span>${agent.assigned_count ?? 0} queued</span>
        <span>${agent.done_recent_count ?? 0} done/3d</span>
      </div>
    </article>`;
}

export async function mountAgentsPanel(root) {
  root.innerHTML = `
    <div class="agent-toolbar">
      <div id="agent-summary" class="summary-chip">loading roster…</div>
      <div id="agent-stream" class="summary-chip">stream pending</div>
    </div>
    <div class="agent-grid" id="agent-grid"></div>
  `;
  const grid = root.querySelector("#agent-grid");
  const summary = root.querySelector("#agent-summary");
  const stream = root.querySelector("#agent-stream");

  function render(payload) {
    const data = payload.data ?? payload;
    const agents = data.agents || [];
    const active = agents.filter(a => a.active).length;
    summary.textContent = `${active}/${agents.length} agents active · updated ${fmtRelTime(data.updated_at)}`;
    grid.innerHTML = agents.map(renderAgent).join("");
  }

  async function fetchOnce() {
    const r = await fetch("/api/agents/status");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    render(await r.json());
  }

  try {
    await fetchOnce();
  } catch (err) {
    grid.innerHTML = `<div class="bubble error">failed to fetch agent status: ${escapeHtml(err.message || err)}</div>`;
  }

  const es = new EventSource("/api/agents/events");
  es.addEventListener("agents", (e) => {
    stream.textContent = "live";
    try { render(JSON.parse(e.data)); }
    catch (err) { console.warn("agent stream parse", err); }
  });
  es.onerror = () => {
    stream.textContent = "reconnecting";
    setTimeout(fetchOnce, 5000);
  };
}
