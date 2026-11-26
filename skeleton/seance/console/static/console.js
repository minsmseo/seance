"use strict";

// Builds the page from /config, reads every device and fills one tile per
// point. Summary, ledger and the tool panel are filled in by later steps.

// ----- Formatter: pure functions, no DOM access ----------------------------
// Each format is chosen from the unit and the value type only. A formatted
// result is { value, unit, detail } of plain strings. Signs are never changed.

function groupDigits(number) {
  return number.toLocaleString("en-US", { maximumFractionDigits: 20 });
}

function pad2(number) {
  return String(number).padStart(2, "0");
}

// Returns { text, title }. An unparseable timestamp is shown unchanged.
function formatTimestamp(iso) {
  const text = String(iso);
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) {
    return { text: text, title: text };
  }
  const local = pad2(date.getHours()) + ":" + pad2(date.getMinutes()) + ":" + pad2(date.getSeconds());
  return { text: local, title: text };
}

function formatUnit(unit) {
  if (unit === "degC") {
    return "\u00b0C";
  }
  if (unit === "percent") {
    return "%";
  }
  if (unit === "state") {
    return "";
  }
  return String(unit);
}

// Detail parts are joined with a comma and a space.
function joinDetail(parts) {
  return parts.join(", ");
}

function formatSeconds(seconds, readTime) {
  if (seconds >= 60) {
    const whole = Math.floor(seconds);
    const days = Math.floor(whole / 86400);
    const hours = Math.floor((whole % 86400) / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    const rest = whole % 60;
    let text;
    if (days >= 1) {
      text = days + "d " + hours + "h " + minutes + "m";
    } else if (hours >= 1) {
      text = hours + "h " + minutes + "m";
    } else {
      text = minutes + "m " + rest + "s";
    }
    return { value: text, unit: "", detail: groupDigits(seconds) + " s" };
  }
  return { value: groupDigits(seconds), unit: "s", detail: formatTimestamp(readTime).text };
}

function formatBytes(bytes) {
  const raw = groupDigits(bytes) + " B";
  const steps = ["kB", "MB", "GB", "TB"];
  let size = Math.abs(bytes);
  if (size < 1000) {
    return { value: groupDigits(bytes), unit: "B", detail: raw };
  }
  let index = -1;
  while (size >= 1000 && index < steps.length - 1) {
    size = size / 1000;
    index += 1;
  }
  const sign = bytes < 0 ? "-" : "";
  return { value: sign + size.toFixed(2), unit: steps[index], detail: raw };
}

function formatBoolean(flag, readTime) {
  return { value: flag ? "on" : "off", unit: "", detail: formatTimestamp(readTime).text };
}

function formatLabeled(label, raw, readTime) {
  return {
    value: String(label),
    unit: "",
    detail: joinDetail(["raw " + raw, formatTimestamp(readTime).text]),
  };
}

// Chooses a format from the unit and the value type of one successful read.
function formatReading(unit, reading) {
  const value = reading.value;
  const readTime = reading.timestamp;
  if (typeof value === "boolean") {
    return formatBoolean(value, readTime);
  }
  if (typeof reading.raw === "number") {
    return formatLabeled(value, reading.raw, readTime);
  }
  if (typeof value === "number") {
    if (unit === "s") {
      return formatSeconds(value, readTime);
    }
    if (unit === "B") {
      return formatBytes(value);
    }
    return { value: groupDigits(value), unit: formatUnit(unit), detail: formatTimestamp(readTime).text };
  }
  return { value: String(value), unit: formatUnit(unit), detail: formatTimestamp(readTime).text };
}

// ----- DOM helpers ---------------------------------------------------------

function addText(parent, tag, className, text) {
  const el = document.createElement(tag);
  if (className) {
    el.className = className;
  }
  el.textContent = text;
  parent.appendChild(el);
  return el;
}

function warningTriangle() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "warning");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("width", "14");
  svg.setAttribute("height", "14");
  svg.setAttribute("aria-hidden", "true");
  const shape = document.createElementNS(ns, "path");
  shape.setAttribute("d", "M8 1 L15 14 L1 14 Z");
  svg.appendChild(shape);
  return svg;
}

function shortSentence(message) {
  const text = String(message);
  const end = text.indexOf(". ");
  return end === -1 ? text : text.slice(0, end + 1);
}

