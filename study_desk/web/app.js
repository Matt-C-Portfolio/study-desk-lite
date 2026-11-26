const form = document.querySelector("#intake"),
  input = document.querySelector("#url"),
  button = document.querySelector("#submit"),
  status = document.querySelector("#status");
let items = [],
  descending = true,
  pollTimer = null,
  submitting = false,
  currentIntakeId = null;
let workspaceBusy = false;
try {
  currentIntakeId = Number(localStorage.getItem("lite-intake-id")) || null;
} catch {}
function selectIntake(id) {
  currentIntakeId = id;
  try {
    localStorage.setItem("lite-intake-id", String(id));
  } catch {}
}
const activeStates = ["checking", "downloading", "transcribing"];
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function message(text, error = false) {
  status.textContent = text;
  status.className = error ? "error" : "";
  input.setAttribute("aria-invalid", String(error));
}
function duration(seconds) {
  if (!Number.isFinite(seconds)) return "";
  const s = Math.floor(seconds);
  return s >= 3600
    ? `${Math.floor(s / 3600)}:${String(Math.floor(s / 60) % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`
    : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
function switchView() {
  if (location.hash === "#reference") history.replaceState(null, "", "#comparison");
  const view =
    location.hash === "#answer-comparison"
      ? "answer-comparison"
      : location.hash === "#ask"
        ? "ask"
        : location.hash === "#graph-comparison"
          ? "graph-comparison"
          : location.hash === "#database"
            ? "database"
            : location.hash === "#architecture"
              ? "architecture"
              : location.hash === "#graph"
                ? "graph"
                : location.hash === "#comparison"
                  ? "comparison"
                  : location.hash === "#processed"
                    ? "library"
                    : "intake";
  for (const name of [
    "intake",
    "library",
    "comparison",
    "graph",
    "architecture",
    "database",
    "graph-comparison",
    "ask",
    "answer-comparison",
  ]) {
    document.querySelector(`#${name}-view`).hidden = name !== view;
    const nav = document.querySelector(`#nav-${name}`);
    if (name === view) nav?.setAttribute("aria-current", "page");
    else nav?.removeAttribute("aria-current");
  }
  document.querySelector("#page-title").textContent = {
    "answer-comparison": "Answer comparison",
    ask: "Ask Study Desk",
    "graph-comparison": "Graph comparison",
    intake: "Video intake",
    library: "Video library",
    comparison: "Model comparison",
    graph: "Video graph",
    architecture: "Architecture",
    database: "Database",
  }[view];
  if (view === "answer-comparison") queueMicrotask(() => window.renderAnswerComparison?.());
  if (view === "graph-comparison") queueMicrotask(() => window.renderGraphComparison?.());
  if (view === "graph") queueMicrotask(() => window.renderLectureGraph?.());
  if (view === "comparison") queueMicrotask(() => window.renderExperimentComparison?.());
}
window.addEventListener("hashchange", switchView);
switchView();
async function processUrl(item, action = "check") {
  const response = await fetch(`/api/urls/${item.id}/process`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action,
      rights_confirmed: document.querySelector("#rights-confirmed").checked,
    }),
  });
  const result = await response.json();
  if (!response.ok) throw Error(result.error || "Could not start transcription.");
}
let progressId = null,
  shownProgress = 0,
  targetProgress = 0,
  progressFrame = null;
