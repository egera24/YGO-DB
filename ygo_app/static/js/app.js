const API = "/api";

const IMG_PLACEHOLDER =
  "data:image/svg+xml," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="174" viewBox="0 0 120 174"><rect fill="#1e293b" width="120" height="174"/><text x="60" y="87" text-anchor="middle" fill="#64748b" font-size="12" font-family="sans-serif">No image</text></svg>'
  );

function cardImgTag(url, attrs = "") {
  const src = url ? escapeHtml(url) : IMG_PLACEHOLDER;
  return `<img src="${src}" alt="" loading="lazy" onerror="this.onerror=null;this.src='${IMG_PLACEHOLDER}'" ${attrs} />`;
}

const state = {
  activeView: "search",
  currentCardId: null,
  currentCard: null,
  activeDeckId: null,
  filters: {},
  token: localStorage.getItem("ygo_token") || null,
  user: null,
  searchPage: 0,
  searchTotal: 0,
  searchParams: new URLSearchParams(),
  exportFormats: null,
  collectionPage: 0,
  collectionTotal: 0,
  collectionFolder: null,
  collectionStats: null,
  collectionItemsById: {},
  collectionLastItems: [],
  collectionViewCache: null,
  decksListCache: null,
  decksQuery: "",
  decksSort: "updated_at",
  decksDetailOpen: false,
  activeDeckDetail: null,
  activePresetId: null,
  searchPresets: [],
  searchResultsById: {},
};

let searchRequestSeq = 0;
let collectionRequestSeq = 0;
let deckDetailRequestSeq = 0;
let decksSearchTimer = null;

const COLLECTION_PAGE_SIZE = 100;
const NO_FOLDER = "__no_folder__";
const COLLECTION_FOLDER_ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>`;
const COLLECTION_CONDITIONS = [
  { value: "Mint", label: "Mint (MT)", tone: "mint" },
  { value: "NearMint", label: "Near Mint (NM)", tone: "nearmint" },
  { value: "Excellent", label: "Excellent (EX)", tone: "excellent" },
  { value: "Good", label: "Good (GD)", tone: "good" },
  { value: "LightPlayed", label: "Light Played (LP)", tone: "lightplayed" },
  { value: "Played", label: "Played (PL)", tone: "played" },
  { value: "Poor", label: "Poor (PO)", tone: "poor" },
];
const COLLECTION_EDITIONS = ["Unlimited", "1st Edition", "Limited Edition"];
const COLLECTION_LANGUAGES = [
  "English",
  "French",
  "Italian",
  "German",
  "Spanish",
  "Portuguese",
];

const ROUTE_VIEWS = new Set(["search", "collection", "decks"]);
const DEFAULT_ROUTE_VIEW = "search";
const ROUTE_SEARCH_KEYS = new Set([
  "q",
  "set_code",
  "category",
  "types",
  "mechanic",
  "attribute",
  "archetype",
  "summoning_condition",
  "link_markers",
  "level_min",
  "level_max",
  "rank_min",
  "rank_max",
  "link_rating_min",
  "link_rating_max",
  "pendulum_scale_min",
  "pendulum_scale_max",
  "atk_min",
  "atk_max",
  "def_min",
  "def_max",
  "owned_only",
  "favorites_only",
]);
const ROUTE_PARAM_MAX_LEN = 500;
const ROUTE_PARAM_MAX_KEYS = 30;
const APP_TITLE_BASE = "YGO Collection & Deck Builder";

let suppressHashSync = false;
let lastAppliedRouteHash = "";

function parseRouteHash() {
  const raw = (window.location.hash || "").replace(/^#/, "");
  const [pathPart, queryPart = ""] = raw.split("?");
  const segments = pathPart.split("/").filter(Boolean);
  const params = new URLSearchParams(queryPart);

  if (segments[0] === "card") {
    if (/^\d+$/.test(segments[1] || "")) {
      return { kind: "card", cardId: segments[1], params };
    }
    return { kind: "tab", view: DEFAULT_ROUTE_VIEW, deckId: null, params, invalid: true };
  }

  const view = segments[0] || DEFAULT_ROUTE_VIEW;
  if (view === "decks" && segments[1]) {
    if (/^\d+$/.test(segments[1])) {
      return { kind: "tab", view: "decks", deckId: Number(segments[1]), params };
    }
    return { kind: "tab", view: "decks", deckId: null, params, invalid: true };
  }
  if (ROUTE_VIEWS.has(view)) {
    return { kind: "tab", view, deckId: null, params };
  }
  return { kind: "tab", view: DEFAULT_ROUTE_VIEW, deckId: null, params, invalid: true };
}

function snapshotFromRouteParams(params) {
  const snapshot = {};
  let count = 0;
  for (const [key, value] of params.entries()) {
    if (!ROUTE_SEARCH_KEYS.has(key) || count >= ROUTE_PARAM_MAX_KEYS) continue;
    const text = String(value).slice(0, ROUTE_PARAM_MAX_LEN).trim();
    if (text) snapshot[key] = text;
    count += 1;
  }
  return snapshot;
}

function parseFolderRouteParam(raw) {
  if (raw == null || raw === "") return null;
  if (raw === NO_FOLDER) return NO_FOLDER;
  if (/^\d+$/.test(raw)) return raw;
  return null;
}

function folderFromRouteParams(params) {
  const folder = params.get("folder");
  return folder ? parseFolderRouteParam(folder) : null;
}

function searchSnapshotMatchesUrl(routeParams) {
  const urlSnap = snapshotFromRouteParams(routeParams);
  const domSnap = searchParamsToSnapshot(buildSearchParams());
  const keys = new Set([...Object.keys(urlSnap), ...Object.keys(domSnap)]);
  for (const k of keys) {
    if ((urlSnap[k] || "") !== (domSnap[k] || "")) return false;
  }
  return true;
}

function tabRouteAlreadyApplied(route, view) {
  if (state.activeView !== view) return false;
  if (view === "search") return searchSnapshotMatchesUrl(route.params);
  if (view === "collection") {
    return state.collectionFolder === folderFromRouteParams(route.params);
  }
  if (view === "decks") {
    if (route.deckId) {
      return state.decksDetailOpen && state.activeDeckId === route.deckId;
    }
    return !state.decksDetailOpen;
  }
  return false;
}

function buildRouteHash() {
  if (isModalVisible("#card-modal") && state.currentCardId) {
    return `#/card/${state.currentCardId}`;
  }

  let path;
  if (state.activeView === "decks" && state.decksDetailOpen && state.activeDeckId) {
    path = `/decks/${state.activeDeckId}`;
  } else {
    path = `/${state.activeView || DEFAULT_ROUTE_VIEW}`;
  }

  const params = new URLSearchParams();
  if (state.activeView === "search") {
    for (const [k, v] of buildSearchParams()) params.set(k, v);
  } else if (state.activeView === "collection" && state.collectionFolder) {
    params.set("folder", state.collectionFolder);
  }

  const qs = params.toString();
  return qs ? `#${path}?${qs}` : `#${path}`;
}

function syncRouteHash({ replace = false } = {}) {
  const hash = buildRouteHash();
  if (window.location.hash === hash) {
    lastAppliedRouteHash = hash;
    return;
  }
  suppressHashSync = true;
  if (replace) history.replaceState(null, "", hash);
  else location.hash = hash;
  lastAppliedRouteHash = hash;
  queueMicrotask(() => {
    suppressHashSync = false;
  });
}

function truncateRouteTitle(text, max = 40) {
  const s = String(text || "");
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function updateRouteDocumentTitle() {
  if (isModalVisible("#card-modal") && state.currentCard?.name) {
    document.title = `Card: ${truncateRouteTitle(state.currentCard.name)} — ${APP_TITLE_BASE}`;
    return;
  }
  if (state.activeView === "decks" && state.decksDetailOpen && state.activeDeckDetail?.name) {
    document.title = `Deck: ${truncateRouteTitle(state.activeDeckDetail.name)} — ${APP_TITLE_BASE}`;
    return;
  }
  if (state.activeView === "collection") {
    document.title = `My Collection — ${APP_TITLE_BASE}`;
    return;
  }
  if (state.activeView === "decks") {
    document.title = `Decks — ${APP_TITLE_BASE}`;
    return;
  }
  document.title = `Search — ${APP_TITLE_BASE}`;
}

async function applyRouteFromHash({ initial = false } = {}) {
  const currentHash = window.location.hash;
  if (!initial && currentHash === lastAppliedRouteHash) return;

  const route = parseRouteHash();

  if (route.kind === "card") {
    const cardId = Number(route.cardId);
    if (state.currentCardId !== cardId || !isModalVisible("#card-modal")) {
      await openCardModal(cardId, { fromRouter: true });
    }
    if (initial) syncRouteHash({ replace: true });
    lastAppliedRouteHash = window.location.hash;
    return;
  }

  if (isModalVisible("#card-modal")) {
    closeCardModalOverlay({ fromRouter: true });
  }

  const view =
    route.invalid && route.view !== "decks" ? DEFAULT_ROUTE_VIEW : route.view;

  if (!initial && tabRouteAlreadyApplied(route, view)) {
    lastAppliedRouteHash = currentHash;
    updateRouteDocumentTitle();
    return;
  }

  if (view === "collection") {
    const newFolder = folderFromRouteParams(route.params);
    if (state.collectionFolder !== newFolder) {
      state.collectionFolder = newFolder;
      state.collectionPage = 0;
    }
  }

  let needsSearchRun = false;
  if (view === "search") {
    const snapshot = snapshotFromRouteParams(route.params);
    if (Object.keys(snapshot).length) {
      applySearchParams(snapshot);
      clearActivePreset();
      needsSearchRun = true;
    }
  }

  const replaceHash = initial && (!window.location.hash || route.invalid);

  await switchView(view, { fromRouter: true, replaceHash });

  if (route.view === "decks") {
    if (!route.invalid && route.deckId) {
      if (!(state.decksDetailOpen && state.activeDeckId === route.deckId)) {
        await openDeckDetail(route.deckId, { fromRouter: true });
      }
    } else {
      closeDeckDetail({ fromRouter: true });
    }
  }

  if (view === "search" && (initial || needsSearchRun)) {
    await runSearch(null, { skipHashSync: true });
  }

  if (route.invalid || replaceHash) {
    syncRouteHash({ replace: true });
  }

  lastAppliedRouteHash = window.location.hash;
}

function conditionLabel(value) {
  if (!value) return "—";
  const match = COLLECTION_CONDITIONS.find((c) => c.value === value);
  return match ? match.label : value;
}

function conditionBadgeHtml(value) {
  if (!value) return "—";
  const match = COLLECTION_CONDITIONS.find((c) => c.value === value);
  const label = match ? match.label : value;
  const tone = match ? match.tone : "unknown";
  return `<span class="condition-badge condition-badge--${tone}">${escapeHtml(label)}</span>`;
}

async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(`${API}${path}`, { ...options, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = err.detail;
    let message = res.statusText;
    let code = null;
    if (typeof detail === "string") {
      message = detail;
    } else if (detail && typeof detail === "object") {
      message = detail.message || JSON.stringify(detail);
      code = detail.code || null;
    }
    const error = new Error(message);
    error.status = res.status;
    error.code = code;
    throw error;
  }
  if (res.status === 204) return null;
  return res.json();
}

const buttonBusyState = new WeakMap();

function showToast(message, { variant = "success", durationMs = 3200 } = {}) {
  const region = $("#toast-region");
  if (!region) return;
  const toast = document.createElement("div");
  toast.className = `toast toast--${variant}`;
  toast.textContent = message;
  region.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("is-visible"));
  const dismissMs = variant === "error" ? durationMs || 5000 : durationMs;
  window.setTimeout(() => {
    toast.classList.remove("is-visible");
    window.setTimeout(() => toast.remove(), 200);
  }, dismissMs);
}

function setButtonBusy(button, busy, { busyLabel = "Loading…" } = {}) {
  if (!button) return;
  if (busy) {
    if (!buttonBusyState.has(button)) {
      buttonBusyState.set(button, button.textContent);
    }
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.classList.add("btn-busy");
    button.innerHTML = `<span class="loading-spinner" role="status" aria-hidden="true"></span>${escapeHtml(busyLabel)}`;
  } else {
    const original = buttonBusyState.get(button);
    if (original != null) {
      button.textContent = original;
      buttonBusyState.delete(button);
    }
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.classList.remove("btn-busy");
  }
}

async function runModalAction(button, action, { busyLabel, successMessage } = {}) {
  setButtonBusy(button, true, { busyLabel });
  try {
    const result = await action();
    if (successMessage) showToast(successMessage);
    return result;
  } catch (err) {
    showToast(err.message || "Something went wrong.", { variant: "error", durationMs: 5000 });
    throw err;
  } finally {
    setButtonBusy(button, false);
  }
}

function $(sel) {
  return document.querySelector(sel);
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const PASSWORD_STRENGTH_MESSAGE =
  "Password must be at least 8 characters and include an uppercase letter, a number, and a special character.";

function validatePasswordStrength(password) {
  if (password.length < 8) {
    return PASSWORD_STRENGTH_MESSAGE;
  }
  if (!/[A-Z]/.test(password)) {
    return PASSWORD_STRENGTH_MESSAGE;
  }
  if (!/\d/.test(password)) {
    return PASSWORD_STRENGTH_MESSAGE;
  }
  if (!/[^A-Za-z0-9]/.test(password)) {
    return PASSWORD_STRENGTH_MESSAGE;
  }
  return null;
}

let authActiveTab = "login";
let authConfig = { turnstile_site_key: null };
let turnstileWidgetId = null;
let pendingVerifyEmail = null;
let resendCooldownInterval = null;

function maskEmail(email) {
  const parts = String(email || "").split("@");
  if (parts.length !== 2) return email;
  const local = parts[0];
  const domain = parts[1];
  const masked =
    local.length <= 2 ? `${local[0] || ""}***` : `${local[0]}***${local.slice(-1)}`;
  return `${masked}@${domain}`;
}

async function loadAuthConfig() {
  try {
    const res = await fetch(`${API}/auth/config`, { headers: { Accept: "application/json" } });
    if (res.ok) authConfig = await res.json();
  } catch {
    /* optional */
  }
}

function loadTurnstileScript() {
  return new Promise((resolve, reject) => {
    if (window.turnstile) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load captcha"));
    document.head.appendChild(script);
  });
}

async function ensureTurnstileWidget() {
  const container = $("#register-turnstile");
  if (!container || !authConfig.turnstile_site_key) return;
  try {
    await loadTurnstileScript();
    container.innerHTML = "";
    turnstileWidgetId = window.turnstile.render(container, {
      sitekey: authConfig.turnstile_site_key,
    });
  } catch {
    /* captcha optional for local dev */
  }
}

function resetTurnstileWidget() {
  if (window.turnstile && turnstileWidgetId != null) {
    try {
      window.turnstile.reset(turnstileWidgetId);
    } catch {
      /* ignore */
    }
  }
}

function getTurnstileToken() {
  if (!authConfig.turnstile_site_key) return null;
  if (!window.turnstile || turnstileWidgetId == null) return "";
  return window.turnstile.getResponse(turnstileWidgetId) || "";
}

function setAuthenticatedShell(visible) {
  document.querySelectorAll(".app-shell").forEach((el) => {
    el.classList.toggle("hidden", !visible);
    el.setAttribute("aria-hidden", visible ? "false" : "true");
  });
  $("#auth-landing")?.classList.toggle("hidden", visible);
}

function updateAuthLandingTitle() {
  if (authActiveTab === "verify") {
    document.title = `Verify email — ${APP_TITLE_BASE}`;
    return;
  }
  document.title =
    authActiveTab === "register"
      ? `Create account — ${APP_TITLE_BASE}`
      : `Sign in — ${APP_TITLE_BASE}`;
}

function showAuthError(message) {
  const el = $("#auth-error");
  if (!el) return;
  el.textContent = message;
  el.classList.remove("hidden");
}

function clearAuthError() {
  const el = $("#auth-error");
  if (!el) return;
  el.textContent = "";
  el.classList.add("hidden");
}

function clearAuthFieldInvalid() {
  document
    .querySelectorAll("#auth-landing input[aria-invalid]")
    .forEach((input) => input.removeAttribute("aria-invalid"));
}

function clearAuthForms() {
  $("#login-email").value = "";
  $("#login-password").value = "";
  $("#register-email").value = "";
  $("#register-password").value = "";
  clearAuthError();
  clearAuthFieldInvalid();
}

function setAuthTabsDisabled(disabled) {
  $("#auth-tab-login")?.toggleAttribute("disabled", disabled);
  $("#auth-tab-register")?.toggleAttribute("disabled", disabled);
}

function switchAuthTab(tab) {
  authActiveTab = tab;
  pendingVerifyEmail = null;
  const isLogin = tab === "login";
  const loginTab = $("#auth-tab-login");
  const registerTab = $("#auth-tab-register");
  const loginPanel = $("#auth-panel-login");
  const registerPanel = $("#auth-panel-register");
  const verifyPanel = $("#auth-panel-verify");

  $("#auth-tabs")?.classList.remove("hidden");
  verifyPanel?.classList.add("hidden");
  if (verifyPanel) verifyPanel.hidden = true;

  loginTab?.classList.toggle("active", isLogin);
  registerTab?.classList.toggle("active", !isLogin);
  loginTab?.setAttribute("aria-selected", isLogin ? "true" : "false");
  registerTab?.setAttribute("aria-selected", isLogin ? "false" : "true");
  if (loginTab) loginTab.tabIndex = isLogin ? 0 : -1;
  if (registerTab) registerTab.tabIndex = isLogin ? -1 : 0;

  loginPanel?.classList.toggle("hidden", !isLogin);
  registerPanel?.classList.toggle("hidden", isLogin);
  if (loginPanel) loginPanel.hidden = !isLogin;
  if (registerPanel) registerPanel.hidden = isLogin;

  clearAuthError();
  updateAuthLandingTitle();
  if (tab === "register") {
    ensureTurnstileWidget();
  }
}

function showVerifyPanel(email) {
  pendingVerifyEmail = email;
  authActiveTab = "verify";
  $("#auth-tabs")?.classList.add("hidden");
  $("#auth-panel-login")?.classList.add("hidden");
  $("#auth-panel-register")?.classList.add("hidden");
  $("#auth-panel-verify")?.classList.remove("hidden");
  const verifyPanel = $("#auth-panel-verify");
  if (verifyPanel) verifyPanel.hidden = false;
  const display = $("#verify-email-display");
  if (display) display.textContent = maskEmail(email);
  $("#verify-code").value = "";
  clearAuthError();
  updateAuthLandingTitle();
  startResendCooldown(60);
  requestAnimationFrame(() => $("#verify-code")?.focus());
}

function startResendCooldown(seconds) {
  const btn = $("#verify-resend-btn");
  if (!btn) return;
  if (resendCooldownInterval) window.clearInterval(resendCooldownInterval);
  let remaining = seconds;
  btn.disabled = true;
  btn.textContent = `Resend code (${remaining}s)`;
  resendCooldownInterval = window.setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      window.clearInterval(resendCooldownInterval);
      resendCooldownInterval = null;
      btn.disabled = false;
      btn.textContent = "Resend code";
      return;
    }
    btn.textContent = `Resend code (${remaining}s)`;
  }, 1000);
}

function showAuthChecking() {
  $("#auth-landing")?.classList.remove("hidden");
  $("#auth-checking")?.classList.remove("hidden");
  $("#auth-landing-body")?.classList.add("hidden");
  document.querySelectorAll(".app-shell").forEach((el) => {
    el.classList.add("hidden");
    el.setAttribute("aria-hidden", "true");
  });
  document.title = `Loading — ${APP_TITLE_BASE}`;
}

function hideAuthChecking() {
  $("#auth-checking")?.classList.add("hidden");
  $("#auth-landing-body")?.classList.remove("hidden");
}

function showAuthLanding() {
  hideAuthChecking();
  $("#auth-landing")?.classList.remove("hidden");
  updateAuthLandingTitle();
  requestAnimationFrame(() => {
    const field = authActiveTab === "register" ? $("#register-email") : $("#login-email");
    field?.focus();
  });
}

function focusAppEntry() {
  requestAnimationFrame(() => {
    const q = $("#q");
    if (q) q.focus();
    else $("#tab-search")?.focus();
  });
}

async function submitAuthForm(form, action, { busyLabel, successToast } = {}) {
  clearAuthError();
  clearAuthFieldInvalid();
  const submitBtn = form?.querySelector('button[type="submit"]');
  setAuthTabsDisabled(true);
  setButtonBusy(submitBtn, true, { busyLabel: busyLabel || "Loading…" });
  try {
    await action();
    if (successToast) showToast(successToast);
  } catch (err) {
    showAuthError(err.message || "Something went wrong.");
    showToast(err.message || "Something went wrong.", {
      variant: "error",
      durationMs: 5000,
    });
    form?.querySelector('input[type="email"]')?.setAttribute("aria-invalid", "true");
    form?.querySelector('input[type="email"]')?.focus();
    throw err;
  } finally {
    setButtonBusy(submitBtn, false);
    setAuthTabsDisabled(false);
  }
}

function updateAuthUI() {
  const loggedIn = Boolean(state.token && state.user);
  $("#auth-logout")?.classList.toggle("hidden", !loggedIn);
  $("#import-collection-btn")?.classList.toggle("hidden", !loggedIn);
  $("#export-collection-btn")?.classList.toggle("hidden", !loggedIn);
  $("#search-presets-bar")?.classList.toggle("hidden", !loggedIn);
  const userEl = $("#auth-user");
  if (loggedIn) {
    userEl.textContent = state.user.email;
    userEl.classList.remove("hidden");
  } else {
    userEl.classList.add("hidden");
  }
}

