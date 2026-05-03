// Kanban panel — read-only view of Hermes' kanban board.
//
// Renders three columns (Backlog / In Progress / Done), with cards showing
// title, priority, assignee, and a relative timestamp. Clicking a card opens
// a modal with body, comments, and recent task_events. Live updates flow in
// over SSE — the server emits a "board" event whenever task_events grows.

function fmtRelTime(unix) {
  if (!unix) return "—";
  const d = Date.now() / 1000 - unix;
  if (d < 60)    return `${Math.floor(d)}s ago`;
  if (d < 3600)  return `${Math.floor(d / 60)}m ago`;
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
  return `${Math.floor(d / 86400)}d ago`;
}

function priClass(p) {
  if (p == null) return "pri-3";
  if (p <= 1) return "pri-1";
  if (p <= 2) return "pri-2";
  return "pri-3";
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);
}

export async function mountKanbanPanel(root) {
  root.innerHTML = `<div class="kanban" id="kanban-grid"></div>`;
  const grid = root.querySelector("#kanban-grid");
  const modalBg = document.getElementById("kb-modal-bg");
  const modalContent = document.getElementById("kb-modal-content");
  const modalClose = document.getElementById("kb-modal-close");

  function render(snap) {
    const data = snap.data ?? snap;
    if (!data.available) {
      grid.innerHTML = `<div style="color:var(--text-dim); padding:1rem;">
        Kanban DB not found at <code>~/.hermes/kanban.db</code>.
        Create a task with the agent to initialize it.
      </div>`;
      return;
    }

    grid.innerHTML = data.columns.map(col => `
      <div class="kanban-column">
        <h3>${escapeHtml(col.name)} <span class="count">${col.tasks.length}</span></h3>
        <div class="kanban-cards">
          ${col.tasks.map(t => `
            <div class="kanban-card" data-task-id="${escapeHtml(t.id)}">
              <div class="title">${escapeHtml(t.title)}</div>
              <div class="meta">
                <span class="${priClass(t.priority)}">P${t.priority ?? "—"}</span>
                <span>${escapeHtml(t.assignee || "—")}</span>
                <span>${fmtRelTime(t.completed_at || t.started_at || t.created_at)}</span>
              </div>
            </div>
          `).join("")}
        </div>
      </div>`).join("");

    grid.querySelectorAll(".kanban-card").forEach(el => {
      el.addEventListener("click", () => openTask(el.dataset.taskId));
    });
  }

  async function openTask(id) {
    try {
      const r = await fetch(`/api/kanban/tasks/${encodeURIComponent(id)}`);
      if (!r.ok) {
        modalContent.innerHTML =
          `<p style="color:var(--bad)">Failed to load task ${escapeHtml(id)}: HTTP ${r.status}</p>`;
        modalBg.classList.add("open");
        return;
      }
      const body = await r.json();
      const t = body.data.task;
      const comments = body.data.comments || [];
      const events = body.data.events || [];

      modalContent.innerHTML = `
        <h3>${escapeHtml(t.title)}</h3>
        <dl class="kv">
          <dt>ID</dt><dd>${escapeHtml(t.id)}</dd>
          <dt>Status</dt><dd>${escapeHtml(t.status)}</dd>
          <dt>Priority</dt><dd>P${t.priority ?? "—"}</dd>
          <dt>Assignee</dt><dd>${escapeHtml(t.assignee || "—")}</dd>
          <dt>Created</dt><dd>${fmtRelTime(t.created_at)}</dd>
          ${t.started_at   ? `<dt>Started</dt><dd>${fmtRelTime(t.started_at)}</dd>` : ""}
          ${t.completed_at ? `<dt>Completed</dt><dd>${fmtRelTime(t.completed_at)}</dd>` : ""}
        </dl>
        ${t.body   ? `<div class="kb-modal-section"><strong>Body</strong><div class="kb-comment">${escapeHtml(t.body)}</div></div>` : ""}
        ${t.result ? `<div class="kb-modal-section"><strong>Result</strong><div class="kb-comment">${escapeHtml(t.result)}</div></div>` : ""}
        <div class="kb-modal-section">
          <strong>Comments (${comments.length})</strong>
          ${comments.length ? comments.map(c => `
            <div class="kb-comment">
              <div style="font-size:0.75rem; color:var(--text-dim);">
                ${escapeHtml(c.author || "—")} · ${fmtRelTime(c.created_at)}
              </div>
              <div>${escapeHtml(c.body)}</div>
            </div>`).join("") :
            `<div style="color:var(--text-dim); margin-top:0.4rem;">No comments yet.</div>`}
        </div>
        <div class="kb-modal-section">
          <strong>Recent events (${events.length})</strong>
          ${events.length ? events.slice(0, 10).map(e => `
            <div class="kb-event">
              <div><span class="kind">${escapeHtml(e.kind)}</span> · ${fmtRelTime(e.created_at)}</div>
              ${e.payload ? `<div style="font-family:var(--mono); font-size:0.8rem; color:var(--text-dim); margin-top:0.25rem; word-break:break-all;">${escapeHtml(e.payload)}</div>` : ""}
            </div>`).join("") :
            `<div style="color:var(--text-dim); margin-top:0.4rem;">No events yet.</div>`}
        </div>`;
      modalBg.classList.add("open");
    } catch (err) {
      console.error("kanban detail fetch", err);
    }
  }

  modalClose.addEventListener("click", () => modalBg.classList.remove("open"));
  modalBg.addEventListener("click", (e) => {
    if (e.target === modalBg) modalBg.classList.remove("open");
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") modalBg.classList.remove("open");
  });

  // Initial fetch so the board renders immediately even if SSE is slow.
  try {
    const r = await fetch("/api/kanban/board");
    if (r.ok) render(await r.json());
  } catch (err) {
    console.warn("initial kanban fetch failed", err);
  }

  // Live updates — server emits a "board" event whenever task_events grows.
  const es = new EventSource("/api/kanban/events");
  es.addEventListener("board", (e) => {
    try { render(JSON.parse(e.data)); }
    catch (err) { console.warn("kanban stream parse", err); }
  });
  es.onerror = () => { /* browser auto-reconnects */ };
}