function paintProgress(value) {
  document.querySelector("#progress-fill").style.width = `${value}%`;
  document.querySelector("#progress-percent").textContent = `${value.toFixed(1)}%`;
  document.querySelector("#progress-track").setAttribute("aria-valuenow", value.toFixed(1));
}
function updateProgress(item) {
  const box = document.querySelector("#transcription-progress");
  const visible =
    item &&
    (item.state === "downloading" ||
      item.state === "transcribing" ||
      (item.method === "Faster-Whisper large-v3" && item.state === "ready") ||
      (progressId === item.id && item.state === "error"));
  box.hidden = !visible;
  if (!visible) {
    cancelAnimationFrame(progressFrame);
    progressFrame = null;
    progressId = null;
    shownProgress = targetProgress = 0;
    return;
  }
  if (progressId !== item.id) {
    cancelAnimationFrame(progressFrame);
    progressFrame = null;
    progressId = item.id;
    shownProgress = targetProgress = 0;
    paintProgress(0);
  }
  const match = (item.detail || "").match(/Transcription progress: ([0-9.]+)%/);
  const legacy = (item.detail || "").match(/Transcribed through ([0-9.]+)s/);
  const complete = item.state === "ready";
  const measured = complete
    ? 100
    : match
      ? Math.min(99.9, Number(match[1]))
      : legacy && item.metadata?.duration
        ? Math.min(99.9, (Number(legacy[1]) / item.metadata.duration) * 100)
        : targetProgress;
  const note = document.querySelector("#progress-note");
  note.textContent = complete
    ? "Transcript saved locally."
    : item.state === "downloading"
      ? "Preparing audio. Transcription has not started yet."
      : item.state === "error"
        ? "Transcription stopped. See the error below."
        : match
          ? "Based on audio transcribed; updates arrive as Whisper finishes segments."
          : "Loading Whisper and waiting for the first audio segmentâ€¦";
  // Animate only toward measured work, never ahead of it. Keep the animation
  // alive across polling updates so neither the bar nor the counter jumps.
  if (item.state === "error") {
    cancelAnimationFrame(progressFrame);
    progressFrame = null;
    return;
  }
  if (measured <= targetProgress) return;
  targetProgress = measured;
  if (progressFrame) return;
  let previous = performance.now();
  function tick(now) {
    const elapsed = Math.min(now - previous, 100);
    previous = now;
    const gap = targetProgress - shownProgress;
    shownProgress += gap * Math.min(1, elapsed / 250);
    if (targetProgress - shownProgress < 0.025) shownProgress = targetProgress;
    paintProgress(shownProgress);
    if (shownProgress < targetProgress) {
      progressFrame = requestAnimationFrame(tick);
    } else {
      progressFrame = null;
    }
  }
  progressFrame = requestAnimationFrame(tick);
}
function renderIntake() {
  const active = items.find(
    (i) =>
      activeStates.includes(i.state) ||
      Object.values(i.study_runs || {}).some((r) => ["running", "queued"].includes(r.status)),
  );
  if (active && active.id !== currentIntakeId) {
    selectIntake(active.id);
    input.value = active.url;
  }
  const item = items.find((i) => i.id === currentIntakeId),
    busy = workspaceBusy || Boolean(active) || submitting;
  updateProgress(item);
  if (typeof renderStudy === "function") renderStudy();
  button.disabled = busy;
  input.disabled = busy;
  const preset = document.querySelector("#lecture-preset");
  preset.disabled = busy;
  const customUrl =
    Boolean(input.value.trim()) &&
    ![...preset.options].some((option) => option.value === input.value.trim());
  const rights = document.querySelector("#rights-confirmed");
  document.querySelector("#rights-agreement").hidden = !customUrl;
  rights.disabled = busy;
  button.disabled = busy || (customUrl && !rights.checked);
  preset.value = [...preset.options].some((option) => option.value === input.value.trim())
    ? input.value.trim()
    : "";
  button.textContent = submitting
    ? "Startingâ€¦"
    : active?.state === "checking"
      ? "Checkingâ€¦"
      : item?.caption_status && item.caption_status !== "unchecked"
        ? "Recheck captions"
        : "Check captions";
  const result = document.querySelector("#step-result");
  result.replaceChildren();
  result.hidden = true;
  const captionButton = document.querySelector("#choose-captions"),
    localButton = document.querySelector("#choose-local"),
    summary = document.querySelector("#choice-summary"),
    choiceStatus = document.querySelector("#choice-status");
  captionButton.disabled = true;
  localButton.disabled = true;
  for (const choice of [captionButton, localButton]) {
    choice.classList.remove("transcript-selected");
    choice.setAttribute("aria-pressed", "false");
  }
  choiceStatus.textContent = "";
  summary.textContent = "Check a video in Step 1 to see your options.";
  if (!item) return;
  if (!input.value) input.value = item.url;
  const captions = item.versions?.captions,
    local = item.versions?.local;
  for (const [choice, version] of [
    [captionButton, captions],
    [localButton, local],
  ]) {
    const selected = Boolean(version?.path && version.path === item.transcript_path);
    choice.classList.toggle("transcript-selected", selected);
    choice.setAttribute("aria-pressed", String(selected));
  }
  const checked = ["available", "unavailable", "error"].includes(item.caption_status);
  captionButton.disabled = busy || !captions;
  localButton.disabled = busy || !checked || (customUrl && !rights.checked && !local);
  captionButton.textContent = captions ? `Use ${captions.method}` : "No captions available";
  localButton.textContent = local ? "Use saved local transcript" : "Transcribe locally";
  summary.textContent =
    item.caption_status === "available"
      ? `${captions?.method || "Captions"} available. Use them or create a separate local transcript.`
      : item.caption_status === "unavailable"
        ? "No captions are available. Choose local transcription to create a transcript."
        : item.caption_status === "error"
          ? "Caption retrieval failed; availability is unknown. Retry Step 1 or choose local transcription."
          : "Check a video in Step 1 to see your options.";
  if (item.state === "checking") {
    message(item.detail || "Checking captionsâ€¦");
    return;
  }
  const label =
    item.caption_status === "available"
      ? `${captions?.method || "Captions"} available`
      : item.caption_status === "unavailable"
        ? "No captions available"
        : item.caption_status === "error"
          ? "Caption retrieval failed"
          : "Captions not checked";
  message(label, item.caption_status === "error");
  if (item.caption_status === "error" && item.state === "error") message(item.detail, true);
  if (activeStates.includes(item.state))
    choiceStatus.textContent = (item.detail || "").startsWith("Transcription progress:")
      ? ""
      : item.detail;
  else if (item.state === "error" && item.caption_status !== "error") {
    choiceStatus.textContent = (item.detail || "").startsWith("Transcription progress:")
      ? ""
      : item.detail;
    choiceStatus.className = "job-detail error";
  } else {
    choiceStatus.className = "job-detail";
    choiceStatus.textContent = item.method
      ? `Selected: ${item.method}. This transcript will be used for processing.`
      : "Nothing selected yet.";
  }
  const meta = item.metadata;
  result.hidden = false;
  const thumb = el("div", "thumbnail"),
    info = el("div", "result-info");
  if (meta.thumbnail_mime) {
    const image = el("img");
    image.src = `/api/urls/${item.id}/thumbnail`;
    image.alt = "";
    thumb.append(image);
  }
  thumb.append(el("span", "duration", duration(meta.duration)));
  info.append(
    el("span", "ready-tag", label),
    el("h3", null, meta.title || item.url),
    el("p", null, meta.channel || meta.uploader || ""),
  );
  const actions = el("div", "result-actions");
  if (captions) {
    const preview = el("button", "secondary", "Preview captions");
    preview.type = "button";
    preview.addEventListener("click", () => openLecture(item, "captions"));
    actions.append(preview);
  }
  if (item.method) {
    const preview = el("button", "secondary", "Preview selected transcript");
    preview.type = "button";
    preview.addEventListener("click", () => openLecture(item));
    actions.append(preview);
  }
  info.append(actions);
  result.append(thumb, info);
}
async function chooseTranscript(action) {
  const item = items.find((i) => i.id === currentIntakeId);
  if (!item) return;
  submitting = true;
  renderIntake();
  try {
    await processUrl(item, action);
    submitting = false;
    await refresh();
  } catch (error) {
    submitting = false;
    renderIntake();
    document.querySelector("#choice-status").textContent = error.message;
  }
}
document
  .querySelector("#choose-captions")
  .addEventListener("click", () => chooseTranscript("captions"));
