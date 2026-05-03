// Dashboard entry point.
//
// Each panel is an ES module that exports a `mount<Name>Panel(rootEl)` function.
// To add a panel: import its mount fn, register it under the data-panel name,
// and add a corresponding <section data-panel="..."> in index.html.

import { mountSystemPanel } from "/static/panels/system.js";
import { mountAgentsPanel } from "/static/panels/agents.js";
import { mountChatPanel } from "/static/panels/chat.js";

const PANELS = {
  system: mountSystemPanel,
  agents: mountAgentsPanel,
  chat: mountChatPanel,
};

const status = document.getElementById("connection-status");

function setStatus(text, color) {
  status.textContent = text;
  if (color) status.style.color = color;
}

let mountedCount = 0;
let failedCount = 0;

document.querySelectorAll(".panel[data-panel]").forEach((el) => {
  const name = el.dataset.panel;
  const mount = PANELS[name];
  const body = el.querySelector(".panel-body");
  if (!mount) {
    console.warn(`no mount fn for panel: ${name}`);
    return;
  }
  Promise.resolve()
    .then(() => mount(body))
    .then(() => { mountedCount++; })
    .catch((err) => {
      failedCount++;
      console.error(`panel ${name} failed`, err);
      body.innerHTML = `<div class="bubble error">panel ${name} failed: ${err.message || err}</div>`;
    });
});

setStatus("ready", "var(--good)");