async function bootstrapAuthenticatedApp() {
  initFilterMultiWidgets();
  setupLinkMarkerGrid();
  setupSummoningSuggestions();

  await Promise.all([loadStatus(), loadFilters(), loadSearchPresets(), loadUserTags()]);
  await applyRouteFromHash({ initial: true });
}

async function login(email, password) {
  try {
    const data = await api("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    state.token = data.access_token;
    localStorage.setItem("ygo_token", state.token);
    state.user = await api("/auth/me");
    setAuthenticatedShell(true);
    updateAuthUI();
    await bootstrapAuthenticatedApp();
  } catch (err) {
    if (err.status === 403 && err.code === "email_not_verified") {
      showVerifyPanel(email);
      throw new Error("Verify your email to continue. Check your inbox for the code.");
    }
    throw err;
  }
}

async function register(email, password) {
  const passwordError = validatePasswordStrength(password);
  if (passwordError) {
    throw new Error(passwordError);
  }
  const body = { email, password };
  const turnstileToken = getTurnstileToken();
  if (authConfig.turnstile_site_key) {
    if (!turnstileToken) {
      throw new Error("Please complete the captcha.");
    }
    body.turnstile_token = turnstileToken;
  }
  const data = await api("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  resetTurnstileWidget();
  if (data.needs_verification) {
    showVerifyPanel(data.email);
    return;
  }
}

async function verifyEmail(email, code) {
  const data = await api("/auth/verify-email", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, code }),
  });
  state.token = data.access_token;
  localStorage.setItem("ygo_token", state.token);
  state.user = await api("/auth/me");
  pendingVerifyEmail = null;
  setAuthenticatedShell(true);
  updateAuthUI();
  await bootstrapAuthenticatedApp();
}

async function resendVerificationCode(email) {
  await api("/auth/resend-code", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  startResendCooldown(60);
}

function logout() {
  state.token = null;
  state.user = null;
  state.activePresetId = null;
  state.searchPresets = [];
  localStorage.removeItem("ygo_token");
  setDatalist("#tag-datalist", []);
  clearAuthForms();
  switchAuthTab("login");
  setAuthenticatedShell(false);
  showAuthLanding();
  updateAuthUI();
  renderSearchPresetSelect();
  if (location.hash !== "#/") {
    suppressHashSync = true;
    location.hash = "#/";
    suppressHashSync = false;
  }
}

async function loadStatus() {
  const status = await api("/status");
  const line = $("#status-line");
  if (!status.ready) {
    line.textContent =
      "Catalog empty — run: python -m ygo_app.jobs.import_catalog (or import_data --from-api)";
    line.style.color = "#f87171";
    return;
  }
  line.style.color = "";
  const parts = [`${status.cards.toLocaleString()} cards`];
  if (status.authenticated) {
    parts.push(
      `${status.collection_items.toLocaleString()} owned`,
      `${status.decks} decks`
    );
  } else {
    parts.push("log in for collection & decks");
  }
  line.textContent = parts.join(" · ");
  line.classList.remove("status-importing");
}

function formatEta(seconds) {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) {
    return "calculating…";
  }
  const totalSec = Math.ceil(seconds);
  if (totalSec < 60) return "<1 min remaining";
  const min = Math.ceil(totalSec / 60);
  if (min < 60) return `~${min} min remaining`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  if (remMin === 0) return `~${hr} hr remaining`;
  return `~${hr} hr ${remMin} min remaining`;
}

function setImportStatusLine(current, total, etaSeconds) {
  const line = $("#status-line");
  if (!line) return;
  line.classList.add("status-importing");
  line.style.color = "";
  const prog = $("#import-progress");
  if (!total) {
    line.textContent = "Importing collection… preparing…";
    if (prog) {
      prog.hidden = false;
      prog.removeAttribute("value");
      prog.max = 100;
    }
    return;
  }
  const pct = Math.round((current / total) * 100);
  const eta = formatEta(etaSeconds);
  line.textContent = `Importing collection… ${current.toLocaleString()} / ${total.toLocaleString()} (${pct}%) · ${eta}`;
  if (prog) {
    prog.hidden = false;
    prog.max = total;
    prog.value = current;
  }
}

function clearImportStatusLine() {
  $("#status-line")?.classList.remove("status-importing");
  const prog = $("#import-progress");
  if (prog) prog.hidden = true;
}

async function readNdjsonStream(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let lastDone = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const ev = JSON.parse(line);
      onEvent?.(ev);
      if (ev.type === "done") lastDone = ev;
      if (ev.type === "error") throw new Error(ev.detail || "Import failed");
    }
  }
  if (buffer.trim()) {
    const ev = JSON.parse(buffer);
    onEvent?.(ev);
    if (ev.type === "done") lastDone = ev;
    if (ev.type === "error") throw new Error(ev.detail || "Import failed");
  }
  return lastDone;
}

const FILTER_MULTI_SUMMARY_MAX = 28;

function getFilterMultiRoot(id) {
  const el = typeof id === "string" ? $(`#${id}`) : id;
  if (!el) return null;
  return el.classList.contains("filter-multi") ? el : el.closest(".filter-multi");
}

function getFilterMultiValues(id) {
  const root = getFilterMultiRoot(id);
  if (!root) return [];
  return Array.from(
    root.querySelectorAll('.filter-multi-panel input[type="checkbox"]:checked')
  )
    .map((cb) => cb.value)
    .filter(Boolean);
}

function updateFilterMultiSummary(root) {
  root = getFilterMultiRoot(root);
  if (!root) return;
  const summary = root.querySelector(".filter-multi-summary");
  if (!summary) return;
  const selected = getFilterMultiValues(root);
  if (selected.length === 0) {
    summary.textContent = "Any";
    return;
  }
  if (selected.length === 1) {
    summary.textContent = selected[0];
    return;
  }
  const joined = selected.join(", ");
  if (selected.length <= 3 && joined.length <= FILTER_MULTI_SUMMARY_MAX) {
    summary.textContent = joined;
    return;
  }
  summary.textContent = `${selected.length} selected`;
}

function setFilterMultiValues(id, values) {
  const root = getFilterMultiRoot(id);
  if (!root) return;
  const wanted = new Set(values);
  root
    .querySelectorAll('.filter-multi-panel input[type="checkbox"]')
    .forEach((cb) => {
      cb.checked = wanted.has(cb.value);
    });
  updateFilterMultiSummary(root);
}

function setFilterMultiOptions(id, values) {
  const root = getFilterMultiRoot(id);
  if (!root) return;
  const panel = root.querySelector(".filter-multi-panel");
  if (!panel) return;
  const selected = new Set(getFilterMultiValues(root));
  panel.innerHTML = "";
  values.forEach((v) => {
    if (!v) return;
    const label = document.createElement("label");
    label.className = "check filter-multi-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = v;
    if (selected.has(v)) input.checked = true;
    label.appendChild(input);
    label.appendChild(document.createTextNode(` ${v}`));
    panel.appendChild(label);
  });
  updateFilterMultiSummary(root);
}

function closeFilterMultiPanel(root) {
  root = getFilterMultiRoot(root);
  if (!root) return;
  const panel = root.querySelector(".filter-multi-panel");
  const trigger = root.querySelector(".filter-multi-trigger");
  if (!panel || panel.hidden) return;
  panel.hidden = true;
  root.classList.remove("is-open");
  trigger?.setAttribute("aria-expanded", "false");
  document
    .querySelector(".advanced-filters-body")
    ?.classList.remove("has-open-filter-multi");
}

function closeAllFilterMultiPanels(exceptRoot = null) {
  document.querySelectorAll(".filter-multi").forEach((r) => {
    if (exceptRoot && r === exceptRoot) return;
    closeFilterMultiPanel(r);
  });
}

function openFilterMultiPanel(root) {
  root = getFilterMultiRoot(root);
  if (!root) return;
  closeAllFilterMultiPanels(root);
  const panel = root.querySelector(".filter-multi-panel");
  const trigger = root.querySelector(".filter-multi-trigger");
  if (!panel) return;
  panel.hidden = false;
  root.classList.add("is-open");
  trigger?.setAttribute("aria-expanded", "true");
  document
    .querySelector(".advanced-filters-body")
    ?.classList.add("has-open-filter-multi");
}

function toggleFilterMultiPanel(root) {
  root = getFilterMultiRoot(root);
  if (!root) return;
  const panel = root.querySelector(".filter-multi-panel");
  if (panel?.hidden) openFilterMultiPanel(root);
  else closeFilterMultiPanel(root);
}

function initFilterMultiWidgets() {
  document.querySelectorAll(".filter-multi").forEach((root) => {
    const trigger = root.querySelector(".filter-multi-trigger");
    const panel = root.querySelector(".filter-multi-panel");
    if (!trigger || !panel) return;

    trigger.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleFilterMultiPanel(root);
    });

    panel.addEventListener("change", (e) => {
      if (e.target.matches('input[type="checkbox"]')) {
        updateFilterMultiSummary(root);
        renderActiveSearchFilters();
      }
    });

    panel.addEventListener("click", (e) => e.stopPropagation());
  });

  document.addEventListener("click", () => closeAllFilterMultiPanels());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAllFilterMultiPanels();
  });
}

function setDatalist(id, values) {
  const dl = $(id);
  if (!dl) return;
  dl.innerHTML = values
    .map((v) => `<option value="${escapeHtml(v)}"></option>`)
    .join("");
}

async function loadFilters() {
  const data = await api("/filters");
  state.filters = data;
  setFilterMultiOptions("filter-types", data.types || []);
  setFilterMultiOptions("filter-mechanic", data.mechanics || []);
  setFilterMultiOptions("filter-attribute", data.attributes || []);
  setDatalist("#archetype-datalist", data.archetypes || []);
  applyStatRangesFromFilters(data.stat_ranges || {});
}

function selectedLinkMarkers() {
  return Array.from(document.querySelectorAll(".link-marker-btn.selected"))
    .map((btn) => btn.dataset.marker)
    .filter(Boolean);
}

function appendRangeParam(params, keyMin, keyMax, minEl, maxEl) {
  const minVal = $(minEl)?.value;
  const maxVal = $(maxEl)?.value;
  if (minVal !== "" && minVal != null) params.set(keyMin, minVal);
  if (maxVal !== "" && maxVal != null) params.set(keyMax, maxVal);
}

const STAT_RANGE_DEFS = [
  { key: "level", min: "#level-min", max: "#level-max", select: true },
  { key: "rank", min: "#rank-min", max: "#rank-max", select: true },
  { key: "link_rating", min: "#link-rating-min", max: "#link-rating-max", select: true },
  {
    key: "pendulum_scale",
    min: "#pendulum-scale-min",
    max: "#pendulum-scale-max",
    select: true,
  },
  { key: "atk", min: "#atk-min", max: "#atk-max", select: false },
  { key: "def", min: "#def-min", max: "#def-max", select: false },
];

let statRangeListenersBound = false;

function clampStatFieldValue(el, bounds) {
  if (!bounds || el.value === "") return;
  const n = Number(el.value);
  if (Number.isNaN(n)) {
    el.value = "";
    return;
  }
  if (n < bounds.min) el.value = String(bounds.min);
  else if (n > bounds.max) el.value = String(bounds.max);
}

function syncFilterRangePair(minEl, maxEl, bounds, source) {
  if (bounds) {
    clampStatFieldValue(minEl, bounds);
    clampStatFieldValue(maxEl, bounds);
  }
  const minVal = minEl.value;
  const maxVal = maxEl.value;
  if (minVal === "" || maxVal === "") return;
  if (Number(minVal) > Number(maxVal)) {
    if (source === "min") maxEl.value = minVal;
    else minEl.value = maxVal;
  }
}

function populateStatRangeSelect(el, bounds) {
  const placeholder = el.querySelector('option[value=""]');
  el.innerHTML = "";
  if (placeholder) el.appendChild(placeholder);
  else {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = el.id.endsWith("-min") ? "min" : "max";
    el.appendChild(opt);
  }
  if (!bounds) return;
  for (let v = bounds.min; v <= bounds.max; v++) {
    const opt = document.createElement("option");
    opt.value = String(v);
    opt.textContent = String(v);
    el.appendChild(opt);
  }
}

function setupNumericRangeSpinFallback(el) {
  if (el.dataset.spinFallbackBound) return;
  el.dataset.spinFallbackBound = "1";
  el.addEventListener("keydown", (e) => {
    if (el.value !== "") return;
    if (el.min === "" || el.max === "") return;
    const lo = Number(el.min);
    const hi = Number(el.max);
    if (Number.isNaN(lo) || Number.isNaN(hi)) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      el.value = String(hi);
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      el.value = String(lo);
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
  });
}

function applyStatRangesFromFilters(statRanges) {
  for (const { key, min, max, select } of STAT_RANGE_DEFS) {
    const bounds = statRanges[key] || null;
    const minEl = $(min);
    const maxEl = $(max);
    if (!minEl || !maxEl) continue;

    const fieldset = minEl.closest("fieldset");
    if (fieldset) {
      fieldset.disabled = !bounds;
    }

    if (select) {
      populateStatRangeSelect(minEl, bounds);
      populateStatRangeSelect(maxEl, bounds);
    } else if (bounds) {
      minEl.min = String(bounds.min);
      minEl.max = String(bounds.max);
      maxEl.min = String(bounds.min);
      maxEl.max = String(bounds.max);
      setupNumericRangeSpinFallback(minEl);
      setupNumericRangeSpinFallback(maxEl);
    } else {
      minEl.removeAttribute("min");
      minEl.removeAttribute("max");
      maxEl.removeAttribute("min");
      maxEl.removeAttribute("max");
    }
  }

  if (statRangeListenersBound) return;
  statRangeListenersBound = true;

  for (const { key, min, max, select } of STAT_RANGE_DEFS) {
    const minEl = $(min);
    const maxEl = $(max);
    if (!minEl || !maxEl) continue;

    const getBounds = () => state.filters?.stat_ranges?.[key] || null;

    const onMinChange = () => {
      syncFilterRangePair(minEl, maxEl, getBounds(), "min");
      renderActiveSearchFilters();
    };
    const onMaxChange = () => {
      syncFilterRangePair(minEl, maxEl, getBounds(), "max");
      renderActiveSearchFilters();
    };

    minEl.addEventListener("change", onMinChange);
    maxEl.addEventListener("change", onMaxChange);
    if (!select) {
      minEl.addEventListener("input", onMinChange);
      maxEl.addEventListener("input", onMaxChange);
    }
  }
}

let summoningSuggestTimer = null;
function setupSummoningSuggestions() {
  const input = $("#filter-summoning");
  if (!input) return;
  input.addEventListener("input", () => {
    clearTimeout(summoningSuggestTimer);
    const q = input.value.trim();
    if (q.length < 2) return;
    summoningSuggestTimer = setTimeout(async () => {
      try {
        const data = await api(
          `/cards/summoning-suggestions?q=${encodeURIComponent(q)}&limit=20`
        );
        setDatalist("#summoning-datalist", data.suggestions || []);
      } catch {
        /* ignore */
      }
    }, 300);
  });
}

function setupLinkMarkerGrid() {
  document.querySelectorAll(".link-marker-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.classList.toggle("selected");
      btn.setAttribute("aria-pressed", btn.classList.contains("selected"));
      renderActiveSearchFilters();
    });
  });
}

function switchView(name, { fromRouter = false, replaceHash = false } = {}) {
  if (!ROUTE_VIEWS.has(name)) name = DEFAULT_ROUTE_VIEW;
  state.activeView = name;

  document.querySelectorAll(".view").forEach((v) => {
    const isActive = v.id === `view-${name}`;
    v.classList.toggle("active", isActive);
    v.hidden = !isActive;
  });

  let activeTab = null;
  document.querySelectorAll(".tab").forEach((t) => {
    const isActive = t.dataset.view === name;
    t.classList.toggle("active", isActive);
    t.setAttribute("aria-selected", isActive ? "true" : "false");
    t.tabIndex = isActive ? 0 : -1;
    if (isActive) activeTab = t;
  });

  if (name === "decks") {
    loadDecks({ background: true });
    if (state.decksDetailOpen) showDecksDetailView();
    else showDecksListView();
  }
  if (name === "collection") loadCollectionView({ background: true });

  updateRouteDocumentTitle();

  if (!fromRouter) {
    activeTab?.focus();
    syncRouteHash({ replace: replaceHash });
  } else if (!isModalVisible("#card-modal")) {
    activeTab?.focus();
  }
}

const SEARCH_PAGE_SIZE = 100;

async function fetchSearchPage(baseParams, offset = 0) {
  const pageParams = new URLSearchParams(baseParams);
  pageParams.set("limit", String(SEARCH_PAGE_SIZE));
  pageParams.set("offset", String(offset));
  return api(`/cards/search?${pageParams}`);
}

function resetSearchFilters() {
  const qEl = $("#q");
  if (qEl) qEl.value = "";
  const setCodeEl = $("#set-code");
  if (setCodeEl) setCodeEl.value = "";
  const ownedEl = $("#owned-only");
  if (ownedEl) ownedEl.checked = false;
  const favEl = $("#favorites-only");
  if (favEl) favEl.checked = false;
  const tagEl = $("#filter-tag");
  if (tagEl) tagEl.value = "";

  document.querySelectorAll(".filter-multi").forEach((root) => {
    root
      .querySelectorAll('.filter-multi-panel input[type="checkbox"]')
      .forEach((cb) => {
        cb.checked = false;
      });
    updateFilterMultiSummary(root);
  });

  const archetypeEl = $("#filter-archetype");
  if (archetypeEl) archetypeEl.value = "";
  const summoningEl = $("#filter-summoning");
  if (summoningEl) summoningEl.value = "";

  for (const sel of [
    "#level-min",
    "#level-max",
    "#rank-min",
    "#rank-max",
    "#link-rating-min",
    "#link-rating-max",
    "#pendulum-scale-min",
    "#pendulum-scale-max",
    "#atk-min",
    "#atk-max",
    "#def-min",
    "#def-max",
  ]) {
    const el = $(sel);
    if (el) el.value = "";
  }

  document.querySelectorAll(".link-marker-btn.selected").forEach((btn) => {
    btn.classList.remove("selected");
    btn.setAttribute("aria-pressed", "false");
  });

  closeAllFilterMultiPanels();
  renderActiveSearchFilters();
}

function removeFilterMultiValue(id, value) {
  const root = getFilterMultiRoot(id);
  if (!root) return;
  const cb = root.querySelector(
    `.filter-multi-panel input[type="checkbox"][value="${CSS.escape(value)}"]`
  );
  if (cb) {
    cb.checked = false;
    updateFilterMultiSummary(root);
  }
}

function clearFilterRange(minSel, maxSel) {
  const minEl = $(minSel);
  const maxEl = $(maxSel);
  if (minEl) minEl.value = "";
  if (maxEl) maxEl.value = "";
}

function formatFilterRangeLabel(name, minVal, maxVal) {
  if (minVal && maxVal) return `${name} ${minVal}–${maxVal}`;
  if (minVal) return `${name} ≥ ${minVal}`;
  if (maxVal) return `${name} ≤ ${maxVal}`;
  return name;
}

function collectActiveSearchFilterChips() {
  const chips = [];
  const q = $("#q")?.value.trim();
  if (q) chips.push({ id: "q", label: `Search: ${q}` });

  const setCode = $("#set-code")?.value.trim();
  if (setCode) chips.push({ id: "set_code", label: `Set: ${setCode}` });

  const tag = $("#filter-tag")?.value.trim();
  if (tag) chips.push({ id: "tag", label: `Tag: ${tag}` });

  if ($("#owned-only")?.checked) chips.push({ id: "owned_only", label: "Owned only" });
  if ($("#favorites-only")?.checked) chips.push({ id: "favorites_only", label: "Favorites" });

  for (const val of getFilterMultiValues("filter-category")) {
    chips.push({ id: `category:${val}`, label: val });
  }
  for (const val of getFilterMultiValues("filter-types")) {
    chips.push({ id: `types:${val}`, label: val });
  }
  for (const val of getFilterMultiValues("filter-mechanic")) {
    chips.push({ id: `mechanic:${val}`, label: val });
  }
  for (const val of getFilterMultiValues("filter-attribute")) {
    chips.push({ id: `attribute:${val}`, label: val });
  }

  const archetype = $("#filter-archetype")?.value.trim();
  if (archetype) chips.push({ id: "archetype", label: `Archetype: ${archetype}` });

  const summoning = $("#filter-summoning")?.value.trim();
  if (summoning) chips.push({ id: "summoning", label: `Summoning: ${summoning}` });

  for (const marker of selectedLinkMarkers()) {
    chips.push({ id: `link_marker:${marker}`, label: `Link: ${marker}` });
  }

  const rangeDefs = [
    { id: "level", name: "Level", min: "#level-min", max: "#level-max" },
    { id: "rank", name: "Rank", min: "#rank-min", max: "#rank-max" },
    { id: "link_rating", name: "Link", min: "#link-rating-min", max: "#link-rating-max" },
    {
      id: "pendulum_scale",
      name: "Pendulum",
      min: "#pendulum-scale-min",
      max: "#pendulum-scale-max",
    },
    { id: "atk", name: "ATK", min: "#atk-min", max: "#atk-max" },
    { id: "def", name: "DEF", min: "#def-min", max: "#def-max" },
  ];
  for (const { id, name, min, max } of rangeDefs) {
    const minVal = $(min)?.value;
    const maxVal = $(max)?.value;
    if (minVal || maxVal) {
      chips.push({ id, label: formatFilterRangeLabel(name, minVal, maxVal) });
    }
  }
  return chips;
}

