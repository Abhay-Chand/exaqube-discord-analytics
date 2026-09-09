// Relative paths — in docker-compose, nginx (this container) proxies /api
// and /health to the backend, so the browser never needs to know the
// backend's address or deal with CORS. For local dev without docker, run
// this via any static server and point API_BASE at the backend directly,
// e.g. const API_BASE = "http://localhost:8000";
const API_BASE = "";

let currentServerId = null;
let chartInstance = null;
let lastQuerySql = null;   // sql of the most recent successful `query` tool call this turn
let lastChartArgs = null;  // args of the most recent successful `chart` tool call this turn (ref_id stripped)
let sessionId = null;

const $ = (id) => document.getElementById(id);

async function fetchJSON(path, options) {
  const res = await fetch(API_BASE + path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).error?.message || detail; } catch (_) { /* body wasn't JSON */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

// ---------- Servers + messages ----------

async function loadServers() {
  const select = $("server-select");
  try {
    const servers = await fetchJSON("/api/servers");
    select.innerHTML = servers.map(s => `<option value="${s.server_id}">${s.server_name}</option>`).join("");
    if (servers.length) {
      currentServerId = servers[0].server_id;
      await loadMessages(currentServerId);
    }
  } catch (e) {
    select.innerHTML = "";
    $("messages-panel").innerHTML = `<div class="error-state">Failed to load servers: ${e.message}</div>`;
  }
}

async function loadMessages(serverId) {
  const panel = $("messages-panel");
  panel.innerHTML = `<div class="empty-state">Loading...</div>`;
  try {
    const rows = await fetchJSON(`/api/servers/${serverId}/messages?limit=25`);
    if (!rows.length) {
      panel.innerHTML = `<div class="empty-state">No messages for this server.</div>`;
      return;
    }
    panel.innerHTML = rows.map(r => `
      <div class="msg-row">
        <div class="meta">${r.user_id} · ${new Date(r.timestamp).toLocaleString()}</div>
        <div>${escapeHtml(r.content || "(no content)")}</div>
      </div>
    `).join("");
  } catch (e) {
    panel.innerHTML = `<div class="error-state">Failed to load messages: ${e.message}</div>`;
  }
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

$("server-select").addEventListener("change", (e) => {
  currentServerId = e.target.value;
  loadMessages(currentServerId);
});

// ---------- Chart rendering ----------

function renderChart(spec) {
  $("chart-empty").style.display = "none";
  const canvas = $("latest-chart");
  canvas.style.display = "block";
  if (chartInstance) chartInstance.destroy();

  const type = spec.chart_type === "scatter" ? "scatter" : (spec.chart_type === "bar" ? "bar" : "line");
  chartInstance = new Chart(canvas.getContext("2d"), {
    type,
    data: {
      labels: spec.categories,
      datasets: spec.series.map(s => ({
        label: s.name,
        data: s.values,
        borderWidth: 2,
        tension: 0.25,
      })),
    },
    options: {
      responsive: true,
      plugins: { title: { display: true, text: spec.title, color: "#e6e6ea" }, legend: { labels: { color: "#e6e6ea" } } },
      scales: {
        x: { title: { display: true, text: spec.x_label, color: "#8a8d99" }, ticks: { color: "#8a8d99" } },
        y: { title: { display: true, text: spec.y_label, color: "#8a8d99" }, ticks: { color: "#8a8d99" } },
      },
    },
  });
  $("pin-button").disabled = !(lastQuerySql && lastChartArgs);
}

function renderMiniChart(canvas, spec) {
  const type = spec.chart_type === "scatter" ? "scatter" : (spec.chart_type === "bar" ? "bar" : "line");
  new Chart(canvas.getContext("2d"), {
    type,
    data: { labels: spec.categories, datasets: spec.series.map(s => ({ label: s.name, data: s.values, borderWidth: 2, tension: 0.25 })) },
    options: { responsive: true, plugins: { title: { display: true, text: spec.title, color: "#e6e6ea" }, legend: { display: false } },
      scales: { x: { ticks: { color: "#8a8d99", maxTicksLimit: 6 } }, y: { ticks: { color: "#8a8d99" } } } },
  });
}

// ---------- Chat (SSE over POST) ----------

function appendChatLine(cls, html) {
  const log = $("chat-log");
  if (log.querySelector(".empty-state")) log.innerHTML = "";
  const div = document.createElement("div");
  div.className = `chat-line ${cls}`;
  div.innerHTML = html;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

async function sendChatMessage(text) {
  appendChatLine("user", escapeHtml(text));
  lastQuerySql = null;
  lastChartArgs = null;
  $("pin-button").disabled = true;

  let assistantDiv = null;
  const controller = new AbortController();

  let response;
  try {
    response = await fetch(API_BASE + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message: text }),
      signal: controller.signal,
    });
  } catch (e) {
    appendChatLine("tool-error", `Connection failed: ${escapeHtml(e.message)}`);
    return;
  }
  if (!response.ok || !response.body) {
    appendChatLine("tool-error", `Chat request failed (HTTP ${response.status}).`);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop(); // keep the last, possibly-incomplete chunk
      for (const raw of events) {
        const line = raw.trim();
        if (!line.startsWith("data:")) continue;
        const payload = JSON.parse(line.slice(5).trim());
        handleChatEvent(payload, () => { assistantDiv = assistantDiv || appendChatLine("assistant", ""); return assistantDiv; });
      }
    }
  } catch (e) {
    appendChatLine("tool-error", `Stream interrupted: ${escapeHtml(e.message)}`);
  }
}

