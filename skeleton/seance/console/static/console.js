"use strict";

// Builds the page structure from /config. Tiles, summary, ledger and the tool
// panel are filled in by later steps.

function addText(parent, tag, className, text) {
  const el = document.createElement(tag);
  if (className) {
    el.className = className;
  }
  el.textContent = text;
  parent.appendChild(el);
  return el;
}

function renderDevices(config) {
  const host = document.getElementById("devices");
  host.textContent = "";
  if (!config.devices || config.devices.length === 0) {
    addText(host, "p", "empty", "No devices are configured.");
    return;
  }
  for (const device of config.devices) {
    const section = document.createElement("section");
    section.className = "device";
    addText(section, "h2", "device-name mono", device.name);
    addText(section, "p", "device-description", device.description);
    const grid = document.createElement("div");
    grid.className = "tile-grid";
    section.appendChild(grid);
    if (!device.points || device.points.length === 0) {
      addText(section, "p", "empty", "No points configured.");
    }
    host.appendChild(section);
  }
}

async function start() {
  const response = await fetch("/config");
  const config = await response.json();
  renderDevices(config);
}

start();
