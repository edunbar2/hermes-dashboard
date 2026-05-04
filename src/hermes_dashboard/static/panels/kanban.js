// Mission Board — dashboard task creation + combined Hermes/Dashboard kanban.

function fmtRelTime(unix) {
  if (!unix) return "—";
  const d = Date.now() / 1000 - unix;
  if (d < 60) return `${Math.max(0, Math.floor(d))}s ago`;
  if (d < 3600) return `${Math.floor(d / 60)}m ago`;
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

function cardHtml(t) {
  const source = t.source || "hermes";
  const assignee = t.assignee || (t.selected_agent ? t.selected_agent : "Awaiting Hermione");
  return `
    <div class="kanban-card ${source}" data-task-id="${escapeHtml(t.id)}" data-source="${escapeHtml(source)}">
      <div class="title">${escapeHtml(t.title)}</div>
      <div class="meta">
        <span class="${priClass(t.priority)}">P${t.priority ?? "—"}</span>
        <span class="assignee">${escapeHtml(assignee)}</span>
        <span>${fmtRelTime(t.completed_at || t.updated_at || t.started_at || t.created_at)}</span>
      </div>
      ${t.handoff_status ? `<div class="handoff">${escapeHtml(t.handoff_status)}</div>` : ""}
    </div>`;
}

export async function mountKanbanPanel(root) {
  root.innerHTML = `
    <div class="task-create">
      <div>
        <h3>Create task for Hermione</h3>
        <p>New tasks enter Assigned / Awaiting Hermione. Hermione then chooses the specialist agent and the board follows status changes across sessions.</p>
      </div>
      <form id="task-form" class="task-form">
        <input name="title" maxlength="160" placeholder="Task title" required>
        <select name="priority" title="Priority">
          <option value="1">P1</option><option value="2" selected>P2</option><option value="3">P3</option><option value="4">P4</option><option value="5">P5</option>
        </select>
        <select name="preferred_agent" title="Preferred agent">
          <option value="">Hermione decides</option>
          <option value="hephaestus">Hephaestus</option><option value="argus">Argus</option><option value="athena">Athena</option>
          <option value="aegis">Aegis</option><option value="daedalus">Daedalus</option><option value="vox">Vox</option>
        </select>
        <textarea name="body" rows="2" placeholder="Objective / constraints"></textarea>
      </form>
      <div class="task-actions">
        <button form="task-form" type="submit">queue task</button>
        <div id="task-create-status" class="create-status"></div>
      </div>
    </div>
    <div class="kanban" id="kanban-grid"></div>`;

  const grid = root.querySelector("#kanban-grid");
  const form = root.querySelector("#task-form");
  const createStatus = root.querySelector("#task-create-status");
  const modalBg = document.getElementById("kb-modal-bg");
  const modalContent = document.getElementById("kb-modal-content");
  const modalClose = document.getElementById("kb-modal-close");

  function render(snap) {
    const data = snap.data ?? snap;
    if (!data.available) {
      grid.innerHTML = `<div style="color:var(--text-dim); padding:1rem;">Kanban state unavailable.</div>`;
      return;
    }
    grid.innerHTML = data.columns.map(col => `
      <div class="kanban-column">
        <h3>${escapeHtml(col.name)} <span class="count">${col.tasks.length}</span></h3>
        <div class="kanban-cards">
          ${col.tasks.length ? col.tasks.map(cardHtml).join("") : `<div class="empty-column">No tasks</div>`}
        </div>
      </div>`).join("");

    grid.querySelectorAll(".kanban-card").forEach(el => {
      el.addEventListener("click", () => {
        if (el.dataset.source === "dashboard") openDashboardTask(el.dataset.taskId, snap);
        else openHermesTask(el.dataset.taskId);
      });
    });
  }

  async function fetchBoard() {
    const r = await fetch("/api/tasks/board");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const snap = await r.json();
    render(snap);
    return snap;
  }

  function findDashboardTask(id, snap) {
    const data = snap.data ?? snap;
    for (const col of data.columns || []) {
      for (const t of col.tasks || []) {
        if (t.id === id && t.source === "dashboard") return t;
      }
    }
    return null;
  }

  function openDashboardTask(id, snap) {
    const t = findDashboardTask(id, snap);
    if (!t) return;
    modalContent.innerHTML = `
      <h3>${escapeHtml(t.title)}</h3>
      <dl class="kv">
        <dt>ID</dt><dd>${escapeHtml(t.id)}</dd>
        <dt>Source</dt><dd>dashboard request</dd>
        <dt>Status</dt><dd>${escapeHtml(t.status)}</dd>
        <dt>Assignee</dt><dd>${escapeHtml(t.assignee || "Hermione")}</dd>
        <dt>Preferred</dt><dd>${escapeHtml(t.preferred_agent || "Hermione decides")}</dd>
        <dt>Handoff</dt><dd>${escapeHtml(t.handoff_status || "awaiting_hermione")}</dd>
        <dt>Created</dt><dd>${fmtRelTime(t.created_at)}</dd>
      </dl>
      ${t.body ? `<div class="kb-modal-section"><strong>Body</strong><div class="kb-comment">${escapeHtml(t.body)}</div></div>` : ""}`;
    modalBg.classList.add("open");
  }

  async function openHermesTask(id) {
    try {
      const r = await fetch(`/api/kanban/tasks/${encodeURIComponent(id)}`);
      if (!r.ok) {
        modalContent.innerHTML = `<p style="color:var(--bad)">Failed to load task ${escapeHtml(id)}: HTTP ${r.status}</p>`;
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
          ${t.started_at ? `<dt>Started</dt><dd>${fmtRelTime(t.started_at)}</dd>` : ""}
          ${t.completed_at ? `<dt>Completed</dt><dd>${fmtRelTime(t.completed_at)}</dd>` : ""}
          ${t.current_step_key ? `<dt>Step</dt><dd>${escapeHtml(t.current_step_key)}</dd>` : ""}
        </dl>
        ${t.body ? `<div class="kb-modal-section"><strong>Body</strong><div class="kb-comment">${escapeHtml(t.body)}</div></div>` : ""}
        ${t.result ? `<div class="kb-modal-section"><strong>Result</strong><div class="kb-comment">${escapeHtml(t.result)}</div></div>` : ""}
        <div class="kb-modal-section"><strong>Comments (${comments.length})</strong>
          ${comments.length ? comments.map(c => `<div class="kb-comment"><div style="font-size:0.75rem;color:var(--text-dim);">${escapeHtml(c.author || "—")} · ${fmtRelTime(c.created_at)}</div><div>${escapeHtml(c.body)}</div></div>`).join("") : `<div style="color:var(--text-dim); margin-top:0.4rem;">No comments yet.</div>`}
        </div>
        <div class="kb-modal-section"><strong>Recent events (${events.length})</strong>
          ${events.length ? events.slice(0, 10).map(e => `<div class="kb-event"><div><span class="kind">${escapeHtml(e.kind)}</span> · ${fmtRelTime(e.created_at)}</div>${e.payload ? `<div style="font-family:var(--mono);font-size:0.8rem;color:var(--text-dim);margin-top:0.25rem;word-break:break-all;">${escapeHtml(e.payload)}</div>` : ""}</div>`).join("") : `<div style="color:var(--text-dim); margin-top:0.4rem;">No events yet.</div>`}
        </div>`;
      modalBg.classList.add("open");
    } catch (err) {
      console.error("kanban detail fetch", err);
    }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    createStatus.textContent = "queuing…";
    try {
      const r = await fetch("/api/tasks", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          title: data.title,
          body: data.body || "",
          priority: Number(data.priority || 2),
          preferred_agent: data.preferred_agent || null,
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      form.reset();
      createStatus.textContent = "queued for Hermione";
      await fetchBoard();
    } catch (err) {
      createStatus.textContent = `failed: ${err.message || err}`;
    }
  });

  modalClose.addEventListener("click", () => modalBg.classList.remove("open"));
  modalBg.addEventListener("click", (e) => { if (e.target === modalBg) modalBg.classList.remove("open"); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") modalBg.classList.remove("open"); });

  try { await fetchBoard(); } catch (err) { grid.innerHTML = `<div class="bubble error">failed to load board: ${escapeHtml(err.message || err)}</div>`; }

  const es = new EventSource("/api/tasks/events");
  es.addEventListener("board", (e) => { try { render(JSON.parse(e.data)); } catch (err) { console.warn("board stream parse", err); } });
  es.onerror = () => { setTimeout(fetchBoard, 5000); };
}