const PRIMARY_SEARCH_FILTER_IDS = new Set([
  "q",
  "set_code",
  "tag",
  "owned_only",
  "favorites_only",
]);

function hasAdvancedSearchFilters() {
  return collectActiveSearchFilterChips().some((chip) => !PRIMARY_SEARCH_FILTER_IDS.has(chip.id));
}

function syncAdvancedFiltersOpen() {
  const details = $("#advanced-filters");
  if (details && hasAdvancedSearchFilters()) details.open = true;
}

function countAdvancedSearchFilters() {
  return collectActiveSearchFilterChips().filter(
    (chip) => !PRIMARY_SEARCH_FILTER_IDS.has(chip.id)
  ).length;
}

function syncAdvancedFiltersSummary() {
  const badge = $("#advanced-filters-count");
  if (!badge) return;
  const count = countAdvancedSearchFilters();
  if (count > 0) {
    badge.textContent = `· ${count}`;
    badge.classList.remove("hidden");
  } else {
    badge.textContent = "";
    badge.classList.add("hidden");
  }
}

function removeSearchFilterChip(chipId) {
  if (chipId === "q") $("#q").value = "";
  else if (chipId === "set_code") $("#set-code").value = "";
  else if (chipId === "tag") $("#filter-tag").value = "";
  else if (chipId === "owned_only") $("#owned-only").checked = false;
  else if (chipId === "favorites_only") $("#favorites-only").checked = false;
  else if (chipId === "archetype") $("#filter-archetype").value = "";
  else if (chipId === "summoning") $("#filter-summoning").value = "";
  else if (chipId.startsWith("category:")) {
    removeFilterMultiValue("filter-category", chipId.slice("category:".length));
  } else if (chipId.startsWith("types:")) {
    removeFilterMultiValue("filter-types", chipId.slice("types:".length));
  } else if (chipId.startsWith("mechanic:")) {
    removeFilterMultiValue("filter-mechanic", chipId.slice("mechanic:".length));
  } else if (chipId.startsWith("attribute:")) {
    removeFilterMultiValue("filter-attribute", chipId.slice("attribute:".length));
  } else if (chipId.startsWith("link_marker:")) {
    const marker = chipId.slice("link_marker:".length);
    const btn = document.querySelector(`.link-marker-btn[data-marker="${marker}"]`);
    if (btn) {
      btn.classList.remove("selected");
      btn.setAttribute("aria-pressed", "false");
    }
  } else if (chipId === "level") clearFilterRange("#level-min", "#level-max");
  else if (chipId === "rank") clearFilterRange("#rank-min", "#rank-max");
  else if (chipId === "link_rating") clearFilterRange("#link-rating-min", "#link-rating-max");
  else if (chipId === "pendulum_scale") {
    clearFilterRange("#pendulum-scale-min", "#pendulum-scale-max");
  } else if (chipId === "atk") clearFilterRange("#atk-min", "#atk-max");
  else if (chipId === "def") clearFilterRange("#def-min", "#def-max");
}

function renderActiveSearchFilters() {
  const bar = $("#search-active-filters");
  const container = $("#search-active-filters-chips");
  if (!bar || !container) return;

  const chips = collectActiveSearchFilterChips();
  if (!chips.length) {
    bar.classList.add("hidden");
    container.innerHTML = "";
    syncAdvancedFiltersSummary();
    return;
  }

  bar.classList.remove("hidden");
  container.innerHTML = chips
    .map(
      (chip) => `
    <span class="search-filter-chip">
      <span>${escapeHtml(chip.label)}</span>
      <button type="button" class="search-filter-chip-remove" data-chip-id="${escapeHtml(chip.id)}" aria-label="Remove ${escapeHtml(chip.label)}">×</button>
    </span>`
    )
    .join("");

  syncAdvancedFiltersOpen();
  syncAdvancedFiltersSummary();
}

function setupSearchFilterChipDelegation() {
  const container = $("#search-active-filters-chips");
  if (!container || container.dataset.delegationBound) return;
  container.dataset.delegationBound = "1";
  container.addEventListener("click", async (e) => {
    const btn = e.target.closest(".search-filter-chip-remove");
    if (!btn?.dataset.chipId) return;
    removeSearchFilterChip(btn.dataset.chipId);
    renderActiveSearchFilters();
    await runSearch();
  });
}

function renderSearchResultsSummary({ loading = false } = {}) {
  const el = $("#search-results-summary");
  if (!el) return;
  if (loading) {
    el.textContent = "Searching…";
    el.classList.remove("hidden");
    return;
  }
  const total = state.searchTotal;
  if (total == null) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  const cardWord = total === 1 ? "card" : "cards";
  el.textContent = `${total.toLocaleString()} ${cardWord}`;
  el.classList.remove("hidden");
}

function closePresetMenu() {
  const menu = $("#search-preset-menu");
  const btn = $("#search-preset-menu-btn");
  if (!menu || menu.hidden) return;
  menu.hidden = true;
  btn?.setAttribute("aria-expanded", "false");
}

function togglePresetMenu() {
  const menu = $("#search-preset-menu");
  const btn = $("#search-preset-menu-btn");
  if (!menu || !btn) return;
  if (!menu.hidden) {
    closePresetMenu();
    return;
  }
  menu.hidden = false;
  btn.setAttribute("aria-expanded", "true");
}

function closeAllCollectionRowMenus() {
  document.querySelectorAll(".collection-row-menu").forEach((menu) => {
    if (menu.hidden) return;
    menu.hidden = true;
    menu.classList.remove("collection-row-menu--fixed");
    menu.style.top = "";
    menu.style.left = "";
    menu.style.width = "";
  });
  document.querySelectorAll(".collection-row-menu-btn").forEach((btn) => {
    btn.setAttribute("aria-expanded", "false");
  });
}

function openCollectionRowMenu(btn) {
  const wrap = btn.closest(".collection-row-menu-wrap");
  const menu = wrap?.querySelector(".collection-row-menu");
  if (!menu) return;
  closeAllCollectionRowMenus();
  menu.hidden = false;
  btn.setAttribute("aria-expanded", "true");
  menu.classList.add("collection-row-menu--fixed");
  const rect = btn.getBoundingClientRect();
  const menuWidth = menu.offsetWidth;
  const left = Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 8);
  menu.style.top = `${rect.bottom + 4}px`;
  menu.style.left = `${Math.max(8, left)}px`;
}

function toggleCollectionRowMenu(btn) {
  const wrap = btn.closest(".collection-row-menu-wrap");
  const menu = wrap?.querySelector(".collection-row-menu");
  if (!menu) return;
  if (!menu.hidden) {
    closeAllCollectionRowMenus();
    return;
  }
  openCollectionRowMenu(btn);
}

function buildSearchParams() {
  const params = new URLSearchParams();
  const q = $("#q").value.trim();
  const setCode = $("#set-code").value.trim();
  if (q) params.set("q", q);
  if (setCode) params.set("set_code", setCode);

  const categories = getFilterMultiValues("filter-category");
  if (categories.length) params.set("category", categories.join(","));

  const types = getFilterMultiValues("filter-types");
  if (types.length) params.set("types", types.join(","));

  const mechanics = getFilterMultiValues("filter-mechanic");
  if (mechanics.length) params.set("mechanic", mechanics.join(","));

  const attrs = getFilterMultiValues("filter-attribute");
  if (attrs.length) params.set("attribute", attrs.join(","));

  const archetype = $("#filter-archetype")?.value.trim();
  if (archetype) params.set("archetype", archetype);

  const summoning = $("#filter-summoning")?.value.trim();
  if (summoning) params.set("summoning_condition", summoning);

  const markers = selectedLinkMarkers();
  if (markers.length) params.set("link_markers", markers.join(","));

  appendRangeParam(params, "level_min", "level_max", "#level-min", "#level-max");
  appendRangeParam(params, "rank_min", "rank_max", "#rank-min", "#rank-max");
  appendRangeParam(
    params,
    "link_rating_min",
    "link_rating_max",
    "#link-rating-min",
    "#link-rating-max"
  );
  appendRangeParam(
    params,
    "pendulum_scale_min",
    "pendulum_scale_max",
    "#pendulum-scale-min",
    "#pendulum-scale-max"
  );
  appendRangeParam(params, "atk_min", "atk_max", "#atk-min", "#atk-max");
  appendRangeParam(params, "def_min", "def_max", "#def-min", "#def-max");

  if ($("#owned-only").checked) params.set("owned_only", "true");
  if ($("#favorites-only").checked) params.set("favorites_only", "true");
  const tag = $("#filter-tag")?.value.trim();
  if (tag) params.set("tag", tag);
  return params;
}

function searchParamsToSnapshot(params) {
  const snapshot = {};
  for (const [key, value] of params.entries()) snapshot[key] = value;
  return snapshot;
}

function applySearchParams(snapshot) {
  resetSearchFilters();
  const s = snapshot || {};

  if (s.q) $("#q").value = s.q;
  if (s.set_code) $("#set-code").value = s.set_code;

  if (s.category) setFilterMultiValues("filter-category", s.category.split(","));
  if (s.types) setFilterMultiValues("filter-types", s.types.split(","));
  if (s.mechanic) setFilterMultiValues("filter-mechanic", s.mechanic.split(","));
  if (s.attribute) setFilterMultiValues("filter-attribute", s.attribute.split(","));

  if (s.archetype) {
    const el = $("#filter-archetype");
    if (el) el.value = s.archetype;
  }
  if (s.summoning_condition) {
    const el = $("#filter-summoning");
    if (el) el.value = s.summoning_condition;
  }

  if (s.link_markers) {
    const markers = new Set(s.link_markers.split(",").filter(Boolean));
    document.querySelectorAll(".link-marker-btn").forEach((btn) => {
      if (markers.has(btn.dataset.marker)) {
        btn.classList.add("selected");
        btn.setAttribute("aria-pressed", "true");
      }
    });
  }

  const rangeMap = [
    ["level_min", "#level-min"],
    ["level_max", "#level-max"],
    ["rank_min", "#rank-min"],
    ["rank_max", "#rank-max"],
    ["link_rating_min", "#link-rating-min"],
    ["link_rating_max", "#link-rating-max"],
    ["pendulum_scale_min", "#pendulum-scale-min"],
    ["pendulum_scale_max", "#pendulum-scale-max"],
    ["atk_min", "#atk-min"],
    ["atk_max", "#atk-max"],
    ["def_min", "#def-min"],
    ["def_max", "#def-max"],
  ];
  for (const [key, sel] of rangeMap) {
    if (s[key]) {
      const el = $(sel);
      if (el) el.value = s[key];
    }
  }

  if (s.owned_only === "true") $("#owned-only").checked = true;
  if (s.favorites_only === "true") $("#favorites-only").checked = true;
  if (s.tag) {
    const el = $("#filter-tag");
    if (el) el.value = s.tag;
  }
  renderActiveSearchFilters();
}

function clearActivePreset() {
  state.activePresetId = null;
  const select = $("#search-preset-select");
  if (select) select.value = "";
}

function renderSearchPresetSelect() {
  const select = $("#search-preset-select");
  if (!select) return;
  const activeId = state.activePresetId;
  select.innerHTML =
    '<option value="">— None —</option>' +
    state.searchPresets
      .map(
        (p) =>
          `<option value="${p.id}"${p.id === activeId ? " selected" : ""}>${escapeHtml(p.name)}</option>`
      )
      .join("");
}

async function loadSearchPresets() {
  if (!state.token) {
    state.searchPresets = [];
    state.activePresetId = null;
    renderSearchPresetSelect();
    return;
  }
  try {
    state.searchPresets = await api("/search-presets");
    if (
      state.activePresetId &&
      !state.searchPresets.some((p) => p.id === state.activePresetId)
    ) {
      state.activePresetId = null;
    }
    renderSearchPresetSelect();
  } catch {
    state.searchPresets = [];
    renderSearchPresetSelect();
  }
}

async function loadUserTags() {
  if (!state.token) {
    setDatalist("#tag-datalist", []);
    return;
  }
  try {
    const data = await api("/cards/tags");
    setDatalist("#tag-datalist", data.tags || []);
  } catch {
    setDatalist("#tag-datalist", []);
  }
}

async function loadSearchPresetById(presetId) {
  const preset = state.searchPresets.find((p) => p.id === presetId);
  if (!preset) return;
  applySearchParams(preset.params);
  state.activePresetId = preset.id;
  renderSearchPresetSelect();
  await runSearch();
}

function currentSearchSnapshot() {
  return searchParamsToSnapshot(buildSearchParams());
}

let presetSaveChoiceResolve = null;
let presetSaveChoiceTrigger = null;

function closeSearchPresetSaveModal(choice = null) {
  const dlg = $("#search-preset-save-modal");
  if (!dlg || dlg.hidden) {
    if (presetSaveChoiceResolve) {
      const resolve = presetSaveChoiceResolve;
      presetSaveChoiceResolve = null;
      resolve(choice);
    }
    return;
  }
  dlg.hidden = true;
  syncModalOpenClass();
  (presetSaveChoiceTrigger ?? $("#search-preset-save"))?.focus();
  presetSaveChoiceTrigger = null;
  if (presetSaveChoiceResolve) {
    const resolve = presetSaveChoiceResolve;
    presetSaveChoiceResolve = null;
    resolve(choice);
  }
}

function promptPresetSaveChoice(presetName) {
  const dlg = $("#search-preset-save-modal");
  if (!dlg) return Promise.resolve(null);
  return new Promise((resolve) => {
    presetSaveChoiceResolve = resolve;
    presetSaveChoiceTrigger = $("#search-preset-save");
    const titleEl = $("#search-preset-save-title");
    if (titleEl) {
      titleEl.textContent = `Update "${presetName}" or save as a new preset?`;
    }
    dlg.hidden = false;
    syncModalOpenClass();
    $("#search-preset-save-overwrite")?.focus();
  });
}

async function finishPresetSave(preset) {
  state.activePresetId = preset.id;
  await loadSearchPresets();
  renderSearchPresetSelect();
  $("#search-preset-select").value = String(preset.id);
  showToast("Preset saved.");
}

async function patchActiveSearchPreset(snapshot) {
  const preset = await api(`/search-presets/${state.activePresetId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ params: snapshot }),
  });
  await finishPresetSave(preset);
}

async function createSearchPresetByName(snapshot, name) {
  try {
    const preset = await api("/search-presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, params: snapshot }),
    });
    await finishPresetSave(preset);
  } catch (err) {
    if (err.status !== 409) {
      showToast(err.message, { variant: "error", durationMs: 5000 });
      return;
    }
    if (!confirm(`A preset named "${name}" already exists. Overwrite it?`)) {
      return;
    }
    const preset = await api("/search-presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, params: snapshot, overwrite: true }),
    });
    await finishPresetSave(preset);
  }
}

async function saveSearchPreset() {
  if (!state.token) {
    showToast("Log in to save presets.", { variant: "error" });
    return;
  }

  const snapshot = currentSearchSnapshot();

  if (state.activePresetId) {
    const current = state.searchPresets.find((p) => p.id === state.activePresetId);
    const choice = await promptPresetSaveChoice(current?.name || "preset");
    if (!choice) return;
    if (choice === "overwrite") {
      await patchActiveSearchPreset(snapshot);
      return;
    }
    const name = prompt("Preset name:");
    if (!name?.trim()) return;
    await createSearchPresetByName(snapshot, name.trim());
    return;
  }

  const name = prompt("Preset name:");
  if (!name?.trim()) return;
  await createSearchPresetByName(snapshot, name.trim());
}

async function renameSearchPreset() {
  if (!state.token) {
    showToast("Log in to rename presets.", { variant: "error" });
    return;
  }
  const presetId = Number($("#search-preset-select")?.value);
  if (!presetId) {
    showToast("Select a preset to rename.", { variant: "error" });
    return;
  }
  const current = state.searchPresets.find((p) => p.id === presetId);
  const newName = prompt("New preset name:", current?.name || "");
  if (!newName?.trim() || newName.trim() === current?.name) return;

  try {
    const preset = await api(`/search-presets/${presetId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName.trim() }),
    });
    state.activePresetId = preset.id;
    await loadSearchPresets();
    renderSearchPresetSelect();
    $("#search-preset-select").value = String(preset.id);
    showToast("Preset renamed.");
  } catch (err) {
    showToast(
      err.status === 409 ? "That name is already in use." : err.message,
      { variant: "error", durationMs: 5000 }
    );
  }
}

async function deleteSearchPreset() {
  if (!state.token) {
    showToast("Log in to delete presets.", { variant: "error" });
    return;
  }
  const presetId = Number($("#search-preset-select")?.value);
  if (!presetId) {
    showToast("Select a preset to delete.", { variant: "error" });
    return;
  }
  const current = state.searchPresets.find((p) => p.id === presetId);
  if (!confirm(`Delete preset "${current?.name || presetId}"?`)) return;

  await api(`/search-presets/${presetId}`, { method: "DELETE" });
  if (state.activePresetId === presetId) state.activePresetId = null;
  await loadSearchPresets();
  showToast("Preset deleted.");
}

function renderSearchPagination() {
  const bar = $("#search-pagination");
  if (!bar) return;
  const total = state.searchTotal;
  const totalPages = Math.max(1, Math.ceil(total / SEARCH_PAGE_SIZE));
  const page = state.searchPage;

  if (totalPages <= 1) {
    bar.classList.add("hidden");
    bar.innerHTML = "";
    return;
  }

  bar.classList.remove("hidden");
  bar.innerHTML = `
    <button type="button" id="search-prev" class="secondary"${page === 0 ? " disabled" : ""}>← Previous</button>
    <span class="search-page-info">Page ${page + 1} of ${totalPages}</span>
    <button type="button" id="search-next" class="secondary"${page >= totalPages - 1 ? " disabled" : ""}>Next →</button>`;

  $("#search-prev")?.addEventListener("click", () => {
    if (state.searchPage > 0) loadSearchPage(state.searchPage - 1);
  });
  $("#search-next")?.addEventListener("click", () => {
    const lastPage = Math.ceil(state.searchTotal / SEARCH_PAGE_SIZE) - 1;
    if (state.searchPage < lastPage) loadSearchPage(state.searchPage + 1);
  });
}

function renderSearchResults(cards) {
  const grid = $("#search-results");
  if (!cards.length) {
    grid.innerHTML = '<p class="empty-msg">No cards found.</p>';
    $("#search-pagination")?.classList.add("hidden");
    state.searchResultsById = {};
    renderSearchResultsSummary();
    return;
  }
  state.searchResultsById = {};
  for (const c of cards) {
    state.searchResultsById[c.id] = c;
  }
  grid.innerHTML = cards
      .map(
        (c) => `
      <article class="card-tile ${c.owned ? "owned" : ""}" data-id="${c.id}">
        ${c.owned ? `<span class="badge badge-owned">×${c.owned_quantity}</span>` : ""}
        ${c.trade_quantity > 0 ? `<span class="badge badge-trade">×${c.trade_quantity}</span>` : ""}
        ${cardImgTag(c.image_url_small)}
        <div class="info">
          <div class="name">${escapeHtml(c.name)}</div>
          <div class="muted">${escapeHtml(c.type || "")}</div>
        </div>
      </article>`
      )
      .join("");
  renderSearchResultsSummary();
}

function setupSearchResultsDelegation() {
  const grid = $("#search-results");
  if (!grid || grid.dataset.delegationBound) return;
  grid.dataset.delegationBound = "1";
  grid.addEventListener("click", (e) => {
    const tile = e.target.closest(".card-tile");
    if (!tile?.dataset.id) return;
    openCardModal(Number(tile.dataset.id));
  });
}

async function loadSearchPage(pageIndex) {
  const seq = ++searchRequestSeq;
  state.searchPage = pageIndex;
  const offset = pageIndex * SEARCH_PAGE_SIZE;
  const grid = $("#search-results");
  grid.innerHTML = '<p class="empty-msg">Searching…</p>';
  $("#search-pagination")?.classList.add("hidden");
  renderSearchResultsSummary({ loading: true });

  try {
    const page = await fetchSearchPage(state.searchParams, offset);
    if (seq !== searchRequestSeq) return;
    state.searchTotal = page.total;
    renderSearchResults(page.items);
    renderSearchPagination();
    renderActiveSearchFilters();
    $("#search-pagination")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    if (seq !== searchRequestSeq) return;
    grid.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
    state.searchTotal = null;
    renderSearchResultsSummary();
  }
}

async function runSearch(e, { skipHashSync = false } = {}) {
  e?.preventDefault?.();
  state.searchParams = buildSearchParams();
  state.searchPage = 0;
  await loadSearchPage(0);
  if (state.activeView === "search" && !skipHashSync) syncRouteHash();
}

const MODAL_TEXT = "#e8eef7";
const MODAL_MUTED = "#94a3b8";

function isPrintingQtyBadgeElement(el) {
  return (
    el.classList.contains("printing-qty-badges") ||
    el.classList.contains("printing-owned-qty") ||
    el.classList.contains("printing-trade-qty") ||
    el.classList.contains("badge-owned") ||
    el.classList.contains("badge-trade")
  );
}