document.querySelector("#choose-local").addEventListener("click", () => chooseTranscript("local"));
function renderLibrary() {
  const query = document.querySelector("#filter").value.toLowerCase();
  const ready = items.filter((i) => i.state === "ready");
  document.querySelector("#library-count").textContent = `${ready.length} videos`;
  const visible = ready
    .filter((i) =>
      `${i.metadata.title || ""} ${i.metadata.channel || ""}`.toLowerCase().includes(query),
    )
    .sort((a, b) => {
      const order =
        String(b.metadata.upload_date || "").localeCompare(String(a.metadata.upload_date || "")) ||
        b.id - a.id;
      return descending ? order : -order;
    });
  const rows = document.querySelector("#library-rows");
  rows.replaceChildren();
  const empty = document.querySelector("#library-empty");
  empty.hidden = visible.length > 0;
  empty.textContent = ready.length
    ? "No videos match your filter."
    : "Processed videos will appear here once a transcript is ready.";
  for (const item of visible) {
    const meta = item.metadata,
      tr = el("tr"),
      video = el("td"),
      cell = el("div", "video-cell"),
      thumb = el("div", "thumbnail");
    if (meta.thumbnail_mime) {
      const image = el("img");
      image.src = `/api/urls/${item.id}/thumbnail`;
      image.alt = "";
      thumb.append(image);
    }
    thumb.append(el("span", "duration", duration(meta.duration)));
    const text = el("div", "video-text"),
      title = el("button", "video-title", meta.title || item.url);
    title.addEventListener("click", () => openLecture(item));
    text.append(
      title,
      el("div", "video-sub", meta.channel || meta.uploader || ""),
      el("p", "video-description", meta.description || ""),
    );
    if (meta.content_license) {
      const license = meta.content_license;
      const details = el("details", "lecture-license");
      details.append(el("summary", "video-sub", `License & attribution · ${license.license_name}`));
      details.append(el("p", "", license.attribution));
      for (const [label, url] of [
        ["MIT OCW source", license.source],
        [license.license_name, license.license_url],
      ]) {
        const link = el("a", "", label);
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        details.append(link, document.createTextNode(" "));
      }
      details.append(el("p", "", "Noncommercial · ShareAlike · " + license.scope));
      text.append(details);
    } else {
      text.append(el("div", "video-sub", "License not verified"));
    }
    cell.append(thumb, text);
    video.append(cell);
    const date = el(
      "td",
      null,
      meta.upload_date
        ? `${meta.upload_date.slice(0, 4)}-${meta.upload_date.slice(4, 6)}-${meta.upload_date.slice(6, 8)}`
        : "Unknown",
    );
    date.append(el("div", "video-sub", "Published"));
    const actions = el("td"),
      open = el("button", "secondary", "Open");
    open.addEventListener("click", () => openLecture(item));
    actions.append(open);
    const study = el("button", "secondary", "Study notes");
    study.addEventListener("click", () => {
      selectIntake(item.id);
      input.value = item.url;
      location.hash = "#intake";
      renderIntake();
      document.querySelector("#study-step").scrollIntoView({ behavior: "smooth" });
    });
    actions.append(study);
    const remove = el("button", "secondary", "Remove");
    remove.addEventListener("click", async () => {
      if (
        !confirm(
          `Remove "${meta.title || item.url}"? This permanently deletes its local metadata, thumbnail, transcripts, audio, and all model results and timings.`,
        )
      )
        return;
      remove.disabled = true;
      try {
        const response = await fetch(`/api/urls/${item.id}`, { method: "DELETE" });
        const result = await response.json();
        if (!response.ok) throw Error(result.error);
        if (currentIntakeId === item.id) {
          selectIntake(null);
          input.value = "";
        }
        if (selectedLecture?.id === item.id) selectedLecture = null;
        await refresh();
      } catch (error) {
        alert(error.message);
        remove.disabled = false;
      }
    });
    actions.append(remove);
    tr.append(
      video,
      el("td", null, item.method || ""),
      el("td", "ready-tag", "Transcript ready"),
      date,
      actions,
    );
    rows.append(tr);
  }
}
async function refresh() {
  const response = await fetch("/api/urls");
  if (!response.ok) throw Error("Could not load videos.");
  items = await response.json();
  const work = await fetch("/api/workspace-status");
  workspaceBusy = work.ok && (await work.json()).busy;
  if (!currentIntakeId) {
    const saved = items.find((item) => item.url === input.value.trim());
    if (saved) selectIntake(saved.id);
  }
  renderIntake();
  renderLibrary();
  window.renderExperimentComparison?.();
  clearTimeout(pollTimer);
  if (
    workspaceBusy ||
    items.some(
      (i) =>
        activeStates.includes(i.state) ||
        Object.values(i.study_runs || {}).some((r) => ["running", "queued"].includes(r.status)),
    )
  )
    pollTimer = setTimeout(() => refresh().catch((e) => message(e.message, true)), 500);
}
let selectedLecture = null;
async function openLecture(item, kind = null) {
  const transcriptEndpoint = kind === "captions" ? "captions" : "transcript";
  selectedLecture = item.id;
  const meta = item.metadata,
    dialog = document.querySelector("#lecture-dialog");
  document.querySelector("#lecture-title").textContent = meta.title || item.url;
  document.querySelector("#lecture-byline").textContent =
    `${meta.channel || meta.uploader || ""} Â· ${duration(meta.duration)}`;
  document.querySelector("#lecture-description").textContent =
    meta.description || "No description available.";
  document.querySelector("#lecture-extra").textContent =
    `License: ${meta.license || "Not supplied by YouTube"} Â· Views at processing: ${meta.view_count?.toLocaleString() || "Unknown"}`;
  document.querySelector("#watch-original").href = item.url;
  document.querySelector("#download-transcript").href =
    `/api/urls/${item.id}/${transcriptEndpoint}`;
  document.querySelector("#transcript-source").textContent =
    kind === "captions" ? item.versions.captions.method : item.method || "";
  const transcript = document.querySelector("#transcript-text");
  transcript.textContent = "Loading transcriptâ€¦";
  const player = document.querySelector("#player");
  player.replaceChildren();
  const id = new URL(item.url).searchParams.get("v");
  if (/^[A-Za-z0-9_-]{11}$/.test(id)) {
    const frame = el("iframe");
    frame.title = meta.title || "Video video";
    frame.src = `https://www.youtube-nocookie.com/embed/${id}`;
    frame.allow = "encrypted-media; fullscreen; picture-in-picture";
    frame.allowFullscreen = true;
    player.append(frame);
  }
  if (!dialog.open) dialog.showModal();
  try {
    const response = await fetch(`/api/urls/${item.id}/${transcriptEndpoint}`);
    if (!response.ok) throw Error("Could not load transcript.");
    const content = await response.text();
    if (selectedLecture === item.id) transcript.textContent = content;
  } catch (error) {
    if (selectedLecture === item.id) transcript.textContent = error.message;
  }
}
document
  .querySelector("#close-lecture")
  .addEventListener("click", () => document.querySelector("#lecture-dialog").close());
