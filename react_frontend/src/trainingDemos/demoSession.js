const STORAGE_KEY = "cocanot-public-demo";
const TIMEOUT_MS = 30 * 60 * 1000;

export function loadDemoState() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;

    const state = JSON.parse(raw);
    const now = Date.now();
    const lastActivity = Number(state.lastActivity || 0);

    if (!lastActivity || now - lastActivity > TIMEOUT_MS) {
      sessionStorage.removeItem(STORAGE_KEY);
      return null;
    }

    return state;
  } catch {
    return null;
  }
}

export function saveDemoState(patch = {}) {
  const current = loadDemoState() || {};
  const next = {
    ...current,
    ...patch,
    lastActivity: Date.now(),
  };

  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  return next;
}

export function resetDemoState() {
  sessionStorage.removeItem(STORAGE_KEY);
}