function applyModalReadableColors() {
  const dlg = $("#card-modal");
  const card = dlg?.querySelector(".modal-card");
  if (!card) return;
  card.style.color = MODAL_TEXT;
  const setLight = (el, color) => el?.style.setProperty("color", color, "important");
  dlg.querySelectorAll(
    ".modal-info h2, .modal-info h3, .modal-info p, .modal-info label, #modal-desc, .printings-list, .printing-row, .printing-row span, .tag"
  ).forEach((el) => {
    if (el.classList.contains("set-code") || isPrintingQtyBadgeElement(el)) return;
    setLight(el, MODAL_TEXT);
  });
  setLight($("#modal-name"), MODAL_TEXT);
  setLight($("#modal-desc"), MODAL_TEXT);
  dlg.querySelectorAll(".modal-info h3").forEach((el) => setLight(el, MODAL_TEXT));
  setLight($("#modal-meta"), MODAL_MUTED);
  setLight($("#modal-passcode"), MODAL_MUTED);
  dlg.querySelectorAll(".printing-row .set-code").forEach((el) => setLight(el, "#d4a017"));
}

function openCardModalOverlay() {
  const dlg = $("#card-modal");
  dlg.hidden = false;
  syncModalOpenClass();
  applyModalReadableColors();
}

function closeCardModalOverlay({ fromRouter = false } = {}) {
  closeCardErrataModal();
  closeCardTipsModal();
  closeAddCollectionModal();
  addCollectionSelectedPrintingKey = null;
  const dlg = $("#card-modal");
  dlg.hidden = true;
  state.currentCardId = null;
  state.currentCard = null;
  const tagInput = $("#tag-input");
  if (tagInput) tagInput.value = "";
  syncModalOpenClass();
  updateRouteDocumentTitle();
  if (fromRouter) return;
  const routeKind = parseRouteHash().kind;
  if (routeKind === "card") {
    if (window.history.length > 1) {
      history.back();
    } else {
      syncRouteHash({ replace: true });
    }
  }
}

function isModalVisible(id) {
  const el = $(id);
  return el && !el.hidden;
}

function syncModalOpenClass() {
  if (
    isModalVisible("#card-modal") ||
    isModalVisible("#card-errata-modal") ||
    isModalVisible("#card-tips-modal") ||
    isModalVisible("#search-help-modal") ||
    isModalVisible("#export-collection-modal") ||
    isModalVisible("#search-preset-save-modal") ||
    isModalVisible("#collection-add-modal") ||
    isModalVisible("#collection-edit-modal")
  ) {
    document.body.classList.add("modal-open");
  } else {
    document.body.classList.remove("modal-open");
  }
}

let searchHelpTrigger = null;
let searchHelpContentRendered = false;
let searchHelpOutsideHandler = null;
let searchHelpRepositionHandler = null;

const SEARCH_HELP_DESKTOP_MQ = "(min-width: 800px)";

const SEARCH_SYNTAX_ROWS = [
  { example: "reveal", description: "Anywhere in name, description, or archetype" },
  { example: '"You can reveal"', description: "Exact phrase (words adjacent)" },
  { example: "reveal hand", description: "Both terms (AND)" },
  { example: "reveal OR hand", description: "Either term" },
  { example: "reveal -hand", description: "Include first term, exclude second" },
  {
    example: "reveal NOT hand",
    description: "Include first term, exclude second (alternate)",
  },
  {
    example: "millenn?um",
    description: "<code>?</code> matches one character",
    descriptionIsHtml: true,
  },
  {
    example: "reveal*",
    description: "<code>*</code> matches any characters",
    descriptionIsHtml: true,
  },
  { example: "12345678", description: "Passcode (digits only)" },
];

function prefersSearchHelpPopover() {
  return window.matchMedia(SEARCH_HELP_DESKTOP_MQ).matches;
}

function isSearchHelpPopoverOpen() {
  const popover = $("#search-help-popover");
  return popover && !popover.hidden;
}

function searchHelpDismissButtonHtml() {
  return `<button type="button" class="search-help-dismiss" aria-label="Close">
      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M18 6 6 18" />
        <path d="m6 6 12 12" />
      </svg>
    </button>`;
}

function renderSearchHelpContent(container, titleId) {
  if (!container) return;
  const rows = SEARCH_SYNTAX_ROWS.map(
    (row) => `
    <tr>
      <td class="search-help-example" data-example="${escapeHtml(row.example)}" tabindex="0" role="button" title="Use this example">
        <code>${escapeHtml(row.example)}</code>
      </td>
      <td>${row.descriptionIsHtml ? row.description : escapeHtml(row.description)}</td>
    </tr>`
  ).join("");

  container.innerHTML = `
    <div class="search-help-shell">
      <div class="search-help-topbar">
        <header class="search-help-header">
          <h2 id="${escapeHtml(titleId)}">Search syntax</h2>
          <p class="muted">Search name, description, and archetype. Not case-sensitive.</p>
        </header>
        ${searchHelpDismissButtonHtml()}
      </div>
      <div class="search-help-table-wrap">
        <table class="search-help-table">
          <thead>
            <tr>
              <th scope="col">Example</th>
              <th scope="col">Description</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <p class="search-help-footnote">Click an example to insert it, then press Enter or Search to run.</p>
    </div>`;

  if (!container.dataset.examplesBound) {
    container.dataset.examplesBound = "1";
    container.addEventListener("click", (e) => {
      if (e.target.closest(".search-help-dismiss")) {
        closeSearchHelp();
        return;
      }
      const cell = e.target.closest(".search-help-example");
      if (!cell?.dataset.example) return;
      insertSearchExample(cell.dataset.example);
    });
    container.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const cell = e.target.closest(".search-help-example");
      if (!cell?.dataset.example) return;
      e.preventDefault();
      insertSearchExample(cell.dataset.example);
    });
  }
}

function ensureSearchHelpContent() {
  if (searchHelpContentRendered) return;
  renderSearchHelpContent($("#search-help-modal-body"), "search-help-title");
  renderSearchHelpContent($("#search-help-popover-body"), "search-help-popover-title");
  searchHelpContentRendered = true;
}

function insertSearchExample(example) {
  const q = $("#q");
  if (!q || !example) return;
  q.value = example;
  closeSearchHelp();
  q.focus();
  renderActiveSearchFilters();
}

function positionSearchHelpPopover() {
  const popover = $("#search-help-popover");
  const anchor = document.querySelector(".search-field--grow");
  if (!popover || popover.hidden || !anchor) return;

  const rect = anchor.getBoundingClientRect();
  const width = Math.min(480, Math.max(rect.width, 320));

  popover.style.width = `${width}px`;
  popover.style.top = `${rect.bottom + 6}px`;
  popover.style.left = `${Math.max(8, rect.left)}px`;
}

function attachSearchHelpPopoverListeners() {
  if (searchHelpOutsideHandler) return;

  searchHelpOutsideHandler = (e) => {
    if (!isSearchHelpPopoverOpen()) return;
    if (
      e.target.closest("#search-help-popover") ||
      e.target.closest("#search-help-btn")
    ) {
      return;
    }
    closeSearchHelp();
  };

  searchHelpRepositionHandler = () => {
    if (isSearchHelpPopoverOpen()) positionSearchHelpPopover();
  };

  document.addEventListener("click", searchHelpOutsideHandler);
  window.addEventListener("resize", searchHelpRepositionHandler);
  window.addEventListener("scroll", searchHelpRepositionHandler, true);
}

function detachSearchHelpPopoverListeners() {
  if (searchHelpOutsideHandler) {
    document.removeEventListener("click", searchHelpOutsideHandler);
    searchHelpOutsideHandler = null;
  }
  if (searchHelpRepositionHandler) {
    window.removeEventListener("resize", searchHelpRepositionHandler);
    window.removeEventListener("scroll", searchHelpRepositionHandler, true);
    searchHelpRepositionHandler = null;
  }
}

function openSearchHelpModal() {
  const dlg = $("#search-help-modal");
  const trigger = $("#search-help-btn");
  if (!dlg) return;
  ensureSearchHelpContent();
  searchHelpTrigger = trigger;
  dlg.hidden = false;
  trigger?.setAttribute("aria-expanded", "true");
  trigger?.setAttribute("aria-controls", "search-help-modal");
  syncModalOpenClass();
  $("#search-help-modal-body")?.querySelector(".search-help-dismiss")?.focus();
}

function closeSearchHelpModal({ silent = false } = {}) {
  const dlg = $("#search-help-modal");
  if (!dlg || dlg.hidden) return;
  dlg.hidden = true;
  syncModalOpenClass();
  if (!silent) {
    $("#search-help-btn")?.setAttribute("aria-expanded", "false");
    (searchHelpTrigger ?? $("#search-help-btn"))?.focus();
    searchHelpTrigger = null;
  }
}

function openSearchHelpPopover() {
  const popover = $("#search-help-popover");
  const trigger = $("#search-help-btn");
  if (!popover) return;
  ensureSearchHelpContent();
  searchHelpTrigger = trigger;
  popover.hidden = false;
  trigger?.setAttribute("aria-expanded", "true");
  trigger?.setAttribute("aria-controls", "search-help-popover");
  positionSearchHelpPopover();
  attachSearchHelpPopoverListeners();
  $("#search-help-popover-body")?.querySelector(".search-help-dismiss")?.focus();
}

function closeSearchHelpPopover({ silent = false } = {}) {
  const popover = $("#search-help-popover");
  if (!popover || popover.hidden) return;
  popover.hidden = true;
  detachSearchHelpPopoverListeners();
  if (!silent) {
    $("#search-help-btn")?.setAttribute("aria-expanded", "false");
    (searchHelpTrigger ?? $("#search-help-btn"))?.focus();
    searchHelpTrigger = null;
  }
}

function openSearchHelp() {
  if (prefersSearchHelpPopover()) {
    closeSearchHelpModal({ silent: true });
    if (isSearchHelpPopoverOpen()) {
      closeSearchHelpPopover();
      return;
    }
    openSearchHelpPopover();
    return;
  }
  closeSearchHelpPopover({ silent: true });
  if (isModalVisible("#search-help-modal")) {
    closeSearchHelpModal();
    return;
  }
  openSearchHelpModal();
}

function closeSearchHelp() {
  const wasOpen =
    isSearchHelpPopoverOpen() || isModalVisible("#search-help-modal");
  closeSearchHelpPopover({ silent: true });
  closeSearchHelpModal({ silent: true });
  $("#search-help-btn")?.setAttribute("aria-expanded", "false");
  if (wasOpen) (searchHelpTrigger ?? $("#search-help-btn"))?.focus();
  searchHelpTrigger = null;
}

function isSearchHelpOpen() {
  return isSearchHelpPopoverOpen() || isModalVisible("#search-help-modal");
}

let modalImageToken = 0;

function beginModalImagePending() {
  modalImageToken += 1;
  const token = modalImageToken;
  const slot = $("#modal-image-slot");
  const loading = $("#modal-image-loading");
  const img = $("#modal-image");
  if (!slot || !loading || !img) return token;

  img.removeAttribute("src");
  img.alt = "";
  img.onload = null;
  img.onerror = null;
  slot.classList.add("is-loading");
  loading.hidden = false;
  slot.setAttribute("aria-busy", "true");
  return token;
}

function finishModalImage(token) {
  if (token !== modalImageToken) return;
  const slot = $("#modal-image-slot");
  const loading = $("#modal-image-loading");
  if (!slot || !loading) return;
  slot.classList.remove("is-loading");
  loading.hidden = true;
  slot.setAttribute("aria-busy", "false");
}

function setModalImage(url, alt, token) {
  const img = $("#modal-image");
  if (!img || token !== modalImageToken) return;

  const src = url || IMG_PLACEHOLDER;

  img.alt = alt || "";
  img.onload = () => {
    img.onload = null;
    finishModalImage(token);
  };
  img.onerror = () => {
    img.onerror = null;
    img.src = IMG_PLACEHOLDER;
    finishModalImage(token);
  };
  img.src = src;

  if (img.complete && img.naturalWidth > 0) {
    img.onload = null;
    finishModalImage(token);
  }
}

function cardTypesList(card) {
  return Array.isArray(card?.types) ? card.types : [];
}

function formatCardTypeline(card) {
  const types = cardTypesList(card);
  const category = card?.category || null;

  const typesLabel = types.length ? types.join(" / ") : null;
  const categoryRedundant = category && types.length === 1 && types[0] === category;

  const parts = [];
  if (category && !categoryRedundant) parts.push(category);
  if (typesLabel && !(categoryRedundant && typesLabel === category)) parts.push(typesLabel);

  if (!parts.length && card?.type) parts.push(card.type);

  return parts.join(" · ");
}

function formatMechanicLabel(mechanic, types) {
  if (!mechanic) return null;
  const remaining = mechanic
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .filter((part) => !types.includes(part));
  return remaining.length ? remaining.join(", ") : null;
}

function formatModalStats(card) {
  const types = cardTypesList(card);
  const typeline = formatCardTypeline(card);

  return [
    typeline || null,
    card.attribute,
    card.level != null ? `Level ${card.level}` : null,
    card.rank != null ? `Rank ${card.rank}` : null,
    card.link_rating != null ? `Link-${card.link_rating}` : null,
    card.pendulum_scale != null ? `Scale ${card.pendulum_scale}` : null,
    formatMechanicLabel(card.mechanic, types),
    card.archetype,
    card.atk != null ? `ATK ${card.atk}` : null,
    card.def != null ? `DEF ${card.def}` : null,
    (card.link_markers || []).length ? `Markers: ${card.link_markers.join(", ")}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

function findModalSeed(cardId) {
  if (state.decksDetailOpen && state.activeDeckDetail?.cards) {
    const deckCard = state.activeDeckDetail.cards.find((c) => c.card_id === cardId);
    if (deckCard) {
      return {
        id: cardId,
        name: deckCard.name || "Loading…",
        image_url_small: deckCard.image_url_small,
        image_url: deckCard.image_url,
        type: deckCard.type,
      };
    }
  }
  const summary = state.searchResultsById[cardId];
  if (summary) return summary;
  const collectionItem = Object.values(state.collectionItemsById).find(
    (item) => item.card_id === cardId
  );
  if (collectionItem) {
    return {
      id: cardId,
      name: collectionItem.card_name || "Loading…",
      image_url_small: collectionItem.image_url_small,
      type: null,
    };
  }
  return null;
}

function renderModalSkeleton() {
  resetModalSupplements();
  renderModalPasscode(null);
  $("#modal-desc").innerHTML = `
    <div class="skeleton skeleton-line"></div>
    <div class="skeleton skeleton-line"></div>
    <div class="skeleton skeleton-line skeleton-line--short"></div>`;
  $("#modal-tags").innerHTML = "";
  const tagInput = $("#tag-input");
  if (tagInput) tagInput.value = "";
  $("#modal-printings").innerHTML = `
    <div class="skeleton skeleton-row"></div>
    <div class="skeleton skeleton-row"></div>
    <div class="skeleton skeleton-row"></div>`;
}

function setModalLoadingState(loading) {
  const card = $("#card-modal")?.querySelector(".modal-card");
  card?.classList.toggle("modal-loading", loading);
  const controls = [
    "#modal-favorite",
    "#tag-input",
    "#tag-add-btn",
    "#owned-add-btn",
    "#deck-target",
    "#deck-zone",
    "#deck-add-card-btn",
  ];
  for (const sel of controls) {
    const el = $(sel);
    if (el) el.disabled = loading;
  }
}

function seedModalPreview(seed, imageToken) {
  $("#modal-name").textContent = seed.name || "Loading…";
  $("#modal-meta").textContent = formatModalStats(seed);
  renderModalPasscode(seed.id ?? state.currentCardId);
  if (seed.is_favorite != null) {
    $("#modal-favorite").textContent = seed.is_favorite ? "★ Favorited" : "☆ Favorite";
  } else {
    $("#modal-favorite").textContent = "☆ Favorite";
  }
  if (seed.image_url_small) {
    setModalImage(seed.image_url_small, seed.name, imageToken);
  }
}

function formatDisplayDate(isoDate) {
  if (!isoDate) return "";
  const parts = String(isoDate).split("-");
  if (parts.length !== 3) return isoDate;
  const year = Number(parts[0]);
  const month = Number(parts[1]) - 1;
  const day = Number(parts[2]);
  const dt = new Date(Date.UTC(year, month, day));
  if (Number.isNaN(dt.getTime())) return isoDate;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(dt);
}

function resetModalSupplements() {
  const supplements = $("#modal-supplements");
  const errataOpen = $("#modal-errata-open");
  const tipsTrigger = $("#modal-tips-trigger");
  if (supplements) supplements.hidden = true;
  if (errataOpen) errataOpen.hidden = true;
  if (tipsTrigger) tipsTrigger.hidden = true;
}

function renderModalSupplements(card) {
  const supplements = $("#modal-supplements");
  const errataOpen = $("#modal-errata-open");
  const tipsTrigger = $("#modal-tips-trigger");

  if (supplements) supplements.hidden = !card;
  if (errataOpen) errataOpen.hidden = !card;
  if (tipsTrigger) tipsTrigger.hidden = !card;
}

function renderSupplementEmpty(bodyEl, message) {
  bodyEl.replaceChildren();
  const p = document.createElement("p");
  p.className = "supplement-empty muted";
  p.textContent = message;
  bodyEl.appendChild(p);
}

function cardHasTips(card) {
  return (card?.tips || []).some((s) => (s.tips || []).length > 0);
}

function renderErrataModal(card) {
  const body = $("#card-errata-body");
  if (!body) return;
  const versions = card.errata || [];
  if (!versions.length) {
    renderSupplementEmpty(body, "This card has no errata yet.");
    return;
  }
  body.replaceChildren();
  for (const version of versions) {
    const block = document.createElement("section");
    block.className = "errata-version";

    const title = document.createElement("h3");
    title.textContent = version.version_label || "Errata";
    block.appendChild(title);

    const metaParts = [];
    if (version.set_name) metaParts.push(version.set_name);
    if (version.set_code) metaParts.push(version.set_code);
    const dateText = formatDisplayDate(version.release_date);
    if (dateText) metaParts.push(`Release date: ${dateText}`);
    if (metaParts.length) {
      const meta = document.createElement("p");
      meta.className = "errata-meta";
      meta.textContent = metaParts.join(" · ");
      block.appendChild(meta);
    }

    const lore = document.createElement("p");
    lore.className = "errata-lore";
    // lore_html is server-sanitized (del/ins/b/i/br only); safe for innerHTML.
    if (version.lore_html) {
      lore.innerHTML = version.lore_html;
    } else {
      if (version.lore_text) {
        const note = document.createElement("p");
        note.className = "errata-lore-fallback muted";
        note.textContent = "Formatted errata unavailable; showing plain text.";
        block.appendChild(note);
      }
      lore.textContent = version.lore_text || "";
    }
    block.appendChild(lore);

    body.appendChild(block);
  }
}

function renderTipsModal(card) {
  const body = $("#card-tips-body");
  if (!body) return;
  if (!cardHasTips(card)) {
    renderSupplementEmpty(body, "There are no tips for this card.");
    return;
  }
  body.replaceChildren();
  for (const section of card.tips || []) {
    const tips = section.tips || [];
    if (!tips.length) continue;
    const wrap = document.createElement("section");
    wrap.className = "tips-section";
    const label = (section.format || "").trim();
    if (label && label.toLowerCase() !== "tips") {
      const heading = document.createElement("h3");
      heading.textContent = label;
      wrap.appendChild(heading);
    }
    const list = document.createElement("ul");
    for (const tip of tips) {
      const li = document.createElement("li");
      li.textContent = tip;
      list.appendChild(li);
    }
    wrap.appendChild(list);
    body.appendChild(wrap);
  }
}

function openCardErrataModal() {
  if (!state.currentCard) return;
  renderErrataModal(state.currentCard);
  const dlg = $("#card-errata-modal");
  if (!dlg) return;
  dlg.hidden = false;
  syncModalOpenClass();
  $("#card-errata-close")?.focus();
}

function closeCardErrataModal() {
  const dlg = $("#card-errata-modal");
  if (!dlg || dlg.hidden) return;
  dlg.hidden = true;
  syncModalOpenClass();
  $("#modal-errata-open")?.focus();
}

function openCardTipsModal() {
  const dlg = $("#card-tips-modal");
  if (!dlg || !state.currentCard) return;
  renderTipsModal(state.currentCard);
  dlg.hidden = false;
  syncModalOpenClass();
  $("#card-tips-close")?.focus();
}

function closeCardTipsModal() {
  const dlg = $("#card-tips-modal");
  if (!dlg || dlg.hidden) return;
  dlg.hidden = true;
  syncModalOpenClass();
  $("#modal-tips-trigger")?.focus();
}

function formatMarketPrice(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${Number(value).toFixed(2).replace(".", ",")} €`;
}

function resolvedCollectionSellPrice(item) {
  if (item.sell_price != null) return item.sell_price;
  if (item.trend_price != null) return item.trend_price;
  return 0;
}

function printingHasMarketPrices(p) {
  return [p.low_price, p.avg_price, p.trend_price].some(
    (value) => value != null && !Number.isNaN(Number(value))
  );
}

function formatMarketPrices(p, { showUnavailable = true } = {}) {
  if (!printingHasMarketPrices(p)) {
    if (!showUnavailable) return "";
    return '<span class="printing-prices-unavailable">Prices unavailable</span>';
  }
  const low = formatMarketPrice(p.low_price);
  const avg = formatMarketPrice(p.avg_price);
  const trend = formatMarketPrice(p.trend_price);
  return `<span aria-label="Low ${low}, Average ${avg}, Trend ${trend}">${low} / ${avg} / ${trend}</span>`;
}

function formatPrintingOwnershipBadges(p) {
  const parts = [];
  if (p.owned_quantity > 0) {
    parts.push(
      `<span class="badge badge-owned printing-owned-qty" aria-label="Owned: ${p.owned_quantity}">×${p.owned_quantity}</span>`
    );
  }
  if (p.trade_quantity > 0) {
    parts.push(
      `<span class="badge badge-trade printing-trade-qty" aria-label="For trade: ${p.trade_quantity}">×${p.trade_quantity}</span>`
    );
  }
  return parts.length
    ? `<span class="printing-qty-badges">${parts.join("")}</span>`
    : "";
}

function formatPrintingOwnershipLabel(p) {
  const parts = [];
  if (p.owned_quantity > 0) parts.push(`×${p.owned_quantity}`);
  if (p.trade_quantity > 0) parts.push(`×${p.trade_quantity}`);
  return parts.length ? ` ${parts.join(" ")}` : "";
}

function formatPriceUpdatedAt(iso) {
  return formatDeckDate(iso);
}

function latestPriceUpdatedAt(printings) {
  let latest = null;
  let latestMs = -Infinity;
  for (const p of printings) {
    if (!printingHasMarketPrices(p) || !p.prices_updated_at) continue;
    const ms = new Date(p.prices_updated_at).getTime();
    if (!Number.isNaN(ms) && ms > latestMs) {
      latestMs = ms;
      latest = p.prices_updated_at;
    }
  }
  return latest;
}

function formatPriceLegend(printings) {
  if (!printings.some(printingHasMarketPrices)) return null;
  const updatedAt = latestPriceUpdatedAt(printings);
  const dateLabel = updatedAt ? formatPriceUpdatedAt(updatedAt) : "";
  const lines = [
    '<span class="printings-price-tooltip-line printings-price-tooltip-line--primary">Low / Avg / Trend</span>',
    '<span class="printings-price-tooltip-line printings-price-tooltip-line--source">Cardmarket</span>',
  ];
  if (dateLabel && updatedAt) {
    lines.push(
      `<time class="printings-price-tooltip-line printings-price-tooltip-line--updated" datetime="${escapeHtml(updatedAt)}">Updated ${escapeHtml(dateLabel)}</time>`
    );
  }
  return {
    html: lines.join(""),
    ariaLabel: dateLabel
      ? `Low, average, and trend prices from Cardmarket, last updated ${dateLabel}`
      : "Low, average, and trend prices from Cardmarket",
  };
}

function renderPrintingsPriceInfo(printings) {
  const legend = formatPriceLegend(printings);
  if (!legend) return "";
  return `<span class="printings-price-info-wrap">
    <button type="button" class="icon-btn printings-price-info" aria-label="${escapeHtml(legend.ariaLabel)}" aria-describedby="modal-printings-price-tooltip">
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <path d="M12 16v-4" />
        <path d="M12 8h.01" />
      </svg>
    </button>
    <span id="modal-printings-price-tooltip" class="printings-price-tooltip" role="tooltip">${legend.html}</span>
  </span>`;
}

function formatPasscode(cardId) {
  if (cardId == null) return "";
  return String(cardId).padStart(8, "0");
}

function renderModalPasscode(cardId) {
  const wrap = $("#modal-passcode");
  const text = $("#modal-passcode-text");
  const copyBtn = $("#modal-passcode-copy");
  if (!wrap || !text) return;
  if (cardId == null) {
    wrap.hidden = true;
    wrap.removeAttribute("aria-label");
    text.textContent = "";
    if (copyBtn) copyBtn.hidden = true;
    return;
  }
  const code = formatPasscode(cardId);
  text.textContent = code;
  wrap.setAttribute("aria-label", `Passcode ${code}`);
  wrap.hidden = false;
  if (copyBtn) copyBtn.hidden = false;
}

function expansionCodeFromSetCode(setCode) {
  const idx = setCode.indexOf("-");
  return idx > 0 ? setCode.slice(0, idx) : setCode;
}

function collectionPrintingKey(p) {
  return `${p.set_code}|${p.set_rarity_code}`;
}

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}

