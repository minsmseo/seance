"use strict";

// All dynamic text is written with textContent, so nothing is parsed as HTML.
// Device names, values and error sentences are shown exactly as received.

function cell(text) {
  const td = document.createElement("td");
  td.textContent = String(text);
  return td;
}

async function loadAudit() {
  const body = document.getElementById("audit-body");
  try {
    const response = await fetch("/audit");
    const entries = await response.json();
    body.replaceChildren();
    for (const e of entries) {
      const tr = document.createElement("tr");
      for (const key of ["timestamp", "tool", "device", "point", "outcome", "duration_ms"]) {
        tr.appendChild(cell(e[key]));
      }
      body.appendChild(tr);
    }
  } catch (err) {
    body.replaceChildren();
    const tr = document.createElement("tr");
    const td = cell("The ledger could not be loaded. Reload the page to try again.");
    td.colSpan = 6;
    tr.appendChild(td);
    body.appendChild(tr);
  }
}

async function sendTool(event) {
  event.preventDefault();
  const out = document.getElementById("tool-result");
  const tool = document.getElementById("tool-name").value;
  const text = document.getElementById("tool-args").value.trim() || "{}";
  let args;
  try {
    args = JSON.parse(text);
  } catch (err) {
    out.textContent = "The arguments are not valid JSON. Fix the text and send again.";
    return;
  }
  if (args === null || typeof args !== "object" || Array.isArray(args)) {
    out.textContent = "The arguments must be a JSON object such as {}. Fix the text and send again.";
    return;
  }
  try {
    const response = await fetch("/tools/" + encodeURIComponent(tool), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    });
    const data = await response.json();
    out.textContent = JSON.stringify(data, null, 2);
  } catch (err) {
    out.textContent = "The console server did not answer. Check that it is running and try again.";
  }
  loadAudit();
}

document.getElementById("tool-form").addEventListener("submit", sendTool);
document.getElementById("resummon").addEventListener("click", () => window.location.reload());
loadAudit();
