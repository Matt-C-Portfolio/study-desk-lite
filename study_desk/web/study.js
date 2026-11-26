let openaiAvailable = false;
fetch("/api/providers")
  .then((r) => r.json())
  .then((data) => {
    openaiAvailable = data.openai;
    renderStudy();
  })
  .catch(() => {});
// Step 3 controls and progress display.
const passRows = ["Extract", "Consolidate", "Review", "Format"].map((name, index) => {
  const row = el("div", "study-pass"),
    head = el("div", "study-pass-head"),
    label = el("span", "study-pass-label", "Waiting"),
    rail = el("div", "study-rail"),
    fill = el("div", "study-fill");
  const timing = el("span", "study-pass-label");
  const right = el("span");
  right.append(timing, label);
  head.append(el("strong", null, `${index + 1}. ${name}`), right);
  rail.append(fill);
  rail.setAttribute("role", "progressbar");
  rail.setAttribute("aria-label", name);
  rail.setAttribute("aria-valuemin", "0");
  rail.setAttribute("aria-valuemax", "100");
  row.append(head, rail);
  document.querySelector("#study-passes").append(row);
  return { label, rail, fill, timing, value: 0, target: 0 };
});
const notesDialog = document.querySelector("#study-dialog");
document.querySelector("#study-close").onclick = () => notesDialog.close();
let studyKey = "",
  studyAnimation = null;