function renderModalTags(tags) {
  $("#modal-tags").innerHTML = (tags || [])
    .map(
      (t) => `<span class="tag">
  <button type="button" class="tag-label" title="Search by this tag">${escapeHtml(t)}</button>
  <button type="button" class="tag-remove" aria-label="Remove tag ${escapeHtml(t)}">×</button>
</span>`
    )
    .join("");
}

async function searchByTag(tag) {
  const filterEl = $("#filter-tag");
  if (filterEl) filterEl.value = tag;
  if (state.activeView !== "search") switchView("search");
  closeCardModalOverlay();
  await runSearch();
}

function renderModalPrintingsList(printings, selectedKey) {
  const listEl = $("#modal-printings");
  if (!listEl) return;

  const hasAnyPrices = printings.some(printingHasMarketPrices);
  listEl.className = `printings-list printings-list--grid${
    hasAnyPrices ? " printings-list--has-prices" : ""
  }`;

  const headerPriceCol = hasAnyPrices
    ? `<span class="printings-col-price">
      <span class="printings-col-price-label">Price</span>
      ${renderPrintingsPriceInfo(printings)}
    </span>`
    : "";
  const header = hasAnyPrices
    ? `
    <div class="printings-list-header">
      <span class="printings-col-printing" aria-hidden="true"></span>
      ${headerPriceCol}
    </div>`
    : "";

  const rows = printings
    .map((p) => {
      const key = collectionPrintingKey(p);
      const selected = selectedKey === key ? " printing-row--selected" : "";
      const owned = p.owned_quantity > 0;
      const canEdit = owned && p.collection_item_id;
      const rowAction = canEdit
        ? "Edit collection entry"
        : "Select for add to collection";
      const priceCell = hasAnyPrices
        ? `<span class="printing-col printing-col-prices muted">${
            formatMarketPrices(p, { showUnavailable: false }) || "—"
          }</span>`
        : "";
      return `
      <div class="printing-row printing-row--selectable printing-row--grid${selected}${
        owned ? " owned" : ""
      }${canEdit ? " printing-row--editable" : ""}"
        data-printing-key="${escapeHtml(key)}"
        data-collection-item-id="${p.collection_item_id ?? ""}"
        role="button" tabindex="0"
        title="${escapeHtml(rowAction)}"
        aria-label="${escapeHtml(`${p.set_code} ${p.set_rarity || ""}. ${rowAction}`)}">
        <span class="printing-col printing-col-main">
          <span class="set-code">${escapeHtml(p.set_code)}</span>
          <span class="rarity">${escapeHtml(p.set_rarity)}</span>
          ${formatPrintingOwnershipBadges(p)}
        </span>
        ${priceCell}
      </div>`;
    })
    .join("");

  listEl.innerHTML = printings.length
    ? `${header}<div class="printings-list-body">${rows}</div>`
    : "";
}

function renderModalCard(card) {
  $("#modal-name").textContent = card.name;
  renderModalPasscode(card.id);
  $("#modal-meta").textContent = formatModalStats(card);
  $("#modal-desc").textContent = card.desc || "";
  $("#modal-desc").classList.remove("modal-load-error");
  $("#modal-favorite").textContent = card.is_favorite ? "★ Favorited" : "☆ Favorite";

  renderModalTags(card.tags);

  const printings = card.printings || [];
  const selectedKey = addCollectionSelectedPrintingKey;
  renderModalPrintingsList(printings, selectedKey);
  renderModalSupplements(card);
  applyModalReadableColors();
}

async function refreshModalCard() {
  if (!state.currentCardId) return;
  const cardId = state.currentCardId;
  const card = await api(`/cards/${cardId}`);
  if (state.currentCardId !== cardId) return;
  state.currentCard = card;
  renderModalCard(card);
  setModalLoadingState(false);
}

async function openCardModal(cardId, { fromRouter = false } = {}) {
  if (state.currentCardId !== cardId) {
    addCollectionSelectedPrintingKey = null;
  }
  state.currentCardId = cardId;
  state.currentCard = null;

  closeCardErrataModal();
  closeCardTipsModal();
  resetModalSupplements();

  $("#modal-name").textContent = "Loading…";
  $("#modal-meta").textContent = "";
  $("#modal-favorite").textContent = "☆ Favorite";

  const imageToken = beginModalImagePending();
  const seed = findModalSeed(cardId);

  if (seed) {
    seedModalPreview(seed, imageToken);
  }

  renderModalSkeleton();
  renderModalPasscode(state.currentCardId);
  setModalLoadingState(true);
  openCardModalOverlay();
  populateDeckSelect();
  if (!fromRouter) syncRouteHash();
  $("#modal-close")?.focus();

  try {
    const card = await api(`/cards/${cardId}`);
    if (state.currentCardId !== cardId) return;

    state.currentCard = card;
    renderModalCard(card);
    setModalImage(card.image_url || card.image_url_small || null, card.name, imageToken);
    setModalLoadingState(false);
    updateRouteDocumentTitle();
  } catch (err) {
    if (state.currentCardId !== cardId) return;
    resetModalSupplements();
    $("#modal-desc").textContent = err.message || "Failed to load card details.";
    $("#modal-desc").classList.add("modal-load-error");
    $("#modal-printings").innerHTML = "";
    finishModalImage(imageToken);
    setModalLoadingState(false);
  }
}

async function refreshOwnedSearchState() {
  if (state.activeView === "search") {
    await loadSearchPage(state.searchPage);
  }
}

function buildCollectionParams(offset = 0) {
  const params = new URLSearchParams();
  params.set("limit", String(COLLECTION_PAGE_SIZE));
  params.set("offset", String(offset));
  if (state.collectionFolder) params.set("folder", state.collectionFolder);
  const q = $("#collection-q")?.value.trim();
  if (q) params.set("q", q);
  const setCode = $("#collection-set-code")?.value.trim();
  if (setCode) params.set("set_code", setCode);
  params.set("sort", $("#collection-sort")?.value || "set_code");
  return params;
}

function renderCollectionStatsLine() {
  const el = $("#collection-stats-line");
  if (!el || !state.collectionStats) return;
  const s = state.collectionStats;
  const folderLabel = s.folders.length + (s.no_folder_count > 0 ? 1 : 0);
  el.textContent = `${s.unique_printings.toLocaleString()} printings · ${s.total_quantity.toLocaleString()} cards · ${folderLabel} folder${folderLabel === 1 ? "" : "s"}`;
}

function itemTotalQuantity(item) {
  const folders = item.folders || [];
  if (!folders.length) return item.quantity;
  return folders.reduce((sum, row) => sum + row.quantity, 0);
}

function formatFolderAllocationsLabel(folders) {
  if (!folders?.length) return "No Folder";
  return folders
    .map((row) => {
      const name = row.name || "No Folder";
      return folders.length > 1 || row.quantity > 1 ? `${name} (${row.quantity})` : name;
    })
    .join(", ");
}

function hasNamedFolderAssignment(folders) {
  return Boolean(folders?.some((row) => row.folder_id != null));
}

function closeFolderAllocationPopover() {
  document.querySelector(".folder-allocation-popover")?.remove();
  document.querySelectorAll(".collection-folder-picker").forEach((btn) => {
    btn.setAttribute("aria-expanded", "false");
  });
}

function toggleFolderAllocationEditor(item, itemId) {
  const existing = document.querySelector(".folder-allocation-popover:not(.move-copy-popover)");
  if (existing?.dataset.itemId === String(itemId)) {
    closeFolderAllocationPopover();
    return;
  }
  openFolderAllocationEditor(item, itemId);
}

function openFolderAllocationEditor(item, itemId) {
  closeFolderAllocationPopover();
  const totalQty = itemTotalQuantity(item);
  const folders = state.collectionStats?.folders || [];
  const current = new Map(
    (item.folders || []).map((row) => [row.folder_id ?? "none", row.quantity])
  );

  const popover = document.createElement("div");
  popover.className = "folder-allocation-popover";
  popover.dataset.itemId = String(itemId);
  popover.innerHTML = `
    <p class="folder-allocation-title">Assign folders (total: ${totalQty})</p>
    <div class="folder-allocation-options">
      <label class="folder-allocation-option">
        <input type="checkbox" data-folder-id="" ${current.has("none") ? "checked" : ""} />
        <span>No Folder</span>
        <input type="number" class="folder-allocation-qty" min="1" max="${totalQty}" value="${current.get("none") || 1}" ${current.has("none") ? "" : "disabled"} />
      </label>
      ${folders
        .map(
          (folder) => `
        <label class="folder-allocation-option">
          <input type="checkbox" data-folder-id="${folder.id}" ${current.has(folder.id) ? "checked" : ""} />
          <span>${escapeHtml(folder.name)}</span>
          <input type="number" class="folder-allocation-qty" min="1" max="${totalQty}" value="${current.get(folder.id) || 1}" ${current.has(folder.id) ? "" : "disabled"} />
        </label>`
        )
        .join("")}
    </div>
    <div class="folder-allocation-actions">
      <button type="button" class="secondary folder-allocation-cancel">Cancel</button>
      <button type="button" class="folder-allocation-save">Save</button>
    </div>`;

  document.body.appendChild(popover);
  const anchor = document.querySelector(`tr[data-id="${itemId}"] .collection-folder-picker`);
  if (anchor) {
    anchor.setAttribute("aria-expanded", "true");
    const rect = anchor.getBoundingClientRect();
    popover.style.top = `${rect.bottom + window.scrollY + 4}px`;
    popover.style.left = `${Math.min(rect.left + window.scrollX, window.innerWidth - popover.offsetWidth - 8)}px`;
  }

  popover.querySelectorAll('input[type="checkbox"]').forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const qtyInput = checkbox.closest(".folder-allocation-option")?.querySelector(".folder-allocation-qty");
      if (qtyInput) qtyInput.disabled = !checkbox.checked;
    });
  });

  popover.querySelector(".folder-allocation-cancel")?.addEventListener("click", closeFolderAllocationPopover);
  popover.querySelector(".folder-allocation-save")?.addEventListener("click", async () => {
    const selected = [];
    popover.querySelectorAll(".folder-allocation-option").forEach((row) => {
      const checkbox = row.querySelector('input[type="checkbox"]');
      if (!checkbox?.checked) return;
      const qty = Math.max(1, Number(row.querySelector(".folder-allocation-qty")?.value) || 1);
      const rawId = checkbox.dataset.folderId;
      selected.push({
        folder_id: rawId === "" ? null : Number(rawId),
        quantity: qty,
      });
    });
    if (!selected.length) {
      alert("Select at least one folder.");
      return;
    }
    const sum = selected.reduce((acc, row) => acc + row.quantity, 0);
    if (sum !== totalQty) {
      alert(`Quantities must sum to ${totalQty} (currently ${sum}).`);
      return;
    }
    try {
      await patchCollectionItem(itemId, { folder_allocations: selected });
      closeFolderAllocationPopover();
      await loadCollectionPage(state.collectionPage);
    } catch (err) {
      alert(err.message);
    }
  });

  setTimeout(() => {
    document.addEventListener(
      "click",
      (e) => {
        if (!popover.contains(e.target) && !e.target.closest(".collection-folder-picker")) {
          closeFolderAllocationPopover();
        }
      },
      { once: true }
    );
  }, 0);
}

function closeMoveCopyPopover() {
  const popover = document.querySelector(".move-copy-popover");
  if (!popover) return;
  if (popover._outsideHandler) {
    document.removeEventListener("click", popover._outsideHandler);
  }
  popover.remove();
}

function sameFolderId(a, b) {
  return (a ?? null) === (b ?? null);
}

function openMoveCopyPopover(item, itemId, mode, anchor) {
  closeFolderAllocationPopover();
  closeMoveCopyPopover();

  const isMove = mode === "move";
  const currentFolderId =
    state.collectionFolder === NO_FOLDER ? null : Number(state.collectionFolder);
  const available = item.quantity;

  const targets = [];
  if (state.collectionFolder !== NO_FOLDER) {
    targets.push({ id: null, name: "No Folder" });
  }
  for (const folder of state.collectionStats?.folders || []) {
    if (folder.id === currentFolderId) continue;
    targets.push({ id: folder.id, name: folder.name });
  }
  if (!targets.length) {
    alert("No other folder available. Create a folder first.");
    return;
  }

  const popover = document.createElement("div");
  popover.className = "folder-allocation-popover move-copy-popover";
  popover.innerHTML = `
    <p class="folder-allocation-title">
      ${isMove ? "Move" : "Copy"} ${escapeHtml(item.card_name || item.set_code)}${isMove ? ` (max ${available})` : ""}
    </p>
    <label class="move-copy-field">
      <span>To folder</span>
      <select class="move-copy-target">
        ${targets
          .map(
            (t) => `<option value="${t.id ?? ""}">${escapeHtml(t.name)}</option>`
          )
          .join("")}
      </select>
    </label>
    <label class="move-copy-field">
      <span>Quantity</span>
      <input type="number" class="move-copy-qty" min="1" ${isMove ? `max="${available}"` : ""} value="1" />
    </label>
    <p class="move-copy-error hidden"></p>
    <div class="folder-allocation-actions">
      <button type="button" class="secondary move-copy-cancel">Cancel</button>
      <button type="button" class="move-copy-confirm">${isMove ? "Move" : "Copy"}</button>
    </div>`;

  document.body.appendChild(popover);
  if (anchor) {
    const rect = anchor.getBoundingClientRect();
    popover.style.top = `${rect.bottom + window.scrollY + 4}px`;
    popover.style.left = `${Math.min(rect.left + window.scrollX, window.innerWidth - popover.offsetWidth - 8)}px`;
  }

  const errorEl = popover.querySelector(".move-copy-error");
  const showError = (msg) => {
    errorEl.textContent = msg;
    errorEl.classList.remove("hidden");
  };

  popover.querySelector(".move-copy-cancel")?.addEventListener("click", closeMoveCopyPopover);
  popover.querySelector(".move-copy-confirm")?.addEventListener("click", async () => {
    errorEl.classList.add("hidden");
    const qty = Number(popover.querySelector(".move-copy-qty")?.value);
    if (!Number.isInteger(qty) || qty < 1) {
      showError("Enter a whole number of at least 1.");
      return;
    }
    if (isMove && qty > available) {
      showError(`Maximum ${available} can be moved from this folder.`);
      return;
    }
    const targetRaw = popover.querySelector(".move-copy-target")?.value ?? "";
    const targetFolderId = targetRaw === "" ? null : Number(targetRaw);

    const allocs = (item.folders || []).map((row) => ({
      folder_id: row.folder_id ?? null,
      quantity: row.quantity,
    }));

    if (isMove) {
      const source = allocs.find((row) => sameFolderId(row.folder_id, currentFolderId));
      if (!source || source.quantity < qty) {
        showError("Not enough copies in this folder.");
        return;
      }
      source.quantity -= qty;
    }
    const target = allocs.find((row) => sameFolderId(row.folder_id, targetFolderId));
    if (target) {
      target.quantity += qty;
    } else {
      allocs.push({ folder_id: targetFolderId, quantity: qty });
    }
    const updated = allocs.filter((row) => row.quantity > 0);
    const body = { folder_allocations: updated };
    if (!isMove) {
      body.quantity = updated.reduce((sum, row) => sum + row.quantity, 0);
    }
    try {
      await patchCollectionItem(itemId, body);
      closeMoveCopyPopover();
      await loadCollectionPage(state.collectionPage);
    } catch (err) {
      showError(err.message);
    }
  });

  const outsideHandler = (e) => {
    if (!popover.contains(e.target)) closeMoveCopyPopover();
  };
  popover._outsideHandler = outsideHandler;
  setTimeout(() => document.addEventListener("click", outsideHandler), 0);
}