// Builds one three-line tile. `outcome` is { reading } or { error }.
function renderTile(point, outcome) {
  const tile = document.createElement("div");
  tile.className = "tile";
  addText(tile, "span", "tile-name", point.name);
  const valueLine = addText(tile, "span", "tile-value", "");
  const detailLine = addText(tile, "span", "tile-detail", "");
  let attention = false;
  if (outcome.error !== undefined) {
    attention = true;
    valueLine.textContent = "Read failed";
    detailLine.textContent = shortSentence(outcome.error);
    tile.title = String(outcome.error);
  } else {
    const shown = formatReading(point.unit, outcome.reading);
    valueLine.textContent = shown.value;
    if (shown.unit) {
      addText(valueLine, "span", "tile-unit", shown.unit);
    }
    detailLine.textContent = shown.detail;
    tile.title = formatTimestamp(outcome.reading.timestamp).title;
    if (typeof point.healthy === "string" && point.healthy) {
      attention = outcome.reading.value !== point.healthy;
    }
  }
  if (attention) {
    tile.classList.add("attention");
    valueLine.insertBefore(warningTriangle(), valueLine.firstChild);
  }
  return { element: tile, attention: attention };
}

// ----- Page ----------------------------------------------------------------

let deviceViews = [];
let refreshing = null;

function renderDevices(config) {
  const host = document.getElementById("devices");
  host.textContent = "";
  deviceViews = [];
  if (!config.devices || config.devices.length === 0) {
    addText(host, "p", "empty", "No devices are configured.");
    return;
  }
  for (const device of config.devices) {
    const section = document.createElement("section");
    section.className = "device";
    const head = document.createElement("div");
    head.className = "device-head";
    addText(head, "h2", "device-name mono", device.name);
    addText(head, "p", "device-description", device.description);
    const health = addText(head, "p", "device-health", "");
    section.appendChild(head);
    const grid = document.createElement("div");
    grid.className = "tile-grid";
    section.appendChild(grid);
    if (!device.points || device.points.length === 0) {
      addText(section, "p", "empty", "No points configured.");
    }
    host.appendChild(section);
    deviceViews.push({ device: device, grid: grid, health: health });
  }
}

// Shown on every point of a device whose reply is missing, unreadable or has no results.
const READ_FAILED = "The console server did not return a reading. Try Read again.";

// Maps the read_points reply to one outcome per configured point.
function outcomesFor(device, body) {
  const byName = new Map();
  let wholeError = null;
  const payload = body ? body.result : null;
  if (payload && typeof payload === "object" && Array.isArray(payload.results)) {
    for (const item of payload.results) {
      if (item && typeof item === "object") {
        byName.set(item.point, item);
      }
    }
  } else {
    wholeError = typeof payload === "string" && payload ? payload : READ_FAILED;
  }
  return device.points.map(function (point) {
    if (wholeError !== null) {
      return { error: wholeError };
    }
    const item = byName.get(point.name);
    if (!item) {
      return { error: "No reply for this point. Try again in a moment." };
    }
    if (item.error !== undefined) {
      return { error: item.error };
    }
    return { reading: item };
  });
}

async function readDevice(view) {
  const device = view.device;
  if (!device.points || device.points.length === 0) {
    view.health.textContent = "No points";
    return { read: 0, attention: [] };
  }
  let body = null;
  try {
    const response = await fetch("/tools/read_points", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        device: device.name,
        points: device.points.map(function (p) {
          return p.name;
        }),
      }),
    });
    body = await response.json();
  } catch (failure) {
    // A rejected fetch or an unparseable body fails every point of this device.
    body = { result: READ_FAILED };
  }
  const outcomes = outcomesFor(device, body);
  const tiles = [];
  const attention = [];
  let read = 0;
  device.points.forEach(function (point, index) {
    const outcome = outcomes[index];
    const made = renderTile(point, outcome);
    if (outcome.error === undefined) {
      read += 1;
    }
    if (made.attention) {
      made.element.tabIndex = -1;
      attention.push({
        device: device.name,
        point: point.name,
        problem: outcome.error !== undefined ? "read failed" : String(outcome.reading.value),
        tile: made.element,
      });
    }
    tiles.push(made.element);
  });
  view.grid.replaceChildren(...tiles);
  view.health.textContent = read + " of " + device.points.length + " points read";
  return { read: read, attention: attention };
}

// Fills the summary strip. `results` holds one entry per device, in device
// order: { read, attention } as returned by readDevice. The chips come from
// the same list that marks the tiles, so chip count equals attention tile count.
function renderSummaryStrip(devices, results) {
  const host = document.getElementById("summary");
  const nodes = [];
  let answering = 0;
  let pointsTotal = 0;
  let pointsRead = 0;
  const chips = [];
  devices.forEach(function (device, index) {
    const count = device.points ? device.points.length : 0;
    const result = results[index];
    pointsTotal += count;
    pointsRead += result.read;
    if (count === 0 || result.read > 0) {
      answering += 1;
    }
    for (const item of result.attention) {
      chips.push(item);
    }
  });
  const devicesText = document.createElement("span");
  devicesText.className = "summary-count";
  devicesText.textContent = answering + " of " + devices.length + " devices answering";
  const pointsText = document.createElement("span");
  pointsText.className = "summary-count";
  pointsText.textContent = pointsRead + " of " + pointsTotal + " points read";
  nodes.push(devicesText, pointsText);
  for (const item of chips) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "attention-chip";
    chip.appendChild(warningTriangle());
    addText(chip, "span", "", item.device + " " + item.point + ": " + item.problem);
    chip.addEventListener("click", function () {
      item.tile.focus();
    });
    nodes.push(chip);
  }
  host.replaceChildren(...nodes);
}