document.querySelector("#lecture-dialog").addEventListener("close", () => {
  selectedLecture = null;
  document.querySelector("#player").replaceChildren();
});
document.querySelector("#filter").addEventListener("input", renderLibrary);
document.querySelector("#sort-date").addEventListener("click", () => {
  descending = !descending;
  document.querySelector("#sort-date").textContent = descending ? "Date â†“" : "Date â†‘";
  renderLibrary();
});
document.querySelector("#lecture-preset").addEventListener("change", (event) => {
  if (input.disabled || !event.target.value) return;
  input.value = event.target.value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
});
input.addEventListener("input", () => {
  if (!submitting) {
    document.querySelector("#rights-confirmed").checked = false;
    const saved = items.find((item) => item.url === input.value.trim());
    selectIntake(saved?.id ?? null);
    renderIntake();
    if (!saved) message("");
  }
});
document.querySelector("#rights-confirmed").addEventListener("change", renderIntake);
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitting = true;
  button.disabled = true;
  input.disabled = true;
  document.querySelector("#lecture-preset").disabled = true;
  button.textContent = "Startingâ€¦";
  document.querySelector("#step-result").hidden = true;
  message("Saving video and checking captionsâ€¦");
  try {
    const response = await fetch("/api/urls", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: input.value.trim() }),
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || "Could not save the URL.");
    selectIntake(result.item.id);
    input.value = result.item.url;
    await processUrl(result.item);
    submitting = false;
    await refresh();
  } catch (error) {
    submitting = false;
    button.disabled = false;
    input.disabled = false;
    document.querySelector("#lecture-preset").disabled = false;
    button.textContent = "Check captions";
    message(error.message, true);
  }
});
refresh().catch((error) => message(error.message, true));