async function createCollectionFolder() {
  const name = prompt("New folder name:");
  if (!name?.trim()) return;
  try {
    await api("/collection/folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    await loadCollectionStats();
    renderCollectionStatsLine();
    renderCollectionSidebar();
  } catch (err) {
    alert(err.message);
  }
}

function renderCollectionSidebar() {
  const list = $("#collection-folder-list");
  if (!list || !state.collectionStats) return;
  const s = state.collectionStats;
  const active = state.collectionFolder;

  const entries = [
    { key: null, label: "All", count: s.total_items, deletable: false },
  ];
  if (s.no_folder_count > 0) {
    entries.push({
      key: NO_FOLDER,
      label: "No Folder",
      count: s.no_folder_count,
      deletable: false,
    });
  }
  for (const f of s.folders) {
    entries.push({
      key: String(f.id),
      label: f.name,
      count: f.item_count,
      deletable: true,
      folderId: f.id,
    });
  }

  list.innerHTML = entries
    .map(
      (e) => `
    <li class="${active === e.key ? "active" : ""}" data-folder="${e.key === null ? "" : encodeURIComponent(e.key)}" data-folder-id="${e.folderId ?? ""}">
      <span class="collection-folder-label">${escapeHtml(e.label)}</span>
      <span class="collection-folder-actions">
        <span class="collection-folder-count muted">${e.count}</span>
        ${e.deletable ? '<button type="button" class="collection-folder-delete" title="Delete folder">×</button>' : ""}
      </span>
    </li>`
    )
    .join("");

  list.querySelectorAll("li").forEach((li) => {
    li.addEventListener("click", async (e) => {
      if (e.target.closest(".collection-folder-delete")) return;
      const raw = li.dataset.folder;
      state.collectionFolder = raw === "" ? null : decodeURIComponent(raw);
      state.collectionPage = 0;
      renderCollectionSidebar();
      syncRouteHash();
      await loadCollectionPage(0);
    });

    li.querySelector(".collection-folder-delete")?.addEventListener("click", async (e) => {
      e.stopPropagation();
      const folderId = Number(li.dataset.folderId);
      const folderName = li.querySelector(".collection-folder-label")?.textContent || "folder";
      const folderStats = s.folders.find((row) => row.id === folderId);
      const qty = folderStats?.quantity ?? 0;
      const count = folderStats?.item_count ?? 0;
      if (
        !confirm(
          `Delete "${folderName}"? ${count} card row(s) (${qty} copies) will move to No Folder.`
        )
      ) {
        return;
      }
      try {
        await api(`/collection/folders/${folderId}`, { method: "DELETE" });
        if (state.collectionFolder === String(folderId)) {
          state.collectionFolder = null;
        }
        await loadCollectionStats();
        renderCollectionStatsLine();
        renderCollectionSidebar();
        await loadCollectionPage(state.collectionPage);
      } catch (err) {
        alert(err.message);
      }
    });

    if (li.dataset.folderId) {
      li.addEventListener("dblclick", async (e) => {
        if (e.target.closest(".collection-folder-delete")) return;
        e.preventDefault();
        const folderId = Number(li.dataset.folderId);
        const fromName = li.querySelector(".collection-folder-label")?.textContent || "";
        const toName = prompt("Rename folder:", fromName);
        if (!toName?.trim() || toName.trim() === fromName) return;
        try {
          await api(`/collection/folders/${folderId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: toName.trim() }),
          });
          await loadCollectionStats();
          renderCollectionSidebar();
          await loadCollectionPage(state.collectionPage);
        } catch (err) {
          alert(err.message);
        }
      });
    }
  });
}

function renderCollectionPagination() {
  const bar = $("#collection-pagination");
  if (!bar) return;
  const total = state.collectionTotal;
  const totalPages = Math.max(1, Math.ceil(total / COLLECTION_PAGE_SIZE));
  const page = state.collectionPage;

  if (totalPages <= 1) {
    bar.classList.add("hidden");
    bar.innerHTML = "";
    return;
  }

  const start = page * COLLECTION_PAGE_SIZE + 1;
  const end = Math.min((page + 1) * COLLECTION_PAGE_SIZE, total);

  bar.classList.remove("hidden");
  bar.innerHTML = `
    <button type="button" id="collection-prev" class="secondary"${page === 0 ? " disabled" : ""}>← Previous</button>
    <span class="search-page-info">Page ${page + 1} of ${totalPages} · ${start.toLocaleString()}–${end.toLocaleString()} of ${total.toLocaleString()}</span>
    <button type="button" id="collection-next" class="secondary"${page >= totalPages - 1 ? " disabled" : ""}>Next →</button>`;

  $("#collection-prev")?.addEventListener("click", () => {
    if (state.collectionPage > 0) loadCollectionPage(state.collectionPage - 1);
  });
  $("#collection-next")?.addEventListener("click", () => {
    const lastPage = Math.ceil(state.collectionTotal / COLLECTION_PAGE_SIZE) - 1;
    if (state.collectionPage < lastPage) loadCollectionPage(state.collectionPage + 1);
  });
}

async function patchCollectionItem(itemId, body) {
  await api(`/collection/${itemId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await loadCollectionStats();
  renderCollectionStatsLine();
  renderCollectionSidebar();
}

async function removeCollectionItem(itemId, { confirm: askConfirm = true } = {}) {
  if (askConfirm && !confirm("Remove this printing from your collection?")) return false;
  await api(`/collection/${itemId}`, { method: "DELETE" });
  await loadCollectionStats();
  renderCollectionStatsLine();
  renderCollectionSidebar();
  await loadCollectionPage(state.collectionPage);
  const tbody = $("#collection-tbody");
  if (tbody && !tbody.querySelector(".collection-row") && state.collectionPage > 0) {
    state.collectionPage -= 1;
    await loadCollectionPage(state.collectionPage);
  }
  await loadStatus();
  return true;
}

let addCollectionContext = null;
let addCollectionSelectedPrintingKey = null;

function populateAddCollectionConditionSelect() {
  const condSel = $("#collection-add-condition");
  if (!condSel || condSel.options.length) return;
  condSel.innerHTML = COLLECTION_CONDITIONS.map(
    (c) => `<option value="${escapeHtml(c.value)}">${escapeHtml(c.label)}</option>`
  ).join("");
}

function populateAddCollectionFolderSelect() {
  const sel = $("#collection-add-folder");
  if (!sel) return;
  const folders = state.collectionStats?.folders || [];
  const current = sel.value;
  sel.innerHTML = [
    '<option value="">No Folder</option>',
    ...folders.map(
      (f) => `<option value="${f.id}">${escapeHtml(f.name)}</option>`
    ),
  ].join("");
  if (current && [...sel.options].some((o) => o.value === current)) {
    sel.value = current;
  }
}

function getAddCollectionSelectedPrinting() {
  const ctx = addCollectionContext;
  if (!ctx) return null;
  const printings = ctx.card.printings || [];
  if (!printings.length) return null;
  if (printings.length === 1) return printings[0];
  const sel = $("#collection-add-card-number");
  const key = sel?.value;
  if (!key) return printings[0];
  const [setCode, rarityCode] = key.split("|");
  return (
    printings.find(
      (p) => p.set_code === setCode && p.set_rarity_code === rarityCode
    ) || printings[0]
  );
}

function syncAddCollectionPrintingFields() {
  const card = addCollectionContext?.card;
  const printing = getAddCollectionSelectedPrinting();
  if (!card || !printing) return;

  const cardNameEl = $("#collection-add-card-name");
  if (cardNameEl) cardNameEl.textContent = card.name || "";

  const setCodeEl = $("#collection-add-set-code");
  if (setCodeEl) setCodeEl.textContent = expansionCodeFromSetCode(printing.set_code);

  const setNameEl = $("#collection-add-set-name");
  if (setNameEl) setNameEl.textContent = printing.set_name || "";

  const rarityEl = $("#collection-add-rarity");
  if (rarityEl) {
    rarityEl.textContent = printing.set_rarity || printing.set_rarity_code || "";
  }

  const staticEl = $("#collection-add-card-number-static");
  if (staticEl) staticEl.textContent = printing.set_code;

  const pricesEl = $("#collection-add-market-prices");
  if (pricesEl) pricesEl.textContent = formatMarketPrices(printing) || "—";
}

function renderAddCollectionCardNumberControl(printings, preselectKey) {
  const wrapMulti = $("#collection-add-card-number-wrap");
  const wrapStatic = $("#collection-add-card-number-static-wrap");
  const sel = $("#collection-add-card-number");
  if (!wrapMulti || !wrapStatic || !sel) return;

  if (printings.length <= 1) {
    wrapMulti.hidden = true;
    wrapStatic.hidden = false;
  } else {
    wrapMulti.hidden = false;
    wrapStatic.hidden = true;
    sel.innerHTML = printings
      .map((p) => {
        const key = collectionPrintingKey(p);
        const owned = formatPrintingOwnershipLabel(p);
        return `<option value="${escapeHtml(key)}">${escapeHtml(p.set_code)} ${escapeHtml(p.set_rarity)}${owned}</option>`;
      })
      .join("");
    const key =
      preselectKey && printings.some((p) => collectionPrintingKey(p) === preselectKey)
        ? preselectKey
        : collectionPrintingKey(printings[0]);
    sel.value = key;
  }
}

function resetAddCollectionNewFolderRow() {
  $("#collection-add-new-folder-row")?.classList.add("hidden");
  const nameInput = $("#collection-add-new-folder-name");
  if (nameInput) nameInput.value = "";
}

async function openAddCollectionModal(card, { printingKey: preselectKey = null } = {}) {
  if (!state.token) {
    showToast("Log in to add to your collection.", { variant: "error" });
    return;
  }

  populateAddCollectionConditionSelect();
  addCollectionContext = { card };

  if (!state.collectionStats) {
    try {
      await loadCollectionStats();
    } catch (err) {
      addCollectionContext = null;
      showToast(err.message || "Could not load folders.", { variant: "error" });
      return;
    }
  }

  populateAddCollectionFolderSelect();

  const printings = card.printings || [];
  const selectedKey = preselectKey || addCollectionSelectedPrintingKey;
  renderAddCollectionCardNumberControl(printings, selectedKey);

  $("#collection-add-quantity").value = "1";
  $("#collection-add-trade-quantity").value = "0";
  $("#collection-add-condition").value = "NearMint";
  $("#collection-add-edition").value = "Unlimited";
  $("#collection-add-language").value = "English";
  $("#collection-add-price-bought").value = "0";
  $("#collection-add-date-bought").value = todayIsoDate();
  $("#collection-add-folder").value = "";
  resetAddCollectionNewFolderRow();

  syncAddCollectionPrintingFields();

  const dlg = $("#collection-add-modal");
  if (!dlg) return;
  dlg.hidden = false;
  syncModalOpenClass();
  $("#collection-add-close")?.focus();
}

function closeAddCollectionModal() {
  const dlg = $("#collection-add-modal");
  if (!dlg || dlg.hidden) return;
  dlg.hidden = true;
  addCollectionContext = null;
  syncModalOpenClass();
}

async function createFolderFromAddModal() {
  const nameInput = $("#collection-add-new-folder-name");
  const name = nameInput?.value?.trim();
  if (!name) {
    showToast("Enter a folder name.", { variant: "error" });
    return;
  }
  try {
    const folder = await api("/collection/folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    await loadCollectionStats();
    populateAddCollectionFolderSelect();
    $("#collection-add-folder").value = String(folder.id);
    resetAddCollectionNewFolderRow();
    showToast(`Folder "${folder.name}" created.`);
  } catch (err) {
    showToast(err.message, { variant: "error" });
  }
}

async function submitAddCollection() {
  if (!addCollectionContext) return;
  const printing = getAddCollectionSelectedPrinting();
  if (!printing) {
    showToast("No printing selected.", { variant: "error" });
    return;
  }

  const qty = Number($("#collection-add-quantity").value);
  if (!Number.isInteger(qty) || qty < 1) {
    showToast("Quantity must be at least 1.", { variant: "error" });
    return;
  }

  const tradeQty = Number($("#collection-add-trade-quantity").value);
  if (!Number.isInteger(tradeQty) || tradeQty < 0) {
    showToast("Trade quantity must be 0 or more.", { variant: "error" });
    return;
  }

  const priceBought = Number($("#collection-add-price-bought").value);
  if (!Number.isFinite(priceBought) || priceBought < 0) {
    showToast("Price bought must be 0 or greater.", { variant: "error" });
    return;
  }

  const folderVal = $("#collection-add-folder").value;
  const folderId = folderVal ? Number(folderVal) : null;
  const card = addCollectionContext.card;

  const body = {
    set_code: printing.set_code,
    rarity: printing.set_rarity_code,
    quantity: qty,
    trade_quantity: tradeQty,
    card_name: card.name,
    expansion_code: expansionCodeFromSetCode(printing.set_code),
    set_name: printing.set_name,
    condition: $("#collection-add-condition").value,
    printing: $("#collection-add-edition").value,
    language: $("#collection-add-language").value,
    folder_id: folderId,
    price_bought: priceBought,
    date_bought: $("#collection-add-date-bought").value || todayIsoDate(),
  };

  const btn = $("#collection-add-submit");
  try {
    await runModalAction(
      btn,
      () =>
        api("/collection", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }),
      { busyLabel: "Adding…", successMessage: `Added ${qty}× ${printing.set_code}` }
    );
  } catch {
    return;
  }

  addCollectionSelectedPrintingKey = collectionPrintingKey(printing);
  state.collectionViewCache = null;
  closeAddCollectionModal();
  refreshModalCard();
  loadStatus();
  refreshOwnedSearchState();
  refreshCollectionIfActive();
}

function selectModalPrintingRow(key) {
  if (!key || !state.currentCard) return;
  addCollectionSelectedPrintingKey = key;
  renderModalCard(state.currentCard);
}

async function activateModalPrintingRow(row) {
  const key = row?.dataset.printingKey;
  if (!key) return;
  const itemId = Number(row.dataset.collectionItemId);
  const printing = (state.currentCard?.printings || []).find(
    (p) => collectionPrintingKey(p) === key
  );
  if (printing?.owned_quantity > 0 && itemId) {
    try {
      const item = await api(`/collection/${itemId}`);
      await openCollectionEditModal(item, itemId);
    } catch (err) {
      showToast(err.message || "Could not open collection entry.", { variant: "error" });
    }
    return;
  }
  selectModalPrintingRow(key);
}

let collectionEditContext = null;

function closeCollectionEditModal() {
  const dlg = $("#collection-edit-modal");
  if (!dlg || dlg.hidden) return;
  dlg.hidden = true;
  collectionEditContext = null;
  syncModalOpenClass();
}

function populateCollectionEditRarity(printings, setCode, item) {
  const raritySel = $("#collection-edit-rarity");
  if (!raritySel) return;
  const seen = new Set();
  const parts = [];
  for (const p of printings) {
    if (p.set_code !== setCode || seen.has(p.set_rarity_code)) continue;
    seen.add(p.set_rarity_code);
    parts.push(
      `<option value="${escapeHtml(p.set_rarity_code)}">${escapeHtml(p.set_rarity || p.set_rarity_code)}</option>`
    );
  }
  if (setCode === item.set_code && !seen.has(item.rarity_code)) {
    parts.unshift(
      `<option value="${escapeHtml(item.rarity_code)}">${escapeHtml(item.rarity_name || item.rarity_display || item.rarity_code)}</option>`
    );
  }
  raritySel.innerHTML = parts.join("");
  if (setCode === item.set_code) raritySel.value = item.rarity_code;
}

async function openCollectionEditModal(item, itemId) {
  const dlg = $("#collection-edit-modal");
  if (!dlg) return;
  collectionEditContext = { item, itemId, printings: [] };

  $("#collection-edit-card-name").textContent = item.card_name || item.set_code;

  const condSel = $("#collection-edit-condition");
  const currentCondition = item.condition || "";
  const isKnownCondition = COLLECTION_CONDITIONS.some(
    (c) => c.value === currentCondition
  );
  condSel.innerHTML = [
    ...(!currentCondition ? ['<option value="">(not set)</option>'] : []),
    ...(currentCondition && !isKnownCondition
      ? [
          `<option value="${escapeHtml(currentCondition)}">${escapeHtml(currentCondition)}</option>`,
        ]
      : []),
    ...COLLECTION_CONDITIONS.map(
      (c) => `<option value="${escapeHtml(c.value)}">${escapeHtml(c.label)}</option>`
    ),
  ].join("");
  condSel.value = currentCondition;

  $("#collection-edit-quantity").value = String(item.quantity);
  $("#collection-edit-trade-quantity").value = String(item.trade_quantity ?? 0);
  const sellDefault = resolvedCollectionSellPrice(item);
  $("#collection-edit-sell-price").value = String(sellDefault);

  const setSel = $("#collection-edit-set");
  const raritySel = $("#collection-edit-rarity");
  const note = $("#collection-edit-note");
  note.classList.add("hidden");
  setSel.disabled = true;
  raritySel.disabled = true;
  setSel.innerHTML = `<option value="${escapeHtml(item.set_code)}">${escapeHtml(item.set_code)}</option>`;
  raritySel.innerHTML = `<option value="${escapeHtml(item.rarity_code)}">${escapeHtml(item.rarity_name || item.rarity_display || item.rarity_code)}</option>`;

  dlg.hidden = false;
  syncModalOpenClass();
  $("#collection-edit-close")?.focus();

  if (!item.card_id) {
    note.textContent =
      "This row isn't matched to the catalog, so Set and Rarity can't be changed here.";
    note.classList.remove("hidden");
    return;
  }
  try {
    const card = await api(`/cards/${item.card_id}`);
    if (!collectionEditContext || collectionEditContext.itemId !== itemId) return;
    const printings = card.printings || [];
    collectionEditContext.printings = printings;
    const setCodes = [...new Set(printings.map((p) => p.set_code))];
    if (!setCodes.includes(item.set_code)) setCodes.unshift(item.set_code);
    setSel.innerHTML = setCodes
      .map((code) => `<option value="${escapeHtml(code)}">${escapeHtml(code)}</option>`)
      .join("");
    setSel.value = item.set_code;
    populateCollectionEditRarity(printings, item.set_code, item);
    setSel.disabled = false;
    raritySel.disabled = false;
  } catch (err) {
    if (!collectionEditContext || collectionEditContext.itemId !== itemId) return;
    note.textContent = `Could not load printings: ${err.message}`;
    note.classList.remove("hidden");
  }
}

async function saveCollectionEdit() {
  if (!collectionEditContext) return;
  const { item, itemId } = collectionEditContext;

  const qty = Number($("#collection-edit-quantity").value);
  if (!Number.isInteger(qty) || qty < 1) {
    alert("Quantity must be a whole number of at least 1.");
    return;
  }

  const tradeQty = Number($("#collection-edit-trade-quantity").value);
  if (!Number.isInteger(tradeQty) || tradeQty < 0) {
    alert("Trade quantity must be a whole number of 0 or more.");
    return;
  }

  const sellPrice = Number($("#collection-edit-sell-price").value);
  if (!Number.isFinite(sellPrice) || sellPrice < 0) {
    alert("Sell price must be 0 or greater.");
    return;
  }

  const body = {};

  const setSel = $("#collection-edit-set");
  const raritySel = $("#collection-edit-rarity");
  if (!setSel.disabled && setSel.value && raritySel.value) {
    if (setSel.value !== item.set_code || raritySel.value !== item.rarity_code) {
      body.set_code = setSel.value;
      body.rarity = raritySel.value;
    }
  }

  const condVal = $("#collection-edit-condition").value;
  const condCanonical = COLLECTION_CONDITIONS.some((c) => c.value === condVal);
  if (condVal !== (item.condition || "") && condCanonical) {
    body.condition = condVal;
  }

  if (qty !== item.quantity) {
    const folderFilter = state.collectionFolder;
    if (!folderFilter) {
      body.quantity = qty;
    } else {
      const folderId = folderFilter === NO_FOLDER ? null : Number(folderFilter);
      const allocs = (item.folders || []).map((row) => ({
        folder_id: row.folder_id,
        quantity: row.quantity,
      }));
      const updated = allocs.map((row) =>
        (row.folder_id === folderId || (row.folder_id == null && folderId == null))
          ? { ...row, quantity: qty }
          : row
      );
      body.quantity = updated.reduce((sum, row) => sum + row.quantity, 0);
      body.folder_allocations = updated;
    }
  }

  if (tradeQty !== (item.trade_quantity ?? 0)) {
    body.trade_quantity = tradeQty;
  }

  const currentSell = resolvedCollectionSellPrice(item);
  if (sellPrice !== currentSell) {
    body.sell_price = sellPrice;
  }

  if (!Object.keys(body).length) {
    closeCollectionEditModal();
    return;
  }
  try {
    await patchCollectionItem(itemId, body);
    closeCollectionEditModal();
    await loadCollectionPage(state.collectionPage);
    if (state.currentCardId) {
      await refreshModalCard();
    }
  } catch (err) {
    alert(err.message);
  }
}

function renderCollectionTable(items) {
  const tbody = $("#collection-tbody");
  const emptyEl = $("#collection-empty");
  const tableWrap = $(".collection-table-wrap");
  if (!tbody) return;

  const inFolder = Boolean(state.collectionFolder);
  $("#collection-table")?.classList.toggle("collection-table--in-folder", inFolder);

  state.collectionItemsById = {};
  for (const item of items) {
    state.collectionItemsById[item.id] = item;
  }

  if (!items.length) {
    tbody.innerHTML = "";
    emptyEl?.classList.remove("hidden");
    tableWrap?.classList.add("hidden");
    $("#collection-pagination")?.classList.add("hidden");
    return;
  }

  emptyEl?.classList.add("hidden");
  tableWrap?.classList.remove("hidden");

  tbody.innerHTML = items
    .map(
      (item) => `
    <tr data-id="${item.id}" data-card-id="${item.card_id ?? ""}" data-total-qty="${itemTotalQuantity(item)}" class="collection-row">
      <td class="collection-thumb">${cardImgTag(item.image_url_small, 'class="collection-thumb-img"')}</td>
      <td>${escapeHtml(item.card_name || "—")}</td>
      <td><span class="set-code">${escapeHtml(item.set_code)}</span></td>
      <td>${escapeHtml(item.rarity_display || item.rarity_code)}</td>
      <td class="collection-qty-cell">${item.quantity}</td>
      <td class="collection-qty-cell">${item.trade_quantity ?? 0}</td>
      <td>${formatMarketPrice(resolvedCollectionSellPrice(item))}</td>
      <td>${conditionBadgeHtml(item.condition)}</td>
      <td class="collection-notes">${escapeHtml(item.notes || "")}</td>
      <td class="collection-row-actions-col">
        <div class="collection-row-actions-wrap">
          <button type="button" class="icon-btn collection-folder-picker collection-folder-icon-btn${hasNamedFolderAssignment(item.folders) ? " collection-folder-icon-btn--assigned" : ""}" aria-label="Edit folder assignments: ${escapeHtml(formatFolderAllocationsLabel(item.folders))}" title="${escapeHtml(formatFolderAllocationsLabel(item.folders))}" aria-haspopup="dialog" aria-expanded="false">
            ${COLLECTION_FOLDER_ICON_SVG}
          </button>
          <div class="collection-row-menu-wrap preset-menu-wrap">
            <button type="button" class="icon-btn secondary collection-row-menu-btn preset-menu-btn" aria-label="Row actions" title="Row actions" aria-haspopup="menu" aria-expanded="false">⋮</button>
            <div class="collection-row-menu preset-menu" hidden role="menu">
              <button type="button" role="menuitem" class="collection-edit-btn">Edit</button>
              ${inFolder ? `
              <button type="button" role="menuitem" class="collection-move-btn">Move</button>
              <button type="button" role="menuitem" class="collection-copy-btn">Copy</button>` : ""}
              <button type="button" role="menuitem" class="collection-delete-btn preset-menu-danger">Delete</button>
            </div>
          </div>
        </div>
      </td>
    </tr>`
    )
    .join("");

  state.collectionLastItems = items;
}

function setupCollectionTableDelegation() {
  const tbody = $("#collection-tbody");
  if (!tbody || tbody.dataset.delegationBound) return;
  tbody.dataset.delegationBound = "1";
  tbody.addEventListener("click", async (e) => {
    const row = e.target.closest(".collection-row");
    if (!row) return;
    const itemId = Number(row.dataset.id);
    const cardId = row.dataset.cardId ? Number(row.dataset.cardId) : null;
    const item = state.collectionItemsById[itemId];
    if (!item) return;

    if (e.target.closest(".collection-row-menu-btn")) {
      e.stopPropagation();
      closeFolderAllocationPopover();
      toggleCollectionRowMenu(e.target.closest(".collection-row-menu-btn"));
      return;
    }
    if (e.target.closest(".collection-edit-btn")) {
      e.stopPropagation();
      closeAllCollectionRowMenus();
      openCollectionEditModal(item, itemId);
      return;
    }
    if (e.target.closest(".collection-folder-picker")) {
      e.stopPropagation();
      closeAllCollectionRowMenus();
      toggleFolderAllocationEditor(item, itemId);
      return;
    }
    if (e.target.closest(".collection-move-btn")) {
      e.stopPropagation();
      const anchor = row.querySelector(".collection-row-menu-btn");
      closeAllCollectionRowMenus();
      openMoveCopyPopover(item, itemId, "move", anchor);
      return;
    }
    if (e.target.closest(".collection-copy-btn")) {
      e.stopPropagation();
      const anchor = row.querySelector(".collection-row-menu-btn");
      closeAllCollectionRowMenus();
      openMoveCopyPopover(item, itemId, "copy", anchor);
      return;
    }
    if (e.target.closest(".collection-delete-btn")) {
      e.stopPropagation();
      closeAllCollectionRowMenus();
      try {
        await removeCollectionItem(itemId);
      } catch (err) {
        alert(err.message);
      }
      return;
    }
    if (e.target.closest(".collection-thumb") && cardId) {
      openCardModal(cardId);
    }
  });
}

async function loadCollectionStats() {
  state.collectionStats = await api("/collection/stats");
}

async function loadCollectionPage(pageIndex) {
  const seq = ++collectionRequestSeq;
  state.collectionPage = pageIndex;
  const tbody = $("#collection-tbody");
  if (tbody) tbody.innerHTML = '<tr><td colspan="10" class="empty-msg">Loading…</td></tr>';
  $("#collection-pagination")?.classList.add("hidden");

  try {
    const offset = pageIndex * COLLECTION_PAGE_SIZE;
    const page = await api(`/collection?${buildCollectionParams(offset)}`);
    if (seq !== collectionRequestSeq) return;
    state.collectionTotal = page.total;
    renderCollectionTable(page.items);
    renderCollectionPagination();
    state.collectionViewCache = {
      folder: state.collectionFolder,
      stats: state.collectionStats,
      items: state.collectionLastItems,
      total: state.collectionTotal,
      page: state.collectionPage,
    };
  } catch (err) {
    if (seq !== collectionRequestSeq) return;
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="10" class="empty-msg">${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

function applyCollectionViewCache(cache) {
  if (!cache || cache.folder !== state.collectionFolder) return false;
  state.collectionStats = cache.stats;
  state.collectionTotal = cache.total;
  state.collectionPage = cache.page;
  renderCollectionStatsLine();
  renderCollectionSidebar();
  renderCollectionTable(cache.items);
  renderCollectionPagination();
  return true;
}

async function loadCollectionView({ background = false } = {}) {
  const loggedIn = Boolean(state.token && state.user);
  $("#collection-login-prompt")?.classList.toggle("hidden", loggedIn);
  $("#collection-main")?.classList.toggle("hidden", !loggedIn);
  if (!loggedIn) return;

  if (background && applyCollectionViewCache(state.collectionViewCache)) {
    loadCollectionViewFresh().catch((err) => {
      const tbody = $("#collection-tbody");
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="10" class="empty-msg">${escapeHtml(err.message)}</td></tr>`;
      }
    });
    return;
  }

  try {
    await loadCollectionViewFresh();
  } catch (err) {
    const tbody = $("#collection-tbody");
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="10" class="empty-msg">${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

async function loadCollectionViewFresh() {
  await loadCollectionStats();
  renderCollectionStatsLine();
  renderCollectionSidebar();
  await loadCollectionPage(state.collectionPage);
}

async function refreshCollectionIfActive() {
  if (state.activeView === "collection" && state.token) {
    await loadCollectionView();
  }
}

function downloadRejectedCsv(csvText) {
  downloadCsvBlob(csvText, "rejected_cards.csv");
}

function downloadCsvBlob(csvText, filename) {
  const blob = new Blob(["\ufeff", csvText], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function loadExportFormats() {
  if (state.exportFormats) return state.exportFormats;
  state.exportFormats = await api("/collection/export-formats");
  return state.exportFormats;
}

function renderExportFormatOptions(formats) {
  const list = $("#export-format-list");
  if (!list) return;
  list.innerHTML = formats
    .map(
      (fmt, index) => `
    <label class="export-format-option">
      <input type="radio" name="export-format" value="${escapeHtml(fmt.id)}"${
        index === 0 ? " checked" : ""
      } />
      <span class="export-format-label">${escapeHtml(fmt.label)}</span>
    </label>`
    )
    .join("");
  const note = $("#export-format-note");
  if (note && formats[0]?.description) {
    note.textContent = formats[0].description;
  }
  list.querySelectorAll('input[name="export-format"]').forEach((input) => {
    input.addEventListener("change", () => {
      const selected = formats.find((f) => f.id === input.value);
      if (note && selected) note.textContent = selected.description || "";
    });
  });
}

function syncExportFolderSelection() {
  const list = $("#export-folder-list");
  const master = $("#export-folder-all");
  const summary = $("#export-folder-summary");
  const confirmBtn = $("#export-collection-confirm");
  if (!list || list.hidden) return;

  const inputs = list.querySelectorAll('input[name="export-folder"]');
  const checked = list.querySelectorAll('input[name="export-folder"]:checked');
  const total = inputs.length;
  const count = checked.length;

  if (master) {
    master.indeterminate = count > 0 && count < total;
    master.checked = count === total;
  }
  if (summary) {
    if (count === 0) {
      summary.textContent = "No folders selected";
    } else if (count === total) {
      summary.textContent = `All folders (${total})`;
    } else {
      summary.textContent = `${count} of ${total} folders`;
    }
  }
  if (confirmBtn) confirmBtn.disabled = count === 0;
}

function renderExportFolderOptions(stats) {
  const list = $("#export-folder-list");
  if (!list) return;
  const options = [];
  if (stats.no_folder_count > 0) {
    options.push({ value: NO_FOLDER, label: "No Folder" });
  }
  for (const folder of stats.folders || []) {
    options.push({ value: String(folder.id), label: folder.name });
  }
  if (!options.length) {
    list.hidden = true;
    const confirmBtn = $("#export-collection-confirm");
    if (confirmBtn) confirmBtn.disabled = false;
    return;
  }
  list.hidden = false;
  list.innerHTML = `
    <legend>Folders</legend>
    <label class="export-folder-master check">
      <input type="checkbox" id="export-folder-all" checked />
      <span>All folders</span>
    </label>
    <p id="export-folder-summary" class="export-folder-summary muted"></p>
    <div class="export-folder-options">
      ${options
        .map(
          (opt) => `
        <label class="export-folder-option check">
          <input type="checkbox" name="export-folder" value="${escapeHtml(opt.value)}" checked />
          <span>${escapeHtml(opt.label)}</span>
        </label>`
        )
        .join("")}
    </div>`;

  const master = $("#export-folder-all");
  master?.addEventListener("change", () => {
    const checked = master.checked;
    list.querySelectorAll('input[name="export-folder"]').forEach((input) => {
      input.checked = checked;
    });
    syncExportFolderSelection();
  });
  list.querySelectorAll('input[name="export-folder"]').forEach((input) => {
    input.addEventListener("change", syncExportFolderSelection);
  });
  syncExportFolderSelection();
}

function getSelectedExportFolders() {
  const inputs = document.querySelectorAll('input[name="export-folder"]');
  if (!inputs.length) return null;
  const checked = document.querySelectorAll('input[name="export-folder"]:checked');
  if (!checked.length) return [];
  if (checked.length === inputs.length) return null;
  return [...checked].map((input) => input.value);
}

let exportCollectionTrigger = null;

function openExportCollectionModal() {
  const dlg = $("#export-collection-modal");
  const trigger = $("#export-collection-btn");
  if (!dlg) return;
  exportCollectionTrigger = trigger;
  dlg.hidden = false;
  syncModalOpenClass();
  $("#export-collection-close")?.focus();
}

function closeExportCollectionModal() {
  const dlg = $("#export-collection-modal");
  if (!dlg || dlg.hidden) return;
  dlg.hidden = true;
  syncModalOpenClass();
  (exportCollectionTrigger ?? $("#export-collection-btn"))?.focus();
  exportCollectionTrigger = null;
}

async function downloadCollectionExport(formatId, folderIds = null) {
  const headers = { Accept: "text/csv" };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const params = new URLSearchParams({ format: formatId });
  if (folderIds) {
    for (const id of folderIds) params.append("folders", id);
  }
  const res = await fetch(`${API}/collection/export-csv?${params}`, { headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  const formats = state.exportFormats || [];
  const fmt = formats.find((f) => f.id === formatId);
  const filename = fmt?.filename || "collection_export.csv";
  const csvText = await res.text();
  const body = csvText.startsWith("\ufeff") ? csvText.slice(1) : csvText;
  downloadCsvBlob(body, filename);
}

function decksListCacheKey() {
  return `${state.decksQuery}\0${state.decksSort}`;
}

async function fetchDecksList(force = false) {
  if (!state.token) return [];
  const cacheKey = decksListCacheKey();
  if (state.decksListCache && state.decksListCache.key === cacheKey && !force) {
    return state.decksListCache.decks;
  }
  const params = new URLSearchParams();
  if (state.decksQuery.trim()) params.set("q", state.decksQuery.trim());
  if (state.decksSort) params.set("sort", state.decksSort);
  const qs = params.toString();
  const decks = await api(`/decks${qs ? `?${qs}` : ""}`);
  state.decksListCache = { key: cacheKey, decks };
  return decks;
}

function invalidateDecksCache() {
  state.decksListCache = null;
}

function formatRelativeDateParts(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const absolute = d.toLocaleString(undefined, {
    dateStyle: "full",
    timeStyle: "short",
  });
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  if (diffMs < 60 * 1000) {
    return { relative: "just now", absolute, iso: d.toISOString() };
  }
  const diffMins = Math.floor(diffMs / (60 * 1000));
  if (diffMins < 60) {
    return { relative: `${diffMins} min ago`, absolute, iso: d.toISOString() };
  }
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfDate = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffDays = Math.round((startOfToday - startOfDate) / (24 * 60 * 60 * 1000));
  if (diffDays === 0) {
    const timeStr = d.toLocaleString(undefined, { timeStyle: "short" });
    return { relative: `today at ${timeStr}`, absolute, iso: d.toISOString() };
  }
  if (diffDays === 1) return { relative: "yesterday", absolute, iso: d.toISOString() };
  if (diffDays > 1 && diffDays < 7) {
    return { relative: `${diffDays} days ago`, absolute, iso: d.toISOString() };
  }
  return {
    relative: d.toLocaleString(undefined, { dateStyle: "medium" }),
    absolute,
    iso: d.toISOString(),
  };
}

function formatDeckDate(iso) {
  const parts = formatRelativeDateParts(iso);
  return parts ? parts.relative : "";
}

function renderDeckTimeHtml(iso, prefix = "Edited") {
  const parts = formatRelativeDateParts(iso);
  if (!parts) return "";
  return `${escapeHtml(prefix)} <time datetime="${escapeHtml(parts.iso)}" title="${escapeHtml(parts.absolute)}">${escapeHtml(parts.relative)}</time>`;
}

function deckCardCount(deck) {
  if (deck.card_count != null) return deck.card_count;
  return (deck.cards || []).reduce((sum, c) => sum + c.quantity, 0);
}

function renderDeckStack(previewCards) {
  const cards = previewCards?.length ? previewCards : [{ image_url: null }];
  const stack = cards.slice(0, 3);
  return stack
    .map((c) => cardImgTag(c.image_url || null, 'class="deck-stack-card"'))
    .join("");
}

function renderDecksGrid(decks) {
  const grid = $("#decks-grid");
  const empty = $("#decks-empty");
  if (!grid) return;
  if (!decks.length) {
    grid.innerHTML = "";
    empty?.classList.remove("hidden");
    return;
  }
  empty?.classList.add("hidden");
  grid.innerHTML = decks
    .map((d) => {
      const countLabel = d.card_count === 1 ? "1 card" : `${d.card_count} cards`;
      const dateLine =
        state.decksSort === "updated_at" && d.updated_at
          ? `<span class="deck-tile-date muted">${renderDeckTimeHtml(d.updated_at, "Edited")}</span>`
          : "";
      return `
    <article class="deck-tile" data-id="${d.id}" tabindex="0" role="button" aria-label="${escapeHtml(d.name)}, ${countLabel}">
      <button type="button" class="deck-tile-delete" data-id="${d.id}" title="Delete deck" aria-label="Delete ${escapeHtml(d.name)}">×</button>
      <div class="deck-stack">${renderDeckStack(d.preview_cards)}</div>
      <div class="deck-tile-meta">
        <span class="deck-tile-name">${escapeHtml(d.name)}</span>
        <span class="deck-tile-count">${countLabel}</span>
        ${dateLine}
      </div>
    </article>`;
    })
    .join("");

  grid.querySelectorAll(".deck-tile").forEach((tile) => {
    tile.addEventListener("click", (e) => {
      if (e.target.closest(".deck-tile-delete")) return;
      openDeckDetail(Number(tile.dataset.id));
    });
    tile.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openDeckDetail(Number(tile.dataset.id));
      }
    });
  });

  grid.querySelectorAll(".deck-tile-delete").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const deckId = Number(btn.dataset.id);
      const deck = decks.find((d) => d.id === deckId);
      const label = deck?.name || "this deck";
      if (!confirm(`Delete deck "${label}"? This cannot be undone.`)) return;
      await api(`/decks/${deckId}`, { method: "DELETE" });
      if (state.activeDeckId === deckId) {
        state.activeDeckId = null;
        closeDeckDetail();
      }
      invalidateDecksCache();
      await loadDecks({ force: true });
      await populateDeckSelect();
    });
  });
}

function showDecksListView() {
  state.decksDetailOpen = false;
  $("#decks-list-view")?.classList.remove("hidden");
  $("#decks-detail-view")?.classList.add("hidden");
}

function showDecksDetailView() {
  state.decksDetailOpen = true;
  $("#decks-list-view")?.classList.add("hidden");
  $("#decks-detail-view")?.classList.remove("hidden");
}

function closeDeckDetail({ fromRouter = false } = {}) {
  state.activeDeckId = null;
  state.activeDeckDetail = null;
  showDecksListView();
  updateRouteDocumentTitle();
  if (!fromRouter) syncRouteHash();
}

function showDeckDetailLoading() {
  const nameEl = $("#deck-name");
  if (nameEl) nameEl.textContent = "Loading…";
  const metaEl = $("#deck-meta");
  if (metaEl) {
    metaEl.innerHTML = "";
    metaEl.removeAttribute("aria-label");
  }
  $("#deck-zones").innerHTML = ["main", "extra", "side"]
    .map(
      (zone) => `
    <section class="deck-zone-row deck-zone-row--loading">
      <h3 class="deck-zone-label">${deckZoneLabel(zone)}</h3>
      <div class="deck-zone-cards">
        <div class="skeleton deck-card-skeleton" aria-hidden="true"></div>
        <div class="skeleton deck-card-skeleton" aria-hidden="true"></div>
        <div class="skeleton deck-card-skeleton" aria-hidden="true"></div>
      </div>
    </section>`
    )
    .join("");
  $("#decks-detail-view")?.setAttribute("aria-busy", "true");
}

function renderDeckDetailMeta(deck) {
  const metaEl = $("#deck-meta");
  if (!metaEl) return;
  const count = deckCardCount(deck);
  const countLabel = count === 1 ? "1 card" : `${count} cards`;
  const parts = formatRelativeDateParts(deck.updated_at);
  if (parts) {
    metaEl.innerHTML = `
      <span class="deck-meta-stat">${escapeHtml(countLabel)}</span>
      <span class="deck-meta-edited">${renderDeckTimeHtml(deck.updated_at, "Edited")}</span>`;
    metaEl.setAttribute("aria-label", `${countLabel}, edited ${parts.relative}`);
  } else {
    metaEl.innerHTML = `<span class="deck-meta-stat">${escapeHtml(countLabel)}</span>`;
    metaEl.setAttribute("aria-label", countLabel);
  }
}

async function populateDeckSelect() {
  const sel = $("#deck-target");
  if (!sel) return;
  if (!state.token) {
    sel.innerHTML = "";
    return;
  }
  const decks = await fetchDecksList();
  if (!decks.length) {
    sel.innerHTML =
      '<option value="" disabled selected>No decks — create one in Decks tab</option>';
    return;
  }
  sel.innerHTML = decks
    .map(
      (d) =>
        `<option value="${d.id}">${escapeHtml(d.name)} (#${d.id})</option>`
    )
    .join("");
  const preferred =
    state.activeDeckId && decks.some((d) => d.id === state.activeDeckId)
      ? state.activeDeckId
      : decks[0].id;
  sel.value = String(preferred);
}

function deckZoneLabel(zone) {
  if (zone === "main") return "Main deck";
  if (zone === "extra") return "Extra deck";
  return "Side deck";
}

function renderDeckCardSlot(deck, card, zone) {
  const imgUrl = card.image_url || card.image_url_small || null;
  const isCover = deck.preview_card_id === card.card_id;
  return `
    <div class="deck-card-slot${isCover ? " is-cover" : ""}" data-card="${card.card_id}" data-zone="${zone}">
      ${cardImgTag(imgUrl)}
      <div class="deck-card-actions">
        <button type="button" class="deck-cover-btn${isCover ? " is-active" : ""}" title="Set as deck cover" aria-label="Set as deck cover">★</button>
        <button type="button" class="deck-minus-btn" title="Remove one" aria-label="Remove one">−</button>
      </div>
    </div>`;
}

async function loadDecks({ background = false, force = false } = {}) {
  const loginMsg = $("#decks-login-msg");
  const empty = $("#decks-empty");
  if (!state.token) {
    $("#decks-grid").innerHTML = "";
    loginMsg?.classList.remove("hidden");
    empty?.classList.add("hidden");
    return;
  }
  loginMsg?.classList.add("hidden");

  if (background && state.decksListCache && !force) {
    renderDecksGrid(state.decksListCache.decks);
    await populateDeckSelect();
    fetchDecksList(true)
      .then((decks) => {
        renderDecksGrid(decks);
        return populateDeckSelect();
      })
      .catch(() => {});
    return;
  }

  const decks = await fetchDecksList(force || !background);
  renderDecksGrid(decks);
  await populateDeckSelect();
}

function renderDeckDetail(deckId, deck) {
  state.activeDeckDetail = deck;
  const nameEl = $("#deck-name");
  if (nameEl) {
    nameEl.textContent = deck.name;
    nameEl.title = "Double-click to rename";
  }
  renderDeckDetailMeta(deck);
  updateRouteDocumentTitle();

  const zones = { main: [], extra: [], side: [] };
  deck.cards.forEach((c) => zones[c.zone]?.push(c));

  $("#deck-zones").innerHTML = ["main", "extra", "side"]
    .map((zone) => {
      const cards = zones[zone];
      const slots = [];
      cards.forEach((c) => {
        for (let i = 0; i < c.quantity; i += 1) {
          slots.push(renderDeckCardSlot(deck, c, zone));
        }
      });
      return `
        <section class="deck-zone-row">
          <h3 class="deck-zone-label">${deckZoneLabel(zone)}</h3>
          <div class="deck-zone-cards">
            ${
              slots.length
                ? slots.join("")
                : '<span class="deck-zone-empty">Empty</span>'
            }
          </div>
        </section>`;
    })
    .join("");

  $("#deck-zones").querySelectorAll(".deck-card-slot").forEach((slot) => {
    const cardId = Number(slot.dataset.card);
    const zone = slot.dataset.zone;
    slot.querySelector(".deck-minus-btn")?.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!state.activeDeckDetail || state.activeDeckDetail.id !== deckId) return;
      const snapshot = JSON.parse(JSON.stringify(state.activeDeckDetail));
      const card = snapshot.cards.find((c) => c.card_id === cardId && c.zone === zone);
      const newQty = (card?.quantity || 1) - 1;
      const cards = snapshot.cards
        .map((c) =>
          c.card_id === cardId && c.zone === zone ? { ...c, quantity: newQty } : c
        )
        .filter((c) => c.quantity > 0);
      const optimistic = {
        ...snapshot,
        cards,
        card_count: cards.reduce((sum, c) => sum + c.quantity, 0),
      };
      renderDeckDetail(deckId, optimistic);
      try {
        const updated = await api(
          `/decks/${deckId}/cards/${cardId}?zone=${zone}&quantity=${newQty}`,
          { method: "PATCH" }
        );
        if (state.activeDeckId !== deckId) return;
        renderDeckDetail(deckId, updated);
        invalidateDecksCache();
      } catch (err) {
        if (state.activeDeckId === deckId) renderDeckDetail(deckId, snapshot);
        alert(err.message);
      }
    });
    slot.querySelector(".deck-cover-btn")?.addEventListener("click", async (e) => {
      e.stopPropagation();
      await setDeckCover(deckId, cardId);
    });
    slot.querySelector("img")?.addEventListener("click", () => openCardModal(cardId));
  });

  $("#decks-detail-view")?.removeAttribute("aria-busy");
}

async function setDeckCover(deckId, cardId) {
  if (!state.activeDeckDetail || state.activeDeckDetail.id !== deckId) return;
  const snapshot = JSON.parse(JSON.stringify(state.activeDeckDetail));
  const optimistic = { ...snapshot, preview_card_id: cardId };
  renderDeckDetail(deckId, optimistic);
  try {
    const updated = await api(`/decks/${deckId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preview_card_id: cardId }),
    });
    if (state.activeDeckId !== deckId) return;
    state.activeDeckDetail = { ...optimistic, ...updated };
    renderDeckDetail(deckId, state.activeDeckDetail);
    invalidateDecksCache();
  } catch (err) {
    if (state.activeDeckId === deckId) renderDeckDetail(deckId, snapshot);
    alert(err.message);
  }
}

async function openDeckDetail(deckId, { fromRouter = false } = {}) {
  state.activeDeckId = deckId;
  const seq = ++deckDetailRequestSeq;
  showDecksDetailView();
  showDeckDetailLoading();
  if (!fromRouter) syncRouteHash();
  try {
    const deck = await api(`/decks/${deckId}`);
    if (seq !== deckDetailRequestSeq || state.activeDeckId !== deckId) return;
    renderDeckDetail(deckId, deck);
  } catch (err) {
    if (seq !== deckDetailRequestSeq) return;
    $("#decks-detail-view")?.removeAttribute("aria-busy");
    const nameEl = $("#deck-name");
    if (nameEl) nameEl.textContent = "Failed to load deck";
    const metaEl = $("#deck-meta");
    if (metaEl) {
      metaEl.innerHTML = "";
      metaEl.removeAttribute("aria-label");
    }
    $("#deck-zones").innerHTML = `<p class="deck-zone-empty modal-load-error">${escapeHtml(err.message || "Failed to load deck.")}</p>`;
    updateRouteDocumentTitle();
  }
}

async function renameDeck() {
  if (!state.token) {
    alert("Log in to rename decks.");
    return;
  }
  if (!state.activeDeckDetail) {
    alert("Open a deck to rename it.");
    return;
  }
  const deckId = state.activeDeckDetail.id;
  const currentName = state.activeDeckDetail.name;
  const newName = prompt("Rename deck:", currentName);
  if (!newName?.trim() || newName.trim() === currentName) return;
  try {
    const updated = await api(`/decks/${deckId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName.trim() }),
    });
    if (state.activeDeckId !== deckId) return;
    state.activeDeckDetail = { ...state.activeDeckDetail, ...updated };
    renderDeckDetail(deckId, state.activeDeckDetail);
    invalidateDecksCache();
    loadDecks({ background: true });
  } catch (err) {
    alert(err.message);
  }
}

async function selectDeck(deckId) {
  await openDeckDetail(deckId);
}

function wireEvents() {
  setupSearchResultsDelegation();
  setupSearchFilterChipDelegation();
  setupCollectionTableDelegation();

  document.querySelectorAll(".tab[data-view]").forEach((tab) => {
    tab.addEventListener("click", () => {
      if (isModalVisible("#card-modal")) {
        closeCardModalOverlay({ fromRouter: true });
      }
      if (tab.dataset.view === "decks" && state.decksDetailOpen) {
        closeDeckDetail({ fromRouter: true });
      }
      switchView(tab.dataset.view);
    });
  });

  window.addEventListener("hashchange", () => {
    if (suppressHashSync) return;
    applyRouteFromHash();
  });

  $("#search-form").addEventListener("submit", runSearch);
  $("#search-form").addEventListener("input", () => renderActiveSearchFilters());
  $("#search-form").addEventListener("change", () => renderActiveSearchFilters());
  $("#search-reset")?.addEventListener("click", async () => {
    resetSearchFilters();
    clearActivePreset();
    await runSearch();
  });
  $("#search-clear-filters")?.addEventListener("click", async () => {
    resetSearchFilters();
    clearActivePreset();
    await runSearch();
  });
  $("#search-preset-select")?.addEventListener("change", async () => {
    const presetId = Number($("#search-preset-select")?.value);
    if (presetId) await loadSearchPresetById(presetId);
    else clearActivePreset();
  });
  $("#search-preset-save")?.addEventListener("click", () => {
    saveSearchPreset().catch((err) =>
      showToast(err.message, { variant: "error", durationMs: 5000 })
    );
  });
  $("#search-preset-menu-btn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    togglePresetMenu();
  });
  $("#search-preset-rename")?.addEventListener("click", () => {
    closePresetMenu();
    renameSearchPreset().catch((err) =>
      showToast(err.message, { variant: "error", durationMs: 5000 })
    );
  });
  $("#search-preset-delete")?.addEventListener("click", () => {
    closePresetMenu();
    deleteSearchPreset().catch((err) =>
      showToast(err.message, { variant: "error", durationMs: 5000 })
    );
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".preset-menu-wrap:not(.collection-row-menu-wrap)")) closePresetMenu();
    if (!e.target.closest(".collection-row-menu-wrap")) closeAllCollectionRowMenus();
  });
  $("#auth-tab-login")?.addEventListener("click", () => {
    switchAuthTab("login");
    $("#login-email")?.focus();
  });
  $("#auth-tab-register")?.addEventListener("click", () => {
    switchAuthTab("register");
    $("#register-email")?.focus();
  });

  $("#auth-login-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await submitAuthForm(
        e.target,
        async () => {
          await login($("#login-email").value, $("#login-password").value);
          focusAppEntry();
        },
        { busyLabel: "Signing in…" }
      );
    } catch {
      /* errors handled in submitAuthForm */
    }
  });

  $("#auth-register-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await submitAuthForm(
        e.target,
        async () => {
          await register($("#register-email").value, $("#register-password").value);
          if (!pendingVerifyEmail) {
            focusAppEntry();
          } else {
            showToast("Check your email for the verification code.");
          }
        },
        { busyLabel: "Creating account…" }
      );
    } catch {
      /* errors handled in submitAuthForm */
    }
  });

  $("#auth-verify-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = pendingVerifyEmail || $("#register-email")?.value;
    if (!email) {
      showAuthError("Missing email for verification.");
      return;
    }
    try {
      await submitAuthForm(
        e.target,
        async () => {
          await verifyEmail(email, $("#verify-code").value.trim());
          focusAppEntry();
        },
        { busyLabel: "Verifying…", successToast: "Email verified — welcome!" }
      );
    } catch {
      /* errors handled in submitAuthForm */
    }
  });

  $("#verify-resend-btn")?.addEventListener("click", async () => {
    const email = pendingVerifyEmail;
    if (!email) return;
    const btn = $("#verify-resend-btn");
    if (btn?.disabled) return;
    clearAuthError();
    setButtonBusy(btn, true, { busyLabel: "Sending…" });
    try {
      await resendVerificationCode(email);
      showToast("If your registration is pending, a new code was sent.");
    } catch (err) {
      showAuthError(err.message || "Could not resend code.");
      showToast(err.message || "Could not resend code.", { variant: "error", durationMs: 5000 });
    } finally {
      setButtonBusy(btn, false);
    }
  });

  $("#verify-back-btn")?.addEventListener("click", () => {
    pendingVerifyEmail = null;
    switchAuthTab("register");
    $("#register-email")?.focus();
  });

  $("#auth-logout")?.addEventListener("click", logout);

  $("#import-collection-btn")?.addEventListener("click", () => {
    if (!state.token) {
      alert("Log in first.");
      return;
    }
    $("#collection-csv-file")?.click();
  });

  $("#export-collection-btn")?.addEventListener("click", async () => {
    if (!state.token) {
      alert("Log in first.");
      return;
    }
    try {
      const [formats, stats] = await Promise.all([
        loadExportFormats(),
        api("/collection/stats"),
      ]);
      if (!formats.length) {
        alert("No export formats available.");
        return;
      }
      state.collectionStats = stats;
      renderExportFormatOptions(formats);
      renderExportFolderOptions(stats);
      openExportCollectionModal();
    } catch (err) {
      alert(err.message);
    }
  });

  $("#export-collection-cancel")?.addEventListener("click", closeExportCollectionModal);
  $("#export-collection-close")?.addEventListener("click", closeExportCollectionModal);
  $("#export-collection-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#export-collection-modal")) closeExportCollectionModal();
  });

  $("#search-preset-save-cancel")?.addEventListener("click", () =>
    closeSearchPresetSaveModal(null)
  );
  $("#search-preset-save-close")?.addEventListener("click", () =>
    closeSearchPresetSaveModal(null)
  );
  $("#search-preset-save-overwrite")?.addEventListener("click", () =>
    closeSearchPresetSaveModal("overwrite")
  );
  $("#search-preset-save-new")?.addEventListener("click", () =>
    closeSearchPresetSaveModal("new")
  );
  $("#search-preset-save-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#search-preset-save-modal")) closeSearchPresetSaveModal(null);
  });

  $("#collection-edit-cancel")?.addEventListener("click", closeCollectionEditModal);
  $("#collection-edit-close")?.addEventListener("click", closeCollectionEditModal);
  $("#collection-edit-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#collection-edit-modal")) closeCollectionEditModal();
  });
  $("#collection-edit-save")?.addEventListener("click", saveCollectionEdit);
  $("#collection-edit-set")?.addEventListener("change", () => {
    if (!collectionEditContext) return;
    populateCollectionEditRarity(
      collectionEditContext.printings,
      $("#collection-edit-set").value,
      collectionEditContext.item
    );
  });

  $("#collection-add-cancel")?.addEventListener("click", closeAddCollectionModal);
  $("#collection-add-close")?.addEventListener("click", closeAddCollectionModal);
  $("#collection-add-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#collection-add-modal")) closeAddCollectionModal();
  });
  $("#collection-add-submit")?.addEventListener("click", submitAddCollection);
  $("#collection-add-card-number")?.addEventListener("change", syncAddCollectionPrintingFields);
  $("#collection-add-new-folder-toggle")?.addEventListener("click", () => {
    $("#collection-add-new-folder-row")?.classList.toggle("hidden");
    $("#collection-add-new-folder-name")?.focus();
  });
  $("#collection-add-new-folder-create")?.addEventListener("click", createFolderFromAddModal);
  $("#collection-add-new-folder-name")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      createFolderFromAddModal();
    }
  });

  $("#export-collection-confirm")?.addEventListener("click", async () => {
    const selected = document.querySelector('input[name="export-format"]:checked');
    if (!selected) {
      alert("Choose an export format.");
      return;
    }
    const confirmBtn = $("#export-collection-confirm");
    if (confirmBtn) confirmBtn.disabled = true;
    try {
      const folderIds = getSelectedExportFolders();
      await downloadCollectionExport(selected.value, folderIds);
      closeExportCollectionModal();
    } catch (err) {
      alert(err.message);
    } finally {
      if (confirmBtn) confirmBtn.disabled = false;
    }
  });

  $("#collection-csv-file")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!confirm(`Import ${file.name}? This replaces your collection.`)) {
      e.target.value = "";
      return;
    }
    const form = new FormData();
    form.append("file", file);
    const importBtn = $("#import-collection-btn");
    if (importBtn) importBtn.disabled = true;
    setImportStatusLine(0, 0, null);
    try {
      const res = await fetch(`${API}/collection/import-csv?replace=true`, {
        method: "POST",
        headers: state.token ? { Authorization: `Bearer ${state.token}` } : {},
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || res.statusText);
      }
      const done = await readNdjsonStream(res, (ev) => {
        if (ev.type === "progress") {
          setImportStatusLine(ev.current, ev.total, ev.eta_seconds);
        }
      });
      if (!done) throw new Error("Import finished without confirmation");
      if (done.rejected_count > 0 && done.rejected_csv) {
        downloadRejectedCsv(done.rejected_csv);
        alert(
          `Imported ${done.imported} rows. ${done.rejected_count} could not be matched — downloaded as rejected_cards.csv.`
        );
      } else {
        alert(`Imported ${done.imported} rows.`);
      }
      await loadStatus();
      await refreshOwnedSearchState();
      await refreshCollectionIfActive();
    } catch (err) {
      alert(err.message);
      await loadStatus();
    } finally {
      clearImportStatusLine();
      if (importBtn) importBtn.disabled = false;
      e.target.value = "";
    }
  });

  $("#collection-new-folder-btn")?.addEventListener("click", createCollectionFolder);

  $("#collection-filter-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    state.collectionPage = 0;
    await loadCollectionPage(0);
  });

  $("#modal-close").addEventListener("click", closeCardModalOverlay);
  $("#card-modal").addEventListener("click", (e) => {
    if (e.target === $("#card-modal")) closeCardModalOverlay();
  });
  $("#modal-passcode-copy")?.addEventListener("click", async () => {
    if (state.currentCardId == null) return;
    const code = formatPasscode(state.currentCardId);
    try {
      await navigator.clipboard.writeText(code);
      showToast("Passcode copied");
    } catch {
      showToast("Could not copy passcode", { variant: "error" });
    }
  });
  $("#modal-errata-open")?.addEventListener("click", openCardErrataModal);
  $("#modal-tips-trigger")?.addEventListener("click", openCardTipsModal);
  $("#card-errata-close")?.addEventListener("click", closeCardErrataModal);
  $("#card-tips-close")?.addEventListener("click", closeCardTipsModal);
  $("#card-errata-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#card-errata-modal")) closeCardErrataModal();
  });
  $("#card-tips-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#card-tips-modal")) closeCardTipsModal();
  });

  $("#search-help-btn")?.addEventListener("click", openSearchHelp);
  $("#search-help-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#search-help-modal")) closeSearchHelp();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (document.querySelector(".folder-allocation-popover:not(.move-copy-popover)")) {
      closeFolderAllocationPopover();
    } else if (document.querySelector(".collection-row-menu:not([hidden])")) closeAllCollectionRowMenus();
    else if (!$("#search-preset-menu")?.hidden) closePresetMenu();
    else if (isModalVisible("#search-preset-save-modal")) closeSearchPresetSaveModal(null);
    else if (isModalVisible("#collection-add-modal")) closeAddCollectionModal();
    else if (isModalVisible("#collection-edit-modal")) closeCollectionEditModal();
    else if (isModalVisible("#export-collection-modal")) closeExportCollectionModal();
    else if (isModalVisible("#card-tips-modal")) closeCardTipsModal();
    else if (isModalVisible("#card-errata-modal")) closeCardErrataModal();
    else if (isSearchHelpOpen()) closeSearchHelp();
    else if (isModalVisible("#card-modal")) closeCardModalOverlay();
  });

  $("#modal-favorite").addEventListener("click", async () => {
    if (!state.token) {
      alert("Log in to use favorites.");
      return;
    }
    const btn = $("#modal-favorite");
    if (btn.disabled) return;

    const wasFavorite = state.currentCard?.is_favorite ?? false;
    const newFavorite = !wasFavorite;

    if (state.currentCard) {
      state.currentCard.is_favorite = newFavorite;
      btn.textContent = newFavorite ? "★ Favorited" : "☆ Favorite";
    }
    btn.disabled = true;

    try {
      await api(`/cards/${state.currentCardId}/favorite`, { method: "POST" });
    } catch (err) {
      if (state.currentCard) {
        state.currentCard.is_favorite = wasFavorite;
        btn.textContent = wasFavorite ? "★ Favorited" : "☆ Favorite";
      }
      showToast(err.message || "Failed to update favorite.", { variant: "error", durationMs: 5000 });
    } finally {
      btn.disabled = false;
    }
  });

  $("#tag-add-btn").addEventListener("click", async () => {
    if (!state.token) {
      alert("Log in to add tags.");
      return;
    }
    const tag = $("#tag-input").value.trim();
    if (!tag) return;
    const btn = $("#tag-add-btn");
    try {
      await runModalAction(
        btn,
        async () => {
          await api(`/cards/${state.currentCardId}/tags`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tag }),
          });
          $("#tag-input").value = "";
          if (state.currentCard) {
            const tags = state.currentCard.tags || [];
            if (!tags.includes(tag)) {
              state.currentCard.tags = [...tags, tag];
              renderModalTags(state.currentCard.tags);
            }
          }
          await loadUserTags();
        },
        { busyLabel: "Adding…", successMessage: `Tag "${tag}" added` }
      );
    } catch {
      // runModalAction already surfaced the error toast
    }
  });

  $("#tag-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      $("#tag-add-btn")?.click();
    }
  });

  $("#modal-tags")?.addEventListener("click", async (e) => {
    const removeBtn = e.target.closest(".tag-remove");
    if (removeBtn) {
      if (!state.token) {
        alert("Log in to manage tags.");
        return;
      }
      const tagEl = removeBtn.closest(".tag");
      const labelBtn = tagEl?.querySelector(".tag-label");
      const tag = labelBtn?.textContent?.trim();
      if (!tag || !state.currentCardId) return;
      if (removeBtn.disabled) return;
      try {
        await runModalAction(
          removeBtn,
          async () => {
            await api(
              `/cards/${state.currentCardId}/tags/${encodeURIComponent(tag)}`,
              { method: "DELETE" }
            );
            if (state.currentCard) {
              state.currentCard.tags = (state.currentCard.tags || []).filter((t) => t !== tag);
              renderModalTags(state.currentCard.tags);
            }
            await loadUserTags();
          },
          { busyLabel: "Removing…", successMessage: `Tag "${tag}" removed` }
        );
      } catch {
        // runModalAction already surfaced the error toast
      }
      return;
    }

    const labelBtn = e.target.closest(".tag-label");
    if (labelBtn) {
      const tag = labelBtn.textContent?.trim();
      if (tag) await searchByTag(tag);
    }
  });

  $("#owned-add-btn").addEventListener("click", () => {
    if (!state.currentCard) return;
    const preselectKey = addCollectionSelectedPrintingKey;
    openAddCollectionModal(state.currentCard, { printingKey: preselectKey });
  });

  $("#modal-printings")?.addEventListener("click", (e) => {
    const row = e.target.closest(".printing-row--selectable");
    if (!row?.dataset.printingKey) return;
    void activateModalPrintingRow(row);
  });
  $("#modal-printings")?.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const row = e.target.closest(".printing-row--selectable");
    if (!row?.dataset.printingKey) return;
    e.preventDefault();
    void activateModalPrintingRow(row);
  });

  $("#deck-add-card-btn").addEventListener("click", async () => {
    if (!state.token) {
      showToast("Log in to add cards to a deck.", { variant: "error" });
      return;
    }
    const deckId = Number($("#deck-target").value);
    if (!deckId) {
      showToast("Create a deck first (Decks tab → New deck).", { variant: "error", durationMs: 5000 });
      return;
    }
    const zone = $("#deck-zone").value;
    const zoneLabel = zone.charAt(0).toUpperCase() + zone.slice(1);
    const btn = $("#deck-add-card-btn");
    try {
      await runModalAction(
        btn,
        async () => {
          const deck = await api(`/decks/${deckId}/cards`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ card_id: state.currentCardId, zone, quantity: 1 }),
          });
          invalidateDecksCache();
          if (deckId === state.activeDeckId && state.decksDetailOpen) {
            renderDeckDetail(deckId, deck);
          }
        },
        { busyLabel: "Adding…", successMessage: `Added to ${zoneLabel} deck` }
      );
    } catch {
      // runModalAction already surfaced the error toast
    }
  });

  $("#decks-back-btn")?.addEventListener("click", () => {
    closeDeckDetail();
    loadDecks({ background: true });
  });

  $("#deck-rename-btn")?.addEventListener("click", () => {
    renameDeck().catch((err) => alert(err.message));
  });
  $("#deck-name")?.addEventListener("dblclick", () => {
    renameDeck().catch((err) => alert(err.message));
  });

  $("#decks-sort")?.addEventListener("change", () => {
    state.decksSort = $("#decks-sort")?.value || "updated_at";
    invalidateDecksCache();
    loadDecks({ force: true });
  });

  $("#decks-q")?.addEventListener("input", () => {
    clearTimeout(decksSearchTimer);
    decksSearchTimer = setTimeout(() => {
      state.decksQuery = $("#decks-q")?.value || "";
      invalidateDecksCache();
      loadDecks({ force: true });
    }, 300);
  });

  $("#new-deck-btn").addEventListener("click", async () => {
    const name = prompt("Deck name:");
    if (!name?.trim()) return;
    const deck = await api("/decks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    invalidateDecksCache();
    state.activeDeckId = deck.id;
    await loadDecks({ force: true });
    selectDeck(deck.id);
  });
}

async function init() {
  wireEvents();
  await loadAuthConfig();
  updateAuthUI();
  try {
    if (state.token) {
      showAuthChecking();
      try {
        state.user = await api("/auth/me");
      } catch {
        state.token = null;
        state.user = null;
        localStorage.removeItem("ygo_token");
      }
    }

    if (state.token && state.user) {
      setAuthenticatedShell(true);
      updateAuthUI();
      await bootstrapAuthenticatedApp();
    } else {
      setAuthenticatedShell(false);
      switchAuthTab("login");
      showAuthLanding();
      updateAuthUI();
    }
  } catch (err) {
    showToast(err.message || "Something went wrong.", {
      variant: "error",
      durationMs: 5000,
    });
    setAuthenticatedShell(false);
    switchAuthTab("login");
    showAuthLanding();
  }
}

init();