function studyActive(item) {
  return Object.values(item.study_runs || {}).some((r) => ["running", "queued"].includes(r.status));
}
function animateStudy() {
  if (studyAnimation) return;
  let previous = performance.now();
  function tick(now) {
    const delta = Math.min(now - previous, 100);
    previous = now;
    let pending = false;
    for (const row of passRows) {
      row.value += (row.target - row.value) * Math.min(1, delta / 250);
      if (Math.abs(row.target - row.value) < 0.025) row.value = row.target;
      else pending = true;
      row.fill.style.width = `${row.value}%`;
      if (row.percent) {
        row.label.textContent = `${row.value.toFixed(1)}%`;
        row.rail.setAttribute("aria-valuenow", row.value.toFixed(1));
      }
    }
    studyAnimation = pending ? requestAnimationFrame(tick) : null;
  }
  studyAnimation = requestAnimationFrame(tick);
}
function renderStudy() {
  const item = items.find((i) => i.id === currentIntakeId),
    selector = document.querySelector("#study-model");
  const running = item && Object.values(item.study_runs || {}).find((r) => r.status === "running");
  if (running) selector.value = running.model;
  const busy =
    workspaceBusy ||
    submitting ||
    items.some((i) => activeStates.includes(i.state) || studyActive(i));
  const baseline = selector.value === "openai";
  document.querySelector(".study-seed-controls").hidden = baseline;
  document.querySelector("#study-seed-hint").hidden = baseline;
  document.querySelector("#study-passes").hidden = false;
  let run = item?.study_runs?.[selector.value];
  if (run && run.transcript_path !== item.transcript_path) run = null;
  selector.disabled = busy;
  const generate = document.querySelector("#study-generate");
  generate.disabled = busy || !item?.transcript_path || (baseline && !openaiAvailable);
  generate.textContent = baseline ? "Generate OpenAI run" : "Generate new run";
  document.querySelector("#study-seed").disabled = busy;
  document.querySelector("#study-five").disabled = busy || !item?.transcript_path;
  document.querySelector("#study-all-local").disabled = busy || !item?.transcript_path;
  renderRunHistory(item);
  const status = document.querySelector("#study-status");
  status.textContent =
    baseline && !openaiAvailable
      ? "Configure OPENAI_API_KEY or your external user key file to enable OpenAI."
      : run
        ? `${run.detail}${run.elapsed ? ` · ${Math.round(run.elapsed)}s` : ""}${Number.isFinite(run.estimated_cost_usd) ? ` · estimated $${run.estimated_cost_usd.toFixed(4)}` : ""}`
        : item?.transcript_path
          ? baseline
            ? "Sends the selected transcript to OpenAI. Luna extracts/formats; Terra consolidates/reviews. API charges apply. Costs and timings are saved per run."
            : `Using ${item.method}. Results are saved separately for each model.`
          : "Choose a transcript in Step 2 first.";
  status.style.color = run?.status === "error" ? "#ad3030" : "";
  const key = `${item?.id}:${selector.value}:${run?.run_number || ""}`;
  if (key !== studyKey) {
    studyKey = key;
    for (const row of passRows) {
      row.value = row.target = 0;
      row.fill.style.width = "0%";
    }
  }
  passRows.forEach((row, i) => {
    const pass = run?.passes?.[i],
      active = run?.status === "running" && run.stage === i;
    row.timing.textContent = Number.isFinite(pass?.elapsed)
      ? `${pass.elapsed.toFixed(1)}s${pass.cached_calls ? ` · ${pass.cached_calls} reused` : ""} · `
      : run
        ? "Timing not recorded · "
        : "";
    const percent = pass?.total > 1 || pass?.status === "complete";
    row.percent = percent;
    row.target = pass ? (100 * pass.done) / pass.total : 0;
    row.rail.classList.toggle("working", active && !percent);
    if (!percent) {
      row.rail.removeAttribute("aria-valuenow");
      row.label.textContent = active
        ? pass?.activity
          ? `Working · ${pass.activity} output updates`
          : "Working…"
        : pass?.status === "running"
          ? "Stopped"
          : "Waiting";
    }
  });
  animateStudy();
  const comparison = run?.comparison;
  document.querySelector("#study-comparison").textContent = comparison
    ? comparison.reviews
      ? `${comparison.extracted} extracted · ${comparison.reviews.length} source chunks reviewed · ${comparison.issues?.length || 0} output issues. Review is advisory and does not filter notes.`
      : `${comparison.extracted} extracted · ${comparison.supported} supported · ${comparison.rejected} rejected · ${comparison.unverified || 0} unverified · ${comparison.quote_mismatches.length} non-verbatim quotes (wording only, not a correctness score). ${comparison.issues?.length || 0} other output issues. Source-check evaluates meaning; its decisions are model judgments.`
    : "";
  document.querySelector("#study-outputs").hidden = !run?.folder;
  document.querySelector("#study-result").hidden = run?.status !== "complete";
  if (run?.status === "complete")
    document.querySelector("#study-download").href = `/api/urls/${item.id}/notes/${selector.value}`;
}
document.querySelector("#study-model").onchange = renderStudy;
async function startStudyRun(action = "generate") {
  const item = items.find((i) => i.id === currentIntakeId);
  if (!item) return;
  const model = document.querySelector("#study-model").value;

  submitting = true;
  renderIntake();
  renderStudy();
  try {
    const response = await fetch(`/api/urls/${item.id}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action,
        model,
        seed:
          document.querySelector("#study-seed").value === ""
            ? null
            : Number(document.querySelector("#study-seed").value),
      }),
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error);
    submitting = false;
    await refresh();
  } catch (error) {
    submitting = false;
    renderIntake();
    renderStudy();
    document.querySelector("#study-status").textContent = error.message;
  }
};
document.querySelector("#study-generate").onclick = () => startStudyRun();
document.querySelector("#study-five").onclick = () => startStudyRun("generate_five");
document.querySelector("#study-all-local").onclick = () => startStudyRun("generate_all_local");
async function showStudyNotes(url) {
  notesDialog.querySelector(".dialog-bar strong").textContent = "Study notes";
  const output = document.querySelector("#study-notes-text");
  output.textContent = "Loading notes…";
  output.className = "rendered-notes";
  notesDialog.showModal();
  try {
    const response = await fetch(url);
    if (!response.ok) throw Error("Could not load study notes.");
    const markdown = await response.text();
    output.innerHTML = DOMPurify.sanitize(marked.parse(markdown), {
      ALLOWED_TAGS: [
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "br",
        "hr",
        "ul",
        "ol",
        "li",
        "strong",
        "em",
        "del",
        "blockquote",
        "pre",
        "code",
        "a",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
      ],
      ALLOWED_ATTR: ["href", "title", "start"],
    });
  } catch (error) {
    output.textContent = error.message;
  }
};
renderStudy();

async function showStudyResults(url) {
  notesDialog.querySelector(".dialog-bar strong").textContent = "Comparison results";
  const output = document.querySelector("#study-notes-text");
  output.textContent = "Loading saved outputs…";
  output.className = "rendered-notes";
  notesDialog.showModal();
  try {
    const response = await fetch(url);
    if (!response.ok) throw Error("Could not load saved outputs.");
    const data = await response.json();
    const comparison = JSON.parse(data.files["comparison.json"] || "{}");
    const claims = Object.values(JSON.parse(data.files["claim-checks.json"] || "{}"));
    output.replaceChildren();
    const add = (tag, text, parent = output) => {
      const element = document.createElement(tag);
      element.textContent = text;
      parent.append(element);
      return element;
    };
    add("h1", "Comparison results");
    add(
      "p",
      "Review observations are model judgments, not independent proof. Original outputs and timings are preserved below.",
    );
    if (comparison.reviews) {
      add("h2", "Review observations");
      add("p", "Advisory feedback only. These observations do not filter content from the notes.");
      for (const review of comparison.reviews) {
        add("h3", review.source);
        add(
          "p",
          Array.isArray(review.observations)
            ? review.observations.join("\n") || "No observations returned."
            : JSON.stringify(review.observations),
        );
      }
    }
    if (claims.length) add("h2", "Legacy claim checks");
    for (const status of ["supported", "rejected", "unverified"]) {
      const group = claims.filter((claim) => claim.status === status);
      if (!group.length) continue;
      const details = add("details", "");
      add("summary", `${status}: ${group.length}`, details);
      for (const claim of group) {
        add("h3", `${claim.id} · ${claim.source}`, details);
        add("p", claim.text, details);
        add("p", claim.reason, details);
        add("blockquote", claim.quote, details);
      }
    }
    add("h2", "Output issues");
    for (const issue of comparison.issues || []) {
      add("p", `${issue.stage} · ${issue.item}: ${issue.problem}. ${issue.action}`);
    }
    if (comparison.quote_mismatches) {
      add("h2", "Legacy quote wording differences");
      add(
        "p",
        `${comparison.quote_mismatches?.length || 0} quotes were not literal matches. These remain recorded separately from semantic source checks.`,
      );
      add("p", (comparison.quote_mismatches || []).join(", "));
    }
    const cleanup = JSON.parse(data.files["display-cleanup.json"] || "[]");
    if (cleanup.length) {
      const details = add("details", "");
      add("summary", `Display cleanup: ${cleanup.length} changes`, details);
      add(
        "p",
        "Repeated list entries and unfinished caption fragments were removed from the display; inline numbered lists were reflowed. Original model output is preserved. This is not a factual review.",
        details,
      );
      for (const change of cleanup) {
        add("h3", `${change.section} · ${change.field}`, details);
        add("p", "Original", details);
        add(
          "pre",
          typeof change.original === "string"
            ? change.original
            : JSON.stringify(change.original, null, 2),
          details,
        );
        add("p", "Displayed", details);
        add(
          "pre",
          typeof change.displayed === "string"
            ? change.displayed
            : JSON.stringify(change.displayed, null, 2),
          details,
        );
      }
    }
    const raw = add("details", "");
    add("summary", "All saved outputs and timings", raw);
    add("pre", JSON.stringify(data, null, 2), raw);
  } catch (error) {
    output.textContent = error.message;
  }
};

document.querySelector("#study-view").onclick = () =>
  showStudyNotes(document.querySelector("#study-download").getAttribute("href"));
document.querySelector("#study-outputs").onclick = () =>
  showStudyResults(
    `/api/urls/${currentIntakeId}/results/${document.querySelector("#study-model").value}`,
  );
function renderRunHistory(item) {
  let root = document.querySelector("#study-run-history");
  if (!root) {
    root = el("section", "panel");
    root.id = "study-run-history";
    root.setAttribute("aria-label", "Run history");
    document.querySelector("#study-step").after(root);
  }
  const header = el("div", "panel-header");
  const heading = el("div");
  heading.append(
    el("h2", null, "Run history"),
    el("p", null, "Compare attempts by model. Each new run is saved separately."),
  );
  header.append(heading);
  const body = el("div", "run-history-body");
  if (item?.url === "https://www.youtube.com/watch?v=k6U-i4gXkLM") {
    const saved = el("button", "secondary", "View original OpenAI baseline");
    saved.onclick = showOpenAIBaseline;
    header.append(saved);
  }
  root.replaceChildren(header, body);
  body.append(
    el(
      "p",
      "hint",
      "The first completed run per model is selected for the graph. Completion does not guarantee accuracy.",
    ),
  );
  for (const model of ["1.5B", "7B", "14B", "openai"]) {
    const section = el("section", "run-history-model");
    const runs = item?.run_history?.[model] || [];
    const modelHead = el("div", "run-model-header");
    modelHead.append(
      el("h3", null, model === "openai" ? "OpenAI · Luna + Terra" : `DeepSeek R1 ${model}`),
      el("span", "hint", `${runs.length} ${runs.length === 1 ? "run" : "runs"}`),
    );
    section.append(modelHead);
    if (!runs.length) section.append(el("p", "hint", "No runs yet."));
    for (const run of runs) {
      const row = el("div", "run-history-row");
      const label =
        run.status === "complete"
          ? "Completed"
          : run.status === "error"
            ? "Failed"
            : run.status === "queued"
              ? "Queued"
              : "Running";
      row.append(
        el("strong", null, `Run ${run.run_number}`),
        el("span", `run-status run-status-${run.status}`, label),
        el(
          "span",
          "run-duration",
          Number.isFinite(run.elapsed) ? `${run.elapsed.toFixed(1)}s` : "--",
        ),
      );
      row.append(
        el(
          "span",
          "run-seed",
          model === "openai"
            ? `Estimated $${(run.estimated_cost_usd || 0).toFixed(4)}`
            : Number.isInteger(run.seed)
              ? `Seed ${run.seed}`
              : "Unseeded pilot",
        ),
      );
      if (run.graph_selected) row.append(el("span", "graph-run-badge", "Selected for graph"));
      const actions = el("div", "run-actions");
      const prefix = `/api/urls/${item.id}`;
      if (run.status === "complete") {
        const button = el("button", "secondary", "View notes");
        button.onclick = () => showStudyNotes(`${prefix}/notes/${model}/${run.run_number}`);
        actions.append(button);
      }
      if (run.folder) {
        const button = el("button", "secondary", "Comparison results");
        button.onclick = () => showStudyResults(`${prefix}/results/${model}/${run.run_number}`);
        actions.append(button);
      }
      row.append(actions);
      if (run.status === "error") row.append(el("small", "run-error", run.detail));
      section.append(row);
    }
    body.append(section);
  }
}

async function showOpenAIBaseline() {
  notesDialog.querySelector(".dialog-bar strong").textContent = "OpenAI baseline · Luna + Terra";
  const output = document.querySelector("#study-notes-text");
  output.className = "rendered-notes baseline-notes";
  output.textContent = "Loading saved baseline…";
  notesDialog.showModal();
  try {
    const response = await fetch("/api/baseline");
    if (!response.ok) throw Error("Could not load baseline.");
    const data = await response.json();
    output.innerHTML = DOMPurify.sanitize(
      marked.parse(data.guide || "No saved baseline available."),
      {
        USE_PROFILES: { html: true },
        FORBID_TAGS: ["img", "style", "iframe", "form", "input", "button"],
      },
    );
  } catch (error) {
    output.textContent = error.message;
  }
}
