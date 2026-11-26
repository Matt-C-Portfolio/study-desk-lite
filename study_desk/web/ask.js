/* Four-mode comparison; saved job IDs resume after refresh without resubmission. */
(() => {
  const root = document.querySelector("#ask-view");
  const el = (tag, text) => {
    const n = document.createElement(tag);
    if (text) n.textContent = text;
    return n;
  };
  const panel = el("section");
  panel.className = "panel comparison-section";
  panel.append(
    el("h2", "Ask across your videos"),
    el(
      "p",
      "Ask once to compare model only, RAG, graph only, and RAG + graph for the selected model.",
    ),
  );
  const form = el("form");
  form.style.padding = "0";
  const question = el("textarea");
  question.id = "ask-question";
  question.required = true;
  question.maxLength = 1500;
  question.rows = 4;
  question.style.width = "100%";
  question.placeholder = "What would you like to understand?";
  const qLabel = el("label", "Question");
  qLabel.htmlFor = question.id;
  form.append(qLabel, question);
  const controls = el("div");
  controls.className = "graph-controls";
  function select(label, options) {
    const wrap = el("label", label),
      s = el("select");
    for (const [value, text] of options) {
      const o = el("option", text);
      o.value = value;
      s.append(o);
    }
    wrap.append(s);
    controls.append(wrap);
    return s;
  }
  const model = select("Model", [
    ["1.5B", "DeepSeek 1.5B"],
    ["7B", "DeepSeek 7B"],
    ["14B", "DeepSeek 14B"],
    ["openai", "OpenAI · Luna (paid API)"],
  ]);
  model.value = "14B";
  const modes = { plain: "Model only", rag: "RAG", graph_only: "Graph only", graph: "RAG + graph" };
  const seedLabel = el("label", "Local seed"),
    seed = el("input");
  seed.type = "number";
  seed.min = 0;
  seed.max = 2147483647;
  seed.value = 42;
  seedLabel.append(seed);
  controls.append(seedLabel);
  model.onchange = () => {
    seed.disabled = model.value === "openai";
  };
  const submit = el("button", "Ask all four");
  submit.type = "submit";
  controls.append(submit);
  form.append(controls);
  panel.append(
    form,
    el(
      "p",
      "All retrieval modes use up to six passages. RAG searches transcripts; graph only starts from concepts and follows relationships; RAG + graph combines three direct matches with up to three connected passages. Graph relationships are model interpretations; citations refer to the transcript.",
    ),
  );
  const status = el("p");
  status.setAttribute("role", "status");
  panel.append(status);
  root.append(panel);
  const output = el("section");
  output.className = "ask-comparison-grid";
  output.hidden = true;
  root.append(output);
  let batch = null;
  const cards = new Map();
  const storageKey = "ask-four-mode-comparison-v1";
  function markdown(node, text) {
    if (!window.marked || !window.DOMPurify) {
      node.textContent = text;
      return;
    }
    const math = [];
    // Accept one or two delimiter backslashes for display only; preserve code and saved text.
    const protectedText = text.replace(
      /```[\s\S]*?```|`[^`\n]+`|(\\{1,2})\[([\s\S]*?)\1\]|(\\{1,2})\(([\s\S]*?)\3\)|\$\$([\s\S]*?)\$\$/g,
      (match, displaySlash, display, inlineSlash, inline, dollars) => {
        if (match.startsWith("`")) return match;
        const token = "ASKMATHTOKEN" + math.length + "END";
        math.push({ token, latex: display ?? inline ?? dollars, display: inline === undefined });
        return token;
      },
    );
    node.innerHTML = DOMPurify.sanitize(marked.parse(protectedText));
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT),
      texts = [];
    while (walker.nextNode()) texts.push(walker.currentNode);
    for (const t of texts) {
      if (t.parentElement.closest("code,pre")) continue;
      const parts = t.textContent.split(/(ASKMATHTOKEN\d+END)/);
      if (parts.length === 1) continue;
      const frag = document.createDocumentFragment();
      for (const part of parts) {
        const item = math.find((m) => m.token === part);
        if (!item) {
          frag.append(document.createTextNode(part));
          continue;
        }
        const span = el("span");
        span.className = item.display ? "ask-math-display" : "";
        if (window.katex)
          katex.render(item.latex, span, {
            displayMode: item.display,
            throwOnError: false,
            trust: false,
          });
        else span.textContent = item.latex;
        frag.append(span);
      }
      t.replaceWith(frag);
    }
  }
  window.renderAnswerMarkdown = markdown;
  function render(data, output) {
    output.hidden = false;
    output.classList.add("ask-result");
    output.replaceChildren(el("h2", modes[data.mode] || data.mode));
    const meta = el(
      "p",
      (data.model === "openai" ? "OpenAI" : "DeepSeek " + data.model) +
        " · " +
        ({ plain: "Model only", rag: "RAG", graph_only: "Graph only", graph: "RAG + graph" }[
          data.mode
        ] || data.mode) +
        " · " +
        data.elapsed +
        "s" +
        (data.seed != null ? " · seed " + data.seed : "") +
        (data.estimated_cost_usd != null
          ? " · estimated $" + data.estimated_cost_usd.toFixed(4)
          : ""),
    );
    meta.className = "ask-meta";
    output.append(meta);
    const answer = el("article");
    answer.className = "ask-answer";
    markdown(answer, data.answer || data.partial_answer || "");
    output.append(answer);
    const cited = new Set(),
      walker = document.createTreeWalker(answer, NodeFilter.SHOW_TEXT),
      nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    const preview = el("aside");
    preview.className = "ask-evidence";
    preview.hidden = true;
    output.append(preview);
    const stamp = (s) =>
      s.start_s != null
        ? Math.floor(s.start_s / 60) + ":" + String(Math.floor(s.start_s % 60)).padStart(2, "0")
        : "";
    const origin = (s) =>
      s.retrieval === "graph neighbor"
        ? "Graph connection"
        : s.retrieval === "graph concept"
          ? "Graph concept"
          : s.retrieval === "direct"
            ? "Direct retrieval"
            : "Retrieved passage";
    function route(node, source) {
      if (source.matched_concepts)
        node.append(el("p", "Matched concepts: " + source.matched_concepts.join(", ")));
      if (source.graph_path) {
        const r = source.graph_path;
        node.append(
          el("p", r.source + " → " + r.relation + " → " + r.target),
          el("small", "Connected to " + r.direct_source_ids.join(", ")),
        );
        if (r.rationale) node.append(el("p", r.rationale));
      }
    }
    function showSource(index) {
      const source = data.sources[index];
      preview.replaceChildren();
      preview.hidden = false;
      const close = el("button", "Close");
      close.type = "button";
      close.onclick = () => {
        preview.hidden = true;
      };
      preview.append(
        close,
        el("h3", "S" + (index + 1) + " · " + source.title),
        el("small", stamp(source) + " · " + origin(source)),
      );
      route(preview, source);
      preview.append(
        el("p", source.text.length > 650 ? source.text.slice(0, 650) + "…" : source.text),
      );
      if (source.text.length > 650) {
        const full = el("details");
        full.append(el("summary", "Full passage"), el("p", source.text));
        preview.append(full);
      }
      try {
        const url = new URL(source.url);
        if (["http:", "https:"].includes(url.protocol)) {
          if (source.start_s != null) url.searchParams.set("t", String(Math.floor(source.start_s)));
          const link = el("a", "Open source video ↗");
          link.href = url.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          preview.append(link);
        }
      } catch {}
    }
    for (const node of nodes) {
      if (node.parentElement.closest("code,pre,.katex")) continue;
      const parts = node.textContent.split(/(\[S\d+\])/);
      if (parts.length === 1) continue;
      const fragment = document.createDocumentFragment();
      for (const part of parts) {
        const match = part.match(/^\[S(\d+)\]$/),
          i = match ? Number(match[1]) - 1 : -1;
        if (i < 0 || i >= (data.sources?.length || 0)) {
          fragment.append(document.createTextNode(part));
          continue;
        }
        cited.add(i);
        const badge = el("button", String(i + 1));
        badge.type = "button";
        badge.className = "ask-citation";
        badge.setAttribute("aria-label", "Show source " + (i + 1));
        badge.onclick = () => {
          showSource(i);
          badge.closest("p,li,section")?.after(preview);
        };
        fragment.append(badge);
      }
      node.replaceWith(fragment);
    }
    for (const warning of data.citation_warnings || []) output.append(el("p", warning));
    if (data.error) output.append(el("p", data.error));
    if (cited.size) {
      const used = el("div");
      used.className = "ask-used";
      used.append(el("strong", "Sources cited"));
      for (const i of cited) {
        const button = el(
          "button",
          "S" + (i + 1) + " · " + origin(data.sources[i]) + " · " + data.sources[i].title,
        );
        button.type = "button";
        button.onclick = () => {
          showSource(i);
          used.after(preview);
        };
        used.append(button);
      }
      output.append(used);
    }
    const unused = (data.sources || [])
      .map((source, i) => ({ source, i }))
      .filter((x) => !cited.has(x.i));
    if (unused.length) {
      const extra = el("details");
      extra.className = "ask-extra";
      extra.append(el("summary", "Other retrieved passages (" + unused.length + ")"));
      for (const { source, i } of unused) {
        const d = el("details");
        d.append(
          el(
            "summary",
            "S" + (i + 1) + " · " + origin(source) + " · " + source.title + " · " + stamp(source),
          ),
          el("p", source.text),
        );
        route(d, source);
        extra.append(d);
      }
      output.append(extra);
    }
    if (data.relationships?.length) {
      const d = el("details");
      d.className = "ask-extra";
      d.append(el("summary", "Graph hints used for retrieval"));
      data.relationships.forEach((r) =>
        d.append(el("p", r.source + " → " + r.relation + " → " + r.target)),
      );
      output.append(d);
    }
  }
  function save() {
    localStorage.setItem(storageKey, JSON.stringify(batch));
  }
  function locked(value) {
    submit.disabled = value;
    model.disabled = value;
    question.disabled = value;
    seed.disabled = value || model.value === "openai";
  }
  function mount() {
    output.hidden = false;
    output.replaceChildren();
    cards.clear();
    question.value = batch.question;
    model.value = batch.model;
    seed.value = batch.seed ?? 42;
    for (const item of batch.items) {
      const card = el("section");
      card.className = "panel comparison-section ask-result";
      card.append(
        el("h2", modes[item.mode]),
        el("p", item.state === "pending" ? "Waiting for earlier modes…" : "Loading saved answer…"),
      );
      output.append(card);
      cards.set(item.mode, card);
    }
  }
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  async function fetchAnswer(id) {
    const r = await fetch("/api/answers/" + id);
    const d = await r.json();
    if (!r.ok) throw Error(d.error || "Could not load answer.");
    return d;
  }
  async function drive() {
    locked(true);
    try {
      for (const item of batch.items) {
        const card = cards.get(item.mode);
        if (item.state === "submitting" && !item.id)
          throw Error(
            "The last submission could not be confirmed. Stopped to avoid creating a duplicate answer.",
          );
        if (!item.id) {
          item.state = "submitting";
          save();
          status.textContent = "Starting " + modes[item.mode] + "…";
          const r = await fetch("/api/answers", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              question: batch.question,
              model: batch.model,
              mode: item.mode,
              seed: batch.seed,
            }),
          });
          const d = await r.json();
          if (!r.ok) {
            item.state = "pending";
            save();
            throw Error(d.error || "Could not start answer.");
          }
          if (!/^[0-9a-f]{32}$/.test(d.id))
            throw Error("Answer submission returned no usable job ID.");
          item.id = d.id;
          item.state = "running";
          save();
        }
        let d = await fetchAnswer(item.id);
        while (["queued", "running"].includes(d.status)) {
          status.textContent =
            batch.items.filter((x) => ["complete", "error"].includes(x.state)).length +
            " / " +
            batch.items.length +
            " finished · " +
            modes[item.mode] +
            " · " +
            d.stage;
          card.replaceChildren(
            el("h2", modes[item.mode]),
            el("p", d.stage + " · " + d.elapsed + "s"),
          );
          await sleep(1500);
          d = await fetchAnswer(item.id);
        }
        item.state = d.status;
        save();
        render(d, card);
        // Give the worker time to release its active-job lock after its final save.
        await sleep(500);
      }
      status.textContent =
        batch.items.length +
        " / " +
        batch.items.length +
        " finished" +
        (batch.items.some((x) => x.state === "error")
          ? " · Some answers failed; their results are shown below."
          : "");
    } catch (e) {
      status.textContent = e.message;
      const resume = el("button", "Resume comparison");
      resume.type = "button";
      resume.onclick = () => {
        resume.remove();
        start();
      };
      status.append(" ", resume);
    } finally {
      locked(false);
    }
  }
  async function start(next = null) {
    const proceed = async () => {
      if (next) {
        batch = next;
        save();
        mount();
      }
      await drive();
    };
    // Only one tab may advance the saved queue; other tabs can still view saved answers.
    if (navigator.locks)
      await navigator.locks.request("study-desk-ask-four", { ifAvailable: true }, async (lock) => {
        if (!lock) {
          status.textContent =
            "This comparison is running in another tab. Refresh here to load its saved progress.";
          return;
        }
        await proceed();
      });
    else await proceed();
  }
  form.onsubmit = (event) => {
    event.preventDefault();
    const requested = new URL(location.href);
    requested.searchParams.delete("answer");
    history.replaceState(null, "", requested);
    start({
      question: question.value.trim(),
      model: model.value,
      seed: Number(seed.value),
      items: Object.keys(modes).map((mode) => ({ mode, state: "pending" })),
    });
  };
  const requested = new URLSearchParams(location.search).get("answer");
  if (requested && /^[0-9a-f]{32}$/.test(requested)) {
    fetchAnswer(requested)
      .then((d) => {
        batch = {
          question: d.question,
          model: d.model,
          seed: d.seed ?? 42,
          items: [{ mode: d.mode, id: d.id, state: d.status }],
        };
        mount();
        const card = cards.get(d.mode);
        render(d, card);
        status.textContent = "Saved answer · " + d.status;
      })
      .catch((e) => {
        status.textContent = e.message;
      });
  } else {
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey));
      if (
        stored &&
        Array.isArray(stored.items) &&
        stored.items.length === 4 &&
        stored.items.every((x) => Object.hasOwn(modes, x.mode))
      ) {
        batch = stored;
        mount();
        start();
      }
    } catch (e) {
      status.textContent = "Could not restore the previous comparison.";
    }
  }
})();
/* Read-only full-evaluation comparison. Metadata is published by the evaluation runner. */
(() => {
  const root = document.querySelector("#answer-comparison-view");
  const models = {
    "1.5B": "DeepSeek 1.5B",
    "7B": "DeepSeek 7B",
    "14B": "DeepSeek 14B",
    openai: "OpenAI",
  };
  const modes = { plain: "Model only", rag: "RAG", graph_only: "Graph only", graph: "RAG + graph" };
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text != null) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
  const select = (label, items, parent) => {
    const l = el("label", label),
      s = el("select");
    for (const [v, t] of items) {
      const o = el("option", t);
      o.value = v;
      s.append(o);
    }
    l.append(s);
    parent.append(l);
    return s;
  };
  let data = null,
    questionId = null,
    chosen = [
      ["14B", "rag"],
      ["14B", "graph"],
    ],
    version = 0,
    loadVersion = 0;
  const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
  const fmt = (n, d = 1) => (n == null ? "—" : n.toFixed(d));
  async function load() {
    const current = ++loadVersion;
    version++;
    root.replaceChildren(el("p", "Loading comparison results…"));
    try {
      const response = await fetch("/data/answer-comparison-data.json");
      if (!response.ok) throw Error("Could not load comparison results.");
      const saved = await response.json();
      if (
        !Array.isArray(saved?.rows) ||
        !saved.rows.length ||
        !Array.isArray(saved?.questions) ||
        !saved.questions.length
      )
        throw Error("Comparison results are not available yet.");
      if (current !== loadVersion) return;
      data = saved;
      render();
    } catch (e) {
      if (current !== loadVersion) return;
      const retry = el("button", "Retry loading comparison", "secondary");
      retry.onclick = load;
      root.replaceChildren(el("p", e.message), retry);
    }
  }
  function render() {
    root.replaceChildren();
    const head = el("section", null, "panel comparison-section");
    head.append(
      el("h2", "Answer comparison"),
      el("p", "120 questions · four systems · four answer modes. Saved results only."),
    );
    const finished = data.rows.filter((r) => ["complete", "error"].includes(r.status)).length;
    head.append(
      el(
        "p",
        `${finished} / ${data.rows.length} attempts finished · Updated ${new Date(data.updated_at).toLocaleString()}`,
      ),
    );
    const refresh = el("button", "Refresh results", "secondary");
    refresh.onclick = load;
    head.append(refresh);
    root.append(head);
    const metricPanel = el("section", null, "panel comparison-section");
    const controls = el("div", null, "ac-controls");
    const category = select(
      "Questions",
      [
        ["", "All categories"],
        ...Array.from(new Set(data.questions.map((q) => q.category))).map((x) => [x, x]),
      ],
      controls,
    );
    metricPanel.append(controls);
    const visuals = el("div");
    metricPanel.append(visuals);
    root.append(metricPanel);
    const colors = { plain: "#7c8c9c", rag: "#238bc4", graph_only: "#8260ac", graph: "#148577" };
    const questionById = new Map(data.questions.map((q) => [q.id, q]));
    function draw() {
      visuals.replaceChildren();
      const ids = new Set(
        data.questions
          .filter((q) => !category.value || q.category === category.value)
          .map((q) => q.id),
      );
      const rows = data.rows.filter((r) => ids.has(r.question_id));
      const terminal = rows.filter((r) => ["complete", "error"].includes(r.status));
      const section = (title, description) => {
        const box = el("section", null, "ac-visual-section");
        box.append(el("h2", title));
        if (description) box.append(el("p", description, "ac-description"));
        visuals.append(box);
        return box;
      };
      const completion = section(
        "Which answers finished?",
        "Completed / finished attempts. Pending and running attempts are shown separately; completion does not measure accuracy.",
      );
      const table = el("table", null, "ac-completion-table");
      const thead = el("thead"),
        hr = el("tr");
      hr.append(el("th", "System"));
      Object.values(modes).forEach((t) => hr.append(el("th", t)));
      thead.append(hr);
      table.append(thead);
      const tbody = el("tbody");
      for (const [model, name] of Object.entries(models)) {
        const tr = el("tr");
        const th = el("th", name);
        th.scope = "row";
        tr.append(th);
        for (const mode of Object.keys(modes)) {
          const all = rows.filter((r) => r.model === model && r.mode === mode),
            done = all.filter((r) => ["complete", "error"].includes(r.status)),
            passed = done.filter((r) => r.status === "complete").length,
            failed = done.length - passed,
            pending = all.length - done.length;
          const td = el("td");
          td.style.background = done.length
            ? `hsl(${Math.round((150 * passed) / done.length)} 30% 93%)`
            : "#f0f2f3";
          td.append(
            el("strong", `${passed} / ${done.length}`),
            el("span", `${failed} failed`),
            el("small", pending ? `${pending} remaining` : "Finished"),
          );
          tr.append(td);
        }
        tbody.append(tr);
      }
      table.append(tbody);
      const scroll = el("div", null, "ac-table-scroll");
      scroll.append(table);
      completion.append(scroll);
      const distribution = section(
        "How much do answers vary?",
        "Each dot is one answer. The diamond is the mean. Hover, focus, or select a dot to see the question and exact value.",
      );
      const picker = el("div", null, "ac-controls");
      const measure = select(
        "Measure",
        [
          ["words", "Answer length · words"],
          ["seconds", "Time per attempt · seconds"],
        ],
        picker,
      );
      distribution.append(picker);
      const plot = el("div", null, "ac-dotplot"),
        detail = el("div", "Select a dot to inspect an answer.", "ac-point-detail");
      detail.setAttribute("aria-live", "polite");
      distribution.append(plot, detail);
      const plotNote = el("p", null, "ac-description");
      distribution.append(plotNote);
      function drawPlot() {
        plot.replaceChildren();
        const key = measure.value;
        const usable = terminal.filter(
          (r) => (key === "seconds" || r.status === "complete") && Number.isFinite(r[key]),
        );
        const max = Math.max(1, ...usable.map((r) => r[key]));
        const ceiling =
          Math.ceil(max / (key === "words" ? 100 : 10)) * (key === "words" ? 100 : 10);
        const axis = el("div", null, "ac-plot-axis");
        axis.append(el("span", ""));
        const ticks = el("div", null, "ac-axis-ticks");
        for (let i = 0; i <= 4; i++) ticks.append(el("span", fmt((ceiling * i) / 4, 0)));
        axis.append(ticks, el("span", "Mean · n"));
        plot.append(axis);
        for (const [model, name] of Object.entries(models)) {
          plot.append(el("h3", name, "ac-plot-model"));
          for (const [mode, label] of Object.entries(modes)) {
            const group = usable.filter((r) => r.model === model && r.mode === mode),
              line = el("div", null, "ac-plot-row");
            line.append(el("span", label));
            const area = el("div", null, "ac-points");
            area.setAttribute("aria-label", name + " " + label);
            for (let i = 0; i <= 4; i++) {
              const guide = el("i", null, "ac-gridline");
              guide.style.left = i * 25 + "%";
              area.append(guide);
            }
            const sorted = [...group].sort((a, b) => a[key] - b[key]);
            const lanes = Array(7).fill(-Infinity);
            for (const r of sorted) {
              const x = (r[key] / ceiling) * 100;
              let lane = lanes.findIndex((last) => x - last > 1.8);
              if (lane < 0) lane = lanes.indexOf(Math.min(...lanes));
              lanes[lane] = x;
              const dot = el("button", null, "ac-point");
              dot.type = "button";
              dot.style.left = x + "%";
              dot.style.top = 8 + lane * 9 + "px";
              dot.style.background = colors[mode];
              if (r.status === "error") dot.classList.add("ac-point-failed");
              const text = `${name} · ${label} · ${r.question_id}: ${questionById.get(r.question_id)?.question} — ${fmt(r[key], key === "words" ? 0 : 2)} ${key === "words" ? "words" : "seconds"} · ${r.status}`;
              dot.title = text;
              dot.setAttribute("aria-label", text);
              const inspect = () => {
                detail.replaceChildren(el("p", text));
                const link = el("a", "Read this answer beside another");
                link.href = "#answer-comparison";
                link.onclick = (e) => {
                  e.preventDefault();
                  q.value = r.question_id;
                  panels[0].model.value = r.model;
                  panels[0].mode.value = r.mode;
                  chosen[0] = [r.model, r.mode];
                  show();
                  compare.scrollIntoView({ behavior: "smooth", block: "start" });
                };
                detail.append(link);
              };
              dot.onmouseenter = dot.onfocus = dot.onclick = inspect;
              area.append(dot);
            }
            const avg = mean(group.map((r) => r[key]));
            if (avg != null) {
              const diamond = el("span", "◆", "ac-mean");
              diamond.style.left = (avg / ceiling) * 100 + "%";
              diamond.title = `Mean ${fmt(avg)}; ${group.length} attempts`;
              area.append(diamond);
            } else area.append(el("small", "No finished answers", "ac-no-points"));
            line.append(area, el("small", `${fmt(avg)} · ${group.length}`));
            plot.append(line);
          }
        }
        plotNote.textContent =
          key === "words"
            ? "Completed answers only. Word count excludes citation markers; it is not a quality score. Each plot uses the same scale across systems."
            : "All finished attempts, including failures (outlined dots). Time is total saved elapsed time. OpenAI used seven concurrent workers; local runs were sequential.";
      }
      measure.onchange = drawPlot;
      drawPlot();
      const evidence = section(
        "Where did the passages come from?",
        "Choose a question to see the actual retrieved passages: blue = direct transcript match, purple = graph, empty = unused. Six slots is the maximum budget, not a guarantee of six sources.",
      );
      const retrievalQuestion = select(
        "Question",
        data.questions.filter((q) => ids.has(q.id)).map((q) => [q.id, `${q.id} · ${q.question}`]),
        evidence,
      );
      const retrieval = el("div", null, "ac-retrieval-grid");
      evidence.append(retrieval);
      let retrievalVersion = 0;
      async function drawRetrieval() {
        const generation = ++retrievalVersion;
        retrieval.replaceChildren();
        for (const [model, name] of Object.entries(models)) {
          const card = el("section", null, "ac-retrieval-card");
          card.append(el("h3", name));
          retrieval.append(card);
          for (const mode of ["rag", "graph_only", "graph"]) {
            const row = rows.find(
              (r) =>
                r.question_id === retrievalQuestion.value && r.model === model && r.mode === mode,
            );
            const line = el("div", null, "ac-slots-row");
            line.append(el("span", modes[mode]));
            const slots = el("div", null, "ac-slots");
            const note = el("small", row?.status || "Pending");
            line.append(slots, note);
            card.append(line);
            for (let i = 0; i < 6; i++) slots.append(el("span", null, "ac-slot"));
            if (!row?.job_id || !["complete", "error"].includes(row.status)) continue;
            fetch("/api/answers/" + row.job_id)
              .then((r) => {
                if (!r.ok) throw Error();
                return r.json();
              })
              .then((answer) => {
                if (generation !== retrievalVersion) return;
                slots.replaceChildren();
                const sources = answer.sources || [];
                for (let i = 0; i < 6; i++) {
                  const s = sources[i],
                    dot = el(
                      s ? "button" : "span",
                      null,
                      "ac-slot" +
                        (s
                          ? String(s.retrieval || "").startsWith("graph")
                            ? " ac-slot-graph"
                            : " ac-slot-direct"
                          : ""),
                    );
                  if (s) {
                    dot.type = "button";
                    dot.title = `[S${i + 1}] ${s.title} · ${s.retrieval || "direct"}`;
                    dot.setAttribute("aria-label", dot.title);
                    dot.onclick = () => {
                      let preview = card.querySelector(".ac-source-preview");
                      if (!preview) {
                        preview = el("div", null, "ac-source-preview");
                        card.append(preview);
                      }
                      preview.replaceChildren(el("strong", dot.title), el("p", s.text));
                    };
                  }
                  slots.append(dot);
                }
                note.textContent = `${sources.length} retrieved · ${row.cited ?? 0} cited${row.status === "error" ? " · failed" : ""}`;
              })
              .catch(() => {
                if (generation === retrievalVersion) note.textContent = "Sources unavailable";
              });
          }
        }
      }
      retrievalQuestion.onchange = drawRetrieval;
      drawRetrieval();
      const citations = el("details", null, "ac-citation-summary");
      citations.append(el("summary", "Citation coverage and source breadth"));
      const ct = el("table");
      const ch = el("tr");
      ["System / mode", "Cited answers", "Avg. sources cited", "Avg. videos cited"].forEach((x) =>
        ch.append(el("th", x)),
      );
      ct.append(ch);
      for (const [model, name] of Object.entries(models))
        for (const mode of ["rag", "graph_only", "graph"]) {
          const group = rows.filter(
            (r) => r.model === model && r.mode === mode && r.status === "complete",
          );
          const tr = el("tr");
          [
            `${name} · ${modes[mode]}`,
            `${group.filter((r) => r.cited > 0).length} / ${group.length}`,
            fmt(mean(group.map((r) => r.cited))),
            fmt(mean(group.map((r) => r.videos))),
          ].forEach((x) => tr.append(el("td", x)));
          ct.append(tr);
        }
      const wrap = el("div", null, "ac-table-scroll");
      wrap.append(ct);
      citations.append(
        wrap,
        el(
          "p",
          "Completed retrieval answers only. A valid citation ID does not establish that the source supports the claim. Model-only answers have no supplied sources.",
        ),
      );
      evidence.append(citations);
      const cost = section(
        "OpenAI cost",
        "Recorded token-based estimates for this question selection. Local electricity and hardware costs are not measured.",
      );
      const api = terminal.filter((r) => r.model === "openai"),
        recorded = api.filter((r) => Number.isFinite(r.cost));
      const total = recorded.reduce((sum, r) => sum + r.cost, 0);
      const cards = el("div", null, "ac-cost-summary");
      for (const [label, value] of [
        ["Total recorded", "$" + total.toFixed(4)],
        ["Mean per attempt", recorded.length ? "$" + (total / recorded.length).toFixed(5) : "—"],
        ["Attempts with costs", `${recorded.length} / ${api.length}`],
      ]) {
        const card = el("div");
        card.append(el("small", label), el("strong", value));
        cards.append(card);
      }
      cost.append(cards);
      visuals.append(
        el(
          "p",
          "While evaluation is running, systems cover different subsets of questions. Use the question selector below for a direct comparison.",
          "ac-description",
        ),
      );
    }
    category.onchange = draw;
    const compare = el("section", null, "panel comparison-section");
    compare.append(
      el("h2", "Read the answers side by side"),
      el(
        "p",
        "Compare correctness, completeness, clarity, and whether the cited passages support the explanation. More words or citations do not automatically mean better.",
      ),
    );
    const q = select(
      "Question",
      data.questions.map((x) => [x.id, `${x.id} · ${x.category} · ${x.question}`]),
      compare,
    );
    if (questionId) q.value = questionId;
    questionId = q.value;
    const grid = el("div", null, "ac-answers");
    compare.append(grid);
    root.append(compare);
    const panels = [];
    for (let i = 0; i < 2; i++) {
      const panel = el("section", null, "ac-answer-card"),
        opts = el("div", null, "ac-controls");
      const model = select("Model", Object.entries(models), opts),
        mode = select("Mode", Object.entries(modes), opts);
      [model.value, mode.value] = chosen[i];
      const body = el("div");
      panel.append(opts, body);
      grid.append(panel);
      panels.push({ model, mode, body });
      model.onchange = mode.onchange = () => {
        chosen[i] = [model.value, mode.value];
        show();
      };
    }
    async function show() {
      const current = ++version;
      questionId = q.value;
      await Promise.all(
        panels.map(async ({ model, mode, body }) => {
          const row = data.rows.find(
            (r) => r.question_id === q.value && r.model === model.value && r.mode === mode.value,
          );
          body.replaceChildren(el("p", row?.status || "Not available"));
          if (!row?.job_id || !["complete", "error"].includes(row.status)) return;
          try {
            const response = await fetch("/api/answers/" + row.job_id);
            if (!response.ok) throw Error("Saved answer unavailable");
            const answer = await response.json();
            if (version !== current) return;
            body.replaceChildren(
              el("p", `${row.status} · ${fmt(row.seconds)}s · ${row.words} words`, "ask-meta"),
            );
            if (answer.error) body.append(el("p", answer.error, "ac-error"));
            const article = el("article", null, "ask-answer");
            window.renderAnswerMarkdown(
              article,
              answer.answer || answer.partial_answer || "No answer saved.",
            );
            body.append(article);
            const a = el("a", "Open saved answer");
            a.href = "/?answer=" + row.job_id + "#ask";
            a.target = "_blank";
            a.rel = "noopener";
            body.append(a);
            if (answer.sources?.length) {
              const sources = el("details");
              sources.append(el("summary", "Source passages (" + answer.sources.length + ")"));
              answer.sources.forEach((s, j) => {
                const d = el("details");
                d.append(
                  el("summary", `[S${j + 1}] ${s.title} · ${s.retrieval || "direct"}`),
                  el("p", s.text),
                );
                sources.append(d);
              });
              body.append(sources);
            }
          } catch (e) {
            if (version === current) body.append(el("p", e.message));
          }
        }),
      );
    }
    q.onchange = show;
    draw();
    show();
  }
  window.renderAnswerComparison = load;
  if (location.hash === "#answer-comparison") load();
})();
