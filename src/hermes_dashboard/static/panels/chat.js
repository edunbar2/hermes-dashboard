// Chat panel — one-shot send to /api/chat/send. Persists session id in
// sessionStorage so reloading the tab keeps the same conversation.

export async function mountChatPanel(root) {
  root.innerHTML = `
    <div class="chat-log" id="chat-log"></div>
    <form class="chat-input-row" id="chat-form">
      <input class="chat-input" id="chat-input" type="text"
             placeholder="Message Hermes…" autocomplete="off">
      <button class="chat-send" type="submit" id="chat-send">Send</button>
    </form>
  `;

  const log = root.querySelector("#chat-log");
  const form = root.querySelector("#chat-form");
  const input = root.querySelector("#chat-input");
  const send = root.querySelector("#chat-send");

  let sessionId = sessionStorage.getItem("hermes_dash_sid") || null;

  function append(role, text) {
    const div = document.createElement("div");
    div.className = `bubble ${role}`;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  // Surface upstream reachability up front so the user knows what to expect.
  try {
    const h = await fetch("/api/chat/health").then(r => r.json());
    if (!h.reachable) {
      append("error", `Hermes api_server unreachable at ${h.url}. Chat won't work until it's running.`);
    }
  } catch (_) { /* ignore */ }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = input.value.trim();
    if (!msg) return;
    append("user", msg);
    input.value = "";
    send.disabled = true;
    const placeholder = append("bot", "…");
    try {
      const r = await fetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg, session_id: sessionId }),
      });
      const body = await r.json();
      if (!r.ok) {
        placeholder.classList.remove("bot");
        placeholder.classList.add("error");
        placeholder.textContent = `error ${r.status}: ${body.detail || JSON.stringify(body)}`;
        return;
      }
      // The chat API returns { reply, session_id, model, raw }.
      placeholder.textContent = body.reply ?? "(empty reply)";
      if (body.session_id) {
        sessionId = body.session_id;
        sessionStorage.setItem("hermes_dash_sid", sessionId);
      }
    } catch (err) {
      placeholder.classList.remove("bot");
      placeholder.classList.add("error");
      placeholder.textContent = `network error: ${err.message || err}`;
    } finally {
      send.disabled = false;
      input.focus();
    }
  });

  input.focus();
}