// The comparison cohort is fixed; metrics use the saved run records, not new generations.
(() => {
  let cohort = null,
    cohortRequest = null;
  async function loadCohort() {
    if (cohort) return;
    if (!cohortRequest) {
      cohortRequest = (async () => {
        const response = await fetch("/data/comparison-cohort.json");
        if (!response.ok) throw Error("Could not load the comparison cohort.");
        const saved = await response.json();
        if (!Array.isArray(saved) || !saved.length) throw Error("Comparison cohort unavailable.");
        cohort = saved;
      })().finally(() => {
        cohortRequest = null;
      });
    }
    await cohortRequest;
  }
  const models = ["1.5B", "7B", "14B", "openai"];
  const labels = {
    "1.5B": "DeepSeek 1.5B",
    "7B": "DeepSeek 7B",
    "14B": "DeepSeek 14B",
    openai: "OpenAI · Luna + Terra",
  };
  const verdicts = {
    "1.5B":
      "Too unreliable for full video guides: omissions, repetition, and incorrect explanations.",
    "7B": "Sometimes useful, but inconsistent. Longer output can mean more repetition.",
    "14B":
      "Strongest local option. Reliable completion, but less detail and occasional technical errors.",
    openai:
      "Strongest coverage and organization in this review. Still contains errors and unfinished material.",
  };
  const seconds = (n) => (Number.isFinite(n) ? `${n.toFixed(1)}s` : "—");
  const money = (n) => `$${n.toFixed(2)}`;
  function records(entry, model) {
    const item = items.find((i) => i.url === entry.url);
    return (item?.run_history?.[model] || []).filter((r) =>
      entry.runs[model].includes(r.run_number),
    );
  }
  function metrics(runs, expected) {
    const complete = runs.filter((r) => r.status === "complete");
    const terminal = runs.filter((r) =>
      ["complete", "error", "failed", "cancelled"].includes(r.status),
    );
    const timed = terminal.filter((r) => Number.isFinite(r.elapsed));
    const successfulTimes = complete.filter((r) => Number.isFinite(r.elapsed));
    const mean = (rs) => (rs.length ? rs.reduce((a, r) => a + r.elapsed, 0) / rs.length : NaN);
    return {
      complete: complete.length,
      expected,
      terminal: terminal.length,
      failed: terminal.length - complete.length,
      mean: mean(timed),
      successMean: mean(successfulTimes),
      total: timed.reduce((a, r) => a + r.elapsed, 0),
      cost:
        terminal.length && terminal.every((r) => Number.isFinite(r.estimated_cost_usd))
          ? terminal.reduce((a, r) => a + r.estimated_cost_usd, 0)
          : null,
    };
  }
  function table(headers, rows) {
    const wrap = el("div", "comparison-table-wrap");
    const t = el("table", "comparison-table");
    const head = el("thead"),
      tr = el("tr");
    for (const h of headers) tr.append(el("th", null, h));
    head.append(tr);
    t.append(head);
    const body = el("tbody");
    for (const row of rows) {
      const line = el("tr");
      for (const value of row) {
        const cell = el("td");
        cell.append(value instanceof Node ? value : document.createTextNode(value));
        line.append(cell);
      }
      body.append(line);
    }
    t.append(body);
    wrap.append(t);
    return wrap;
  }
  function variationLabel(groups) {
    const cvs = groups
      .filter((v) => v.length >= 2)
      .map((values) => {
        const mean = values.reduce((a, b) => a + b, 0) / values.length;
        return mean > 0
          ? (100 * Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length)) /
              mean
          : null;
      })
      .filter((v) => v !== null);
    const label = el(
      "small",
      "chart-variation",
      cvs.length
        ? `${(cvs.reduce((a, b) => a + b, 0) / cvs.length).toFixed(1)}% variation`
        : "Variation: insufficient runs",
    );
    label.title = `Standard deviation ÷ mean × 100, using completed runs within each video. Average across ${cvs.length} eligible video(s); at least two runs required. Lower means less variation, not higher accuracy.`;
    return label;
  }
  let compressionSelection = "all";
  let compressionData = null;
  let compressionLoading = false;
  // Count text consistently; remove attribution, timestamp references and Markdown syntax.
  function wordCount(text) {
    return text
      .split("<!-- ocw-attribution -->")[0]
      .replace(/^Lecture reference:.*$/gm, "")
      .replace(/^```.*$/gm, "")
      .replace(/!\[.*?\]\(.*?\)/g, "")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .split(/\s+/)
      .filter((word) => /[\p{L}\p{N}]/u.test(word)).length;
  }
  async function loadCompression() {
    if (compressionLoading) return;
    compressionLoading = true;
    const data = [],
      tasks = [];
    for (const entry of cohort) {
      const item = items.find((i) => i.url === entry.url);
      if (!item) continue;
      const row = { url: entry.url, title: entry.title, words: null, runs: [] };
      data.push(row);
      tasks.push(async () => {
        const r = await fetch(`/api/urls/${item.id}/transcript`);
        if (!r.ok) throw Error("Transcript unavailable");
        row.words = wordCount(await r.text());
      });
      for (const model of models)
        for (const run of records(entry, model)) {
          if (run.status !== "complete") continue;
          tasks.push(async () => {
            const r = await fetch(`/api/urls/${item.id}/notes/${model}/${run.run_number}`);
            if (!r.ok) throw Error("Guide unavailable");
            row.runs.push({ model, number: run.run_number, words: wordCount(await r.text()) });
          });
        }
    }
    let failures = 0;
    await Promise.all(
      Array.from({ length: 4 }, async () => {
        while (tasks.length) {
          const task = tasks.shift();
          try {
            await task();
          } catch {
            failures++;
          }
        }
      }),
    );
    compressionData = { rows: data, failures };
    compressionLoading = false;
    paintCompression();
    paintCost();
    paintTime();
  }
  function paintCompression() {
    const host = document.querySelector("#compression-chart");
    if (!host) return;
    host.replaceChildren();
    if (!compressionData) {
      host.append(el("p", "hint", "Loading saved guide and transcript word counts…"));
      return;
    }
    const rows = compressionData.rows.filter(
      (r) => compressionSelection === "all" || r.url === compressionSelection,
    );
    const series = models.map((model) => ({
      model,
      points: rows.flatMap((row) =>
        row.words > 0
          ? row.runs
              .filter((r) => r.model === model)
              .map((r) => ({
                ...r,
                ratio: (r.words / row.words) * 100,
                title: row.title,
                transcript: row.words,
              }))
          : [],
      ),
    }));
    const maximum = Math.max(100, ...series.flatMap((s) => s.points.map((p) => p.ratio)));
    const limit = Math.ceil(maximum / 25) * 25;
    const caption = el(
      "p",
      "hint",
      compressionSelection === "all"
        ? "All videos · each dot is one completed run. Bars show the mean of individual guide/transcript percentages."
        : "Each dot is one completed run. Bars show the mean for this video.",
    );
    host.append(caption);
    const axis = el("div", "compression-axis");
    axis.append(el("span", null, "0%"), el("span", null, `${limit}% of transcript length`));
    host.append(axis);
    const colors = ["#9a658b", "#b47b24", "#287f83", "#287bb5"];
    for (const [index, seriesRow] of series.entries()) {
      const points = seriesRow.points;
      const line = el("div", "compression-row");
      line.append(el("strong", null, labels[seriesRow.model]));
      const plot = el("div", "compression-track");
      const reference = el("div", "compression-reference");
      reference.style.left = `${(100 / limit) * 100}%`;
      reference.title = "100%: guide equals transcript length";
      plot.append(reference);
      if (points.length) {
        const mean = points.reduce((a, p) => a + p.ratio, 0) / points.length;
        const bar = el("div", "compression-bar");
        bar.style.width = `${(mean / limit) * 100}%`;
        bar.style.background = colors[index];
        plot.append(bar);
        points
          .sort((a, b) => a.number - b.number)
          .forEach((p, i) => {
            const dot = el("button", "compression-dot");
            dot.style.left = `${(p.ratio / limit) * 100}%`;
            dot.style.top = `${9 + (i % 5) * 7}px`;
            dot.style.borderColor = colors[index];
            const description = `${p.title} · ${labels[p.model]} run ${p.number}: ${p.words.toLocaleString()} / ${p.transcript.toLocaleString()} words (${p.ratio.toFixed(1)}%)`;
            dot.title = description;
            dot.setAttribute("aria-label", description);
            dot.onclick = () =>
              (document.querySelector("#compression-detail").textContent = description);
            plot.append(dot);
          });
        const stats = el("span", null, `${mean.toFixed(1)}% · n=${points.length}`);
        stats.append(
          variationLabel(
            rows.map((row) =>
              row.runs.filter((r) => r.model === seriesRow.model).map((r) => r.words),
            ),
          ),
        );
        line.append(plot, stats);
      } else line.append(plot, el("span", null, "No completed guides"));
      host.append(line);
    }
    host.append(
      el(
        "p",
        "hint",
        "Dashed line = transcript length (100%). Above 100% means expansion. Failed attempts are excluded, not counted as zero-length guides. Shorter does not automatically mean better. Variation measures spread across completed runs within a video; All videos averages those percentages, excluding videos with fewer than two usable runs.",
      ),
    );
    const info = el(
      "p",
      "compression-detail",
      "Select a dot for its video, run, and exact word counts.",
    );
    info.id = "compression-detail";
    host.append(info);
    if (compressionData.failures)
      host.append(
        el(
          "p",
          "error",
          `${compressionData.failures} files could not be loaded. Refresh results to retry.`,
        ),
      );
  }
  function compressionSection() {
    const section = el("section", "panel comparison-section");
    section.append(el("h2", null, "Guide length relative to transcript"));
    section.append(
      el(
        "p",
        null,
        "50% means the guide is half as long as its transcript. Guide words ÷ transcript words × 100.",
      ),
    );
    const label = el("label", null, "Video");
    label.htmlFor = "compression-lecture";
    const select = el("select");
    select.id = "compression-lecture";
    const all = el("option", null, "All 10 videos");
    all.value = "all";
    select.append(all);
    for (const entry of cohort) {
      const option = el("option", null, entry.title);
      option.value = entry.url;
      select.append(option);
    }
    select.value = compressionSelection;
    select.onchange = () => {
      compressionSelection = select.value;
      paintCompression();
    };
    section.append(label, select);
    const host = el("div");
    host.id = "compression-chart";
    section.append(host);
    section.append(
      el(
        "p",
        "hint",
        "Counts include headings, prose, code, and formulas. Attribution, lecture-reference lines, Markdown fences, and punctuation-only tokens are excluded. Uses the saved selected transcripts and completed guides in this experiment.",
      ),
    );
    queueMicrotask(() => {
      paintCompression();
      if (!compressionData && items.length) loadCompression();
    });
    return section;
  }
  let timeSelection = "all";
  let timeMeasure = "total";
  let paintTime = () => {};
  function timeChart() {
    const section = el("section", "panel comparison-section");
    section.append(
      el("h2", null, "Time to generate a guide"),
      el(
        "p",
        null,
        "Bars show average time for completed runs. Lower means faster, not necessarily better.",
      ),
    );
    const label = el("label", null, "Video");
    label.htmlFor = "time-lecture";
    const select = el("select");
    select.id = "time-lecture";
    const all = el("option", null, "All 10 videos");
    all.value = "all";
    select.append(all);
    for (const entry of cohort) {
      const option = el("option", null, entry.title);
      option.value = entry.url;
      select.append(option);
    }
    select.value = timeSelection;
    section.append(label, select);
    const measureLabel = el("label", null, "Time measure");
    measureLabel.htmlFor = "time-measure";
    const measure = el("select");
    measure.id = "time-measure";
    for (const [value, text] of [
      ["total", "Total generation time"],
      ["normalized", "Time per 1,000 transcript words"],
    ]) {
      const option = el("option", null, text);
      option.value = value;
      measure.append(option);
    }
    measure.value = timeMeasure;
    section.append(measureLabel, measure);
    const host = el("div");
    section.append(host);
    function paint() {
      host.replaceChildren();
      const normalized = timeMeasure === "normalized";
      if (normalized && !compressionData) {
        host.append(el("p", "hint", "Loading transcript word counts…"));
        return;
      }
      const unit = normalized ? "sec / 1,000 words" : "min";
      const divisor = normalized ? 1 : 60;
      const selected = cohort.filter((e) => timeSelection === "all" || e.url === timeSelection);
      const missing = normalized
        ? selected.filter((e) => !(compressionData.rows.find((r) => r.url === e.url)?.words > 0))
            .length
        : 0;
      if (normalized)
        host.append(
          el(
            "p",
            "hint",
            "Run seconds ÷ saved transcript words × 1,000. Output length and reasoning can still affect generation time.",
          ),
        );
      if (missing)
        host.append(
          el("p", "hint", `${missing} lecture(s) excluded: transcript word count unavailable.`),
        );
      const entries = cohort
        .filter((e) => timeSelection === "all" || e.url === timeSelection)
        .filter((e) => !normalized || compressionData.rows.find((r) => r.url === e.url)?.words > 0);
      const series = models.map((model) => {
        const points = [];
        for (const entry of entries) {
          const factor = normalized
            ? 1000 / compressionData.rows.find((r) => r.url === entry.url).words
            : 1;
          const runs = records(entry, model).filter(
            (r) =>
              Number.isFinite(r.elapsed) &&
              ["complete", "error", "failed", "cancelled"].includes(r.status),
          );
          const complete = runs.filter((r) => r.status === "complete");
          if (timeSelection === "all") {
            if (complete.length)
              points.push({
                value: (complete.reduce((a, r) => a + r.elapsed, 0) / complete.length) * factor,
                description: `${entry.title}: mean of ${complete.length} completed runs`,
                failed: false,
              });
          } else
            for (const r of runs)
              points.push({
                value: r.elapsed * factor,
                description: `Run ${r.run_number}: ${r.status}${r.execution?.worker_limit ? ` · worker limit ${r.execution.worker_limit}` : ""}`,
                failed: r.status !== "complete",
              });
        }
        return { model, points };
      });
      const step = normalized ? 10 : 60;
      const limit = Math.max(
        step,
        Math.ceil(Math.max(0, ...series.flatMap((s) => s.points.map((p) => p.value))) / step) *
          step,
      );
      host.append(
        el(
          "p",
          "hint",
          timeSelection === "all"
            ? "One dot per video, averaging its completed runs. Bars give each video equal weight."
            : "One dot per attempt. Red × marks a failed or cancelled attempt; these are excluded from the bar average.",
        ),
      );
      const axis = el("div", "compression-axis");
      axis.append(el("span", null, `0 ${unit}`), el("span", null, `${limit / divisor} ${unit}`));
      host.append(axis);
      const detail = el("p", "compression-detail", "Select a dot to see exact timings.");
      const colors = ["#9a658b", "#b47b24", "#287f83", "#287bb5"];
      series.forEach((s, index) => {
        const row = el("div", "compression-row");
        row.append(el("strong", null, labels[s.model]));
        const track = el("div", "compression-track");
        const complete = s.points.filter((p) => !p.failed),
          mean = complete.length
            ? complete.reduce((a, p) => a + p.value, 0) / complete.length
            : null;
        if (mean !== null) {
          const bar = el("div", "compression-bar");
          bar.style.width = `${(mean / limit) * 100}%`;
          bar.style.background = colors[index];
          track.append(bar);
        }
        s.points.forEach((p, i) => {
          const dot = el(
            "button",
            p.failed ? "compression-dot time-failed" : "compression-dot",
            p.failed ? "×" : undefined,
          );
          dot.style.left = `${(p.value / limit) * 100}%`;
          dot.style.top = `${9 + (i % 5) * 7}px`;
          dot.style.borderColor = p.failed ? "#b83333" : colors[index];
          const text = `${labels[s.model]} · ${p.description} · ${(p.value / divisor).toFixed(2)} ${unit}`;
          dot.title = text;
          dot.setAttribute("aria-label", text);
          dot.onclick = () => (detail.textContent = text);
          track.append(dot);
        });
        const stats = el(
          "span",
          null,
          mean === null ? "No completed runs" : `${(mean / divisor).toFixed(2)} ${unit}`,
        );
        stats.append(
          variationLabel(
            entries.map((entry) =>
              records(entry, s.model)
                .filter((r) => r.status === "complete" && Number.isFinite(r.elapsed))
                .map((r) => r.elapsed),
            ),
          ),
        );
        row.append(track, stats);
        host.append(row);
      });
      host.append(
        detail,
        el(
          "p",
          "hint",
          "Wall-clock time per run, not total batch duration. API results include sequential runs and runs under a seven-worker limit. Variation measures spread across completed runs within each video, averaged across eligible videos. At least two completed runs are required. The table below also reports averages including failures.",
        ),
      );
    }
    paintTime = paint;
    measure.onchange = () => {
      timeMeasure = measure.value;
      paint();
    };
    select.onchange = () => {
      timeSelection = select.value;
      paint();
    };
    paint();
    return section;
  }
  let costMeasure = "total";
  let paintCost = () => {};
  function costChart() {
    const section = el("section", "panel comparison-section");
    section.append(
      el("h2", null, "API cost per video"),
      el(
        "p",
        null,
        "Average cost and minimum–maximum range in US cents. Hover or select a row to see individual run costs.",
      ),
    );
    const label = el("label", null, "Cost measure");
    label.htmlFor = "cost-measure";
    const select = el("select");
    select.id = "cost-measure";
    for (const [value, text] of [
      ["total", "Cost per video"],
      ["normalized", "Cost per 1,000 transcript words"],
    ]) {
      const option = el("option", null, text);
      option.value = value;
      select.append(option);
    }
    select.value = costMeasure;
    const host = el("div");
    section.append(label, select, host);
    function paint() {
      host.replaceChildren();
      const normalized = costMeasure === "normalized";
      if (normalized && !compressionData) {
        host.append(el("p", "hint", "Loading transcript word counts…"));
        return;
      }
      const unit = normalized ? "¢ / 1,000 words" : "¢";
      const names = [
        "Python introduction",
        "AI introduction",
        "DFS, hill climbing & beam",
        "Branch and bound / A*",
        "Minimax & alpha-beta",
        "Nearest neighbors",
        "Identification trees",
        "Neural networks",
        "Deep neural networks",
        "Support vector machines",
      ];
      const rows = cohort.map((entry, i) => {
        const runs = records(entry, "openai")
          .filter(
            (r) =>
              ["complete", "error", "failed", "cancelled"].includes(r.status) &&
              Number.isFinite(r.estimated_cost_usd),
          )
          .sort((a, b) => a.run_number - b.run_number);
        const words = compressionData?.rows.find((row) => row.url === entry.url)?.words;
        return {
          entry,
          name: names[i] || entry.title,
          runs,
          words,
          factor: normalized ? (words > 0 ? 1000 / words : null) : 1,
        };
      });
      const step = normalized ? 1 : 5;
      const limit = Math.max(
        step,
        Math.ceil(
          Math.max(
            0,
            ...rows
              .filter((r) => r.factor !== null)
              .flatMap((r) => r.runs.map((x) => x.estimated_cost_usd * 100 * r.factor)),
          ) / step,
        ) * step,
      );
      const scroll = el("div", "cost-points-scroll");
      const chart = el("div", "cost-points-chart");
      scroll.append(chart);
      const axis = el("div", "cost-points-axis");
      for (let i = 0; i <= 4; i++) {
        const tick = el("span", null, `${((limit * i) / 4).toFixed(normalized ? 2 : 0)}¢`);
        tick.style.left = `${i * 25}%`;
        axis.append(tick);
      }
      chart.append(axis);
      const detail = el(
        "p",
        "compression-detail",
        "Hover or select a video to see its five run costs.",
      );
      for (const row of rows) {
        const line = el("div", "cost-points-row");
        const name = el("strong", "cost-short-name", row.name);
        name.title = row.entry.title;
        line.append(name);
        const plot = el("div", "cost-points-plot");
        for (let i = 0; i <= 4; i++) {
          const grid = el("span", "cost-grid-line");
          grid.style.left = `${i * 25}%`;
          plot.append(grid);
        }
        if (row.runs.length && row.factor !== null) {
          const costs = row.runs.map((r) => r.estimated_cost_usd * 100 * row.factor),
            min = Math.min(...costs),
            max = Math.max(...costs),
            mean = costs.reduce((a, b) => a + b, 0) / costs.length;
          const range = el("span", "cost-range-line");
          range.style.left = `${(min / limit) * 100}%`;
          range.style.width = `${((max - min) / limit) * 100}%`;
          plot.append(range);
          const avg = el("span", "cost-average-marker");
          avg.style.left = `${(mean / limit) * 100}%`;
          plot.append(avg);
          const text = `${row.entry.title} · Average ${mean.toFixed(2)} ${unit} · Range ${min.toFixed(2)}–${max.toFixed(2)} ${unit}${normalized ? ` · ${row.words.toLocaleString()} transcript words` : ""} · ${row.runs.map((r) => `Run ${r.run_number}: ${(r.estimated_cost_usd * 100 * row.factor).toFixed(2)} ${unit}`).join(" · ")}`;
          line.tabIndex = 0;
          line.setAttribute("role", "button");
          line.setAttribute("aria-label", text);
          line.title = text;
          const show = () => (detail.textContent = text);
          line.onmouseenter = show;
          line.onfocus = show;
          line.onclick = show;
          line.onkeydown = (event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              show();
            }
          };
          const stats = el("div", "cost-point-stats");
          stats.append(el("strong", null, `${mean.toFixed(2)}¢`));
          if (row.runs.length !== 5) stats.append(el("small", null, `${row.runs.length}/5 runs`));
          line.append(plot, stats);
        } else
          line.append(
            plot,
            el("span", null, row.factor === null ? "Transcript unavailable" : "No recorded costs"),
          );
        chart.append(line);
      }
      host.append(
        el(
          "p",
          "hint",
          normalized
            ? "Cents per 1,000 saved transcript words: run cost ÷ transcript words × 1,000. Output length and reasoning still affect cost."
            : "Cents per video.",
        ),
        scroll,
        detail,
        el(
          "p",
          "hint",
          "Dot = average; line = minimum to maximum, on the same scale for every video. USD estimates from recorded token usage, not billing receipts. Finished attempts include failures if any; pending or missing costs are excluded.",
        ),
      );
    }
    paintCost = paint;
    select.onchange = () => {
      costMeasure = select.value;
      paint();
    };
    paint();
    return section;
  }
  window.renderExperimentComparison = async () => {
    const root = document.querySelector("#experiment-comparison");
    if (!cohort) {
      root.replaceChildren(el("p", "hint", "Loading comparison cohort…"));
      try {
        await loadCohort();
      } catch (error) {
        const retry = el("button", "secondary", "Retry loading comparison");
        retry.onclick = () => window.renderExperimentComparison();
        root.replaceChildren(el("p", "error", error.message), retry);
        return;
      }
    }
    const open = new Set([...root.querySelectorAll("details[open]")].map((x) => x.dataset.url));
    root.replaceChildren();
    const intro = el("section", "panel comparison-intro");
    intro.append(
      el("p", "step-label", "10-video experiment"),
      el("h2", null, "Local models vs. the API guides"),
      el(
        "p",
        null,
        "One saved transcript per video. Five attempts per system: seeded local runs and unseeded mixed-model OpenAI runs.",
      ),
      el(
        "p",
        "hint",
        "Metrics below come from the saved experiment runs. Quality observations are a manual review dated October 28, 2026, not automated scores or an exhaustive fact-check.",
      ),
    );
    const reload = el("button", "secondary", "Refresh results");
    reload.onclick = async () => {
      reload.disabled = true;
      try {
        compressionData = null;
        await refresh();
      } catch (e) {
        reload.disabled = false;
        reload.textContent = "Refresh failed — try again";
      }
    };
    intro.append(reload);
    root.append(intro);
    const cards = el("div", "comparison-cards");
    const aggregates = {};
    for (const model of models) {
      const m = metrics(
        cohort.flatMap((e) => records(e, model)),
        cohort.reduce((a, e) => a + e.runs[model].length, 0),
      );
      aggregates[model] = m;
      const card = el("section", "panel comparison-card");
      card.append(
        el("h3", null, labels[model]),
        el(
          "strong",
          "comparison-rate",
          m.terminal ? `${Math.round((m.complete / m.terminal) * 100)}%` : "—",
        ),
        el(
          "p",
          null,
          `${m.complete}/${m.terminal} finished attempts succeeded · ${m.failed} failed or cancelled`,
        ),
      );
      const progress = document.createElement("progress");
      progress.max = m.terminal || 1;
      progress.value = m.complete;
      progress.setAttribute("aria-label", `${labels[model]} successful finished attempts`);
      card.append(progress);
      card.append(
        el("p", "hint", `${m.expected - m.terminal} missing or unfinished attempts`),
        el("p", "comparison-verdict", verdicts[model]),
      );
      cards.append(card);
    }
    root.append(cards);
    root.append(compressionSection());
    root.append(timeChart());
    root.append(costChart());
    const timing = el("section", "panel comparison-section");
    timing.append(el("h2", null, "Time & cost"));
    timing.append(
      table(
        [
          "System",
          "Average / attempt",
          "Average / completed run",
          "Total recorded time",
          "Estimated API cost",
        ],
        models.map((model) => {
          const m = aggregates[model];
          return [
            labels[model],
            seconds(m.mean),
            seconds(m.successMean),
            `${(m.total / 60).toFixed(1)} min`,
            model === "openai" ? (m.cost === null ? "Unavailable" : money(m.cost)) : "$0 API fees",
          ];
        }),
      ),
    );
    timing.append(
      el(
        "p",
        "hint",
        "Attempt averages include failures, which can end early. Each system targets 50 attempts; pending attempts are excluded from timing averages. Local electricity and hardware costs are not measured; API costs are estimates, not billing receipts.",
      ),
    );
    root.append(timing);
    const lectures = el("section", "comparison-lectures");
    lectures.append(
      el("h2", null, "Video-by-video review"),
      el(
        "p",
        "hint",
        "Expand a video for its metrics and the specific guides reviewed. Completion does not guarantee accuracy.",
      ),
    );
    for (const entry of cohort) {
      const item = items.find((i) => i.url === entry.url);
      const detail = el("details", "panel comparison-lecture");
      detail.dataset.url = entry.url;
      detail.open = open.has(entry.url);
      const summary = el("summary");
      summary.append(el("strong", null, entry.title));
      detail.append(summary);
      const body = el("div", "comparison-lecture-body");
      const reviews = el("div", "comparison-review-grid");
      for (const [title, text] of [
        ["OpenAI guide", entry.openai_review],
        ["Local guides", entry.local_review],
      ]) {
        const block = el("div");
        block.append(el("h3", null, title), el("p", null, text));
        reviews.append(block);
      }
      body.append(reviews);
      body.append(
        table(
          ["System", "Completed", "Avg. attempt", "API cost", "Reviewed guide"],
          models.map((model) => {
            const rs = records(entry, model),
              m = metrics(rs, entry.runs[model].length),
              ref = entry.reviewed[model];
            const reviewed = rs.find(
              (r) =>
                r.run_number === ref?.run_number &&
                r.digest === ref.digest &&
                r.status === "complete",
            );
            let link = "Reviewed run unavailable";
            if (reviewed && item) {
              link = el("button", "secondary", `View run ${reviewed.run_number}`);
              link.onclick = () =>
                showStudyNotes(`/api/urls/${item.id}/notes/${model}/${reviewed.run_number}`);
            }
            return [
              labels[model],
              `${m.complete}/${m.expected}`,
              seconds(m.mean),
              model === "openai"
                ? m.cost === null
                  ? "Unavailable"
                  : money(m.cost)
                : "$0 API fees",
              link,
            ];
          }),
        ),
      );
      const digests = new Set(
        models.flatMap((m) =>
          records(entry, m)
            .map((r) => r.digest)
            .filter(Boolean),
        ),
      );
      body.append(
        el(
          "p",
          "hint",
          digests.size === 1
            ? "Saved transcript hashes match across the available cohort runs."
            : digests.size > 1
              ? "Transcript hashes differ across these runs; interpret comparisons with care."
              : "No saved transcript hashes available.",
        ),
      );
      body.append(
        el(
          "p",
          "hint",
          "Included runs: " + models.map((m) => `${m}: ${entry.runs[m].join(", ")}`).join(" · "),
        ),
      );
      detail.append(body);
      lectures.append(detail);
    }
    root.append(lectures);
    const method = el("section", "panel comparison-section");
    method.append(
      el("h2", null, "How to read this comparison"),
      el(
        "p",
        null,
        "The cohort is fixed to the original 150 local attempts and OpenAI runs 1–5 for each video. Video 2 uses 1.5B runs 6–10, excluding its duplicate first batch. New runs do not silently change this experiment.",
      ),
      el(
        "p",
        null,
        "The manual review compares the first completed guide in each cohort and samples variation in other local runs. It is not a numerical quality benchmark. OpenAI uses Luna for extraction and formatting, Terra for consolidation and review; each local system uses one model throughout. This compares systems, not model size alone.",
      ),
    );
    method.append(
      el(
        "p",
        "hint",
        "The additional OpenAI experiment switched from sequential execution to a maximum of seven concurrent workers without restarting the active run. Later attempts record their worker limit. Parallel execution may affect wall-clock timings, so API timing comparisons include both sequential and parallel runs.",
      ),
    );
    root.append(method);
  };
})();
