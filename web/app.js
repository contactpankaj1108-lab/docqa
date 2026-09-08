/* DocQA front end: upload documents, ask questions, read cited answers. */

const $ = (id) => document.getElementById(id);

const state = {
  documents: [],
  selected: new Set(),
  history: [],
  busy: false,
};

const SUGGESTIONS = [
  "What are the responsibilities of a data science intern?",
  "How quickly must a security incident be reported, and to whom?",
  "How many annual leave days do employees get, and how many can be carried over?",
  "What PPE is mandatory on the warehouse floor?",
];

/* ---------------------------------------------------------------- helpers */

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = response.headers.get("content-type")?.includes("json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const detail = body && body.detail ? body.detail : body;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

/* ------------------------------------------------------------- documents */

async function refreshDocuments() {
  const data = await api("/api/documents");
  state.documents = data.documents;
  // Drop selections for documents that no longer exist.
  state.selected = new Set([...state.selected].filter((id) => state.documents.some((d) => d.id === id)));
  renderDocuments();
}

function renderDocuments() {
  const list = $("doc-list");
  $("doc-count").textContent = state.documents.length;
  list.innerHTML = "";

  if (!state.documents.length) {
    list.innerHTML = `<li class="muted" style="font-size:12.5px">No documents yet. Upload one to get started.</li>`;
    return;
  }

  for (const doc of state.documents) {
    const item = document.createElement("li");
    item.className = `doc${doc.status === "failed" ? " failed" : ""}`;

    const pages = doc.pages ? `${doc.pages} pages · ` : "";
    const meta = doc.status === "failed"
      ? `<span style="color:var(--err)">${escapeHtml(doc.error || "failed")}</span>`
      : `${pages}${doc.n_chunks} chunks · ${formatSize(doc.size_bytes)}`;

    item.innerHTML = `
      <input type="checkbox" ${state.selected.has(doc.id) ? "checked" : ""}
             ${doc.status !== "indexed" ? "disabled" : ""} title="Restrict search to this document">
      <div>
        <div class="doc-name" title="${escapeHtml(doc.filename)}">${escapeHtml(doc.filename)}</div>
        <div class="doc-meta">${meta}</div>
      </div>
      <div class="doc-actions">
        <button class="icon-button" data-act="download" title="Download original">↓</button>
        <button class="icon-button danger" data-act="delete" title="Remove">✕</button>
      </div>`;

    item.querySelector("input").addEventListener("change", (event) => {
      if (event.target.checked) state.selected.add(doc.id);
      else state.selected.delete(doc.id);
    });
    item.querySelector(".doc-name").addEventListener("click", () => showPreview(doc));
    item.querySelector('[data-act="download"]').addEventListener("click", () => {
      window.open(`/api/documents/${doc.id}/file`, "_blank");
    });
    item.querySelector('[data-act="delete"]').addEventListener("click", async () => {
      if (!confirm(`Remove "${doc.filename}" from the index?`)) return;
      await api(`/api/documents/${doc.id}`, { method: "DELETE" });
      await Promise.all([refreshDocuments(), refreshStats()]);
    });

    list.appendChild(item);
  }
}

async function showPreview(doc) {
  $("preview-title").textContent = doc.filename;
  $("preview-body").innerHTML = `<p class="muted">Loading…</p>`;
  $("preview").showModal();
  try {
    const detail = await api(`/api/documents/${doc.id}`);
    if (!detail.preview.length) {
      $("preview-body").innerHTML = `<p class="muted">No extracted text to preview.</p>`;
      return;
    }
    $("preview-body").innerHTML = detail.preview.map((chunk) => `
      <div class="preview-chunk">
        <div class="label">Chunk ${chunk.ordinal + 1}${chunk.page ? ` · page ${chunk.page}` : ""}</div>
        <div>${escapeHtml(chunk.text)}</div>
      </div>`).join("");
  } catch (error) {
    $("preview-body").innerHTML = `<p class="notice err">${escapeHtml(error.message)}</p>`;
  }
}

async function uploadFiles(files) {
  if (!files.length) return;
  const log = $("upload-log");
  log.hidden = false;
  log.innerHTML = `<div class="busy">Uploading ${files.length} file${files.length > 1 ? "s" : ""}…</div>`;

  const form = new FormData();
  for (const file of files) form.append("files", file);

  try {
    const result = await api("/api/documents", { method: "POST", body: form });
    const lines = [
      ...result.uploaded.map((doc) => `<div class="ok">✓ ${escapeHtml(doc.filename)}${
        doc.duplicate ? " — already indexed" : ` — ${doc.n_chunks} chunks`}</div>`),
      ...result.failed.map((item) => `<div class="err">✕ ${escapeHtml(item.filename || "file")} — ${escapeHtml(item.error)}</div>`),
    ];
    log.innerHTML = lines.join("");
  } catch (error) {
    log.innerHTML = `<div class="err">✕ ${escapeHtml(error.message)}</div>`;
  }

  await Promise.all([refreshDocuments(), refreshStats()]);
  setTimeout(() => { $("upload-log").hidden = true; }, 8000);
}

/* --------------------------------------------------------------- answers */

function renderAnswerText(text) {
  // Turn "[2]" and "[1, 3]" into clickable chips that scroll to the source.
  return escapeHtml(text).replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (_, group) =>
    group.split(",").map((n) => `<span class="cite" data-n="${n.trim()}">${n.trim()}</span>`).join("")
  );
}

