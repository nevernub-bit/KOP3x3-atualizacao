import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

// --- Test simulation scope -------------------------------------------------
// The flag lives in sessionStorage: it dies with the tab, and the backend only
// accepts the TEST scope with a valid admin token. A visitor can never end up
// reading simulation data by accident.
const TEST_FLAG = "kop_test_mode";

export const isTestMode = () => {
  try {
    return sessionStorage.getItem(TEST_FLAG) === "1";
  } catch {
    return false;
  }
};

export function setTestMode(on) {
  try {
    if (on) sessionStorage.setItem(TEST_FLAG, "1");
    else sessionStorage.removeItem(TEST_FLAG);
  } catch { /* storage bloqueado: modo teste simplesmente não persiste */ }
  // Leaving the simulation must also drop the scope from the address bar,
  // otherwise a reload of this tab would adopt TEST again.
  if (!on) {
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.has("scope")) {
        url.searchParams.delete("scope");
        window.history.replaceState({}, "", url);
      }
    } catch { /* sem history: nada a limpar */ }
  }
  window.dispatchEvent(new Event("kop-test-mode-change"));
}

// The Telão and the draw presentation are opened in a second tab/screen, where
// sessionStorage starts empty. The scope travels in the URL (?scope=TEST) and
// that tab adopts it, so every request it makes carries the header. The header
// alone grants nothing: the backend still requires an admin token for TEST.
export function adoptScopeFromUrl(search = window.location.search) {
  try {
    const wanted = (new URLSearchParams(search).get("scope") || "").toUpperCase();
    if (!wanted) return false;
    if (wanted === "TEST") {
      sessionStorage.setItem(TEST_FLAG, "1");
      return true;
    }
    if (wanted === "REAL" || wanted === "PROD" || wanted === "PRODUCTION") {
      sessionStorage.removeItem(TEST_FLAG);
    }
  } catch { /* storage bloqueado: segue o escopo padrão (real) */ }
  return false;
}

adoptScopeFromUrl();

/** Keeps links inside the simulation (Telão, sorteio) pointing at TEST. */
export const scopedLink = (path) =>
  isTestMode() ? `${path}${path.includes("?") ? "&" : "?"}scope=TEST` : path;

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("kop_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  if (isTestMode()) config.headers["X-KOP-Scope"] = "TEST";
  return config;
});

export function formatErr(detail) {
  if (!detail) return "Erro inesperado.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map(d => d.msg || JSON.stringify(d)).join(" ");
  if (detail?.msg) return detail.msg;
  return String(detail);
}
