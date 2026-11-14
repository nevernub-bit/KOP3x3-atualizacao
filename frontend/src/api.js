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
  window.dispatchEvent(new Event("kop-test-mode-change"));
}

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