async function loadConfig() {
  const response = await fetch("/config");
  return response.json();
}

async function runRefresh() {
  const config = await loadConfig();
  if (typeof config.title === "string" && config.title) {
    document.getElementById("app-name").textContent = config.title;
  }
  if (deviceViews.length === 0) {
    renderDevices(config);
  }
  const results = await Promise.all(deviceViews.map(readDevice));
  renderSummaryStrip(config.devices || [], results);
  const stamp = formatTimestamp(new Date().toISOString());
  const lastRead = document.getElementById("last-read");
  lastRead.textContent = stamp.text;
  lastRead.title = stamp.title;
}

// Used by the first page load and by Read again. Tiles stay on screen while a
// re-read is in flight; a second call during a read shares the running one.
function refreshAll() {
  if (refreshing === null) {
    refreshing = runRefresh().finally(function () {
      refreshing = null;
    });
  }
  return refreshing;
}

// ----- Ledger --------------------------------------------------------------

const REASON_SENTENCES = {
  rejected: "The call was refused because this console only reads. Use a read tool instead.",
  unknown_tool: "That tool does not exist. Pick one from the tool list.",
  unknown_target: "That device or point is not configured. Pick one from the lists.",
  invalid_argument: "The call had a missing or invalid argument. Check the arguments and send it again.",
  timeout: "The device did not answer in time. Check that it is running and read again.",
  adapter_error: "The device could not be read. Check that it is running and try again.",
};

const GENERIC_REASON = "The call did not succeed. Read again, and check the device if it keeps failing.";

function reasonSentence(outcome) {
  const key = String(outcome);
  if (Object.prototype.hasOwnProperty.call(REASON_SENTENCES, key)) {
    return REASON_SENTENCES[key];
  }
  return GENERIC_REASON;
}

const LEDGER_MAX_NAMED_POINTS = 3;

// Builds the target of one entry. More than three points show as
// "<device>, <n> points" with the full list in the row title. Otherwise each
// name sits in its own nowrap span and lines wrap only at the commas.
function renderLedgerTarget(entry, row) {
  const points = entry.point ? String(entry.point).split(",") : [];
  const names = [];
  if (entry.device) {
    names.push(entry.device);
  }
  if (points.length > LEDGER_MAX_NAMED_POINTS) {
    names.push(points.length + " points");
    row.title = points.join(", ");
  } else {
    for (const point of points) {
      names.push(point);
    }
  }
  if (names.length === 0) {
    return null;
  }
  const target = document.createElement("span");
  target.className = "ledger-target ledger-detail";
  target.title = (entry.device ? [entry.device] : []).concat(points).join(", ");
  names.forEach(function (name, index) {
    if (index > 0) {
      addText(target, "span", "ledger-sep", ", ");
    }
    addText(target, "span", "ledger-name", name);
  });
  return target;
}

// Replaces the Ledger rows with one row per entry, in the order received.
function renderLedgerRows(entries) {
  const host = document.getElementById("ledger-list");
  if (!entries || entries.length === 0) {
    const empty = document.createElement("li");
    empty.className = "ledger-empty";
    empty.textContent = "No calls yet.";
    host.replaceChildren(empty);
    return;
  }
  const rows = entries.map(function (entry) {
    const row = document.createElement("li");
    const main = document.createElement("div");
    main.className = "ledger-line ledger-line-main";
    const meta = document.createElement("div");
    meta.className = "ledger-line ledger-line-meta";
    const failed = entry.outcome !== "ok";
    if (failed) {
      row.classList.add("attention");
      main.appendChild(warningTriangle());
    }
    addText(main, "span", "ledger-tool", entry.tool);
    const target = renderLedgerTarget(entry, row);
    if (target) {
      main.appendChild(target);
    }
    const source = entry.source === "console" ? "console" : "agent";
    addText(meta, "span", "ledger-source ledger-source-" + source, source);
    addText(meta, "span", "ledger-outcome", entry.outcome);
    const when = formatTimestamp(entry.timestamp);
    const time = addText(meta, "span", "ledger-time ledger-detail", when.text);
    time.title = when.title;
    row.appendChild(main);
    row.appendChild(meta);
    if (failed) {
      addText(row, "p", "ledger-reason", reasonSentence(entry.outcome));
    }
    return row;
  });
  host.replaceChildren(...rows);
}