function renderSources(container, sources) {
  if (!sources.length) return;
  container.innerHTML = `
    <div class="sources-head">Sources</div>
    ${sources.map((source) => `
      <div class="source${source.cited ? " cited" : ""}" data-n="${source.n}">
        <span class="n">${source.n}</span>
        <div>
          <div class="where">${escapeHtml(source.filename)}${source.page ? ` · page ${source.page}` : ""}</div>
          <div class="snippet">${escapeHtml(source.snippet)}</div>
        </div>
      </div>`).join("")}`;
}

function addTurn(question) {
  $("empty-state")?.remove();

  const turn = document.createElement("div");
  turn.className = "turn";
  turn.innerHTML = `
    <div class="bubble-user">${escapeHtml(question)}</div>
    <div class="answer"><span class="dots"><span></span><span></span><span></span></span></div>
    <div class="notice-slot"></div>
    <div class="sources"></div>
    <div class="meta-line"></div>`;
  $("transcript").appendChild(turn);
  turn.scrollIntoView({ behavior: "smooth", block: "start" });

  // Clicking a citation chip highlights the matching source card.
  turn.addEventListener("click", (event) => {
    const chip = event.target.closest(".cite");
    if (!chip) return;
    const card = turn.querySelector(`.source[data-n="${chip.dataset.n}"]`);
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.animate([{ opacity: 0.35 }, { opacity: 1 }], { duration: 550 });
  });

  return {
    answer: turn.querySelector(".answer"),
    notice: turn.querySelector(".notice-slot"),
    sources: turn.querySelector(".sources"),
    meta: turn.querySelector(".meta-line"),
  };
}

async function ask(question) {
  if (state.busy || !question.trim()) return;
  state.busy = true;
  $("ask-button").disabled = true;

  const slots = addTurn(question);
  let answerText = "";
  let sources = [];

  const payload = {
    question,
    history: state.history.slice(-6),
    document_ids: state.selected.size ? [...state.selected] : null,
  };

  try {
    const response = await fetch("/api/ask/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`Request failed (${response.status})`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Server-sent events are separated by a blank line.
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        const event = JSON.parse(line.slice(5).trim());

        if (event.type === "sources") {
          sources = event.sources;
          renderSources(slots.sources, sources);
        } else if (event.type === "delta") {
          answerText += event.text;
          slots.answer.innerHTML = renderAnswerText(answerText);
          $("transcript").scrollTop = $("transcript").scrollHeight;
        } else if (event.type === "done") {
          if (event.sources) renderSources(slots.sources, event.sources);
          const timing = event.timing_ms || {};
          const bits = [];
          if (event.mode === "extractive") bits.push("extractive answer (no model configured)");
          if (event.model) bits.push(event.model);
          if (timing.retrieval != null) bits.push(`retrieval ${Math.round(timing.retrieval)} ms`);
          if (timing.total != null) bits.push(`total ${Math.round(timing.total)} ms`);
          slots.meta.textContent = bits.join(" · ");
        } else if (event.type === "error") {
          slots.notice.innerHTML = `<div class="notice err">${escapeHtml(event.message)}</div>`;
        }
      }
    }

    if (!answerText) {
      slots.answer.innerHTML = `<span class="muted">No answer was produced.</span>`;
    } else {
      state.history.push({ role: "user", content: question });
      state.history.push({ role: "assistant", content: answerText });
    }
  } catch (error) {
    slots.answer.innerHTML = "";
    slots.notice.innerHTML = `<div class="notice err">${escapeHtml(error.message)}</div>`;
  } finally {
    state.busy = false;
    $("ask-button").disabled = false;
    $("question").focus();
  }
}

/* ----------------------------------------------------------------- setup */

async function refreshStats() {
  try {
    const stats = await api("/api/stats");
    const engine = stats.generation === "claude"
      ? `answers by ${stats.model}`
      : "extractive answers — set ANTHROPIC_API_KEY for generated ones";
    const dense = stats.dense_retrieval ? "hybrid retrieval" : "lexical retrieval";
    $("status-line").textContent =
      `${stats.documents} documents · ${stats.chunks} chunks · ${dense} · ${engine}`;
  } catch {
    $("status-line").textContent = "Could not reach the API.";
  }
}

function renderSuggestions() {
  const box = $("suggestions");
  if (!box) return;
  box.innerHTML = SUGGESTIONS.map((text) =>
    `<button class="suggestion" type="button">${escapeHtml(text)}</button>`).join("");
  box.querySelectorAll(".suggestion").forEach((button) => {
    button.addEventListener("click", () => ask(button.textContent));
  });
}

function setupComposer() {
  const box = $("question");
  box.addEventListener("input", () => {
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, 160)}px`;
  });
  box.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      $("ask-form").requestSubmit();
    }
  });
  $("ask-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const question = box.value.trim();
    if (!question) return;
    box.value = "";
    box.style.height = "auto";
    ask(question);
  });
}

function setupUpload() {
  const zone = $("dropzone");
  $("file-input").addEventListener("change", (event) => {
    uploadFiles([...event.target.files]);
    event.target.value = "";
  });
  ["dragenter", "dragover"].forEach((name) =>
    zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.add("hover"); }));
  ["dragleave", "drop"].forEach((name) =>
    zone.addEventListener(name, (event) => { event.preventDefault(); zone.classList.remove("hover"); }));
  zone.addEventListener("drop", (event) => uploadFiles([...event.dataTransfer.files]));
}

function setupPreview() {
  $("preview-close").addEventListener("click", () => $("preview").close());
  $("preview").addEventListener("click", (event) => {
    if (event.target.id === "preview") $("preview").close();
  });
}

setupComposer();
setupUpload();
setupPreview();
renderSuggestions();
refreshDocuments();
refreshStats();
