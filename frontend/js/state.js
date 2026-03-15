const SESSION_KEY = "aiTrainer.session";
const REPORTS_KEY = "aiTrainer.reports";

function readStorage(storage, key, fallback) {
  try {
    const raw = storage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeStorage(storage, key, value) {
  storage.setItem(key, JSON.stringify(value));
}

export function getSession() {
  return readStorage(sessionStorage, SESSION_KEY, {});
}

export function setSession(nextState) {
  writeStorage(sessionStorage, SESSION_KEY, nextState || {});
}

export function updateSession(partial) {
  const previous = getSession();
  const nextState = { ...previous, ...partial, updatedAt: new Date().toISOString() };
  setSession(nextState);
  return nextState;
}

export function clearSession() {
  sessionStorage.removeItem(SESSION_KEY);
}

export function saveInterviewReport(resumeId, report) {
  const reports = readStorage(localStorage, REPORTS_KEY, {});
  reports[resumeId] = report;
  writeStorage(localStorage, REPORTS_KEY, reports);
}

export function getInterviewReport(resumeId) {
  const reports = readStorage(localStorage, REPORTS_KEY, {});
  return reports[resumeId] || null;
}
