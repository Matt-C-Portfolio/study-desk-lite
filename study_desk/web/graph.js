/* Graph browser: saved model decisions, original claims, and source passages. */
(() => {
  const root = document.querySelector("#graph-view");
  let model = "14B",
    data = null,
    selected = null,
    area = "",
    query = "",
    timer = null,
    loading = false;
  const names = {
    "1.5B": "DeepSeek 1.5B",
    "7B": "DeepSeek 7B",
    "14B": "DeepSeek 14B",
    openai: "OpenAI · Luna + Terra",
  };
  model = Object.hasOwn(names, localStorage.getItem("graph-model"))
    ? localStorage.getItem("graph-model")
    : "14B";
  const make = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const button = (label, fn) => {
    const n = make("button", "secondary", label);
    n.type = "button";
    n.onclick = fn;
    return n;
  };
  function section(title) {
    const n = make("section", "panel graph-panel");
    n.append(make("h2", "", title));
    return n;
  }
  const controls = section("Concept graphs");
  controls.append(
    make(
      "p",
      "",
      "Extracted topics → shared concepts → subject areas. Original claims and evidence stay attached. Each graph uses the first successful run per video for that system.",
    ),
  );
  const bar = make("div", "graph-controls"),
    select = make("select");
  select.setAttribute("aria-label", "Graph model");
  for (const [key, label] of Object.entries(names)) {
    const o = make("option", "", label);
    o.value = key;
    select.append(o);
  }
  select.value = model;
  select.onchange = () => {
    model = select.value;
    localStorage.setItem("graph-model", model);
    selected = null;
    area = "";
    query = "";
    search.value = "";
    load();
  };
  const build = button("Build graph", () =>
    start(model, Boolean(data?.build && data.build.status !== "held")),
  );
  const all = button("Build all local graphs", () => start("all", false));
  const reload = button("Refresh", () => load());
  bar.append(select, build, all, reload);
  controls.append(bar);
  controls.append(
    make(
      "p",
      "hint",
      "Local models run on this computer. OpenAI builds use the configured API and record estimated cost. Existing guide runs are preserved.",
    ),
  );
  const status = make("div", "graph-status");
  status.setAttribute("aria-live", "polite");
  controls.append(status);
  const progress = make("progress");
  progress.max = 100;
  progress.setAttribute("aria-label", "Graph stage progress");
  controls.append(progress);
  const metrics = make("p", "graph-metrics");
  controls.append(metrics);
  const workspace = section("Explore connections"),
    filters = make("div", "graph-controls");
  const search = make("input");
  search.placeholder = "Find a concept…";
  search.setAttribute("aria-label", "Find a concept");
  search.oninput = () => {
    query = search.value;
    draw();
  };
  const areas = make("select");
  areas.setAttribute("aria-label", "Subject area");
  areas.onchange = () => {
    area = areas.value;
    selected = null;
    draw();
  };
  filters.append(
    search,
    areas,
    button("Show overview", () => {
      selected = null;
      draw();
    }),
  );
  workspace.append(filters);
  workspace.append(
    make(
      "p",
      "hint",
      "Blue = concept · green = subject area · solid line = model relationship · dashed line = membership. Select a node or a concept below to inspect its sources.",
    ),
  );
  const layout = make("div", "graph-layout"),
    canvas = make("div", "graph-canvas"),
    details = make("aside", "graph-details");
  layout.append(canvas, details);
  workspace.append(layout);
  const list = make("div", "graph-concept-list");
  workspace.append(list);
  const audit = section("Sources and model decisions");
  root.append(controls, workspace, audit);
  async function start(which, rebuild) {
    build.disabled = all.disabled = true;
    try {
      const r = await fetch(`/api/graph/${which}/build`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rebuild }),
      });
      const result = await r.json();
      if (!r.ok) throw Error(result.error);
      await load();
    } catch (e) {
      status.textContent = e.message;
      build.disabled = all.disabled = false;
    }
  }
  async function load() {
    if (loading) {
      return;
    }
    loading = true;
    clearTimeout(timer);
    const requested = model;
    try {
      const [r, work] = await Promise.all([
        fetch(`/api/graph/${requested}`),
        fetch("/api/workspace-status"),
      ]);
      if (!r.ok || !work.ok) throw Error("Could not load graph records.");
      const next = await r.json(),
        busy = (await work.json()).busy;
      if (requested !== model) {
        loading = false;
        return load();
      }
      data = next;
      const b = data.build;
      build.textContent =
        b?.status === "held" ? "Build graph" : b ? "Build a new version" : "Build graph";
      all.disabled = build.disabled = busy;
      status.textContent = b
        ? `${names[model]} · ${b.status} · ${b.detail} ${b.total > 0 && ["running", "queued"].includes(b.status) ? `(${b.done}/${b.total})` : ""}${b.activity ? ` · ${b.activity} token events this call` : ""}`
        : "No graph built for this system yet.";
      if (b?.status === "held")
        status.textContent =
          "Ready when you choose Build graph. OpenAI is excluded from bulk builds.";
      progress.hidden = !b || !["running", "queued"].includes(b.status);
      progress.value = b?.total ? (b.done / b.total) * 100 : 0;
      metrics.textContent = b
        ? `${data.inputs.length} videos · ${data.claims.length} original claims · ${data.concepts.filter((c) => !c.merged_into_id).length} concepts · ${data.edges.length} relationships · ${b.issues?.length || 0} issues · ${b.calls || 0} model calls · ${Math.round(b.elapsed || 0)}s · ${b.settings?.seed != null ? "seed " + b.settings.seed : "unseeded"}${b.estimated_cost_usd != null ? ` · estimated $${b.estimated_cost_usd.toFixed(3)}` : ""}`
        : "";
      areas.replaceChildren();
      const o = make("option", "", "All subject areas");
      o.value = "";
      areas.append(o);
      for (const a of data.areas) {
        const n = make("option", "", a.label);
        n.value = String(a.id);
        areas.append(n);
      }
      areas.value = area;
      const openSections = new Set(
        [...root.querySelectorAll("details[open]")].map(
          (n) => n.querySelector("summary")?.textContent,
        ),
      );
      const scroll = details.scrollTop;
      draw();
      renderAudit();
      for (const n of root.querySelectorAll("details")) {
        if (openSections.has(n.querySelector("summary")?.textContent)) n.open = true;
      }
      details.scrollTop = scroll;
      if (busy && !root.hidden) timer = setTimeout(load, 2000);
    } catch (e) {
      status.textContent = "Connection interrupted. Retrying… Your build continues on the server.";
      if (!root.hidden) timer = setTimeout(load, 3000);
    } finally {
      loading = false;
    }
  }
  function svgEl(tag, attrs, text) {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function draw() {
    canvas.replaceChildren();
    list.replaceChildren();
    details.replaceChildren();
    if (!data) return;
    const active = data.concepts.filter((c) => !c.merged_into_id),
      byId = new Map(active.map((c) => [c.id, c]));
    let visible = active.filter(
      (c) =>
        (!area || c.area_ids.includes(Number(area))) &&
        (!query ||
          [c.label, c.description, ...c.aliases]
            .join(" ")
            .toLowerCase()
            .includes(query.toLowerCase())),
    );
    const focus = byId.get(selected);
    if (focus) {
      const ids = new Set([focus.id]);
      for (const e of data.edges) {
        if (e.source_id === focus.id) ids.add(e.target_id);
        if (e.target_id === focus.id) ids.add(e.source_id);
      }
      visible = active.filter((c) => ids.has(c.id));
    }
    if (!visible.length) {
      canvas.append(
        make(
          "p",
          "graph-empty",
          data.build?.status === "running"
            ? "Concepts will appear as extracted topics are prepared."
            : "No matching concepts yet.",
        ),
      );
    } else {
      const svg = svgEl("svg", {
        viewBox: "0 0 900 650",
        role: "img",
        "aria-label": "Concepts, subject areas, and model relationships",
      });
      const defs = svgEl("defs", {}),
        marker = svgEl("marker", {
          id: "concept-arrow",
          viewBox: "0 0 10 10",
          refX: 15,
          refY: 5,
          markerWidth: 5,
          markerHeight: 5,
          orient: "auto",
        });
      marker.append(svgEl("path", { d: "M0 0L10 5L0 10Z", fill: "#8da5b6" }));
      defs.append(marker);
      svg.append(defs);
      const pos = new Map(),
        groups = new Map();
      for (const c of visible) {
        const aid = c.area_ids[0] || 0;
        if (!groups.has(aid)) groups.set(aid, []);
        groups.get(aid).push(c);
      }
      let gi = 0;
      const columns = Math.ceil(Math.sqrt(groups.size)),
        rows = Math.ceil(groups.size / columns);
      const centers = new Map();
      for (const [aid, cs] of groups) {
        const cx = (((gi % columns) + 0.5) * 900) / columns,
          cy = ((Math.floor(gi / columns) + 0.5) * 650) / rows;
        gi++;
        centers.set(aid, { x: cx, y: cy });
        const radius = Math.min(900 / columns, 650 / rows) * 0.34;
        cs.forEach((c, i) => {
          const angle = (2 * Math.PI * i) / cs.length - Math.PI / 2;
          pos.set(c.id, { x: cx + radius * Math.cos(angle), y: cy + radius * Math.sin(angle) });
        });
      }
      for (const c of visible) {
        const p = pos.get(c.id);
        for (const aid of c.area_ids.length ? c.area_ids : [0]) {
          const center = centers.get(aid);
          if (center)
            svg.append(
              svgEl("line", {
                x1: center.x,
                y1: center.y,
                x2: p.x,
                y2: p.y,
                stroke: "#c0d5c7",
                "stroke-dasharray": "3 4",
              }),
            );
        }
      }
      for (const edge of data.edges) {
        const a = pos.get(edge.source_id),
          b = pos.get(edge.target_id);
        if (a && b) {
          const line = svgEl("line", {
            x1: a.x,
            y1: a.y,
            x2: b.x,
            y2: b.y,
            stroke: "#8da5b6",
            "stroke-width": 1.5,
            "marker-end": "url(#concept-arrow)",
          });
          line.append(
            svgEl(
              "title",
              {},
              `${byId.get(edge.source_id)?.label} → ${edge.predicate} → ${byId.get(edge.target_id)?.label}`,
            ),
          );
          svg.append(line);
        }
      }
      for (const [aid, p] of centers) {
        const a = data.areas.find((a) => a.id === aid),
          g = svgEl("g", {
            class: "graph-svg-node",
            tabindex: 0,
            role: "button",
            "aria-label": a?.label || "Unassigned subject area",
          });
        g.append(svgEl("circle", { cx: p.x, cy: p.y, r: 18, fill: "#d9e8d9", stroke: "#61906d" }));
        g.append(
          svgEl(
            "text",
            { x: p.x, y: p.y + 34, "text-anchor": "middle", class: "graph-svg-label" },
            a?.label || "No subject area",
          ),
        );
        g.onclick = () => {
          area = aid ? String(aid) : "";
          areas.value = area;
          selected = null;
          draw();
        };
        g.onkeydown = (e) => {
          if (e.key === "Enter") g.onclick();
        };
        svg.append(g);
      }
      for (const c of visible) {
        const p = pos.get(c.id),
          g = svgEl("g", {
            class: "graph-svg-node",
            tabindex: 0,
            role: "button",
            "aria-label": c.label,
          });
        g.append(
          svgEl("circle", {
            cx: p.x,
            cy: p.y,
            r: c.id === selected ? 13 : 8,
            fill: c.id === selected ? "#132f51" : "#4b9fd0",
            stroke: "#fff",
            "stroke-width": 2,
          }),
        );
        g.append(svgEl("title", {}, c.label));
        if (visible.length <= 22)
          g.append(
            svgEl(
              "text",
              { x: p.x, y: p.y - 15, "text-anchor": "middle", class: "graph-svg-label" },
              c.label.length > 32 ? c.label.slice(0, 30) + "…" : c.label,
            ),
          );
        g.onclick = () => {
          selected = c.id;
          draw();
        };
        g.onkeydown = (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            g.onclick();
          }
        };
        svg.append(g);
      }
      canvas.append(svg);
    }
    for (const c of visible.sort((a, b) => a.label.localeCompare(b.label))) {
      const b = button(c.label, () => {
        selected = c.id;
        draw();
      });
      if (c.id === selected) b.classList.add("selected");
      list.append(b);
    }
    if (focus) showConcept(focus);
    else
      details.append(
        make("h3", "", "Select a concept"),
        make(
          "p",
          "hint",
          "Inspect original claims, examples, video timestamps, and relationships here. The graph records model interpretations; source links are not verification.",
        ),
      );
  }
  function showConcept(c) {
    details.append(make("h3", "", c.label), make("p", "", c.description));
    if (c.aliases.length) details.append(make("p", "hint", "Aliases: " + c.aliases.join(", ")));
    const assigned = data.areas.filter((a) => c.area_ids.includes(a.id));
    details.append(
      make(
        "p",
        "hint",
        "Subject areas: " + (assigned.map((a) => a.label).join(", ") || "Unassigned"),
      ),
    );
    const edges = data.edges.filter((e) => e.source_id === c.id || e.target_id === c.id);
    if (edges.length) {
      details.append(make("h4", "", "Relationships"));
      for (const e of edges) {
        const other = data.concepts.find(
          (x) => x.id === (e.source_id === c.id ? e.target_id : e.source_id),
        );
        const d = make("details");
        d.append(
          make(
            "summary",
            "",
            `${e.source_id === c.id ? "→" : "←"} ${e.predicate}: ${other?.label || "Unknown"}`,
          ),
          make("p", "", e.rationale),
          make("p", "hint", `${e.claim_ids.length} linked claims; model-proposed relationship.`),
        );
        details.append(d);
      }
    }
    details.append(make("h4", "", `${c.claim_ids.length} original claims`));
    for (const claim of data.claims.filter((x) => c.claim_ids.includes(x.id)))
      appendClaim(details, claim);
  }
  function appendClaim(parent, claim) {
    const card = make("details", "graph-claim"),
      input = data.inputs.find((i) => i.video_id === claim.video_id);
    card.append(
      make(
        "summary",
        "",
        claim.claim_text.length > 180 ? claim.claim_text.slice(0, 177) + "…" : claim.claim_text,
      ),
      make(
        "p",
        "hint",
        `${input?.title || ""} · run ${input?.run_number} · ${claim.extraction_id}`,
      ),
    );
    if (claim.claim_text.length > 180) card.append(make("p", "", claim.claim_text));
    const topic = claim.original.topic;
    card.append(make("p", "hint", "Video topic: " + topic.title));
    if (topic.examples?.length) {
      card.append(make("h4", "", "Original topic examples"));
      for (const text of topic.examples) card.append(make("pre", "graph-example", text));
    }
    const spans = data.spans
      .filter((s) => claim.span_ids.includes(s.id))
      .sort((a, b) => (a.start_char || 0) - (b.start_char || 0));
    if (spans.length) {
      const first = spans[0];
      const a = make(
        "a",
        "",
        `Source ${first.source_id}${first.start_s != null ? " · " + duration(first.start_s) + "–" + duration(first.end_s) : ""}`,
      );
      a.href =
        (input?.url || "") + (first.start_s != null ? "&t=" + Math.floor(first.start_s) : "");
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      card.append(a, make("p", "hint", "Timestamp covers the original extraction chunk."));
      const source = make("details");
      source.append(make("summary", "", "Read original transcript passage"));
      for (const span of spans) source.append(make("p", "graph-source", span.text_content));
      card.append(source);
    }
    parent.append(card);
  }
  function renderAudit() {
    audit.replaceChildren(make("h2", "", "Sources and model decisions"));
    if (!data?.build) return;
    const sources = make("details");
    sources.append(make("summary", "", `${data.inputs.length} selected video runs`));
    for (const i of data.inputs) {
      const p = make("p", "", `${i.title} · ${names[i.model]} · run ${i.run_number}`);
      const a = make("a", "", " View guide");
      a.href = `/api/urls/${i.video_id}/notes/${i.model}/${i.run_number}`;
      a.target = "_blank";
      p.append(a);
      sources.append(p);
      if (i.attribution)
        sources.append(
          make(
            "p",
            "hint",
            `${i.attribution.license_name || "MIT OpenCourseWare"} · ${i.attribution.creators || ""}`,
          ),
        );
    }
    audit.append(sources);
    const unassigned = data.claims.filter((c) => !c.concept_ids.length),
      u = make("details");
    u.append(make("summary", "", `${unassigned.length} unassigned claims (retained)`));
    for (const c of unassigned) appendClaim(u, c);
    audit.append(u);
    const decisions = make("details");
    decisions.append(make("summary", "", `${data.resolutions.length} consolidation decisions`));
    for (const r of data.resolutions) {
      const a = data.concepts.find((c) => c.id === r.candidate_id),
        b = data.concepts.find((c) => c.id === r.matched_id);
      decisions.append(make("p", "", `${r.decision}: ${a?.label} / ${b?.label} — ${r.rationale}`));
    }
    audit.append(decisions);
    const issues = make("details");
    issues.append(make("summary", "", `${data.build.issues?.length || 0} model/output issues`));
    for (const i of data.build.issues || [])
      issues.append(make("p", "", `${i.stage}: ${i.detail}`));
    audit.append(issues);
    for (const name of data.build.missing_lectures || [])
      audit.append(make("p", "error", "No successful input: " + name));
    if (data.build.timings)
      audit.append(
        make(
          "p",
          "hint",
          Object.entries(data.build.timings)
            .map(([k, v]) => `${k}: ${v.toFixed(1)}s`)
            .join(" · "),
        ),
      );
    if (data.builds?.length > 1)
      audit.append(make("p", "hint", "Earlier graph builds remain saved."));
  }
  window.renderLectureGraph = load;
  if (location.hash === "#graph") load();
})();