function handleChatEvent(evt, getAssistantDiv) {
  switch (evt.event) {
    case "session":
      sessionId = evt.session_id;
      break;
    case "status":
      // intentionally not logged per-iteration to keep the log readable;
      // uncomment for verbose debugging:
      // appendChatLine("status", `thinking (iteration ${evt.iteration})...`);
      break;
    case "token":
      getAssistantDiv().innerHTML += escapeHtml(evt.text);
      break;
    case "tool_call":
      appendChatLine("tool-call", `→ calling <b>${evt.name}</b>(${escapeHtml(JSON.stringify(evt.arguments))})`);
      if (evt.name === "query") lastQuerySql = evt.arguments.sql;
      if (evt.name === "chart") {
        const { ref_id, ...rest } = evt.arguments;
        lastChartArgs = rest;
      }
      break;
    case "tool_result":
      appendChatLine("tool-result", `✓ ${escapeHtml(evt.display_text)}`);
      if (evt.ref.kind === "chart_spec") {
        renderChart(evt.ref.preview);
      }
      break;
    case "tool_error":
      appendChatLine("tool-error", `✗ ${escapeHtml(evt.message)}${evt.retryable ? "" : " (won't retry)"}`);
      break;
    case "assistant_message":
      break; // full text already streamed in as tokens
    case "error":
      appendChatLine("tool-error", escapeHtml(evt.message));
      break;
    case "done":
      break;
  }
}

$("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  sendChatMessage(text);
});

// ---------- Pins ----------

async function loadPins() {
  const grid = $("pins-grid");
  try {
    const pins = await fetchJSON("/api/pins");
    if (!pins.length) {
      grid.innerHTML = `<div class="empty-state">No pinned charts yet.</div>`;
      return;
    }
    grid.innerHTML = "";
    for (const pin of pins) {
      const card = document.createElement("div");
      card.className = "pin-card";
      card.innerHTML = `<h3>${escapeHtml(pin.title)}</h3><canvas height="140"></canvas>
        <div class="pin-actions">
          <button data-action="refresh" data-id="${pin.pin_id}">Refresh</button>
          <button data-action="delete" data-id="${pin.pin_id}">Delete</button>
        </div>`;
      grid.appendChild(card);
      if (pin.result_cache) renderMiniChart(card.querySelector("canvas"), pin.result_cache);
    }
  } catch (e) {
    grid.innerHTML = `<div class="error-state">Failed to load pins: ${e.message}</div>`;
  }
}

$("pins-grid").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const id = btn.dataset.id;
  if (btn.dataset.action === "delete") {
    await fetch(API_BASE + `/api/pins/${id}`, { method: "DELETE" });
    loadPins();
  } else if (btn.dataset.action === "refresh") {
    await fetch(API_BASE + `/api/pins/${id}/refresh`, { method: "POST" });
    loadPins();
  }
});

$("pin-button").addEventListener("click", async () => {
  if (!lastQuerySql || !lastChartArgs) return;
  const title = prompt("Title for this pin?", lastChartArgs.title || "Untitled chart");
  if (!title) return;
  try {
    await fetchJSON("/api/pins", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, query_sql: lastQuerySql, chart_args: lastChartArgs }),
    });
    loadPins();
  } catch (e) {
    alert(`Failed to pin: ${e.message}`);
  }
});

loadServers();
loadPins();
