/* The UI controls a resumable Python execution, never a prerecorded animation.
   Polling reads published snapshots; only explicit commands advance code. */
"use strict";
const $ = (id) => document.getElementById(id);
const svgNS = "http://www.w3.org/2000/svg";
const pretty = (value) => JSON.stringify(value, null, 2);
let catalog,
  session = null,
  busy = false,
  followLive = true,
  selectedSeq = null,
  inspectedNode = null;
let activeTab = "event",
  contextSide = "after",
  editorKey = "",
  pollTimer = null,
  sourceVersion = 0;
let sourcePinned = false,
  lastTimelineKey = "",
  lastSourceKey = "",
  isEditingArgument = false;
const sourceCache = new Map(),
  histories = new Map();

async function api(path, body) {
  // Endpoints and providers are server-controlled. User data is rendered as text.
  const response = await fetch(
    path,
    body === undefined
      ? {}
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function report(error) {
  $("notice").textContent =
    error instanceof Error ? error.message : String(error);
  $("notice").hidden = false;
}

function clearNotice() {
  $("notice").hidden = true;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function svgElement(tag, attributes = {}, text) {
  const node = document.createElementNS(svgNS, tag);
  Object.entries(attributes).forEach(([key, value]) =>
    node.setAttribute(key, value),
  );
  if (text !== undefined) node.textContent = text;
  return node;
}

function diagramEdges() {
  // Base links show shared components; mode links show the selected control path.
  return [...catalog.edges, ...catalog.mode_edges];
}

function drawGraph() {
  // Geometry, edges, IDs, and source responsibility all come from one catalog.
  const svg = $("runtime-graph");
  const defs = svgElement("defs"),
    marker = svgElement("marker", {
      id: "arrow",
      viewBox: "0 0 10 10",
      refX: "9",
      refY: "5",
      markerWidth: "6",
      markerHeight: "6",
      orient: "auto-start-reverse",
    });
  marker.append(
    svgElement("path", { d: "M0 0 L10 5 L0 10 z", fill: "#879eaa" }),
  );
  defs.append(marker);
  svg.append(defs);
  diagramEdges().forEach((edge) => {
    const path = svgElement("path", {
      d: edge.path,
      class: "graph-edge",
      "data-edge": edge.id,
    });
    path.append(svgElement("title", {}, edge.label));
    svg.append(path);
    if (edge.label_position) {
      // Keep a visible short label beside each route while the title retains detail.
      const [x, y] = edge.label_position;
      svg.append(
        svgElement(
          "text",
          { x, y, class: "edge-label", "data-edge-label": edge.id },
          edge.short_label || edge.label,
        ),
      );
    }
  });
  catalog.nodes.forEach((node) => {
    const [x, y, width, height] = node.position;
    // Store node geometry locally so each mode can place and size its own card.
    const group = svgElement("g", {
      class: "graph-node",
      "data-node": node.id,
      transform: `translate(${x} ${y})`,
      tabindex: "0",
      role: "button",
      "aria-label": `Inspect ${node.label}`,
    });
    group.append(svgElement("rect", { x: 0, y: 0, width, height }));
    group.append(
      svgElement(
        "text",
        { x: 13, y: 19, class: "node-tag" },
        node.id === "runtime" ? "CONTROL BOUNDARY" : node.tag,
      ),
    );
    const label =
      node.id === "environment"
        ? "Tool data"
        : node.id === "context"
          ? "Context"
          : node.id === "runtime"
            ? "Runtime"
            : node.label;
    group.append(
      svgElement("text", { x: 13, y: 41, class: "node-label" }, label),
    );
    group.append(
      svgElement(
        "text",
        { x: 13, y: height - 11, class: "node-state" },
        "idle",
      ),
    );
    const inspect = () => {
      inspectedNode = node.id;
      followLive = false;
      selectedSeq = null;
      sourcePinned = false;
      renderGraph();
      renderInspector();
      updateFollowButton();
    };
    group.addEventListener("click", inspect);
    group.addEventListener("keydown", (event) => {
      if (["Enter", " "].includes(event.key)) {
        event.preventDefault();
        inspect();
      }
    });
    svg.append(group);
  });
}

function eventSelection() {
  const events = session?.result.events || [];
  if (inspectedNode)
    return (
      [...events].reverse().find((event) => event.node === inspectedNode) ||
      null
    );
  return followLive
    ? events.at(-1)
    : events.find((event) => event.seq === selectedSeq);
}

function renderGraph() {
  const events = session?.result.events || [];
  const visited = new Set(events.map((event) => event.node));
  const pointer = session?.active_action || session?.next_action;
  const inspecting =
    inspectedNode || (!followLive ? eventSelection()?.node : null);
  // The active session is authoritative; otherwise preview the selected pattern.
  const modeId = session?.config?.mode || $("mode").value || "agent";
  const mode = catalog.mode_views[modeId] || catalog.mode_views.agent;
  const activeNodes = new Set(mode.node_ids);
  const activeEdges = new Set(mode.edge_ids);
  const nodesById = new Map(catalog.nodes.map((node) => [node.id, node]));
  const edgesById = new Map(diagramEdges().map((edge) => [edge.id, edge]));
  $("mode-banner").dataset.mode = modeId;
  $("mode-title").textContent = mode.label;
  $("mode-decision").textContent = mode.decision_owner;
  $("mode-description").textContent = mode.description;
  $("mode-model").textContent = mode.model_behavior;
  $("mode-tools").textContent = mode.tool_behavior;
  document.querySelectorAll(".graph-node").forEach((node) => {
    const id = node.dataset.node;
    const active = pointer?.node === id;
    const inMode = activeNodes.has(id);
    // Relayout every component when the learner selects a different control pattern.
    const [x, y, width, height] =
      mode.positions[id] || nodesById.get(id).position;
    node.setAttribute("transform", `translate(${x} ${y})`);
    node.querySelector("rect").setAttribute("width", width);
    node.querySelector("rect").setAttribute("height", height);
    node.querySelector(".node-state").setAttribute("y", height - 11);
    node.classList.toggle("visited", visited.has(id));
    node.classList.toggle("next", active && session?.debug_status === "paused");
    node.classList.toggle(
      "running",
      active && session?.debug_status === "running",
    );
    node.classList.toggle("inspected", inspecting === id);
    node.classList.toggle("mode-inactive", !inMode);
    node.setAttribute(
      "aria-label",
      `${inMode ? "In this mode" : "Not used in this mode"}: inspect ${node.querySelector(".node-label").textContent}`,
    );
    node.querySelector(".node-state").textContent = active
      ? session.debug_status === "running"
        ? "RUNNING"
        : "NEXT"
      : visited.has(id)
        ? "executed"
        : inMode
          ? "IN THIS MODE"
          : "NOT USED";
  });
  document.querySelectorAll(".graph-edge").forEach((edge) => {
    const id = edge.dataset.edge;
    const inMode = activeEdges.has(id);
    const eventKinds = edgesById.get(id)?.event_kinds || [];
    // Mode geometry keeps arrows attached to the repositioned node cards.
    if (mode.edge_paths[id]) edge.setAttribute("d", mode.edge_paths[id]);
    edge.classList.toggle("mode-hidden", !inMode);
    edge.classList.toggle("mode-path", inMode);
    edge.classList.toggle(
      "executed",
      inMode && events.some((event) => eventKinds.includes(event.kind)),
    );
    const latest = events.at(-1);
    edge.classList.toggle(
      "active",
      inMode &&
        session?.debug_status === "running" &&
        eventKinds.includes(latest?.kind),
    );
  });
  document.querySelectorAll(".edge-label[data-edge-label]").forEach((label) => {
    const id = label.dataset.edgeLabel;
    const [x, y] = mode.label_positions[id] ||
      edgesById.get(id)?.label_position || [0, 0];
    label.setAttribute("x", x);
    label.setAttribute("y", y);
    label.classList.toggle("mode-hidden", !activeEdges.has(id));
  });
}

function updateFollowButton() {
  $("follow-live").textContent = followLive
    ? "Following live"
    : "Return to live →";
  $("follow-live").setAttribute("aria-pressed", String(followLive));
}

function renderTimeline() {
  const events = session?.result.events || [];
  const key = `${session?.session_id}:${events.length}:${followLive}:${selectedSeq}`;
  $("timeline-count").textContent = events.length;
  if (!events.length) {
    if (key === lastTimelineKey) return;
    lastTimelineKey = key;
    $("timeline").replaceChildren(
      element(
        "div",
        "empty",
        "Paused before accepting the goal. Step to begin real execution.",
      ),
    );
    return;
  }
  if (key === lastTimelineKey) return;
  lastTimelineKey = key;
  const timeline = $("timeline"),
    oldScroll = timeline.scrollTop;
  timeline.replaceChildren();
  events.forEach((event) => {
    // Keep list semantics on a wrapper so each event remains a keyboard button.
    const item = element("div", "timeline-item");
    item.setAttribute("role", "listitem");
    const button = element("button", "timeline-row");
    button.type = "button";
    button.dataset.seq = event.seq;
    button.classList.toggle(
      "selected",
      followLive ? event.seq === events.at(-1).seq : event.seq === selectedSeq,
    );
    button.classList.toggle("error", event.kind.endsWith("error"));
    button.classList.toggle("override", event.kind === "debug_override");
    const content = element("span");
    content.append(
      element("strong", "", event.title),
      element("small", "", `${event.kind} · ${event.node}`),
    );
    button.append(
      element("span", "seq", String(event.seq).padStart(2, "0")),
      content,
      element(
        "span",
        "duration",
        event.operation_ms === undefined ? "edit" : `${event.operation_ms} ms`,
      ),
    );
    button.addEventListener("click", () => {
      selectedSeq = event.seq;
      followLive = false;
      inspectedNode = null;
      sourcePinned = false;
      renderTimeline();
      renderGraph();
      renderInspector();
      updateFollowButton();
    });
    item.append(button);
    timeline.append(item);
  });
  timeline.scrollTop = followLive ? timeline.scrollHeight : oldScroll;
}

function renderContext(event) {
  // Before/After snapshots come from the runtime; no inferred context is added.
  const before = event?.state_before?.messages || [];
  const after = event?.state_after?.messages || session?.result.messages || [];
  const messages = contextSide === "before" ? before : after;
  $("context-count").textContent = `${messages.length} messages`;
  $("context-before").classList.toggle("active", contextSide === "before");
  $("context-after").classList.toggle("active", contextSide === "after");
  const added = after.length - before.length;
  const changed = pretty(before) !== pretty(after);
  $("context-diff").textContent = event
    ? `${event.kind}: ${added > 0 ? `+${added} message${added === 1 ? "" : "s"}` : changed ? "Existing message changed" : "No context change"}. Provider/tool results become context only at their recorded boundary.`
    : "Initial state: no context has been assembled.";
  const container = $("context-messages");
  container.replaceChildren();
  if (!messages.length)
    container.append(element("p", "hint", "No messages at this boundary."));
  messages.forEach((message, index) => {
    const card = element("article", "context-message");
    card.classList.toggle(
      "added",
      contextSide === "after" && index >= before.length,
    );
    const role = element("div", "message-role");
    role.append(
      element("span", "", message.role.toUpperCase()),
      element(
        "span",
        "",
        `#${index + 1}${message.tool_name ? ` / ${message.tool_name}` : ""}`,
      ),
    );
    const content = message.tool_calls?.length
      ? pretty(message)
      : message.content;
    card.append(
      role,
      element(
        "pre",
        "",
        typeof content === "string" ? content : pretty(content),
      ),
    );
    container.append(card);
  });
}

async function renderSource(event) {
  let location;
  const node =
    inspectedNode && catalog.nodes.find((entry) => entry.id === inspectedNode);
  if (node) location = { file: node.file, symbol: node.symbol };
  else
    location = followLive
      ? (session?.active_action || session?.next_action)?.source ||
        event?.source
      : event?.source;
  const file = sourcePinned
    ? $("source-file").value
    : location?.file || "runtime.py";
  if (!sourcePinned) $("source-file").value = file;
  const key = `${file}:${location?.line}:${location?.end_line}:${location?.symbol}`;
  if (key === lastSourceKey) return;
  lastSourceKey = key;
  const version = ++sourceVersion;
  try {
    if (!sourceCache.has(file))
      sourceCache.set(
        file,
        (await api(`/api/source?file=${encodeURIComponent(file)}`)).source,
      );
    if (version !== sourceVersion) return;
    const lines = sourceCache.get(file).split("\n");
    let start =
      !sourcePinned && location?.file === file ? location?.line : null;
    let end =
      !sourcePinned && location?.file === file ? location?.end_line : null;
    if (!start && node?.file === file) {
      const name = node.symbol.split(".").at(-1);
      const found = lines.findIndex(
        (line) =>
          line.includes(`def ${name}(`) ||
          line.includes(`class ${name}`) ||
          line.startsWith(`${name} =`),
      );
      if (found >= 0) start = end = found + 1;
    }
    $("source-position").textContent = start
      ? `L${start}${end && end !== start ? `–${end}` : ""}`
      : "file view";
    const source = $("source-code");
    source.replaceChildren();
    lines.forEach((text, index) => {
      const line = element("span", "source-line");
      line.classList.toggle(
        "current",
        index + 1 >= start && index + 1 <= (end || start),
      );
      line.append(
        element("span", "source-number", String(index + 1)),
        document.createTextNode(text || " "),
      );
      source.append(line);
    });
    if (activeTab === "source" && start)
      source
        .querySelector(".current")
        ?.scrollIntoView({ block: "center", behavior: "instant" });
  } catch (error) {
    report(error);
  }
}

function renderInspector() {
  const event = eventSelection();
  const node =
    inspectedNode && catalog.nodes.find((entry) => entry.id === inspectedNode);
  $("inspection-mode").textContent = node
    ? `NODE / ${node.id.toUpperCase()}`
    : followLive
      ? "LIVE STATE"
      : `HISTORY / EVENT ${selectedSeq}`;
  $("inspect-title").textContent = node
    ? node.label
    : event
      ? event.kind
      : "Initial runtime state";
  $("inspect-description").textContent = node
    ? node.description
    : event
      ? event.title
      : "Nothing has executed. Step advances one actual boundary.";
  $("event-meta").textContent = event
    ? `#${event.seq} · ${event.node} · wall +${event.elapsed_ms} ms${event.operation_ms === undefined ? "" : ` · operation ${event.operation_ms} ms`}`
    : "No executed event at this position.";
  $("payload").textContent = pretty(
    event?.payload ||
      (node
        ? {
            component: node.id,
            responsibility: node.description,
            source: node.file,
          }
        : {
            next_action: session?.next_action || null,
            status: session?.debug_status || "waiting",
          }),
  );
  renderContext(event);
  if (activeTab === "source") renderSource(event);
}

function renderPending() {
  const pending =
    session?.next_action?.kind === "execute_tool" &&
    session.debug_status === "paused" &&
    catalog.tools.some(
      (schema) => schema.function.name === session.next_action.tool?.name,
    );
  $("pending-editor").hidden = !pending;
  if (!pending) {
    editorKey = "";
    return;
  }
  const tool = session.next_action.tool;
  // Every current tool has one required input; derive the editor from its schema.
  const schema = catalog.tools.find(
    (entry) => entry.function.name === tool.name,
  ).function;
  const argument = schema.parameters.required[0];
  const definition = schema.parameters.properties[argument];
  const key = `${session.session_id}:${tool.call_id}`;
  $("pending-call").textContent =
    `${tool.name} · ${tool.call_id} · tool has not executed`;
  $("pending-label").textContent = `${argument} to execute`;
  $("pending-value").maxLength = definition.maxLength || 2000;
  $("pending-value").dataset.argument = argument;
  if (key !== editorKey && !isEditingArgument) {
    $("pending-value").value = tool.arguments?.[argument] || "";
    editorKey = key;
  }
}

function render() {
  const running = session?.debug_status === "running";
  const terminal =
    session &&
    ["completed", "cancelled", "error"].includes(session.debug_status);
  const paused = session?.debug_status === "paused";
  $("debug-status").textContent = session
    ? session.stop_requested
      ? "Stopping after operation…"
      : session.pause_requested
        ? "Pausing after operation…"
        : session.breakpoint_hit
          ? "Breakpoint hit"
          : session.debug_status[0].toUpperCase() +
            session.debug_status.slice(1)
    : "No active run";
  $("status-dot").className = `status-dot ${session?.debug_status || ""}`;
  $("session-short").textContent = session
    ? session.session_id.slice(0, 8)
    : "Create a paused run to begin";
  $("setup-toggle").textContent = document.body.classList.contains(
    "setup-collapsed",
  )
    ? "Show setup"
    : "Hide setup";
  $("step").disabled = $("continue").disabled = !paused || busy;
  $("pause").disabled = !running || busy || session?.pause_requested;
  $("stop").disabled = !session || terminal || busy || session?.stop_requested;
  $("create").disabled = running || busy;
  $("run-history").disabled = running || busy;
  $("export").disabled = !session;
  $("apply-breakpoints").disabled = !paused || busy;
  ["break-model", "break-tool", "break-context"].forEach(
    (id) => ($(id).disabled = running || busy),
  );
  $("save-query").disabled = busy;
  const result = session?.result;
  $("model-count").textContent = result?.model_calls || 0;
  $("tool-count").textContent = result?.tool_calls || 0;
  $("message-count").textContent = result?.messages.length || 0;
  $("event-count").textContent = result?.events.length || 0;
  const pointer = session?.active_action || session?.next_action;
  $("next-label").textContent =
    pointer?.label ||
    (terminal
      ? `Run stopped: ${result.status}`
      : "Create a run, then Step or Continue.");
  $("next-source").textContent = pointer?.source
    ? `${pointer.source.file}:${pointer.source.line}`
    : "—";
  $("execution-position").textContent = !session
    ? "No code has executed."
    : running
      ? `EXECUTING / ${pointer?.kind || "waiting for worker"}`
      : terminal
        ? `STOPPED / ${result.status}`
        : `PAUSED BEFORE / ${pointer.kind}`;
  $("output").textContent =
    result?.answer ||
    (result?.status === "running"
      ? "No final answer yet. Execution is not complete."
      : "No final answer yet.");
  // Runtime status stays in progress while paused; expose debugger state here.
  const resultLabel = terminal
    ? "STOPPED · " + result.status
    : paused
      ? "PAUSED · NOT FINAL"
      : running
        ? session.active_action
          ? "EXECUTING"
          : "CONTINUING"
        : "NOT STARTED";
  $("result-status").textContent = resultLabel
    .toUpperCase()
    .replaceAll("_", " ");
  renderGraph();
  renderTimeline();
  renderInspector();
  renderPending();
  updateFollowButton();
}

function applySnapshot(snapshot) {
  // An older poll can never move the debugger backwards after a command reply.
  if (
    session?.session_id === snapshot.session_id &&
    snapshot.revision < session.revision
  )
    return;
  session = snapshot;
  histories.set(snapshot.session_id, {
    id: snapshot.session_id,
    prompt: snapshot.config.prompt,
    status: snapshot.debug_status,
  });
  const history = $("run-history");
  if (
    ![...history.options].some((option) => option.value === session.session_id)
  ) {
    const option = element(
      "option",
      "",
      `${session.session_id.slice(0, 6)} · ${session.config.prompt.slice(0, 30)}`,
    );
    option.value = session.session_id;
    history.append(option);
  }
  history.value = session.session_id;
  render();
  schedulePoll();
}

function schedulePoll() {
  clearTimeout(pollTimer);
  if (session?.debug_status !== "running") return;
  const id = session.session_id;
  pollTimer = setTimeout(async () => {
    try {
      const snapshot = await api(
        `/api/debug/session?id=${encodeURIComponent(id)}`,
      );
      if (session?.session_id === id) applySnapshot(snapshot);
    } catch (error) {
      report(error);
    }
  }, 160);
}

function selectedBreakpoints() {
  return ["break-model", "break-tool", "break-context"]
    .filter((id) => $(id).checked)
    .map((id) => $(id).value);
}

async function createRun(event) {
  event?.preventDefault();
  if (busy || session?.debug_status === "running") return;
  busy = true;
  clearNotice();
  render();
  try {
    // A new context is a new run; explicitly stop the previous paused engine.
    if (session?.debug_status === "paused")
      await api("/api/debug/control", {
        session_id: session.session_id,
        action: "stop",
      });
    const snapshot = await api("/api/debug/create", {
      prompt: $("prompt").value,
      mode: $("mode").value,
      provider: $("provider").value,
      fault: $("fault").value,
      max_steps: Number($("max-steps").value),
      breakpoints: selectedBreakpoints(),
      delay_ms: Number($("pace").value),
    });
    clearTimeout(pollTimer);
    followLive = true;
    selectedSeq = null;
    inspectedNode = null;
    editorKey = "";
    lastTimelineKey = "";
    sourcePinned = false;
    lastSourceKey = "";
    $("timeline").replaceChildren(
      element(
        "div",
        "empty",
        "Paused before accepting the goal. Step to begin real execution.",
      ),
    );
    applySnapshot(snapshot);
    // On small screens, put the live graph and inspector above setup controls.
    if (window.matchMedia("(max-width: 900px)").matches)
      document.body.classList.add("setup-collapsed");
  } catch (error) {
    report(error);
  } finally {
    busy = false;
    render();
  }
}

async function control(action) {
  if (busy || !session) return;
  busy = true;
  clearNotice();
  render();
  try {
    const snapshot = await api("/api/debug/control", {
      session_id: session.session_id,
      action,
      revision: session.revision,
    });
    followLive = true;
    selectedSeq = null;
    inspectedNode = null;
    sourcePinned = false;
    applySnapshot(snapshot);
  } catch (error) {
    report(error);
    try {
      applySnapshot(
        await api(
          `/api/debug/session?id=${encodeURIComponent(session.session_id)}`,
        ),
      );
    } catch (_) {
      /* The original error remains visible. */
    }
  } finally {
    busy = false;
    render();
  }
}

function selectTab(name) {
  activeTab = name;
  ["event", "context", "source", "data"].forEach((tab) => {
    $("tab-" + tab).setAttribute("aria-selected", String(tab === name));
    $("view-" + tab).hidden = tab !== name;
  });
  if (name === "source") {
    lastSourceKey = "";
    renderSource(eventSelection());
  }
}

function updateConfig() {
  const workflow = $("mode").value === "workflow",
    agent = $("mode").value === "agent";
  $("provider").disabled = workflow;
  $("fault").disabled = !agent;
  if (!agent) $("fault").value = "none";
  const provider = $("provider").value;
  $("provider-note").textContent = workflow
    ? "Code selects the lookup. No model calls."
    : provider === "offline"
      ? "Deterministic teaching model. No real LLM inference."
      : provider === "ollama"
        ? "Real local LLM. Start Ollama first. Errors remain visible; no offline fallback."
        : "Cloud-hosted Workers AI. Requests use account quota; errors remain visible with no fallback.";
  // Before a run exists, changing the selector previews that mode's actual topology.
  if (catalog) renderGraph();
}

async function initialize() {
  try {
    catalog = await api("/api/catalog");
    drawGraph();
    // Tool cards make local computation and external weather I/O explicit.
    catalog.tools.forEach((schema) => {
      const capability = schema.function;
      const card = element("article", "tool-card");
      card.append(
        element("strong", "", capability.name),
        element("p", "", capability.description),
      );
      if (capability.name === "search_weather") {
        // Link directly to the two fixed API contracts shown by the executor.
        [
          [
            "Geocoding API documentation",
            "https://open-meteo.com/en/docs/geocoding-api",
          ],
          ["Forecast API documentation", "https://open-meteo.com/en/docs"],
        ].forEach(([label, href]) => {
          const source = element("a", "", label);
          source.href = href;
          source.target = "_blank";
          source.rel = "noreferrer";
          card.append(source);
        });
        card.append(
          element(
            "p",
            "hint",
            "Network access occurs only after Step at the tool boundary.",
          ),
        );
      }
      if (capability.name === "calculate")
        card.append(
          element(
            "p",
            "hint",
            "Evaluated locally with a restricted Python AST; no eval or code execution.",
          ),
        );
      $("tool-catalog").append(card);
    });
    catalog.documents.forEach((document) => {
      const card = element("article", "document-card");
      card.append(
        element("span", "doc-id", document.id),
        element("strong", "", document.title),
        element("p", "", document.text),
      );
      $("documents").append(card);
    });
    $("tool-schema").textContent = pretty(catalog.tools);
    $("config-form").addEventListener("submit", createRun);
    ["mode", "provider"].forEach((id) =>
      $(id).addEventListener("change", updateConfig),
    );
    document
      .querySelectorAll("[data-prompt]")
      .forEach((button) =>
        button.addEventListener(
          "click",
          () => ($("prompt").value = button.dataset.prompt),
        ),
      );
    ["step", "continue", "pause", "stop"].forEach((action) =>
      $(action).addEventListener("click", () => control(action)),
    );
    ["event", "context", "source", "data"].forEach((name) =>
      $("tab-" + name).addEventListener("click", () => selectTab(name)),
    );
    ["before", "after"].forEach((side) =>
      $("context-" + side).addEventListener("click", () => {
        contextSide = side;
        renderContext(eventSelection());
      }),
    );
    $("follow-live").addEventListener("click", () => {
      followLive = true;
      selectedSeq = null;
      inspectedNode = null;
      sourcePinned = false;
      render();
    });
    $("source-file").addEventListener("change", () => {
      sourcePinned = true;
      lastSourceKey = "";
      renderSource(eventSelection());
    });
    $("pending-value").addEventListener(
      "focus",
      () => (isEditingArgument = true),
    );
    $("pending-value").addEventListener(
      "blur",
      () => (isEditingArgument = false),
    );
    $("save-query").addEventListener("click", async () => {
      if (busy || !session) return;
      busy = true;
      clearNotice();
      render();
      try {
        const snapshot = await api("/api/debug/argument", {
          session_id: session.session_id,
          revision: session.revision,
          argument: $("pending-value").dataset.argument,
          value: $("pending-value").value,
        });
        editorKey = "";
        followLive = true;
        selectedSeq = null;
        inspectedNode = null;
        applySnapshot(snapshot);
      } catch (error) {
        report(error);
      } finally {
        busy = false;
        render();
      }
    });
    $("apply-breakpoints").addEventListener("click", async () => {
      if (busy || !session) return;
      busy = true;
      clearNotice();
      render();
      try {
        applySnapshot(
          await api("/api/debug/breakpoints", {
            session_id: session.session_id,
            revision: session.revision,
            breakpoints: selectedBreakpoints(),
          }),
        );
      } catch (error) {
        report(error);
      } finally {
        busy = false;
        render();
      }
    });
    $("run-history").addEventListener("change", async () => {
      const id = $("run-history").value;
      if (!id || busy) return;
      busy = true;
      clearNotice();
      try {
        const snapshot = await api(
          `/api/debug/session?id=${encodeURIComponent(id)}`,
        );
        followLive = true;
        selectedSeq = null;
        inspectedNode = null;
        editorKey = "";
        sourcePinned = false;
        lastTimelineKey = "";
        lastSourceKey = "";
        ["break-model", "break-tool", "break-context"].forEach(
          (key) =>
            ($(key).checked = snapshot.breakpoints.includes($(key).value)),
        );
        applySnapshot(snapshot);
      } catch (error) {
        report(error);
      } finally {
        busy = false;
        render();
      }
    });
    $("export").addEventListener("click", () => {
      const url = URL.createObjectURL(
        new Blob([pretty(session)], { type: "application/json" }),
      );
      const anchor = element("a");
      anchor.href = url;
      anchor.download = `debug-trace-${session.result.run_id}.json`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    $("setup-toggle").addEventListener("click", () => {
      document.body.classList.toggle("setup-collapsed");
      $("setup-toggle").textContent = document.body.classList.contains(
        "setup-collapsed",
      )
        ? "Show setup"
        : "Hide setup";
    });
    $("help-toggle").addEventListener("click", () => $("help").showModal());
    document.addEventListener("keydown", (event) => {
      if (event.key === "F10") {
        event.preventDefault();
        if (!$("step").disabled) control("step");
      }
      if (event.key === "F8") {
        event.preventDefault();
        if (!$("continue").disabled) control("continue");
      }
    });
    updateConfig();
    render();
  } catch (error) {
    report(error);
    $("create").disabled = true;
  }
}
initialize();