/* Read-only comparison of the latest saved graph for each system. */
(() => {
  const root = document.querySelector("#graph-comparison-view");
  const names = {
    "1.5B": "DeepSeek 1.5B",
    "7B": "DeepSeek 7B",
    "14B": "DeepSeek 14B",
    openai: "OpenAI",
  };
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text != null) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };
  const panel = (title) => {
    const n = el("section", null, "panel comparison-section");
    n.append(el("h2", title));
    root.append(n);
    return n;
  };
  let loading = false;
  window.renderGraphComparison = async () => {
    if (loading) return;
    loading = true;
    root.replaceChildren(el("p", "Loading saved graphs…"));
    const results = await Promise.allSettled(
      Object.keys(names).map(async (model) => {
        const r = await fetch("/api/graph/" + model);
        if (!r.ok) throw Error("Unable to load " + names[model]);
        return { model, ...(await r.json()) };
      }),
    );
    root.replaceChildren();
    const intro = panel("Compare the concept graphs");
    intro.append(
      el(
        "p",
        "Latest saved build per system. Each starts with its own first successful guide run per video.",
      ),
    );
    const refresh = el("button", "Refresh results", "secondary");
    refresh.onclick = window.renderGraphComparison;
    intro.append(refresh);
    const rows = [];
    results.forEach((r, i) => {
      if (r.status === "rejected") {
        intro.append(el("p", names[Object.keys(names)[i]] + ": unavailable"));
        return;
      }
      const d = r.value;
      if (!d.build) {
        intro.append(el("p", names[d.model] + ": no saved build"));
        return;
      }
      const active = d.concepts.filter((c) => !c.merged_into_id),
        ids = new Set(active.map((c) => c.id));
      const edges = d.edges.filter((e) => ids.has(e.source_id) && ids.has(e.target_id));
      const claims = new Map(d.claims.map((c) => [c.id, c]));
      const lectures = new Map(
        active.map((c) => [
          c.id,
          new Set(c.claim_ids.map((id) => claims.get(id)?.video_id).filter((v) => v != null)),
        ]),
      );
      const cross = edges.filter((e) => {
        const a = lectures.get(e.source_id),
          b = lectures.get(e.target_id);
        return a.size && b.size && ![...a].some((id) => b.has(id));
      }).length;
      const linked = new Set(edges.flatMap((e) => [e.source_id, e.target_id]));
      rows.push({
        ...d,
        active,
        edges,
        cross,
        isolated: active.filter((c) => !linked.has(c.id)).length,
      });
    });
    const lectureMap = new Map();
    rows.forEach((r) => r.inputs.forEach((i) => lectureMap.set(i.video_id, i.title)));
    const lectureIds = [...lectureMap.keys()].sort((a, b) => a - b);
    const palette = [
      "#277da1",
      "#d97706",
      "#7b52ab",
      "#36825a",
      "#be4773",
      "#737b24",
      "#a15b32",
      "#4269bc",
      "#008880",
      "#9c478d",
    ];
    const color = (id) => palette[lectureIds.indexOf(id) % palette.length] || "#777";
    const code = (id) => "V" + (lectureIds.indexOf(id) + 1);
    const svg = (tag, attrs, text) => {
      const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
      Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
      if (text != null) n.textContent = text;
      return n;
    };
    rows.forEach((r) => {
      const claims = new Map(r.claims.map((c) => [c.id, c]));
      r.lectureSets = new Map();
      r.primary = new Map();
      r.active.forEach((c) => {
        const counts = new Map();
        c.claim_ids.forEach((id) => {
          const v = claims.get(id)?.video_id;
          if (v != null) counts.set(v, (counts.get(v) || 0) + 1);
        });
        r.lectureSets.set(c.id, new Set(counts.keys()));
        r.primary.set(c.id, [...counts].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0]?.[0]);
      });
      r.cells = new Map();
      r.edges.forEach((e) => {
        for (const a of r.lectureSets.get(e.source_id))
          for (const b of r.lectureSets.get(e.target_id)) {
            const key = a + ":" + b;
            if (!r.cells.has(key)) r.cells.set(key, []);
            r.cells.get(key).push(e);
          }
      });
    });
    const previews = panel("How each system organizes the videos");
    previews.append(
      el(
        "p",
        "Same video positions, node size, and layout rules across all four graphs. Each dot is a concept; lines are model-proposed relationships.",
      ),
    );
    const grid = el("div", null, "gc-preview-grid");
    previews.append(grid);
    for (const model of Object.keys(names)) {
      const card = el("article", null, "gc-preview"),
        r = rows.find((r) => r.model === model);
      card.append(el("h3", names[model]));
      grid.append(card);
      if (!r) {
        card.append(el("p", "No graph available"));
        continue;
      }
      const picture = svg("svg", {
          viewBox: "0 0 340 340",
          role: "img",
          "aria-label": names[model] + " concept graph",
        }),
        pos = new Map();
      lectureIds.forEach((id, i) => {
        const angle = (2 * Math.PI * i) / lectureIds.length - Math.PI / 2,
          cx = 170 + 118 * Math.cos(angle),
          cy = 170 + 118 * Math.sin(angle);
        picture.append(
          svg(
            "text",
            {
              x: 170 + 151 * Math.cos(angle),
              y: 174 + 151 * Math.sin(angle),
              "text-anchor": "middle",
              fill: color(id),
              class: "gc-preview-label",
            },
            code(id),
          ),
        );
        const nodes = r.active
          .filter((c) => r.primary.get(c.id) === id)
          .sort((a, b) => a.label.localeCompare(b.label) || a.id - b.id);
        nodes.forEach((c, j) => {
          const rad = nodes.length === 1 ? 0 : 32 * Math.sqrt((j + 0.5) / nodes.length),
            a = j * 2.399963;
          pos.set(c.id, { x: cx + rad * Math.cos(a), y: cy + rad * Math.sin(a) });
        });
      });
      const unknown = r.active.filter((c) => !pos.has(c.id));
      unknown.forEach((c, j) =>
        pos.set(c.id, {
          x: 170 + 20 * Math.cos((j * 6.28) / unknown.length),
          y: 170 + 20 * Math.sin((j * 6.28) / unknown.length),
        }),
      );
      r.edges.forEach((e) => {
        const a = pos.get(e.source_id),
          b = pos.get(e.target_id);
        picture.append(
          svg("line", {
            x1: a.x,
            y1: a.y,
            x2: b.x,
            y2: b.y,
            stroke: "#647789",
            "stroke-opacity": 0.23,
            "stroke-width": 0.65,
          }),
        );
      });
      r.active.forEach((c) => {
        const p = pos.get(c.id),
          dot = svg("circle", {
            cx: p.x,
            cy: p.y,
            r: 2.8,
            fill: color(r.primary.get(c.id)),
            stroke: r.lectureSets.get(c.id).size > 1 ? "#13294b" : "#fff",
            "stroke-width": 0.7,
          });
        dot.append(
          svg("title", {}, c.label + " · " + [...r.lectureSets.get(c.id)].map(code).join(", ")),
        );
        picture.append(dot);
      });
      const expand = el("button", null, "gc-expand");
      expand.type = "button";
      expand.setAttribute("aria-label", "Enlarge " + names[model] + " graph");
      expand.title = "Click to enlarge";
      expand.append(picture);
      card.append(expand);
      expand.onclick = () => {
        const dialog = el("dialog", null, "gc-preview-dialog"),
          bar = el("div", null, "dialog-bar"),
          heading = el("strong", names[model] + " · Concept graph"),
          close = el("button", "Close", "secondary");
        heading.id = "gc-enlarged-title";
        dialog.setAttribute("aria-labelledby", heading.id);
        close.type = "button";
        close.onclick = () => dialog.close();
        bar.append(heading, close);
        const body = el("div", null, "gc-enlarged-body"),
          large = picture.cloneNode(true);
        body.append(
          large,
          el(
            "p",
            r.active.length +
              " concepts · " +
              r.edges.length +
              " relationships. Hover over a concept to read its label.",
            "hint",
          ),
        );
        const key = el("div", null, "gc-enlarged-key");
        lectureIds.forEach((id) => {
          const item = el("p", code(id) + " · " + lectureMap.get(id));
          item.style.borderLeft = "4px solid " + color(id);
          key.append(item);
        });
        body.append(key);
        dialog.append(bar, body);
        document.body.append(dialog);
        dialog.addEventListener(
          "close",
          () => {
            dialog.remove();
            expand.focus();
          },
          { once: true },
        );
        dialog.addEventListener("click", (event) => {
          if (event.target === dialog) {
            const bounds = dialog.getBoundingClientRect();
            if (
              event.clientX < bounds.left ||
              event.clientX > bounds.right ||
              event.clientY < bounds.top ||
              event.clientY > bounds.bottom
            )
              dialog.close();
          }
        });
        dialog.showModal();
      };
      card.append(
        el("p", r.active.length + " concepts · " + r.edges.length + " relationships", "hint"),
      );
    }
    previews.append(
      el(
        "p",
        "Color follows the video contributing the most claims to a concept; a dark outline marks concepts shared across videos. Layout is schematic, not a semantic-distance map.",
        "hint",
      ),
    );
    const legend = el("details", null, "gc-legend");
    legend.append(el("summary", "Video color key"));
    lectureIds.forEach((id) => {
      const p = el("p", code(id) + " · " + lectureMap.get(id));
      p.style.borderLeft = "4px solid " + color(id);
      legend.append(p);
    });
    legend.open = true;
    previews.append(legend);
    const heat = panel("Connections between videos");
    heat.append(
      el(
        "p",
        "Rows are the source video; columns are the destination. Select a cell to inspect the actual directed relationships.",
      ),
    );
    const picker = el("select");
    picker.setAttribute("aria-label", "Heatmap system");
    rows.forEach((r) => {
      const o = el("option", names[r.model]);
      o.value = r.model;
      picker.append(o);
    });
    heat.append(picker);
    const scaleMax = Math.max(
      1,
      ...rows.flatMap((r) => [...r.cells.values()].map((v) => v.length)),
    );
    heat.append(
      el(
        "p",
        "Shared color scale: 0–" +
          scaleMax +
          " relationships. A relationship involving a concept from multiple videos appears in each applicable cell; cells cannot be summed for a unique total. Diagonal cells show within-video links.",
        "hint",
      ),
    );
    const mapWrap = el("div", null, "gc-heat-scroll"),
      inspector = el("div", null, "gc-cell-detail");
    inspector.setAttribute("aria-live", "polite");
    heat.append(mapWrap, inspector);
    function drawHeat() {
      mapWrap.replaceChildren();
      inspector.replaceChildren(el("p", "Choose a cell to see its connections."));
      const r = rows.find((r) => r.model === picker.value);
      if (!r) return;
      const byId = new Map(r.active.map((c) => [c.id, c]));
      const table = el("table", null, "gc-heatmap"),
        thead = el("thead"),
        header = el("tr");
      header.append(el("th", "From ↓ / To →"));
      lectureIds.forEach((id) => {
        const h = el("th", code(id));
        h.scope = "col";
        h.title = lectureMap.get(id);
        header.append(h);
      });
      thead.append(header);
      table.append(thead);
      const tbody = el("tbody");
      lectureIds.forEach((a) => {
        const tr = el("tr"),
          label = el("th", code(a));
        label.scope = "row";
        label.title = lectureMap.get(a);
        tr.append(label);
        lectureIds.forEach((b) => {
          const matches = r.cells.get(a + ":" + b) || [],
            td = el("td"),
            button = el("button", String(matches.length));
          button.type = "button";
          button.title = lectureMap.get(a) + " → " + lectureMap.get(b);
          button.setAttribute(
            "aria-label",
            button.title + ": " + matches.length + " relationships",
          );
          button.setAttribute("aria-pressed", "false");
          const ratio = matches.length / scaleMax;
          button.style.background = matches.length
            ? "hsl(205 55% " + (94 - 62 * ratio) + "%)"
            : "#f1f3f2";
          button.style.color = ratio > 0.6 ? "white" : "#13294b";
          button.onclick = () => {
            mapWrap
              .querySelectorAll("button")
              .forEach((n) => n.setAttribute("aria-pressed", "false"));
            button.setAttribute("aria-pressed", "true");
            inspector.replaceChildren(
              el("h3", code(a) + " → " + code(b) + " · " + matches.length + " relationships"),
              el("p", lectureMap.get(a) + " → " + lectureMap.get(b), "hint"),
            );
            if (!matches.length)
              inspector.append(el("p", "No recorded relationships for this video pair."));
            const list = el("div", null, "gc-edges");
            matches.forEach((e) => {
              const d = el("details");
              d.append(
                el(
                  "summary",
                  byId.get(e.source_id).label +
                    " → " +
                    e.predicate +
                    " → " +
                    byId.get(e.target_id).label,
                ),
                el("p", e.rationale),
                el("p", e.claim_ids.length + " linked claims · model-proposed connection", "hint"),
              );
              list.append(d);
            });
            inspector.append(list);
          };
          td.append(button);
          tr.append(td);
        });
        tbody.append(tr);
      });
      table.append(tbody);
      mapWrap.append(table);
    }
    picker.onchange = drawHeat;
    drawHeat();
    const stats = panel("Graph counts"),
      countWrap = el("div", null, "comparison-table-wrap"),
      countTable = el("table", null, "comparison-table"),
      countHead = el("thead"),
      countRow = el("tr");
    [
      "System",
      "Input claims",
      "Concepts",
      "Relationships",
      "Cross-video links*",
      "Isolated concepts",
    ].forEach((t) => countRow.append(el("th", t)));
    countHead.append(countRow);
    countTable.append(countHead);
    const countBody = el("tbody");
    rows.forEach((r) => {
      const tr = el("tr");
      [
        names[r.model],
        r.claims.length,
        r.active.length,
        r.edges.length,
        r.cross,
        r.isolated,
      ].forEach((v) => tr.append(el("td", String(v))));
      countBody.append(tr);
    });
    countTable.append(countBody);
    countWrap.append(countTable);
    stats.append(
      countWrap,
      el(
        "p",
        "*Unique relationships between concepts with no shared source video. This stricter measure differs from the heatmap’s source-membership counts. More links do not establish better accuracy.",
        "hint",
      ),
    );

    const costs = panel("Build time and cost"),
      wrap = el("div", null, "comparison-table-wrap"),
      table = el("table", null, "comparison-table");
    const head = el("thead"),
      hr = el("tr");
    [
      "System / build",
      "Status",
      "Videos",
      "Time",
      "Model calls",
      "API cost",
      "Recorded issues",
    ].forEach((t) => hr.append(el("th", t)));
    head.append(hr);
    table.append(head);
    const body = el("tbody");
    rows.forEach((r) => {
      const b = r.build,
        tr = el("tr");
      [
        names[r.model] + " · #" + b.id,
        b.status,
        r.inputs.length,
        b.elapsed != null ? (b.elapsed / 60).toFixed(1) + " min" : "—",
        b.calls ?? "—",
        r.model === "openai"
          ? b.estimated_cost_usd != null
            ? "$" + b.estimated_cost_usd.toFixed(3)
            : "Not recorded"
          : "No API charge",
        b.issues?.length ?? 0,
      ].forEach((v) => tr.append(el("td", String(v))));
      body.append(tr);
    });
    table.append(body);
    wrap.append(table);
    costs.append(
      wrap,
      el(
        "p",
        "API cost is estimated from recorded usage. Local hardware and electricity costs are not measured. These are individual builds, not repeated-trial averages.",
        "hint",
      ),
    );
    loading = false;
  };
  if (location.hash === "#graph-comparison") window.renderGraphComparison();
})();
