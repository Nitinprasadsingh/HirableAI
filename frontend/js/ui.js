export function byId(id) {
  return document.getElementById(id);
}

export function setStatus(element, message, type = "info") {
  if (!element) return;
  element.textContent = message;
  element.className = `status-pill status-${type}`;
}

export function setProgress(element, value) {
  if (!element) return;
  const safe = Math.max(0, Math.min(100, Number(value) || 0));
  element.style.width = `${safe}%`;
}

export function appendEvent(listElement, message) {
  if (!listElement) return;
  const item = document.createElement("li");
  item.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
  listElement.prepend(item);
}

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export function formatPercent(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`;
}

export function getQueryParam(name) {
  const params = new URLSearchParams(window.location.search);
  return params.get(name);
}

export function toggleHidden(element, hidden) {
  if (!element) return;
  element.classList.toggle("hidden", hidden);
}

export function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