const LEDGER_POLL_MS = 2000;
const LEDGER_ERROR = "The ledger could not be loaded. It will try again in 2 seconds.";
let ledgerInFlight = false;

function setLedgerNote(text) {
  const note = document.getElementById("ledger-note");
  note.textContent = text;
  note.hidden = text === "";
}

// Fetches /audit once. A call while one is pending is skipped.
async function pollAudit() {
  if (ledgerInFlight) {
    return;
  }
  ledgerInFlight = true;
  try {
    const response = await fetch("/audit");
    if (!response.ok) {
      throw new Error("audit status " + response.status);
    }
    const entries = await response.json();
    renderLedgerRows(entries);
    setLedgerNote("");
  } catch (failure) {
    setLedgerNote(LEDGER_ERROR);
  } finally {
    ledgerInFlight = false;
  }
}

// For the tool panel: refresh the Ledger now, sharing the in-flight guard.
function refreshLedgerNow() {
  return pollAudit();
}

// ----- Read again ----------------------------------------------------------

async function onReadAgain() {
  const button = document.getElementById("read-again");
  button.disabled = true;
  try {
    await refreshAll();
  } catch (failure) {
    document.getElementById("summary").textContent =
      "The console could not read the devices. Check that the server is running and try again.";
  } finally {
    button.disabled = false;
  }
}

// ----- Tool panel ----------------------------------------------------------

const SERVER_SILENT =
  "The console server did not answer. Check that it is running and try again.";
const NEEDS_DEVICE = ["list_points", "read_points", "device_health", "read_point"];
let toolDevices = [];

function fillSelect(select, values) {
  const options = values.map(function (value) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    return option;
  });
  select.replaceChildren(...options);
}

function selectedDevice() {
  const name = document.getElementById("device-select").value;
  return toolDevices.find(function (d) {
    return d.name === name;
  });
}

function fillPointSelect() {
  const device = selectedDevice();
  const names = device && device.points ? device.points.map(function (p) {
    return p.name;
  }) : [];
  fillSelect(document.getElementById("point-select"), names);
}

function updateSelectState() {
  const tool = document.getElementById("tool-select").value;
  document.getElementById("device-select").disabled = NEEDS_DEVICE.indexOf(tool) === -1;
  document.getElementById("point-select").disabled = tool !== "read_point";
}

function toolArguments(tool) {
  const args = {};
  if (NEEDS_DEVICE.indexOf(tool) === -1) {
    return args;
  }
  const device = selectedDevice();
  args.device = document.getElementById("device-select").value;
  if (tool === "read_point") {
    args.point = document.getElementById("point-select").value;
  } else if (tool === "read_points") {
    args.points = (device && device.points ? device.points : []).map(function (p) {
      return p.name;
    });
  }
  return args;
}

async function sendTool() {
  const reply = document.getElementById("tool-reply");
  const send = document.getElementById("tool-send");
  const tool = document.getElementById("tool-select").value;
  send.disabled = true;
  try {
    const response = await fetch("/tools/" + encodeURIComponent(tool), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toolArguments(tool)),
    });
    const body = await response.json();
    reply.textContent = JSON.stringify(body, null, 2);
  } catch (failure) {
    reply.textContent = SERVER_SILENT;
  } finally {
    send.disabled = false;
    refreshLedgerNow();
  }
}

async function initToolPanel() {
  const toolSelect = document.getElementById("tool-select");
  const deviceSelect = document.getElementById("device-select");
  try {
    const config = await loadConfig();
    toolDevices = config.devices || [];
    fillSelect(toolSelect, config.tools || []);
    fillSelect(deviceSelect, toolDevices.map(function (d) {
      return d.name;
    }));
    fillPointSelect();
  } catch (failure) {
    document.getElementById("tool-reply").textContent = SERVER_SILENT;
  }
  updateSelectState();
  toolSelect.addEventListener("change", updateSelectState);
  deviceSelect.addEventListener("change", fillPointSelect);
  document.getElementById("tool-form").addEventListener("submit", function (event) {
    event.preventDefault();
    sendTool();
  });
}

pollAudit();
setInterval(pollAudit, LEDGER_POLL_MS);

document.getElementById("read-again").addEventListener("click", onReadAgain);
initToolPanel();
refreshAll().catch(function () {
  document.getElementById("summary").textContent =
    "The console could not read the devices. Check that the server is running and try Read again.";
});
