import {
  closeBulkCollectionModal,
  initBulkCollection,
  isBulkCollectionSaving,
  refreshBulkCollectionAuthVisibility,
  refreshBulkCollectionCurrency,
} from "./bulk-collection.js";
import {
  COLLECTION_CONDITIONS,
  COLLECTION_EDITIONS,
  conditionBadgeHtml,
  editionBadgeHtml,
  normalizeConditionValue,
  normalizeEditionValue,
} from "./condition-edition-badges.js";
import { createFilterCombobox } from "./filter-combobox.js";
import { rarityBadgeHtml } from "./rarity-badges.js";
import {
  bindDetailsPanelToggle,
  bindSortDirToggle,
  bindTableHeaderSort,
  readSortDir,
  setSortDir,
  syncSortToggleLabel,
  syncTableHeaderSort,
} from "./sort-controls.js";
import {
  appConfirm,
  appPrompt,
  cancelAppDialog,
  initAppDialogs,
  isAppDialogOpen,
} from "./ui-dialogs.js";

const API = "/api";
const CURRENCY_STORAGE_KEY = "ygo-currency";

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
  deckSaved: null,
  deckDraft: null,
  deckDirty: false,
  activePresetId: null,
  searchPresets: [],
  searchResultsById: {},
  formatsList: [],
  banlistsByFormat: {},
  genesysPointLists: [],
  zoneTooltips: {},
  tradeSettings: null,
  currency: "EUR",
  publicConfig: {
    eur_huf_rate: 390,
    eur_huf_rate_source: "fallback",
    eur_huf_rate_as_of: null,
  },
};

let searchRequestSeq = 0;
let collectionRequestSeq = 0;
let deckDetailRequestSeq = 0;
let deckValidationPreviewSeq = 0;
let deckValidationPreviewTimer = null;
let decksSearchTimer = null;
let searchEverLoaded = false;

const COLLECTION_PAGE_SIZE = 100;
const NO_FOLDER = "__no_folder__";
const COLLECTION_FOLDER_ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>`;
const INFO_ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></svg>`;
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
  "for_trade_only",
  "format",
  "banlist_revision_id",
  "banlist_status",
  "genesys_point_list_id",
  "points_min",
  "points_max",
  "sort",
  "sort_dir",
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
    const leavingDirtyDeck =
      state.decksDetailOpen &&
      state.deckDirty &&
      (view !== "decks" ||
        route.invalid ||
        !route.deckId ||
        route.deckId !== state.activeDeckId);
    if (!initial && leavingDirtyDeck && !(await confirmLeaveDeck())) {
      syncRouteHash({ replace: true });
      return;
    }
    if (!route.invalid && route.deckId) {
      if (!(state.decksDetailOpen && state.activeDeckId === route.deckId)) {
        await openDeckDetail(route.deckId, { fromRouter: true });
      }
    } else {
      closeDeckDetail({ fromRouter: true });
    }
  }

  if (view === "search" && (initial || needsSearchRun || !searchEverLoaded)) {
    await runSearch(null, { skipHashSync: true });
  }

  if (route.invalid || replaceHash) {
    syncRouteHash({ replace: true });
  }

  lastAppliedRouteHash = window.location.hash;
}

function collectionReleaseDateCell(item) {
  const text = formatNumericDate(item.release_date) || "—";
  const titleAttr = item.release_date ? ` title="${escapeHtml(text)}"` : "";
  return `<td class="collection-release-date"${titleAttr}>${escapeHtml(text)}</td>`;
}

function collectionNotesCell(item) {
  const notes = (item.notes || "").trim();
  if (!notes) {
    return '<td class="collection-notes"></td>';
  }
  return `<td class="collection-notes collection-notes--filled" title="${escapeHtml(notes)}">${escapeHtml(notes)}</td>`;
}

function collectionFolderCell(item) {
  const label = formatFolderAllocationsLabel(item.folders);
  return `<td class="collection-col-folder">${escapeHtml(label)}</td>`;
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
let authConfig = { turnstile_site_key: null, oauth_providers: [] };
let turnstileWidgetId = null;
let pendingVerifyEmail = null;
let resendCooldownInterval = null;

const OAUTH_ICONS = {
  google:
    '<svg class="auth-oauth-icon" viewBox="0 0 24 24" aria-hidden="true"><path fill="#EA4335" d="M12 10.2v3.6h5.1c-.2 1.2-1.6 3.6-5.1 3.6-3.1 0-5.6-2.6-5.6-5.8S8.9 5.8 12 5.8c1.8 0 3 .8 3.7 1.5l2.5-2.4C16.5 3.4 14.4 2.4 12 2.4 6.9 2.4 2.8 6.5 2.8 11.6S6.9 20.8 12 20.8c6.9 0 8.6-4.8 8.6-7.2 0-.5 0-.9-.1-1.2H12z"/><path fill="#34A853" d="M3.9 7.5l3 2.2c.8-2.4 2.9-4 5.1-4 .8 0 1.5.2 2.1.5l2.5-2.4C15.2 2.7 13.7 2 12 2 8.1 2 4.8 4.5 3.9 7.5z"/><path fill="#4A90E2" d="M12 22c3.2 0 5.9-1 7.9-2.8l-3.7-3c-1 .7-2.3 1.2-4.2 1.2-3.2 0-5.9-2.2-6.9-5.1l-3 2.3C5.4 19.8 8.4 22 12 22z"/><path fill="#FBBC05" d="M21.6 13.2c.1-.5.2-1 .2-1.6 0-.6-.1-1.1-.2-1.6H12v3.1h5.4c-.3 1.4-1.2 2.6-2.5 3.4l3.7 3c2.2-2 3.5-5 3.5-8.3z"/></svg>',
  discord:
    '<svg class="auth-oauth-icon" viewBox="0 0 24 24" aria-hidden="true"><path fill="#5865F2" d="M20.3 4.4A17.7 17.7 0 0 0 15.5 3l-.2.4a16.2 16.2 0 0 1 7.7 0l-.2-.4a17.5 17.5 0 0 0-4.8 1.4A17.1 17.1 0 0 0 12 3c-.7 0-1.4.1-2.1.2a17.5 17.5 0 0 0-4.8-1.4l-.2.4a16.2 16.2 0 0 1 7.7 0l-.2-.4A17.7 17.7 0 0 0 8.5 3C4.7 4.1 1.6 6.7.1 10.1a17.8 17.8 0 0 0 5.4 7.2l.4-.5a11.4 11.4 0 0 1-1.7-2.6l.4.2a12.5 12.5 0 0 0 10.1 0l.4-.2a11.4 11.4 0 0 1-1.7 2.6l.4.5a17.8 17.8 0 0 0 5.4-7.2c-.6-1.9-1.6-3.6-3-5.1ZM8.7 14.1c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Zm6.6 0c-1 0-1.8-.9-1.8-2s.8-2 1.8-2 1.8.9 1.8 2-.8 2-1.8 2Z"/></svg>',
  github:
    '<svg class="auth-oauth-icon" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2a10 10 0 0 0-3.2 19.5c.5.1.7-.2.7-.5v-1.7c-2.9.6-3.5-1.2-3.5-1.2-.5-1.1-1.1-1.4-1.1-1.4-.9-.6.1-.6.1-.6 1 .1 1.5 1 1.5 1 .9 1.5 2.3 1.1 2.9.8.1-.7.4-1.1.7-1.4-2.3-.3-4.7-1.1-4.7-5.1 0-1.1.4-2 1.1-2.7-.1-.3-.5-1.3.1-2.7 0 0 .9-.3 2.9 1a10 10 0 0 1 5.3 0c2-1.3 2.9-1 2.9-1 .6 1.4.2 2.4.1 2.7.7.7 1.1 1.6 1.1 2.7 0 4-2.4 4.8-4.7 5.1.4.3.8 1 .8 2v3c0 .3.2.6.7.5A10 10 0 0 0 12 2Z"/></svg>',
  microsoft:
    '<svg class="auth-oauth-icon" viewBox="0 0 24 24" aria-hidden="true"><rect fill="#F25022" x="2" y="2" width="9" height="9"/><rect fill="#7FBA00" x="13" y="2" width="9" height="9"/><rect fill="#00A4EF" x="2" y="13" width="9" height="9"/><rect fill="#FFB900" x="13" y="13" width="9" height="9"/></svg>',
};

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
    if (res.ok) {
      authConfig = await res.json();
      if (!Array.isArray(authConfig.oauth_providers)) {
        authConfig.oauth_providers = [];
      }
    }
  } catch {
    /* optional */
  }
  renderOAuthButtons();
}

function renderOAuthButtons() {
  const providers = authConfig.oauth_providers || [];
  const hasOAuth = providers.length > 0;
  for (const { containerId, dividerId } of [
    { containerId: "auth-oauth-login", dividerId: "auth-divider-login" },
    { containerId: "auth-oauth-register", dividerId: "auth-divider-register" },
  ]) {
    const container = $(`#${containerId}`);
    const divider = $(`#${dividerId}`);
    if (!container) continue;
    container.innerHTML = "";
    container.hidden = !hasOAuth;
    if (divider) divider.classList.toggle("hidden", !hasOAuth);
    if (!hasOAuth) continue;
    for (const provider of providers) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "auth-oauth-btn secondary";
      btn.setAttribute("aria-label", `Continue with ${provider.name}`);
      btn.innerHTML = `${OAUTH_ICONS[provider.id] || ""}<span>Continue with ${provider.name}</span>`;
      btn.addEventListener("click", () => {
        clearAuthError();
        window.location.href = provider.start_url;
      });
      container.appendChild(btn);
    }
  }
}

function parseOAuthHashParams() {
  const raw = window.location.hash.replace(/^#/, "");
  if (!raw) return null;
  const params = new URLSearchParams(raw.includes("=") ? raw : "");
  const exchange = params.get("oauth_exchange");
  const error = params.get("oauth_error");
  if (!exchange && !error) return null;
  return { exchange, error };
}

function clearOAuthHash() {
  const { pathname, search } = window.location;
  history.replaceState(null, "", `${pathname}${search}`);
}

async function handleOAuthReturn() {
  const oauthParams = parseOAuthHashParams();
  if (!oauthParams) return false;

  clearOAuthHash();
  if (oauthParams.error) {
    showAuthError(decodeURIComponent(oauthParams.error));
    showToast(decodeURIComponent(oauthParams.error), {
      variant: "error",
      durationMs: 5000,
    });
    return true;
  }

  showAuthChecking();
  try {
    const data = await api("/auth/oauth/complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exchange_token: oauthParams.exchange }),
    });
    state.token = data.access_token;
    localStorage.setItem("ygo_token", state.token);
    state.user = await api("/auth/me");
    setAuthenticatedShell(true);
    updateAuthUI();
    await bootstrapAuthenticatedApp();
    return true;
  } catch (err) {
    state.token = null;
    state.user = null;
    localStorage.removeItem("ygo_token");
    setAuthenticatedShell(false);
    switchAuthTab("login");
    showAuthLanding();
    showAuthError(err.message || "Social sign-in failed.");
    showToast(err.message || "Social sign-in failed.", {
      variant: "error",
      durationMs: 5000,
    });
    return true;
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
  $("#account-settings-wrap")?.classList.toggle("hidden", !loggedIn);
  if (!loggedIn) closeAccountSettingsMenu();
  $("#collection-toolbar-actions")?.classList.toggle("hidden", !loggedIn);
  refreshBulkCollectionAuthVisibility(loggedIn);
  $("#search-presets-bar")?.classList.toggle("hidden", !loggedIn);
  const userEl = $("#auth-user");
  if (userEl) {
    userEl.textContent = loggedIn ? state.user.email : "";
  }
}

async function bootstrapAuthenticatedApp() {
  initFilterMultiWidgets();
  setupLinkMarkerGrid();
  setupSummoningSuggestions();

  state.currency = loadCurrencyPreference();
  syncCurrencySelect();
  syncPriceInputFields();
  await loadPublicConfig();

  const route = parseRouteHash();
  const initialView =
    route.kind === "card"
      ? null
      : route.invalid && route.view !== "decks"
        ? DEFAULT_ROUTE_VIEW
        : route.view;
  // Show the correct pane immediately so the default Search view doesn't flash
  // while the initial data requests below are in flight.
  if (initialView && initialView !== "search") applyViewChrome(initialView);
  if (initialView === "search") showSearchLoadingState();

  await Promise.all([loadStatus(), loadFilters(), loadSearchPresets(), loadUserTags(), loadFormats()]);
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
  searchEverLoaded = false;
  localStorage.removeItem("ygo_token");
  setDatalist("#tag-datalist", []);
  clearAuthForms();
  switchAuthTab("login");
  setAuthenticatedShell(false);
  showAuthLanding();
  updateAuthUI();
  renderSearchPresetList();
  if (location.hash !== "#/") {
    suppressHashSync = true;
    location.hash = "#/";
    suppressHashSync = false;
  }
}

async function confirmLogout() {
  const ok = await appConfirm({
    title: "Log out",
    message: "Log out of your account?",
    confirmLabel: "Log out",
  });
  if (!ok) return;
  logout();
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

const IMPORT_PHASE_WEIGHTS = {
  started: { start: 0, end: 2 },
  replacing: { start: 2, end: 8 },
  parsing: { start: 8, end: 12 },
  preloading: { start: 12, end: 55 },
  importing: { start: 55, end: 98 },
  finalizing: { start: 98, end: 99.5 },
};

const IMPORT_ASYMPTOTIC_CAP = 0.88;
const IMPORT_INDETERMINATE_MS = 250;
const IMPORT_FINISH_ANIM_MS = 300;

function estimateImportPhaseTauMs(phase, rowCount, fileSizeBytes) {
  let baseSec = 2;
  if (phase === "preloading") baseSec = 10;
  else if (phase === "parsing") baseSec = 3;
  const rowScale = rowCount > 0 ? Math.log10(Math.max(rowCount, 10)) * 4 : 0;
  const fileScale = fileSizeBytes > 0 ? Math.log10(Math.max(fileSizeBytes, 1024)) * 0.5 : 0;
  if (phase === "preloading") return (baseSec + rowScale) * 1000;
  return (baseSec + fileScale) * 1000;
}

class ImportProgressTracker {
  constructor() {
    this.reset();
  }

  reset() {
    this.active = false;
    this.phase = "started";
    this.message = "";
    this.current = 0;
    this.total = 0;
    this.rowCount = 0;
    this.etaSeconds = null;
    this.displayPct = 0;
    this.realMappedPct = 0;
    this.phaseStartMs = 0;
    this.startedMs = 0;
    this.fileSizeBytes = 0;
    this.rafId = null;
    this.finishing = false;
    this.hasServerEvent = false;
  }

  start({ fileSizeBytes = 0 } = {}) {
    this.reset();
    this.active = true;
    this.fileSizeBytes = fileSizeBytes;
    this.startedMs = performance.now();
    this.phaseStartMs = this.startedMs;
    this._scheduleTick();
  }

  stop() {
    this.active = false;
    this.finishing = false;
    if (this.rafId != null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
  }

  onServerEvent(ev) {
    if (ev.type !== "progress") return;
    this.hasServerEvent = true;
    const newPhase = ev.phase || "importing";
    if (newPhase !== this.phase) {
      this.phase = newPhase;
      this.phaseStartMs = performance.now();
    }
    this.message = ev.message || formatImportPhaseLabel(this.phase);
    this.current = ev.current || 0;
    this.total = ev.total || 0;
    this.etaSeconds = ev.eta_seconds ?? null;
    if (this.phase === "importing" && this.total > 0) {
      this.rowCount = this.total;
    }
    if (this.phase === "parsing" && ev.message) {
      const match = ev.message.match(/Read ([\d,]+) rows/);
      if (match) this.rowCount = Number.parseInt(match[1].replace(/,/g, ""), 10);
    }
    this.realMappedPct = this._mapRealProgress();
    this.displayPct = Math.max(this.displayPct, this.realMappedPct);
    this._render();
  }

  _phaseWeight(phase) {
    return IMPORT_PHASE_WEIGHTS[phase] || IMPORT_PHASE_WEIGHTS.started;
  }

  _mapRealProgress() {
    const weight = this._phaseWeight(this.phase);
    const span = weight.end - weight.start;
    let fraction = 0;
    if (this.total > 0 && this.current > 0) {
      fraction = Math.min(1, this.current / this.total);
    } else if (this.phase === "started") {
      fraction = 1;
    }
    return weight.start + span * fraction;
  }

  _asymptoticProgress() {
    const weight = this._phaseWeight(this.phase);
    const span = weight.end - weight.start;
    const elapsed = performance.now() - this.phaseStartMs;
    const tau = estimateImportPhaseTauMs(this.phase, this.rowCount, this.fileSizeBytes);
    const fraction = IMPORT_ASYMPTOTIC_CAP * (1 - Math.exp((-3 * elapsed) / tau));
    return weight.start + span * fraction;
  }

  _computeDisplayPct() {
    const asymptotic = this._asymptoticProgress();
    return Math.min(99.5, Math.max(this.displayPct, asymptotic, this.realMappedPct));
  }

  _scheduleTick() {
    if (!this.active || this.finishing) return;
    this.rafId = requestAnimationFrame(() => this.tick());
  }

  tick() {
    if (!this.active || this.finishing) return;
    this.displayPct = this._computeDisplayPct();
    this._render();
    this._scheduleTick();
  }

  _render() {
    const pct = Math.round(this.displayPct);
    const phaseEl = $("#import-progress-phase");
    const bar = $("#import-progress-bar");
    const pctEl = $("#import-progress-percent");
    const etaEl = $("#import-progress-eta");
    const showIndeterminate = !this.hasServerEvent
      && performance.now() - this.startedMs < IMPORT_INDETERMINATE_MS;

    if (phaseEl) {
      if (this.phase === "importing" && this.total > 0) {
        const remaining = Math.max(0, this.total - this.current);
        phaseEl.textContent =
          `Importing… ${this.current.toLocaleString()} processed · ${remaining.toLocaleString()} remaining`;
      } else {
        phaseEl.textContent = this.message || formatImportPhaseLabel(this.phase);
      }
    }
    if (bar) {
      bar.max = 100;
      if (showIndeterminate) bar.removeAttribute("value");
      else bar.value = pct;
    }
    if (pctEl) pctEl.textContent = showIndeterminate ? "" : `${pct}%`;
    if (etaEl) {
      if (this.phase === "importing" && this.etaSeconds != null) {
        const eta = formatEta(this.etaSeconds);
        etaEl.textContent = eta ? `About ${eta} left` : "";
      } else {
        etaEl.textContent = "";
      }
    }
    setImportProgressIndeterminate(showIndeterminate);
    setImportStatusLineFromTracker(this, { showIndeterminate });
  }

  animateToComplete() {
    this.finishing = true;
    const startPct = this.displayPct;
    const startMs = performance.now();
    return new Promise((resolve) => {
      const step = (now) => {
        const t = Math.min(1, (now - startMs) / IMPORT_FINISH_ANIM_MS);
        this.displayPct = startPct + (100 - startPct) * t;
        this._render();
        if (t < 1) requestAnimationFrame(step);
        else {
          this.displayPct = 100;
          this._render();
          this.stop();
          resolve();
        }
      };
      requestAnimationFrame(step);
    });
  }
}

const importProgressTracker = new ImportProgressTracker();

function formatImportPhaseLabel(phase) {
  switch (phase) {
    case "started":
      return "Starting import…";
    case "replacing":
      return "Removing existing collection…";
    case "parsing":
      return "Reading CSV…";
    case "preloading":
      return "Loading catalog matches…";
    case "finalizing":
      return "Saving changes…";
    default:
      return "Preparing…";
  }
}

function setImportProgressIndeterminate(indeterminate) {
  const card = document.querySelector("#import-progress-modal .import-progress-card");
  card?.classList.toggle("import-progress-card--indeterminate", indeterminate);
  const hint = $("#import-progress-hint");
  if (hint) hint.classList.toggle("hidden", !indeterminate);
  const dlg = $("#import-progress-modal");
  if (dlg) {
    if (indeterminate) dlg.setAttribute("aria-busy", "true");
    else dlg.removeAttribute("aria-busy");
  }
}

function setImportStatusLineFromTracker(tracker, { showIndeterminate = false } = {}) {
  const line = $("#status-line");
  if (!line) return;
  line.classList.add("status-importing");
  line.style.color = "";
  const prog = $("#import-progress");
  const pct = Math.round(tracker.displayPct);
  if (tracker.phase === "importing" && tracker.total > 0) {
    const remaining = Math.max(0, tracker.total - tracker.current);
    const rowPct = Math.round((tracker.current / tracker.total) * 100);
    const eta = formatEta(tracker.etaSeconds);
    line.textContent =
      `Importing… ${tracker.current.toLocaleString()} processed · ${remaining.toLocaleString()} remaining (${rowPct}%) · ${eta}`;
  } else {
    const msg = tracker.message || formatImportPhaseLabel(tracker.phase);
    line.textContent = showIndeterminate ? msg : `${msg} (${pct}%)`;
  }
  if (prog) {
    prog.hidden = false;
    prog.max = 100;
    if (showIndeterminate) prog.removeAttribute("value");
    else prog.value = pct;
  }
}

function setImportStatusLine(current, total, etaSeconds, extra = {}) {
  if (importProgressTracker.active) return;
  const line = $("#status-line");
  if (!line) return;
  line.classList.add("status-importing");
  line.style.color = "";
  const prog = $("#import-progress");
  const remaining = extra.remaining ?? (total > 0 ? Math.max(0, total - current) : 0);
  const phase = extra.phase || "importing";
  if (!total && phase !== "importing") {
    const msg = extra.message || formatImportPhaseLabel(phase);
    line.textContent = msg;
    if (prog) {
      prog.hidden = false;
      prog.removeAttribute("value");
      prog.max = 100;
    }
    return;
  }
  const pct = Math.round((current / total) * 100);
  const eta = formatEta(etaSeconds);
  line.textContent = `Importing… ${current.toLocaleString()} processed · ${remaining.toLocaleString()} remaining (${pct}%) · ${eta}`;
  if (prog) {
    prog.hidden = false;
    prog.max = 100;
    prog.value = pct;
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

function applyViewChrome(name) {
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

  return activeTab;
}

function switchView(name, { fromRouter = false, replaceHash = false } = {}) {
  if (!ROUTE_VIEWS.has(name)) name = DEFAULT_ROUTE_VIEW;
  const activeTab = applyViewChrome(name);

  if (name === "decks") {
    loadDecks({ background: true });
    if (state.decksDetailOpen) showDecksDetailView();
    else showDecksListView();
  }
  if (name === "collection") loadCollectionView({ background: true });
  // Ensure the search grid is populated the first time it becomes visible.
  // The router handles its own initial/param-driven searches; here we cover
  // direct switches (e.g. tab clicks) that would otherwise show an empty grid.
  if (name === "search" && !fromRouter && !searchEverLoaded) {
    runSearch();
  }

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
  const forTradeEl = $("#for-trade-only");
  if (forTradeEl) forTradeEl.checked = false;
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

  const searchSortEl = $("#search-sort");
  if (searchSortEl) searchSortEl.value = "";
  setSortDir($("#search-sort-dir"), "asc");
  syncSearchSortToggleLabel();

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

  if ($("#owned-only")?.checked) chips.push({ id: "owned_only", label: "Owned" });
  if ($("#for-trade-only")?.checked) chips.push({ id: "for_trade_only", label: "Trade" });
  if ($("#favorites-only")?.checked) chips.push({ id: "favorites_only", label: "Favourites" });

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
  for (const val of getFilterMultiValues("filter-banlist-status")) {
    chips.push({ id: `banlist_status:${val}`, label: val });
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
  "for_trade_only",
]);

function hasAdvancedSearchFilters() {
  return collectActiveSearchFilterChips().some((chip) => !PRIMARY_SEARCH_FILTER_IDS.has(chip.id));
}

let advancedFiltersUserCollapsed = false;

function syncAdvancedFiltersOpen() {
  const details = $("#advanced-filters");
  const hadAdvanced = hasAdvancedSearchFilters();
  if (!hadAdvanced) advancedFiltersUserCollapsed = false;
  if (details && hadAdvanced && !advancedFiltersUserCollapsed) details.open = true;
  syncAdvancedFiltersToggle();
}

function syncAdvancedFiltersToggle() {
  const details = $("#advanced-filters");
  const btn = $("#advanced-filters-toggle");
  if (!details || !btn) return;
  btn.setAttribute("aria-expanded", details.open ? "true" : "false");
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
    badge.textContent = `(${count})`;
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
  else if (chipId === "for_trade_only") $("#for-trade-only").checked = false;
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
  } else if (chipId.startsWith("banlist_status:")) {
    removeFilterMultiValue("filter-banlist-status", chipId.slice("banlist_status:".length));
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
    el.classList.add("hidden");
    el.textContent = "";
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

const SEARCH_TOOL_PANELS = ["search-presets-panel", "search-sort-panel", "advanced-filters"];

/** When opening one panel, which others to close. Sort and advanced filters may stay open together. */
const SEARCH_TOOL_PANEL_CLOSE_TARGETS = {
  "search-presets-panel": ["search-sort-panel", "advanced-filters"],
  "search-sort-panel": ["search-presets-panel"],
  "advanced-filters": ["search-presets-panel"],
};

function normalizeSearchToolPanelId(panelId) {
  if (!panelId) return null;
  return panelId.startsWith("#") ? panelId.slice(1) : panelId;
}

function closeSearchToolPanels(exceptDetailsId = null) {
  const exceptId = normalizeSearchToolPanelId(exceptDetailsId);
  const targets = exceptId
    ? SEARCH_TOOL_PANEL_CLOSE_TARGETS[exceptId] ?? SEARCH_TOOL_PANELS.filter((id) => id !== exceptId)
    : SEARCH_TOOL_PANELS;
  for (const id of targets) {
    if (id === exceptId) continue;
    const details = $(`#${id}`);
    if (details?.open) details.open = false;
  }
}

function bindSearchToolPanel(toggleSelector, detailsId, { onUserToggle } = {}) {
  bindDetailsPanelToggle($(toggleSelector), $(detailsId), {
    beforeToggle: (willOpen) => {
      if (willOpen) closeSearchToolPanels(detailsId);
    },
    onUserToggle,
  });
}

function syncSearchSortToggleLabel() {
  syncSortToggleLabel({
    select: $("#search-sort"),
    dirBtn: $("#search-sort-dir"),
    labelEl: $("#search-sort-toggle-label"),
    dirIconEl: $("#search-sort-toggle-dir"),
    toggle: $("#search-sort-toggle"),
    subject: "results",
  });
}

function syncCollectionTableHeaderSort() {
  syncTableHeaderSort(
    $("#collection-table"),
    $("#collection-sort")?.value || "set_code",
    readSortDir($("#collection-sort-dir"))
  );
}

function syncSearchPresetToggleLabel() {
  const toggle = $("#search-preset-toggle");
  const label = $("#search-preset-toggle-label");
  if (!toggle) return;
  const active = state.searchPresets.find((p) => p.id === state.activePresetId);
  toggle.setAttribute(
    "aria-label",
    active ? `Search presets (${active.name} active)` : "Search presets"
  );
  toggle.setAttribute("data-tooltip", active ? active.name : "Presets");
  if (label) {
    label.textContent = active ? active.name : "Presets";
    label.classList.remove("hidden");
  }
}

const PRESET_RENAME_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/><path d="m15 5 4 4"/></svg>';
const PRESET_DELETE_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>';

function renderSearchPresetList() {
  const list = $("#search-preset-list");
  const emptyEl = $("#search-preset-empty");
  if (!list) return;
  const activeId = state.activePresetId;
  if (!state.searchPresets.length) {
    list.innerHTML = "";
    emptyEl?.classList.remove("hidden");
  } else {
    emptyEl?.classList.add("hidden");
    list.innerHTML = state.searchPresets
      .map((p) => {
        const activeClass = p.id === activeId ? " search-preset-row--active" : "";
        const safeName = escapeHtml(p.name);
        return `<div class="search-preset-row${activeClass}" role="listitem" data-preset-id="${p.id}">
          <button type="button" class="search-preset-row-name" data-preset-load="${p.id}">${safeName}</button>
          <div class="search-preset-row-actions">
            <button type="button" class="icon-btn secondary search-preset-rename-btn" data-preset-rename="${p.id}" aria-label="Rename ${safeName}" data-tooltip="Rename">${PRESET_RENAME_ICON}</button>
            <button type="button" class="icon-btn secondary search-preset-delete-btn preset-menu-danger" data-preset-delete="${p.id}" aria-label="Delete ${safeName}" data-tooltip="Delete">${PRESET_DELETE_ICON}</button>
          </div>
        </div>`;
      })
      .join("");
  }
  syncSearchPresetToggleLabel();
}

const COLLECTION_TOOLBAR_MENUS = [
  ["collection-manage-menu", "collection-manage-menu-btn"],
  ["collection-trade-menu", "collection-trade-menu-btn"],
];

function closeCollectionToolbarMenus() {
  for (const [menuId, btnId] of COLLECTION_TOOLBAR_MENUS) {
    const menu = $(`#${menuId}`);
    const btn = $(`#${btnId}`);
    if (!menu || menu.hidden) continue;
    menu.hidden = true;
    btn?.setAttribute("aria-expanded", "false");
  }
}

function closeAccountSettingsMenu() {
  const menu = $("#account-settings-menu");
  const btn = $("#account-settings-btn");
  if (!menu || menu.hidden) return;
  menu.hidden = true;
  btn?.setAttribute("aria-expanded", "false");
}

function toggleAccountSettingsMenu() {
  const menu = $("#account-settings-menu");
  const btn = $("#account-settings-btn");
  if (!menu || !btn) return;
  const isOpen = !menu.hidden;
  closeAccountSettingsMenu();
  closeCollectionToolbarMenus();
  closeSearchToolPanels();
  closeAllCollectionRowMenus();
  closeAllCollectionFolderMenus();
  closeAllDeckTileMenus();
  if (isOpen) return;
  menu.hidden = false;
  btn.setAttribute("aria-expanded", "true");
}

function toggleCollectionToolbarMenu(menuId, btnId) {
  const menu = $(`#${menuId}`);
  const btn = $(`#${btnId}`);
  if (!menu || !btn) return;
  const isOpen = !menu.hidden;
  closeCollectionToolbarMenus();
  closeAccountSettingsMenu();
  closeSearchToolPanels();
  closeAllCollectionRowMenus();
  closeAllDeckTileMenus();
  if (isOpen) return;
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

function closeAllCollectionFolderMenus() {
  document.querySelectorAll(".collection-folder-menu").forEach((menu) => {
    if (menu.hidden) return;
    menu.hidden = true;
    menu.classList.remove("collection-folder-menu--fixed");
    menu.style.top = "";
    menu.style.left = "";
  });
  document.querySelectorAll(".collection-folder-menu-btn").forEach((btn) => {
    btn.setAttribute("aria-expanded", "false");
  });
}

function openCollectionRowMenu(btn) {
  const wrap = btn.closest(".collection-row-menu-wrap");
  const menu = wrap?.querySelector(".collection-row-menu");
  if (!menu) return;
  closeAllCollectionRowMenus();
  closeAllCollectionFolderMenus();
  closeCollectionToolbarMenus();
  closeSearchToolPanels();
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

function openCollectionFolderMenu(btn) {
  const wrap = btn.closest(".collection-folder-menu-wrap");
  const menu = wrap?.querySelector(".collection-folder-menu");
  if (!menu) return;
  closeAllCollectionFolderMenus();
  closeAllCollectionRowMenus();
  closeCollectionToolbarMenus();
  closeDeleteFolderPopover();
  menu.hidden = false;
  btn.setAttribute("aria-expanded", "true");
  menu.classList.add("collection-folder-menu--fixed");
  const rect = btn.getBoundingClientRect();
  const menuWidth = menu.offsetWidth;
  const left = Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 8);
  menu.style.top = `${rect.bottom + 4}px`;
  menu.style.left = `${Math.max(8, left)}px`;
}

function toggleCollectionFolderMenu(btn) {
  const wrap = btn.closest(".collection-folder-menu-wrap");
  const menu = wrap?.querySelector(".collection-folder-menu");
  if (!menu) return;
  if (!menu.hidden) {
    closeAllCollectionFolderMenus();
    return;
  }
  openCollectionFolderMenu(btn);
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
  if (mechanics.length) params.set("mechanic", mechanics.join("|"));

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
  if ($("#for-trade-only").checked) params.set("for_trade_only", "true");
  const tag = $("#filter-tag")?.value.trim();
  if (tag) params.set("tag", tag);
  const format = $("#search-format")?.value;
  if (format) params.set("format", format);
  const fmt = state.formatsList.find((f) => f.code === format);
  if (fmt?.banlist_selectable) {
    const banlist = $("#search-banlist")?.value;
    if (banlist) params.set("banlist_revision_id", banlist);
  }
  if (fmt?.uses_banlist) {
    const statuses = getFilterMultiValues("filter-banlist-status");
    if (statuses.length) params.set("banlist_status", statuses.join(","));
  }
  const genesysList = $("#search-genesys-list")?.value;
  if (genesysList) params.set("genesys_point_list_id", genesysList);
  if (fmt?.uses_point_list) {
    const pointsMin = $("#points-min")?.value;
    const pointsMax = $("#points-max")?.value;
    if (pointsMin) params.set("points_min", pointsMin);
    if (pointsMax) params.set("points_max", pointsMax);
  }
  const searchSort = $("#search-sort")?.value || "";
  if (searchSort) params.set("sort", searchSort);
  const searchSortDir = readSortDir($("#search-sort-dir"));
  if (searchSort && searchSortDir !== "asc") params.set("sort_dir", searchSortDir);
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
  if (s.mechanic) setFilterMultiValues("filter-mechanic", s.mechanic.split("|"));
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
  if (s.for_trade_only === "true") $("#for-trade-only").checked = true;
  if (s.tag) {
    const el = $("#filter-tag");
    if (el) el.value = s.tag;
  }
  if (s.format) {
    const el = $("#search-format");
    if (el) el.value = s.format;
    updateSearchFormatUi();
  }
  if (s.banlist_revision_id && s.format) {
    const fmt = state.formatsList.find((f) => f.code === s.format);
    if (fmt?.banlist_selectable) {
      const el = $("#search-banlist");
      if (el) el.value = s.banlist_revision_id;
    }
  }
  if (s.banlist_status) {
    setFilterMultiValues("filter-banlist-status", s.banlist_status.split(","));
  }
  if (s.points_min) {
    const el = $("#points-min");
    if (el) el.value = s.points_min;
  }
  if (s.points_max) {
    const el = $("#points-max");
    if (el) el.value = s.points_max;
  }
  if (s.sort) {
    const el = $("#search-sort");
    if (el) el.value = s.sort;
  }
  if (s.sort_dir) {
    setSortDir($("#search-sort-dir"), s.sort_dir);
  }
  syncSearchSortToggleLabel();
  renderActiveSearchFilters();
}

function clearActivePreset() {
  state.activePresetId = null;
  renderSearchPresetList();
}

async function loadSearchPresets() {
  if (!state.token) {
    state.searchPresets = [];
    state.activePresetId = null;
    renderSearchPresetList();
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
    renderSearchPresetList();
  } catch {
    state.searchPresets = [];
    renderSearchPresetList();
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
  renderSearchPresetList();
  const panel = $("#search-presets-panel");
  if (panel?.open) panel.open = false;
  await runSearch();
}

function currentSearchSnapshot() {
  return searchParamsToSnapshot(buildSearchParams());
}

let presetSaveChoiceResolve = null;
let presetSaveChoiceTrigger = null;
let presetNameResolve = null;
let presetNameTrigger = null;
let importModeResolve = null;
let importModeTrigger = null;
let importProgressCanClose = false;
let importProgressDonePayload = null;

function closeSearchPresetNameModal(result = null) {
  const dlg = $("#search-preset-name-modal");
  if (!dlg || dlg.hidden) {
    if (presetNameResolve) {
      const resolve = presetNameResolve;
      presetNameResolve = null;
      resolve(result);
    }
    return;
  }
  dlg.hidden = true;
  syncModalOpenClass();
  (presetNameTrigger ?? $("#search-preset-save"))?.focus();
  presetNameTrigger = null;
  if (presetNameResolve) {
    const resolve = presetNameResolve;
    presetNameResolve = null;
    resolve(result);
  }
}

function promptPresetName({ title, defaultValue = "", submitLabel = "Save" }) {
  const dlg = $("#search-preset-name-modal");
  if (!dlg) return Promise.resolve(null);
  return new Promise((resolve) => {
    presetNameResolve = resolve;
    presetNameTrigger = document.activeElement;
    const titleEl = $("#search-preset-name-title");
    if (titleEl) titleEl.textContent = title;
    const input = $("#search-preset-name-input");
    if (input) {
      input.value = defaultValue;
    }
    const submitBtn = $("#search-preset-name-submit");
    if (submitBtn) submitBtn.textContent = submitLabel;
    dlg.hidden = false;
    syncModalOpenClass();
    input?.focus();
    input?.select();
  });
}

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

function closeImportModeModal(choice = null) {
  const dlg = $("#import-mode-modal");
  if (!dlg || dlg.hidden) {
    if (importModeResolve) {
      const resolve = importModeResolve;
      importModeResolve = null;
      resolve(choice);
    }
    return;
  }
  dlg.hidden = true;
  syncModalOpenClass();
  (importModeTrigger ?? $("#import-collection-btn"))?.focus();
  importModeTrigger = null;
  if (importModeResolve) {
    const resolve = importModeResolve;
    importModeResolve = null;
    resolve(choice);
  }
}

function promptImportModeChoice(fileName) {
  const dlg = $("#import-mode-modal");
  if (!dlg) return Promise.resolve(null);
  return new Promise((resolve) => {
    importModeResolve = resolve;
    importModeTrigger = $("#import-collection-btn");
    const titleEl = $("#import-mode-title");
    if (titleEl) titleEl.textContent = `Import ${fileName}`;
    dlg.hidden = false;
    syncModalOpenClass();
    $("#import-mode-append")?.focus();
  });
}

function formatImportResultMessage(done) {
  const parts = [];
  if (done.imported > 0) parts.push(`${done.imported} new`);
  if (done.merged > 0) parts.push(`${done.merged} merged`);
  const summary = parts.length ? parts.join(", ") : "No rows imported";
  if (done.rejected_count > 0) {
    return `${summary}. ${done.rejected_count} could not be matched — downloaded as rejected_cards.csv.`;
  }
  return `${summary}.`;
}

function openImportProgressModal(fileSizeBytes = 0) {
  importProgressCanClose = false;
  importProgressDonePayload = null;
  const dlg = $("#import-progress-modal");
  if (!dlg) return;
  const title = $("#import-progress-title");
  if (title) title.textContent = "Importing collection";
  const phase = $("#import-progress-phase");
  if (phase) phase.textContent = "Preparing…";
  const pctEl = $("#import-progress-percent");
  if (pctEl) pctEl.textContent = "";
  const etaEl = $("#import-progress-eta");
  if (etaEl) etaEl.textContent = "";
  const summary = $("#import-progress-summary");
  if (summary) {
    summary.textContent = "";
    summary.classList.add("hidden");
  }
  const bar = $("#import-progress-bar");
  if (bar) {
    bar.removeAttribute("value");
    bar.max = 100;
  }
  const closeBtn = $("#import-progress-close");
  if (closeBtn) {
    closeBtn.hidden = true;
    closeBtn.disabled = true;
  }
  const actions = $("#import-progress-actions");
  if (actions) actions.hidden = true;
  setImportProgressIndeterminate(true);
  importProgressTracker.start({ fileSizeBytes });
  dlg.hidden = false;
  syncModalOpenClass();
}

function updateImportProgress(ev) {
  if (ev.type !== "progress") return;
  importProgressTracker.onServerEvent(ev);
}

function showImportProgressResult(done) {
  importProgressCanClose = true;
  importProgressDonePayload = done;
  importProgressTracker.stop();
  setImportProgressIndeterminate(false);
  const title = $("#import-progress-title");
  if (title) title.textContent = "Import complete";
  const phase = $("#import-progress-phase");
  if (phase) phase.textContent = "";
  const bar = $("#import-progress-bar");
  if (bar && bar.max) bar.value = bar.max;
  const summary = $("#import-progress-summary");
  if (summary) {
    summary.textContent = formatImportResultMessage(done);
    summary.classList.remove("hidden");
  }
  const pctEl = $("#import-progress-percent");
  if (pctEl) pctEl.textContent = "100%";
  const etaEl = $("#import-progress-eta");
  if (etaEl) etaEl.textContent = "";
  const closeBtn = $("#import-progress-close");
  if (closeBtn) {
    closeBtn.hidden = false;
    closeBtn.disabled = false;
    closeBtn.focus();
  }
  const actions = $("#import-progress-actions");
  if (actions) actions.hidden = false;
}

function showImportProgressError(message) {
  importProgressCanClose = true;
  importProgressDonePayload = null;
  importProgressTracker.stop();
  setImportProgressIndeterminate(false);
  const title = $("#import-progress-title");
  if (title) title.textContent = "Import failed";
  const phase = $("#import-progress-phase");
  if (phase) phase.textContent = message;
  const summary = $("#import-progress-summary");
  if (summary) {
    summary.textContent = "";
    summary.classList.add("hidden");
  }
  const pctEl = $("#import-progress-percent");
  if (pctEl) pctEl.textContent = "";
  const etaEl = $("#import-progress-eta");
  if (etaEl) etaEl.textContent = "";
  const closeBtn = $("#import-progress-close");
  if (closeBtn) {
    closeBtn.hidden = false;
    closeBtn.disabled = false;
    closeBtn.focus();
  }
  const actions = $("#import-progress-actions");
  if (actions) actions.hidden = false;
}

async function closeImportProgressModal() {
  const dlg = $("#import-progress-modal");
  if (!dlg || dlg.hidden || !importProgressCanClose) return;
  dlg.hidden = true;
  syncModalOpenClass();
  importProgressCanClose = false;
  const payload = importProgressDonePayload;
  importProgressDonePayload = null;
  $("#import-collection-btn")?.focus();
  if (payload) {
    await loadStatus();
    await refreshOwnedSearchState();
    await refreshCollectionIfActive();
  }
}

async function runCollectionImport(file, replace) {
  const form = new FormData();
  form.append("file", file);
  const importBtn = $("#import-collection-btn");
  if (importBtn) importBtn.disabled = true;
  openImportProgressModal(file.size || 0);
  try {
    const res = await fetch(`${API}/collection/import-csv?replace=${replace ? "true" : "false"}`, {
      method: "POST",
      headers: state.token ? { Authorization: `Bearer ${state.token}` } : {},
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    const done = await readNdjsonStream(res, (ev) => {
      updateImportProgress(ev);
    });
    if (!done) throw new Error("Import finished without confirmation");
    if (done.rejected_count > 0 && done.rejected_csv) {
      downloadRejectedCsv(done.rejected_csv);
    }
    await importProgressTracker.animateToComplete();
    showImportProgressResult(done);
  } catch (err) {
    showImportProgressError(err.message);
    await loadStatus();
  } finally {
    importProgressTracker.stop();
    clearImportStatusLine();
    if (importBtn) importBtn.disabled = false;
  }
}

async function finishPresetSave(preset) {
  state.activePresetId = preset.id;
  await loadSearchPresets();
  renderSearchPresetList();
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
    if (
      !(await appConfirm({
        title: "Overwrite preset",
        message: `A preset named "${name}" already exists. Overwrite it?`,
        confirmLabel: "Overwrite",
        danger: true,
      }))
    ) {
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
    const name = await promptPresetName({ title: "Save search preset" });
    if (!name?.trim()) return;
    await createSearchPresetByName(snapshot, name.trim());
    return;
  }

  const name = await promptPresetName({ title: "Save search preset" });
  if (!name?.trim()) return;
  await createSearchPresetByName(snapshot, name.trim());
}

async function renameSearchPreset(presetId) {
  if (!state.token) {
    showToast("Log in to rename presets.", { variant: "error" });
    return;
  }
  if (!presetId) return;
  const current = state.searchPresets.find((p) => p.id === presetId);
  const newName = await promptPresetName({
    title: "Rename preset",
    defaultValue: current?.name || "",
    submitLabel: "Rename",
  });
  if (!newName?.trim() || newName.trim() === current?.name) return;

  try {
    const preset = await api(`/search-presets/${presetId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName.trim() }),
    });
    state.activePresetId = preset.id;
    await loadSearchPresets();
    renderSearchPresetList();
    showToast("Preset renamed.");
  } catch (err) {
    showToast(
      err.status === 409 ? "That name is already in use." : err.message,
      { variant: "error", durationMs: 5000 }
    );
  }
}

async function deleteSearchPreset(presetId) {
  if (!state.token) {
    showToast("Log in to delete presets.", { variant: "error" });
    return;
  }
  if (!presetId) return;
  const current = state.searchPresets.find((p) => p.id === presetId);
  if (
    !(await appConfirm({
      title: "Delete preset",
      message: `Delete preset "${current?.name || presetId}"?`,
      confirmLabel: "Delete",
      danger: true,
    }))
  ) {
    return;
  }

  await api(`/search-presets/${presetId}`, { method: "DELETE" });
  if (state.activePresetId === presetId) state.activePresetId = null;
  await loadSearchPresets();
  showToast("Preset deleted.");
}

function setSearchPaginationHidden(hidden) {
  for (const bar of document.querySelectorAll("[data-search-pagination]")) {
    bar.classList.toggle("hidden", hidden);
    if (hidden) bar.innerHTML = "";
  }
}

function bindSearchPaginationBar(bar) {
  bar.querySelector('[data-action="prev"]')?.addEventListener("click", () => {
    if (state.searchPage > 0) loadSearchPage(state.searchPage - 1);
  });
  bar.querySelector('[data-action="next"]')?.addEventListener("click", () => {
    const lastPage = Math.ceil(state.searchTotal / SEARCH_PAGE_SIZE) - 1;
    if (state.searchPage < lastPage) loadSearchPage(state.searchPage + 1);
  });
}

function renderSearchPagination() {
  const bars = document.querySelectorAll("[data-search-pagination]");
  if (!bars.length) return;
  const total = state.searchTotal;
  const totalPages = Math.max(1, Math.ceil(total / SEARCH_PAGE_SIZE));
  const page = state.searchPage;

  if (totalPages <= 1) {
    setSearchPaginationHidden(true);
    return;
  }

  const html = `
    <button type="button" data-action="prev" class="secondary"${page === 0 ? " disabled" : ""}>← Previous</button>
    <span class="search-page-info">Page ${page + 1} of ${totalPages}</span>
    <button type="button" data-action="next" class="secondary"${page >= totalPages - 1 ? " disabled" : ""}>Next →</button>`;

  for (const bar of bars) {
    bar.classList.remove("hidden");
    bar.innerHTML = html;
    bindSearchPaginationBar(bar);
  }
}

const SEARCH_SKELETON_COUNT = 10;

function renderSearchLoadingSkeleton() {
  const tiles = Array.from({ length: SEARCH_SKELETON_COUNT }, () => `
    <article class="card-tile card-tile--skeleton" aria-hidden="true">
      <div class="skeleton search-card-skeleton-img"></div>
      <div class="info">
        <div class="skeleton skeleton-line"></div>
        <div class="skeleton skeleton-line skeleton-line--short"></div>
      </div>
    </article>`).join("");
  return `<p class="sr-only" role="status">Searching…</p>${tiles}`;
}

function showSearchLoadingState() {
  const grid = $("#search-results");
  if (!grid) return;
  grid.innerHTML = renderSearchLoadingSkeleton();
  grid.setAttribute("aria-busy", "true");
  setSearchPaginationHidden(true);
  renderSearchResultsSummary({ loading: true });
}

function renderSearchResults(cards) {
  const grid = $("#search-results");
  grid.removeAttribute("aria-busy");
  if (!cards.length) {
    grid.innerHTML = '<p class="empty-msg">No cards found.</p>';
    setSearchPaginationHidden(true);
    state.searchResultsById = {};
    renderSearchResultsSummary();
    return;
  }
  state.searchResultsById = {};
  for (const c of cards) {
    state.searchResultsById[c.id] = c;
  }
  grid.innerHTML = cards
      .map((c) => {
        const formatBadge = formatBadgeHtml(c);
        return `
      <article class="card-tile ${c.owned ? "owned" : ""}" data-id="${c.id}">
        <div class="card-tile-image-wrap">
          ${c.owned ? `<span class="badge badge-owned">×${c.owned_quantity}</span>` : ""}
          ${c.trade_quantity > 0 ? `<span class="badge badge-trade">×${c.trade_quantity}</span>` : ""}
          ${cardImgTag(c.image_url_small)}
          ${formatBadge ? `<div class="card-tile-format-badge">${formatBadge}</div>` : ""}
        </div>
        <div class="info">
          <div class="name">${escapeHtml(c.name)}</div>
          <div class="muted">${escapeHtml(c.type || "")}</div>
        </div>
      </article>`;
      })
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
  searchEverLoaded = true;
  state.searchPage = pageIndex;
  const offset = pageIndex * SEARCH_PAGE_SIZE;
  const grid = $("#search-results");
  showSearchLoadingState();

  try {
    const page = await fetchSearchPage(state.searchParams, offset);
    if (seq !== searchRequestSeq) return;
    state.searchTotal = page.total;
    renderSearchResults(page.items);
    renderSearchPagination();
    renderActiveSearchFilters();
    $("#search-results")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    if (seq !== searchRequestSeq) return;
    grid.removeAttribute("aria-busy");
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
    isAppDialogOpen() ||
    isModalVisible("#card-modal") ||
    isModalVisible("#card-errata-modal") ||
    isModalVisible("#card-tips-modal") ||
    isModalVisible("#search-help-modal") ||
    isModalVisible("#formats-info-modal") ||
    isModalVisible("#export-collection-modal") ||
    isModalVisible("#search-preset-save-modal") ||
    isModalVisible("#search-preset-name-modal") ||
    isModalVisible("#import-mode-modal") ||
    isModalVisible("#import-progress-modal") ||
    isModalVisible("#collection-add-modal") ||
    isModalVisible("#collection-edit-modal") ||
    isModalVisible("#bulk-collection-modal") ||
    isModalVisible("#collection-stats-modal") ||
    isModalVisible("#delete-account-modal") ||
    isModalVisible("#trade-settings-modal")
  ) {
    document.body.classList.add("modal-open");
  } else {
    document.body.classList.remove("modal-open");
  }
}

let searchHelpTrigger = null;
let formatsInfoTrigger = null;
let searchHelpContentRendered = false;
let searchHelpOutsideHandler = null;
let searchHelpRepositionHandler = null;

const SEARCH_HELP_DESKTOP_MQ = "(min-width: 800px)";
const SEARCH_HELP_SIZE_KEY = "ygo_search_help_size";
const SEARCH_HELP_MIN_W = 320;
const SEARCH_HELP_MIN_H = 240;
const SEARCH_HELP_DEFAULT_W = 520;
const SEARCH_HELP_VIEWPORT_MARGIN_PX = 32;
const SEARCH_HELP_MAX_H_RATIO = 0.9;

function searchHelpMaxWidth() {
  return Math.max(SEARCH_HELP_MIN_W, window.innerWidth - SEARCH_HELP_VIEWPORT_MARGIN_PX);
}

function searchHelpMaxHeight() {
  return Math.max(SEARCH_HELP_MIN_H, window.innerHeight * SEARCH_HELP_MAX_H_RATIO);
}

function searchHelpDefaultHeight() {
  return Math.max(SEARCH_HELP_MIN_H, window.innerHeight * 0.75);
}

const COLLECTION_ADD_SIZE_KEY = "ygo_collection_add_size";
const COLLECTION_ADD_MIN_W = 320;
const COLLECTION_ADD_MIN_H = 280;
const COLLECTION_ADD_DEFAULT_W = 448;
const COLLECTION_ADD_VIEWPORT_MARGIN_PX = 32;
const COLLECTION_ADD_MAX_H_RATIO = 0.9;
const RESIZABLE_PANEL_RESIZING_CLASS = "search-help-resizing";

function loadResizablePanelSize(storageKey) {
  try {
    const raw = sessionStorage.getItem(storageKey);
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (typeof data.width === "number" && typeof data.height === "number") {
      return { width: data.width, height: data.height };
    }
  } catch {
    /* ignore */
  }
  return null;
}

function saveResizablePanelSize(storageKey, width, height) {
  try {
    sessionStorage.setItem(storageKey, JSON.stringify({ width, height }));
  } catch {
    /* ignore */
  }
}

function clampResizablePanelSize(width, height, { minW, minH, maxW, maxH }) {
  return {
    width: Math.max(minW, Math.min(maxW, Math.round(width))),
    height: Math.max(minH, Math.min(maxH, Math.round(height))),
  };
}

function applyResizablePanelSize(panel, width, height, limits) {
  const clamped = clampResizablePanelSize(width, height, limits);
  panel.style.width = `${clamped.width}px`;
  panel.style.height = `${clamped.height}px`;
  return clamped;
}

function getResizablePanelDefaultSize(storageKey, limits, computeDefault) {
  const saved = loadResizablePanelSize(storageKey);
  if (saved) return clampResizablePanelSize(saved.width, saved.height, limits);
  const defaults = computeDefault();
  return clampResizablePanelSize(defaults.width, defaults.height, limits);
}

function initResizablePanel(panel, { storageKey, limits, onResizeDuring }) {
  if (!panel || panel.dataset.resizeBound === "1") return;
  const handle = panel.querySelector(".search-help-resize-handle");
  if (!handle) return;
  panel.dataset.resizeBound = "1";

  let startX = 0;
  let startY = 0;
  let startW = 0;
  let startH = 0;

  function onPointerMove(e) {
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    applyResizablePanelSize(panel, startW + dx, startH + dy, limits);
    onResizeDuring?.(panel);
  }

  function onPointerUp(e) {
    document.body.classList.remove(RESIZABLE_PANEL_RESIZING_CLASS);
    handle.releasePointerCapture?.(e.pointerId);
    document.removeEventListener("pointermove", onPointerMove);
    document.removeEventListener("pointerup", onPointerUp);
    const rect = panel.getBoundingClientRect();
    saveResizablePanelSize(storageKey, rect.width, rect.height);
  }

  handle.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const rect = panel.getBoundingClientRect();
    startX = e.clientX;
    startY = e.clientY;
    startW = rect.width;
    startH = rect.height;
    document.body.classList.add(RESIZABLE_PANEL_RESIZING_CLASS);
    handle.setPointerCapture(e.pointerId);
    document.addEventListener("pointermove", onPointerMove);
    document.addEventListener("pointerup", onPointerUp);
  });
}

function searchHelpLimits() {
  return {
    minW: SEARCH_HELP_MIN_W,
    minH: SEARCH_HELP_MIN_H,
    maxW: searchHelpMaxWidth(),
    maxH: searchHelpMaxHeight(),
  };
}

function loadSearchHelpSize() {
  return loadResizablePanelSize(SEARCH_HELP_SIZE_KEY);
}

function saveSearchHelpSize(width, height) {
  saveResizablePanelSize(SEARCH_HELP_SIZE_KEY, width, height);
}

function clampSearchHelpSize(width, height) {
  return clampResizablePanelSize(width, height, searchHelpLimits());
}

function applySearchHelpSize(panel, width, height) {
  return applyResizablePanelSize(panel, width, height, searchHelpLimits());
}

function getSearchHelpDefaultSize(anchorWidth) {
  return getResizablePanelDefaultSize(SEARCH_HELP_SIZE_KEY, searchHelpLimits(), () => {
    const defaultW =
      anchorWidth != null
        ? Math.min(SEARCH_HELP_DEFAULT_W, Math.max(anchorWidth, SEARCH_HELP_MIN_W))
        : SEARCH_HELP_DEFAULT_W;
    return { width: defaultW, height: searchHelpDefaultHeight() };
  });
}

function collectionAddMaxWidth() {
  return Math.max(COLLECTION_ADD_MIN_W, window.innerWidth - COLLECTION_ADD_VIEWPORT_MARGIN_PX);
}

function collectionAddMaxHeight() {
  return Math.max(COLLECTION_ADD_MIN_H, window.innerHeight * COLLECTION_ADD_MAX_H_RATIO);
}

function collectionAddDefaultHeight() {
  return Math.max(COLLECTION_ADD_MIN_H, Math.min(window.innerHeight * 0.75, 560));
}

function collectionAddLimits() {
  return {
    minW: COLLECTION_ADD_MIN_W,
    minH: COLLECTION_ADD_MIN_H,
    maxW: collectionAddMaxWidth(),
    maxH: collectionAddMaxHeight(),
  };
}

function applyCollectionAddPanelSize(panel) {
  const size = getResizablePanelDefaultSize(
    COLLECTION_ADD_SIZE_KEY,
    collectionAddLimits(),
    () => ({ width: COLLECTION_ADD_DEFAULT_W, height: collectionAddDefaultHeight() })
  );
  applyResizablePanelSize(panel, size.width, size.height, collectionAddLimits());
}

function initCollectionAddResize(panel) {
  initResizablePanel(panel, {
    storageKey: COLLECTION_ADD_SIZE_KEY,
    limits: collectionAddLimits(),
  });
}

function initSearchHelpResize(panel) {
  initResizablePanel(panel, {
    storageKey: SEARCH_HELP_SIZE_KEY,
    limits: searchHelpLimits(),
    onResizeDuring: (resizedPanel) => {
      if (resizedPanel.id === "search-help-popover") {
        clampSearchHelpPopoverPosition();
      }
    },
  });
}

function clampSearchHelpPopoverPosition() {
  const popover = $("#search-help-popover");
  const anchor = document.querySelector(".search-field--grow");
  if (!popover || popover.hidden || !anchor) return;

  const margin = 8;
  const gap = 6;
  const rect = anchor.getBoundingClientRect();
  const popRect = popover.getBoundingClientRect();
  const width = popRect.width;
  const height = popRect.height;

  let left = Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin));
  let top = rect.bottom + gap;

  if (top + height > window.innerHeight - margin) {
    const aboveTop = rect.top - height - gap;
    top = aboveTop >= margin ? aboveTop : margin;
  }

  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
}

function applySearchHelpPanelSize(panel, anchorWidth) {
  const size = getSearchHelpDefaultSize(anchorWidth);
  applySearchHelpSize(panel, size.width, size.height);
}

function repositionSearchHelpOnViewportChange() {
  const popover = $("#search-help-popover");
  if (!popover || popover.hidden) return;
  const rect = popover.getBoundingClientRect();
  const clamped = clampSearchHelpSize(rect.width, rect.height);
  if (clamped.width !== rect.width || clamped.height !== rect.height) {
    applySearchHelpSize(popover, clamped.width, clamped.height);
  }
  clampSearchHelpPopoverPosition();
}

const SEARCH_SYNTAX_SECTIONS = [
  {
    title: "Basics",
    rows: [
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
      { example: "12345678", description: "Passcode when the whole query is digits" },
      { example: "(reveal OR summon) hand", description: "Group with parentheses" },
    ],
  },
  {
    title: "Fields",
    rows: [
      { example: "name:Utopia", description: "Search card name only" },
      { example: "desc:destroy", description: "Search description only" },
      { example: "archetype:Hero", description: "Search archetype only" },
      { example: "summoning:\"2+ monsters\"", description: "Summoning condition text" },
      { example: "text:reveal", description: "Explicit name + description + archetype" },
      { example: "passcode:89631139", description: "Passcode inside a compound query" },
    ],
  },
  {
    title: "Case sensitivity",
    rows: [
      {
        example: "name:=Number",
        description: "Case-sensitive match in name (e.g. Xyz Number cards)",
        descriptionIsHtml: false,
      },
      {
        example: 'name:="Number 39"',
        description: "Case-sensitive phrase in name",
      },
      {
        example: "name:number",
        description: "Case-insensitive name search (also matches Number)",
      },
    ],
  },
  {
    title: "Stats",
    rows: [
      { example: "atk:>=3000", description: "ATK greater than or equal to 3000" },
      { example: "def:2000", description: "Exact DEF" },
      { example: "level:4..8", description: "Level range (inclusive)" },
      { example: "rank:2", description: "Exact rank" },
      { example: "link:2", description: "Link rating" },
      { example: "scale:1", description: "Pendulum scale" },
    ],
  },
  {
    title: "Properties",
    rows: [
      { example: "category:Monster", description: "Card category" },
      { example: "type:Effect", description: "Monster / spell type label" },
      { example: "mechanic:Xyz", description: "Summoning mechanic" },
      { example: "attribute:DARK", description: "Monster attribute" },
      { example: "cardtype:Spell", description: "Spell / Trap / Monster card type" },
      { example: "markers:Top,Bottom", description: "Link markers (all required)" },
      { example: "set:LOB", description: "Set code substring" },
    ],
  },
  {
    title: "Collection",
    rows: [
      { example: "tag:staple", description: "Your tag on a card (logged in)" },
      { example: "owned:true", description: "Cards in your collection" },
      { example: "favorite:true", description: "Your favorited cards" },
    ],
  },
  {
    title: "Format",
    rows: [
      { example: "format:Advanced", description: "Format-legal card pool" },
      { example: "banlist:Forbidden", description: "Banlist status (with format)" },
      { example: "points:>=5", description: "Genesys points (with format)" },
    ],
  },
  {
    title: "Combined example",
    rows: [
      {
        example: "name:=Number mechanic:Xyz",
        description: "Xyz Number cards by case-sensitive name + mechanic",
      },
      {
        example: "name:=Number -desc:number",
        description: "Number in name, exclude lowercase in description",
      },
    ],
  },
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

function searchHelpIdPrefix(titleId) {
  return titleId.replace(/-title$/, "");
}

function renderSearchHelpTableRows(rows) {
  return rows
    .map(
      (row) => `
    <tr>
      <td class="search-help-example" data-example="${escapeHtml(row.example)}" tabindex="0" role="button" title="Use this example">
        <code>${escapeHtml(row.example)}</code>
      </td>
      <td>${row.descriptionIsHtml ? row.description : escapeHtml(row.description)}</td>
    </tr>`
    )
    .join("");
}

function initSearchHelpTabs(shell) {
  const tablist = shell.querySelector(".search-help-tabs");
  const tabs = [...shell.querySelectorAll(".search-help-tab")];
  const panels = [...shell.querySelectorAll(".search-help-panel")];
  const scrollWrap = shell.querySelector(".search-help-table-wrap");
  if (!tablist || !tabs.length) return;

  function activateTab(index) {
    tabs.forEach((tab, i) => {
      const selected = i === index;
      tab.setAttribute("aria-selected", selected ? "true" : "false");
      tab.tabIndex = selected ? 0 : -1;
      tab.classList.toggle("active", selected);
    });
    panels.forEach((panel, i) => {
      panel.hidden = i !== index;
    });
    if (scrollWrap) scrollWrap.scrollTop = 0;
  }

  tablist.addEventListener("click", (e) => {
    const tab = e.target.closest(".search-help-tab");
    if (!tab) return;
    const index = tabs.indexOf(tab);
    if (index >= 0) activateTab(index);
  });

  tablist.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const current = tabs.findIndex((t) => t.getAttribute("aria-selected") === "true");
    if (current < 0) return;
    const next =
      e.key === "ArrowRight"
        ? (current + 1) % tabs.length
        : (current - 1 + tabs.length) % tabs.length;
    e.preventDefault();
    tabs[next].focus();
    activateTab(next);
  });
}

function renderSearchHelpContent(container, titleId) {
  if (!container) return;
  const prefix = searchHelpIdPrefix(titleId);

  const tabsHtml = SEARCH_SYNTAX_SECTIONS.map(
    (section, i) => `
    <button
      type="button"
      class="search-help-tab${i === 0 ? " active" : ""}"
      role="tab"
      id="${escapeHtml(prefix)}-tab-${i}"
      aria-selected="${i === 0 ? "true" : "false"}"
      aria-controls="${escapeHtml(prefix)}-panel-${i}"
      tabindex="${i === 0 ? "0" : "-1"}"
    >${escapeHtml(section.title)}</button>`
  ).join("");

  const panelsHtml = SEARCH_SYNTAX_SECTIONS.map((section, i) => {
    const rows = renderSearchHelpTableRows(section.rows);
    return `
    <div
      class="search-help-panel"
      role="tabpanel"
      id="${escapeHtml(prefix)}-panel-${i}"
      aria-labelledby="${escapeHtml(prefix)}-tab-${i}"
      ${i !== 0 ? "hidden" : ""}
    >
      <table class="search-help-table">
        <thead>
          <tr>
            <th scope="col">Example</th>
            <th scope="col">Description</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }).join("");

  container.innerHTML = `
    <div class="search-help-shell">
      <div class="search-help-topbar">
        <header class="search-help-header">
          <h2 id="${escapeHtml(titleId)}">Search syntax</h2>
          <p class="muted">Unqualified terms are case-insensitive. Use <code>field:=value</code> for case-sensitive matches.</p>
        </header>
        ${searchHelpDismissButtonHtml()}
      </div>
      <div class="search-help-tabs" role="tablist" aria-label="Search syntax sections">${tabsHtml}</div>
      <div class="search-help-table-wrap">${panelsHtml}</div>
      <p class="search-help-footnote">Click an example to insert it, then press Enter or Search to run.</p>
    </div>`;

  initSearchHelpTabs(container.querySelector(".search-help-shell"));

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

  applySearchHelpPanelSize(popover, anchor.getBoundingClientRect().width);
  clampSearchHelpPopoverPosition();
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
    if (isSearchHelpPopoverOpen()) repositionSearchHelpOnViewportChange();
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
  const card = dlg.querySelector(".modal-card--search-help");
  if (card) {
    applySearchHelpPanelSize(card);
    initSearchHelpResize(card);
  }
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
  initSearchHelpResize(popover);
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
        banlist_status: deckCard.banlist_status ?? null,
        genesys_points: deckCard.genesys_points ?? null,
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
  const contextEl = $("#modal-format-context");
  if (contextEl) {
    contextEl.textContent = "";
    contextEl.hidden = true;
  }
  const badgesEl = $("#modal-format-badges");
  if (badgesEl) badgesEl.innerHTML = "";
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
  renderModalFormatBadges(seed);
  renderModalPasscode(seed.passcode ?? null);
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

function formatNumericDate(isoDate) {
  if (!isoDate) return "";
  const parts = String(isoDate).split("-");
  if (parts.length !== 3) return isoDate;
  const [year, month, day] = parts;
  return `${day.padStart(2, "0")}.${month.padStart(2, "0")}.${year}`;
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

function loadCurrencyPreference() {
  try {
    const stored = localStorage.getItem(CURRENCY_STORAGE_KEY);
    if (stored === "HUF" || stored === "EUR") return stored;
  } catch {
    /* ignore */
  }
  return "EUR";
}

function saveCurrencyPreference(currency) {
  try {
    localStorage.setItem(CURRENCY_STORAGE_KEY, currency);
  } catch {
    /* ignore */
  }
}

function getSelectedCurrency() {
  return state.currency === "HUF" ? "HUF" : "EUR";
}

function getEurHufRate() {
  const rate = Number(state.publicConfig?.eur_huf_rate);
  return Number.isFinite(rate) && rate > 0 ? rate : 390;
}

function formatDisplayPrice(eurValue) {
  if (eurValue == null || Number.isNaN(Number(eurValue))) return "—";
  const eur = Number(eurValue);
  if (getSelectedCurrency() === "HUF") {
    return `${Math.round(eur * getEurHufRate()).toLocaleString("hu-HU")} HUF`;
  }
  return `${eur.toFixed(2).replace(".", ",")} €`;
}

function displayInputValue(eurValue) {
  if (eurValue === "" || eurValue == null) return "";
  const num = Number(eurValue);
  if (Number.isNaN(num)) return "";
  if (getSelectedCurrency() === "HUF") {
    return String(Math.round(num * getEurHufRate()));
  }
  return String(num);
}

function priceInputStep() {
  return getSelectedCurrency() === "HUF" ? "1" : "0.01";
}

function parsePriceInput(raw, currency = getSelectedCurrency()) {
  const trimmed = String(raw ?? "").trim();
  if (trimmed === "") return 0;
  const num = Number(trimmed);
  if (Number.isNaN(num) || num < 0) return Number.NaN;
  if (currency === "HUF") {
    return Math.round((num / getEurHufRate()) * 100) / 100;
  }
  return num;
}

function updateCurrencyRateHint() {
  const hint = $("#app-currency-rate");
  if (!hint) return;
  if (getSelectedCurrency() !== "HUF") {
    hint.textContent = "";
    hint.classList.add("hidden");
    hint.setAttribute("aria-hidden", "true");
    return;
  }
  const source = state.publicConfig?.eur_huf_rate_source;
  const rateText = getEurHufRate().toFixed(2);
  let message = `1 EUR = ${rateText} HUF`;
  if (source === "fallback") {
    message += " · fallback";
  }
  hint.textContent = message;
  hint.classList.remove("hidden");
  hint.removeAttribute("aria-hidden");
}

function syncCurrencySelect() {
  const select = $("#app-currency");
  if (select) select.value = getSelectedCurrency();
  updateCurrencyRateHint();
}

function syncPriceInputFields() {
  const code = getSelectedCurrency();
  document.querySelectorAll("[data-currency-suffix]").forEach((el) => {
    el.textContent = code;
  });
  const addPrice = $("#collection-add-price-bought");
  const editSell = $("#collection-edit-sell-price");
  if (addPrice) addPrice.step = priceInputStep();
  if (editSell) editSell.step = priceInputStep();
}

function refreshPriceSurfaces() {
  if (Array.isArray(state.collectionLastItems)) {
    renderCollectionTable(state.collectionLastItems);
  }
  if (collectionDetailStatsCache && isModalVisible("#collection-stats-modal")) {
    renderCollectionDetailStats(collectionDetailStatsCache);
  }
  if (state.currentCard && isModalVisible("#card-modal")) {
    renderModalCard(state.currentCard);
  }
  if (isModalVisible("#collection-add-modal")) {
    syncAddCollectionPrintingFields();
  }
  refreshBulkCollectionCurrency();
}

function setCurrency(currency) {
  const prevCurrency = getSelectedCurrency();
  let addPriceEur = null;
  let editSellEur = null;

  if (isModalVisible("#collection-add-modal")) {
    addPriceEur = parsePriceInput($("#collection-add-price-bought")?.value, prevCurrency);
  }
  if (isModalVisible("#collection-edit-modal")) {
    editSellEur = parsePriceInput($("#collection-edit-sell-price")?.value, prevCurrency);
  }

  const next = currency === "HUF" ? "HUF" : "EUR";
  state.currency = next;
  saveCurrencyPreference(next);
  syncCurrencySelect();
  syncPriceInputFields();

  if (addPriceEur != null && !Number.isNaN(addPriceEur)) {
    const input = $("#collection-add-price-bought");
    if (input) input.value = displayInputValue(addPriceEur);
  }
  if (editSellEur != null && !Number.isNaN(editSellEur)) {
    const input = $("#collection-edit-sell-price");
    if (input) input.value = displayInputValue(editSellEur);
  }

  refreshPriceSurfaces();
}

async function loadPublicConfig() {
  try {
    const res = await fetch(`${API}/public/config`);
    if (res.ok) {
      state.publicConfig = await res.json();
    }
  } catch {
    /* keep defaults */
  }
  syncCurrencySelect();
  syncPriceInputFields();
  refreshPriceSurfaces();
}

function formatMarketPrice(value) {
  return formatDisplayPrice(value);
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

function formatMarketPricesText(p, { showUnavailable = true } = {}) {
  if (!printingHasMarketPrices(p)) {
    if (!showUnavailable) return "";
    return "Prices unavailable";
  }
  const low = formatMarketPrice(p.low_price);
  const avg = formatMarketPrice(p.avg_price);
  const trend = formatMarketPrice(p.trend_price);
  return `${low} / ${avg} / ${trend}`;
}

function formatMarketPrices(p, { showUnavailable = true } = {}) {
  const text = formatMarketPricesText(p, { showUnavailable });
  if (!text) return "";
  if (!printingHasMarketPrices(p)) {
    return `<span class="printing-prices-unavailable">${escapeHtml(text)}</span>`;
  }
  const low = formatMarketPrice(p.low_price);
  const avg = formatMarketPrice(p.avg_price);
  const trend = formatMarketPrice(p.trend_price);
  return `<span aria-label="Low ${low}, Average ${avg}, Trend ${trend}">${text}</span>`;
}

function formatPrintingOwnershipBadges(p) {
  const parts = [];
  if (p.owned_quantity > 0) {
    const variantHint =
      p.collection_variant_count > 1
        ? ` · ${p.collection_variant_count} entries`
        : "";
    parts.push(
      `<span class="badge badge-owned printing-owned-qty" aria-label="Owned: ${p.owned_quantity}${variantHint}">×${p.owned_quantity}${variantHint ? `<span class="printing-variant-hint">${escapeHtml(variantHint)}</span>` : ""}</span>`
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

function formatPasscode(passcode) {
  if (passcode == null) return "";
  return String(passcode).padStart(8, "0");
}

function renderModalPasscode(passcode) {
  const wrap = $("#modal-passcode");
  const text = $("#modal-passcode-text");
  const copyBtn = $("#modal-passcode-copy");
  if (!wrap || !text) return;
  // Cards printed without a passcode have passcode == null -> hide the row.
  if (passcode == null) {
    wrap.hidden = true;
    wrap.removeAttribute("aria-label");
    text.textContent = "";
    if (copyBtn) copyBtn.hidden = true;
    return;
  }
  const code = formatPasscode(passcode);
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
      const hasVariants = owned && (p.collection_variant_count || 0) > 1;
      const canEdit = owned && p.collection_item_id;
      const rowAction = canEdit
        ? "Edit collection entry"
        : hasVariants
          ? "View entries in My Collection"
          : owned
            ? "Select for add to collection"
            : "Select for add to collection";
      const priceCell = hasAnyPrices
        ? `<span class="printing-col printing-col-prices muted">${
            formatMarketPrices(p, { showUnavailable: false }) || "—"
          }</span>`
        : "";
      return `
      <div class="printing-row printing-row--selectable printing-row--grid${selected}${
        owned ? " owned" : ""
      }${canEdit || hasVariants ? " printing-row--editable" : ""}"
        data-printing-key="${escapeHtml(key)}"
        data-collection-item-id="${p.collection_item_id ?? ""}"
        data-set-code="${escapeHtml(p.set_code)}"
        data-collection-variant-count="${p.collection_variant_count ?? 0}"
        role="button" tabindex="0"
        title="${escapeHtml(rowAction)}"
        aria-label="${escapeHtml(`${p.set_code} ${p.set_rarity || ""}. ${rowAction}`)}">
        <span class="printing-col printing-col-main">
          <span class="set-code">${escapeHtml(p.set_code)}</span>
          <span class="rarity">${rarityBadgeHtml({ set_rarity: p.set_rarity, set_rarity_code: p.set_rarity_code })}</span>
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
  renderModalPasscode(card.passcode ?? null);
  $("#modal-meta").textContent = formatModalStats(card);
  renderModalFormatBadges(card);
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
  const card = await api(`/cards/${cardId}${buildCardDetailQuery()}`);
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
  renderModalPasscode(seed?.passcode ?? null);
  setModalLoadingState(true);
  openCardModalOverlay();
  populateDeckSelect();
  if (!fromRouter) syncRouteHash();
  $("#modal-close")?.focus();

  try {
    const card = await api(`/cards/${cardId}${buildCardDetailQuery()}`);
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

function buildCollectionFilterParams() {
  const params = new URLSearchParams();
  if (state.collectionFolder) params.set("folder", state.collectionFolder);
  const cardName = collectionFilterComboboxes?.cardName?.resolveValue();
  if (cardName) params.set("card_name", cardName);
  const setCode = collectionFilterComboboxes?.setCode?.resolveValue();
  if (setCode) params.set("set_code", setCode);
  const setName = collectionFilterComboboxes?.setName?.resolveValue();
  if (setName) params.set("set_name", setName);
  const rarity = $("#collection-rarity")?.value;
  if (rarity) params.set("rarity", rarity);
  const edition = $("#collection-edition")?.value;
  if (edition) params.set("edition", edition);
  const condition = $("#collection-condition")?.value;
  if (condition) params.set("condition", condition);
  return params;
}

function buildCollectionParams(offset = 0) {
  const params = buildCollectionFilterParams();
  params.set("limit", String(COLLECTION_PAGE_SIZE));
  params.set("offset", String(offset));
  params.set("sort", $("#collection-sort")?.value || "set_code");
  const collectionSortDir = readSortDir($("#collection-sort-dir"));
  if (collectionSortDir !== "asc") params.set("sort_dir", collectionSortDir);
  return params;
}

const COLLECTION_TABLE_SKELETON_ROWS = 8;
const COLLECTION_SIDEBAR_SKELETON_ITEMS = 5;

function setCollectionBusy(busy) {
  const main = $("#collection-main");
  if (main) {
    if (busy) main.setAttribute("aria-busy", "true");
    else main.removeAttribute("aria-busy");
  }
}

function renderCollectionTableSkeletonRow() {
  return `
    <tr class="collection-row collection-row--skeleton" aria-hidden="true">
      <td class="collection-thumb"><div class="skeleton collection-skel-thumb"></div></td>
      <td>
        <div class="skeleton skeleton-line collection-skel-line"></div>
        <div class="skeleton skeleton-line skeleton-line--short collection-skel-line"></div>
      </td>
      <td><div class="skeleton skeleton-line collection-skel-line--narrow"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--narrow"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--narrow"></div></td>
      <td><div class="skeleton collection-skel-cell"></div></td>
      <td><div class="skeleton collection-skel-cell"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--narrow"></div></td>
      <td><div class="skeleton collection-skel-badge"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--narrow"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--notes"></div></td>
      <td><div class="skeleton collection-skel-actions"></div></td>
    </tr>`;
}

function renderCollectionTableLoadingSkeleton() {
  const rows = Array.from({ length: COLLECTION_TABLE_SKELETON_ROWS }, () =>
    renderCollectionTableSkeletonRow()
  ).join("");
  return `<tr class="collection-skel-sr-only"><td colspan="12"><p class="sr-only" role="status">Loading collection…</p></td></tr>${rows}`;
}

function showCollectionTableLoading() {
  const tbody = $("#collection-tbody");
  if (!tbody) return;
  $("#collection-empty")?.classList.add("hidden");
  document.querySelector(".collection-table-wrap")?.classList.remove("hidden");
  tbody.innerHTML = renderCollectionTableLoadingSkeleton();
  setCollectionBusy(true);
}

const collectionSuggestionCache = {
  card_name: [],
  set_code: [],
  set_name: [],
};

let collectionFilterComboboxes = null;
let collectionStatsRequestSeq = 0;
let collectionStatsTrigger = null;
let collectionDetailStatsCache = null;

function makeSuggestionCombobox(field, inputSel, listSel, placeholders) {
  return createFilterCombobox({
    inputSel,
    listSel,
    allLabel: placeholders.all,
    emptyMessage: placeholders.empty,
    optionClass: "collection-filter-option",
    getOptions: () =>
      collectionSuggestionCache[field].map((value) => ({ value, label: value })),
    getLabel: (row) => row.label,
    getValue: (row) => row.value,
    filterOptions: (query) => {
      const q = (query || "").trim().toLowerCase();
      const rows = collectionSuggestionCache[field].map((value) => ({
        value,
        label: value,
      }));
      if (!q) return rows;
      return rows.filter((row) => row.label.toLowerCase().includes(q));
    },
    resolveValue: (text, stored) => {
      const trimmed = (text || "").trim();
      if (!trimmed) return "";
      if (stored && collectionSuggestionCache[field].includes(stored)) return stored;
      const exact = collectionSuggestionCache[field].find(
        (value) => value.toLowerCase() === trimmed.toLowerCase()
      );
      if (exact) return exact;
      const partial = collectionSuggestionCache[field].filter((value) =>
        value.toLowerCase().includes(trimmed.toLowerCase())
      );
      if (partial.length === 1) return partial[0];
      return trimmed;
    },
    onSearch: async (query) => {
      const params = buildCollectionFilterParams();
      params.set("field", field);
      if (query?.trim()) params.set("q", query.trim());
      params.delete(field === "card_name" ? "card_name" : field === "set_code" ? "set_code" : "set_name");
      const data = await api(`/collection/suggestions?${params}`);
      collectionSuggestionCache[field] = data.values || [];
    },
  });
}

function initCollectionFilterComboboxes() {
  if (collectionFilterComboboxes) return collectionFilterComboboxes;
  collectionFilterComboboxes = {
    cardName: makeSuggestionCombobox(
      "card_name",
      "#collection-card-name",
      "#collection-card-name-list",
      { all: "All cards", empty: "No matching cards" }
    ),
    setCode: makeSuggestionCombobox(
      "set_code",
      "#collection-set-code",
      "#collection-set-code-list",
      { all: "All set codes", empty: "No matching set codes" }
    ),
    setName: makeSuggestionCombobox(
      "set_name",
      "#collection-set-name",
      "#collection-set-name-list",
      { all: "All set names", empty: "No matching set names" }
    ),
  };
  collectionFilterComboboxes.cardName.bindEvents();
  collectionFilterComboboxes.setCode.bindEvents();
  collectionFilterComboboxes.setName.bindEvents();
  return collectionFilterComboboxes;
}

function closeCollectionFilterComboboxes() {
  collectionFilterComboboxes?.cardName?.close();
  collectionFilterComboboxes?.setCode?.close();
  collectionFilterComboboxes?.setName?.close();
}

function syncCollectionSelectOptions(selectId, values, allLabel) {
  const select = $(selectId);
  if (!select) return;
  const current = select.value;
  select.innerHTML = `<option value="">${escapeHtml(allLabel)}</option>`;
  for (const value of values) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value;
    select.appendChild(opt);
  }
  if (current && values.includes(current)) select.value = current;
  else select.value = "";
}

async function loadCollectionFilterOptions() {
  if (!state.token) return;
  try {
    const data = await api(`/collection/filters?${buildCollectionFilterParams()}`);
    const raritySelect = $("#collection-rarity");
    if (raritySelect) {
      const current = raritySelect.value;
      raritySelect.innerHTML = '<option value="">All rarities</option>';
      for (const row of data.rarities || []) {
        const opt = document.createElement("option");
        opt.value = row.rarity_code;
        opt.textContent = row.rarity_name || row.rarity_code;
        raritySelect.appendChild(opt);
      }
      if (current && (data.rarities || []).some((row) => row.rarity_code === current)) {
        raritySelect.value = current;
      } else {
        raritySelect.value = "";
      }
    }
    syncCollectionSelectOptions("#collection-edition", data.editions || [], "All editions");
    syncCollectionSelectOptions("#collection-condition", data.conditions || [], "All conditions");
  } catch {
    /* ignore filter option errors */
  }
}

function formatCollectionStatPrice(value) {
  return formatDisplayPrice(value);
}

const COLLECTION_STAT_VALUE_IDS = [
  "collection-stat-printings",
  "collection-stat-cards",
  "collection-stat-sum-low",
  "collection-stat-sum-avg",
  "collection-stat-sum-trend",
];

function renderCollectionStatsMaxSkeletonRow() {
  return `
    <tr class="collection-row collection-row--skeleton" aria-hidden="true">
      <td class="collection-thumb"><div class="skeleton collection-skel-thumb"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--narrow"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--narrow"></div></td>
      <td><div class="skeleton collection-skel-badge"></div></td>
      <td><div class="skeleton collection-skel-cell"></div></td>
      <td><div class="skeleton collection-skel-cell"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--narrow"></div></td>
      <td><div class="skeleton collection-skel-badge"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--narrow"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--notes"></div></td>
    </tr>`;
}

function showCollectionDetailStatsLoading() {
  const body = $("#collection-stats-body");
  body?.setAttribute("aria-busy", "true");
  for (const id of COLLECTION_STAT_VALUE_IDS) {
    const el = $(`#${id}`);
    if (el) {
      el.innerHTML = '<span class="skeleton collection-stat-value-skeleton" aria-hidden="true"></span>';
    }
  }
  $("#collection-stats-max-empty")?.classList.add("hidden");
  $("#collection-stats-max-wrap")?.classList.remove("hidden");
  const tbody = $("#collection-stats-max-tbody");
  if (tbody) {
    tbody.innerHTML = `<tr class="collection-skel-sr-only"><td colspan="11"><p class="sr-only" role="status">Loading statistics…</p></td></tr>${renderCollectionStatsMaxSkeletonRow()}`;
  }
}

function resetCollectionDetailStats() {
  $("#collection-stats-body")?.removeAttribute("aria-busy");
  for (const id of COLLECTION_STAT_VALUE_IDS) {
    const el = $(`#${id}`);
    if (el) el.textContent = "—";
  }
  const tbody = $("#collection-stats-max-tbody");
  if (tbody) tbody.innerHTML = "";
  $("#collection-stats-max-wrap")?.classList.add("hidden");
  $("#collection-stats-max-empty")?.classList.remove("hidden");
}

function renderCollectionStatsFolderOptions(selectedFolder = state.collectionFolder) {
  const select = $("#collection-stats-folder");
  if (!select || !state.collectionStats) return;
  const s = state.collectionStats;
  const parts = [`<option value="">All</option>`];
  if (s.no_folder_count > 0) {
    parts.push(`<option value="${NO_FOLDER}">No Folder</option>`);
  }
  for (const folder of s.folders) {
    parts.push(
      `<option value="${folder.id}">${escapeHtml(folder.name)}</option>`
    );
  }
  select.innerHTML = parts.join("");
  select.value = selectedFolder ?? "";
}

function renderCollectionDetailStats(data) {
  collectionDetailStatsCache = data;
  $("#collection-stats-body")?.removeAttribute("aria-busy");
  $("#collection-stat-printings")?.replaceChildren(
    document.createTextNode((data.unique_printings ?? 0).toLocaleString())
  );
  $("#collection-stat-cards")?.replaceChildren(
    document.createTextNode((data.total_quantity ?? 0).toLocaleString())
  );
  $("#collection-stat-sum-low")?.replaceChildren(
    document.createTextNode(formatCollectionStatPrice(data.sum_low_price))
  );
  $("#collection-stat-sum-avg")?.replaceChildren(
    document.createTextNode(formatCollectionStatPrice(data.sum_avg_price))
  );
  $("#collection-stat-sum-trend")?.replaceChildren(
    document.createTextNode(formatCollectionStatPrice(data.sum_trend_price))
  );

  const tbody = $("#collection-stats-max-tbody");
  const wrap = $("#collection-stats-max-wrap");
  const emptyEl = $("#collection-stats-max-empty");
  const item = data.max_value_item;
  if (!tbody) return;

  if (!item) {
    tbody.innerHTML = "";
    wrap?.classList.add("hidden");
    emptyEl?.classList.remove("hidden");
    return;
  }

  emptyEl?.classList.add("hidden");
  wrap?.classList.remove("hidden");
  tbody.innerHTML = `
    <tr class="collection-row collection-stats-max-row" data-card-id="${item.card_id ?? ""}">
      <td class="collection-thumb">${cardImgTag(item.image_url_small, 'class="collection-thumb-img"')}</td>
      <td>${escapeHtml(item.card_name || "—")}</td>
      <td><span class="set-code">${escapeHtml(item.set_code)}</span></td>
      ${collectionFolderCell(item)}
      <td>${rarityBadgeHtml(item)}</td>
      <td>${editionBadgeHtml(item.printing || item.edition)}</td>
      <td class="collection-qty-cell">${item.quantity}</td>
      <td class="collection-qty-cell collection-col-trade-qty">${item.trade_quantity ?? 0}</td>
      <td>${formatMarketPrice(resolvedCollectionSellPrice(item))}</td>
      <td>${conditionBadgeHtml(item.condition)}</td>
      ${collectionReleaseDateCell(item)}
      ${collectionNotesCell(item)}
    </tr>`;

  tbody.querySelector(".collection-thumb")?.addEventListener("click", () => {
    if (item.card_id) openCardModal(item.card_id);
  });
}

async function loadCollectionDetailStats(folder = state.collectionFolder) {
  const seq = ++collectionStatsRequestSeq;
  showCollectionDetailStatsLoading();
  const params = new URLSearchParams();
  if (folder) params.set("folder", folder);
  try {
    const data = await api(`/collection/stats/detail?${params}`);
    if (seq !== collectionStatsRequestSeq) return;
    renderCollectionDetailStats(data);
  } catch (err) {
    if (seq !== collectionStatsRequestSeq) return;
    resetCollectionDetailStats();
    showToast(err.message || "Could not load statistics", { variant: "error" });
  }
}

function openCollectionStatsModal() {
  const modal = $("#collection-stats-modal");
  const trigger = $("#collection-stats-btn");
  if (!modal) return;
  collectionStatsTrigger = trigger;
  renderCollectionStatsFolderOptions(state.collectionFolder);
  modal.hidden = false;
  trigger?.setAttribute("aria-expanded", "true");
  syncModalOpenClass();
  loadCollectionDetailStats($("#collection-stats-folder")?.value || state.collectionFolder);
  $("#collection-stats-folder")?.focus();
}

function closeCollectionStatsModal() {
  const modal = $("#collection-stats-modal");
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  syncModalOpenClass();
  (collectionStatsTrigger ?? $("#collection-stats-btn"))?.setAttribute("aria-expanded", "false");
  (collectionStatsTrigger ?? $("#collection-stats-btn"))?.focus();
  collectionStatsTrigger = null;
}

function showCollectionStatsLoading() {
  const btn = $("#collection-stats-btn");
  if (!btn) return;
  btn.setAttribute("aria-busy", "true");
}

function clearCollectionStatsLoading() {
  $("#collection-stats-btn")?.removeAttribute("aria-busy");
}

function renderCollectionStatsLine() {
  clearCollectionStatsLoading();
}

function renderCollectionSidebarLoadingSkeleton() {
  const list = $("#collection-folder-list");
  if (!list) return;
  list.innerHTML = Array.from({ length: COLLECTION_SIDEBAR_SKELETON_ITEMS }, () => `
    <li class="collection-folder-skeleton" aria-hidden="true">
      <div class="skeleton skeleton-line collection-skel-folder-label"></div>
      <div class="skeleton skeleton-line collection-skel-folder-count"></div>
    </li>`).join("");
}

function showCollectionViewLoading() {
  showCollectionStatsLoading();
  renderCollectionSidebarLoadingSkeleton();
  showCollectionTableLoading();
  $("#collection-pagination")?.classList.add("hidden");
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
    (item.folders || [])
      .filter((row) => row.folder_id != null)
      .map((row) => [row.folder_id, row.quantity])
  );
  const hasLegacyNoFolder = (item.folders || []).some((row) => row.folder_id == null);

  const popover = document.createElement("div");
  popover.className = "folder-allocation-popover";
  popover.dataset.itemId = String(itemId);
  popover.innerHTML = `
    <p class="folder-allocation-title">Assign folders (total: ${totalQty})</p>
    ${
      hasLegacyNoFolder
        ? '<p class="folder-allocation-hint muted">Assign all copies to a folder.</p>'
        : ""
    }
    <div class="folder-allocation-options">
      ${
        folders.length
          ? folders
              .map(
                (folder) => `
        <label class="folder-allocation-option">
          <input type="checkbox" data-folder-id="${folder.id}" ${current.has(folder.id) ? "checked" : ""} />
          <span>${escapeHtml(folder.name)}</span>
          <input type="number" class="folder-allocation-qty" min="1" max="${totalQty}" value="${current.get(folder.id) || 1}" ${current.has(folder.id) ? "" : "disabled"} />
        </label>`
              )
              .join("")
          : '<p class="muted">Create a folder first.</p>'
      }
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
      if (!rawId) return;
      selected.push({
        folder_id: Number(rawId),
        quantity: qty,
      });
    });
    if (!selected.length) {
      showToast("Folder is required. Select at least one folder.", { variant: "error" });
      return;
    }
    if (selected.some((row) => row.folder_id == null || Number.isNaN(row.folder_id))) {
      showToast("Folder is required.", { variant: "error" });
      return;
    }
    const sum = selected.reduce((acc, row) => acc + row.quantity, 0);
    if (sum !== totalQty) {
      showToast(`Quantities must sum to ${totalQty} (currently ${sum}).`, { variant: "error" });
      return;
    }
    try {
      await patchCollectionItem(itemId, { folder_allocations: selected });
      closeFolderAllocationPopover();
      await loadCollectionPage(state.collectionPage);
    } catch (err) {
      showToast(err.message, { variant: "error" });
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
  for (const folder of state.collectionStats?.folders || []) {
    if (folder.id === currentFolderId) continue;
    targets.push({ id: folder.id, name: folder.name });
  }
  if (!targets.length) {
    showToast("No other folder available. Create a folder first.", { variant: "error" });
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
    if (!targetRaw) {
      showError("Folder is required.");
      return;
    }
    const targetFolderId = Number(targetRaw);

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
    if (updated.some((row) => row.folder_id == null)) {
      showError("Folder is required. Move all unfiled copies to a folder.");
      return;
    }
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
  const name = await appPrompt({
    title: "New folder",
    label: "Folder name",
    submitLabel: "Create",
  });
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
    showToast(err.message, { variant: "error" });
  }
}

function closeDeleteFolderPopover() {
  document.querySelector(".delete-folder-popover")?.remove();
}

function openDeleteFolderPopover(folderId, folderName, count, qty, anchor) {
  closeDeleteFolderPopover();
  closeAllCollectionFolderMenus();
  closeFolderAllocationPopover();
  closeMoveCopyPopover();

  const destinations = (state.collectionStats?.folders || []).filter(
    (folder) => folder.id !== folderId
  );
  const canMove = destinations.length > 0;
  const defaultMode = canMove ? "move" : "remove";

  const popover = document.createElement("div");
  popover.className = "folder-allocation-popover delete-folder-popover";
  popover.innerHTML = `
    <p class="folder-allocation-title">Delete "${escapeHtml(folderName)}"</p>
    <p class="muted">${count} card row(s) (${qty} copies) are in this folder.</p>
    <fieldset class="delete-folder-mode-fieldset">
      <legend class="sr-only">What should happen to the cards?</legend>
      <label class="delete-folder-mode${canMove ? "" : " delete-folder-mode--disabled"}">
        <input type="radio" name="delete-folder-mode" value="move" ${defaultMode === "move" ? "checked" : ""} ${canMove ? "" : "disabled"} />
        <span>Move cards to another folder</span>
      </label>
      <label class="delete-folder-mode">
        <input type="radio" name="delete-folder-mode" value="remove" ${defaultMode === "remove" ? "checked" : ""} />
        <span>Remove cards from collection</span>
      </label>
    </fieldset>
    <label class="move-copy-field delete-folder-move-field${canMove && defaultMode === "move" ? "" : " hidden"}">
      <span>Move cards to</span>
      <select class="delete-folder-target" ${canMove ? "" : "disabled"}>
        <option value="" disabled selected>Select a folder…</option>
        ${destinations
          .map(
            (folder) =>
              `<option value="${folder.id}">${escapeHtml(folder.name)}</option>`
          )
          .join("")}
      </select>
    </label>
    <p class="delete-folder-remove-warning muted${defaultMode === "remove" ? "" : " hidden"}">
      All copies in this folder will be removed from your collection. Cards in other folders are not affected.
    </p>
    <p class="move-copy-error hidden"></p>
    <div class="folder-allocation-actions">
      <button type="button" class="secondary delete-folder-cancel">Cancel</button>
      <button type="button" class="delete-folder-confirm">Delete</button>
    </div>`;

  document.body.appendChild(popover);
  if (anchor) {
    const rect = anchor.getBoundingClientRect();
    popover.style.top = `${rect.bottom + window.scrollY + 4}px`;
    popover.style.left = `${Math.min(rect.left + window.scrollX, window.innerWidth - popover.offsetWidth - 8)}px`;
  }

  const errorEl = popover.querySelector(".move-copy-error");
  const moveField = popover.querySelector(".delete-folder-move-field");
  const removeWarning = popover.querySelector(".delete-folder-remove-warning");

  function selectedMode() {
    return popover.querySelector('input[name="delete-folder-mode"]:checked')?.value || "remove";
  }

  function syncModeUi() {
    const mode = selectedMode();
    moveField?.classList.toggle("hidden", mode !== "move");
    removeWarning?.classList.toggle("hidden", mode !== "remove");
    errorEl.classList.add("hidden");
  }

  popover.querySelectorAll('input[name="delete-folder-mode"]').forEach((input) => {
    input.addEventListener("change", syncModeUi);
  });
  popover.querySelector(".delete-folder-cancel")?.addEventListener("click", closeDeleteFolderPopover);
  popover.querySelector(".delete-folder-confirm")?.addEventListener("click", async () => {
    errorEl.classList.add("hidden");
    const mode = selectedMode();
    let url = `/collection/folders/${folderId}`;
    if (mode === "remove") {
      url += "?remove_cards=true";
    } else {
      const targetRaw = popover.querySelector(".delete-folder-target")?.value ?? "";
      if (!targetRaw) {
        errorEl.textContent = "Folder is required.";
        errorEl.classList.remove("hidden");
        return;
      }
      url += `?target_folder_id=${Number(targetRaw)}`;
    }
    try {
      await api(url, { method: "DELETE" });
      if (state.collectionFolder === String(folderId)) {
        state.collectionFolder = null;
      }
      closeDeleteFolderPopover();
      await loadCollectionStats();
      renderCollectionStatsLine();
      renderCollectionSidebar();
      await loadCollectionPage(state.collectionPage);
    } catch (err) {
      errorEl.textContent = err.message || "Could not delete folder.";
      errorEl.classList.remove("hidden");
    }
  });

  setTimeout(() => {
    document.addEventListener(
      "click",
      (e) => {
        if (
          !popover.contains(e.target) &&
          !e.target.closest(".collection-folder-menu-wrap")
        ) {
          closeDeleteFolderPopover();
        }
      },
      { once: true }
    );
  }, 0);
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
        ${
          e.deletable
            ? `<div class="collection-folder-menu-wrap preset-menu-wrap">
          <button type="button" class="icon-btn secondary collection-folder-menu-btn preset-menu-btn" aria-label="Folder actions" title="Folder actions" aria-haspopup="menu" aria-expanded="false">⋮</button>
          <div class="collection-folder-menu preset-menu" hidden role="menu">
            <button type="button" role="menuitem" class="collection-folder-rename-btn">Rename</button>
            <button type="button" role="menuitem" class="collection-folder-delete-btn preset-menu-danger">Delete</button>
          </div>
        </div>`
            : ""
        }
      </span>
    </li>`
    )
    .join("");

  list.querySelectorAll("li").forEach((li) => {
    li.addEventListener("click", async (e) => {
      if (e.target.closest(".collection-folder-menu-wrap")) return;
      const raw = li.dataset.folder;
      state.collectionFolder = raw === "" ? null : decodeURIComponent(raw);
      state.collectionPage = 0;
      renderCollectionSidebar();
      syncRouteHash();
      closeCollectionFilterComboboxes();
      await loadCollectionFilterOptions();
      await loadCollectionPage(0);
    });

    const folderId = li.dataset.folderId ? Number(li.dataset.folderId) : null;
    const folderName = () =>
      li.querySelector(".collection-folder-label")?.textContent || "folder";

    async function renameFolder() {
      if (!folderId) return;
      const fromName = folderName();
      const toName = await appPrompt({
        title: "Rename folder",
        label: "Folder name",
        defaultValue: fromName,
        submitLabel: "Rename",
      });
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
        showToast(err.message, { variant: "error" });
      }
    }

    async function deleteFolder(anchor) {
      if (!folderId) return;
      const name = folderName();
      const folderStats = s.folders.find((row) => row.id === folderId);
      const qty = folderStats?.quantity ?? 0;
      const count = folderStats?.item_count ?? 0;
      if (count === 0 && qty === 0) {
        const ok = await appConfirm({
          title: "Delete folder",
          message: `Delete empty folder "${name}"?`,
          confirmLabel: "Delete",
          danger: true,
        });
        if (!ok) return;
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
          showToast(err.message, { variant: "error" });
        }
        return;
      }
      openDeleteFolderPopover(folderId, name, count, qty, anchor);
    }

    li.querySelector(".collection-folder-menu-btn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleCollectionFolderMenu(e.currentTarget);
    });
    li.querySelector(".collection-folder-rename-btn")?.addEventListener("click", async (e) => {
      e.stopPropagation();
      closeAllCollectionFolderMenus();
      await renameFolder();
    });
    li.querySelector(".collection-folder-delete-btn")?.addEventListener("click", async (e) => {
      e.stopPropagation();
      const menuBtn = li.querySelector(".collection-folder-menu-btn");
      closeAllCollectionFolderMenus();
      await deleteFolder(menuBtn);
    });

    if (folderId) {
      li.addEventListener("dblclick", async (e) => {
        if (e.target.closest(".collection-folder-menu-wrap")) return;
        e.preventDefault();
        await renameFolder();
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
  if (askConfirm) {
    const ok = await appConfirm({
      title: "Remove printing",
      message: "Remove this printing from your collection?",
      confirmLabel: "Remove",
      danger: true,
    });
    if (!ok) return false;
  }
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
    '<option value="" disabled>Select a folder…</option>',
    ...folders.map(
      (f) => `<option value="${f.id}">${escapeHtml(f.name)}</option>`
    ),
  ].join("");
  if (current && [...sel.options].some((o) => o.value === current)) {
    sel.value = current;
  } else {
    sel.value = "";
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
    rarityEl.innerHTML = rarityBadgeHtml({
      set_rarity: printing.set_rarity,
      set_rarity_code: printing.set_rarity_code,
    });
  }

  const staticEl = $("#collection-add-card-number-static");
  if (staticEl) staticEl.textContent = printing.set_code;

  const pricesEl = $("#collection-add-market-prices");
  if (pricesEl) {
    pricesEl.textContent = formatMarketPricesText(printing, { showUnavailable: false }) || "—";
  }
}

function setAddCollectionFieldVisible(el, visible) {
  if (!el) return;
  el.hidden = !visible;
  el.classList.toggle("hidden", !visible);
}

function renderAddCollectionCardNumberControl(printings, preselectKey) {
  const wrapMulti = $("#collection-add-card-number-wrap");
  const wrapStatic = $("#collection-add-card-number-static-wrap");
  const rarityWrap = $("#collection-add-rarity-wrap");
  const sel = $("#collection-add-card-number");
  if (!wrapMulti || !wrapStatic || !sel) return;

  if (printings.length <= 1) {
    setAddCollectionFieldVisible(wrapMulti, false);
    setAddCollectionFieldVisible(wrapStatic, true);
    setAddCollectionFieldVisible(rarityWrap, true);
  } else {
    setAddCollectionFieldVisible(wrapMulti, true);
    setAddCollectionFieldVisible(wrapStatic, false);
    setAddCollectionFieldVisible(rarityWrap, false);
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
  $("#collection-add-price-bought").value = displayInputValue(0);
  syncPriceInputFields();
  $("#collection-add-date-bought").value = todayIsoDate();
  $("#collection-add-notes").value = "";
  $("#collection-add-folder").value = "";
  resetAddCollectionNewFolderRow();

  syncAddCollectionPrintingFields();

  const dlg = $("#collection-add-modal");
  if (!dlg) return;
  dlg.hidden = false;
  syncModalOpenClass();
  const modalCard = dlg.querySelector(".modal-card--collection-add");
  if (modalCard) {
    applyCollectionAddPanelSize(modalCard);
    initCollectionAddResize(modalCard);
  }
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

  const priceBought = parsePriceInput($("#collection-add-price-bought").value);
  if (Number.isNaN(priceBought) || priceBought < 0) {
    showToast("Price bought must be 0 or greater.", { variant: "error" });
    return;
  }

  const folderVal = $("#collection-add-folder").value;
  if (!folderVal) {
    showToast("Folder is required.", { variant: "error" });
    return;
  }
  const folderId = Number(folderVal);
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

  const notesVal = ($("#collection-add-notes")?.value || "").trim();
  if (notesVal) {
    body.notes = notesVal;
  }

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

async function openCollectionForPrinting(setCode) {
  const setCodeInput = $("#collection-set-code");
  if (setCodeInput) setCodeInput.value = setCode;
  state.collectionPage = 0;
  closeCardModalOverlay();
  await switchView("collection");
  await loadCollectionPage(0);
}

async function activateModalPrintingRow(row) {
  const key = row?.dataset.printingKey;
  if (!key) return;
  const itemId = Number(row.dataset.collectionItemId);
  const variantCount = Number(row.dataset.collectionVariantCount || 0);
  const setCode = row.dataset.setCode || "";
  const printing = (state.currentCard?.printings || []).find(
    (p) => collectionPrintingKey(p) === key
  );
  if (printing?.owned_quantity > 0 && variantCount > 1 && !itemId) {
    await openCollectionForPrinting(setCode);
    showToast("Multiple editions/conditions — pick the row to edit in My Collection.");
    return;
  }
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

  const editionSel = $("#collection-edit-edition");
  const currentEdition = item.printing || item.edition || "Unlimited";
  const isKnownEdition = COLLECTION_EDITIONS.includes(currentEdition);
  editionSel.innerHTML = [
    ...(currentEdition && !isKnownEdition
      ? [
          `<option value="${escapeHtml(currentEdition)}">${escapeHtml(currentEdition)}</option>`,
        ]
      : []),
    ...COLLECTION_EDITIONS.map(
      (e) => `<option value="${escapeHtml(e)}">${escapeHtml(e)}</option>`
    ),
  ].join("");
  editionSel.value = currentEdition;

  $("#collection-edit-quantity").value = String(item.quantity);
  $("#collection-edit-trade-quantity").value = String(item.trade_quantity ?? 0);
  const sellDefault = resolvedCollectionSellPrice(item);
  $("#collection-edit-sell-price").value = displayInputValue(sellDefault);
  syncPriceInputFields();
  $("#collection-edit-notes").value = item.notes || "";

  const setSel = $("#collection-edit-set");
  const raritySel = $("#collection-edit-rarity");
  const hint = $("#collection-edit-hint");
  hint.classList.add("hidden");
  setSel.disabled = true;
  raritySel.disabled = true;
  setSel.innerHTML = `<option value="${escapeHtml(item.set_code)}">${escapeHtml(item.set_code)}</option>`;
  raritySel.innerHTML = `<option value="${escapeHtml(item.rarity_code)}">${escapeHtml(item.rarity_name || item.rarity_display || item.rarity_code)}</option>`;

  dlg.hidden = false;
  syncModalOpenClass();
  $("#collection-edit-close")?.focus();

  if (!item.card_id) {
    hint.textContent =
      "This row isn't matched to the catalog, so Set and Rarity can't be changed here.";
    hint.classList.remove("hidden");
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
    hint.textContent = `Could not load printings: ${err.message}`;
    hint.classList.remove("hidden");
  }
}

async function saveCollectionEdit() {
  if (!collectionEditContext) return;
  const { item, itemId } = collectionEditContext;

  const qty = Number($("#collection-edit-quantity").value);
  if (!Number.isInteger(qty) || qty < 1) {
    showToast("Quantity must be a whole number of at least 1.", { variant: "error" });
    return;
  }

  const tradeQty = Number($("#collection-edit-trade-quantity").value);
  if (!Number.isInteger(tradeQty) || tradeQty < 0) {
    showToast("Trade quantity must be a whole number of 0 or more.", { variant: "error" });
    return;
  }

  const sellPrice = parsePriceInput($("#collection-edit-sell-price").value);
  if (Number.isNaN(sellPrice) || sellPrice < 0) {
    showToast("Sell price must be 0 or greater.", { variant: "error" });
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

  const condVal = normalizeConditionValue($("#collection-edit-condition").value);
  const currentCondition = normalizeConditionValue(item.condition || "");
  const condCanonical = COLLECTION_CONDITIONS.some((c) => c.value === condVal);
  if (condVal !== currentCondition && condCanonical) {
    body.condition = condVal;
  }

  const editionVal = normalizeEditionValue($("#collection-edit-edition")?.value);
  const currentEdition = normalizeEditionValue(item.printing || item.edition || "Unlimited");
  if (editionVal && editionVal !== currentEdition) {
    body.printing = editionVal;
  }

  if (qty !== item.quantity) {
    const folderFilter = state.collectionFolder;
    // All / No Folder views: total quantity only (legacy No Folder rows keep
    // their null allocation until reassigned via the folder picker).
    if (!folderFilter || folderFilter === NO_FOLDER) {
      body.quantity = qty;
    } else {
      const folderId = Number(folderFilter);
      const allocs = (item.folders || []).map((row) => ({
        folder_id: row.folder_id,
        quantity: row.quantity,
      }));
      const updated = allocs
        .map((row) =>
          row.folder_id === folderId ? { ...row, quantity: qty } : row
        )
        .filter((row) => row.quantity > 0);
      if (updated.some((row) => row.folder_id == null)) {
        showToast("Folder is required. Assign all unfiled copies to a folder first.", { variant: "error" });
        return;
      }
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

  const notesVal = ($("#collection-edit-notes")?.value || "").trim();
  const currentNotes = (item.notes || "").trim();
  if (notesVal !== currentNotes) {
    body.notes = notesVal || null;
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
    showToast(err.message, { variant: "error" });
  }
}

function renderCollectionTable(items) {
  const tbody = $("#collection-tbody");
  const emptyEl = $("#collection-empty");
  const tableWrap = document.querySelector(".collection-table-wrap");
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
    setCollectionBusy(false);
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
      ${collectionFolderCell(item)}
      <td>${rarityBadgeHtml(item)}</td>
      <td>${editionBadgeHtml(item.printing || item.edition)}</td>
      <td class="collection-qty-cell">${item.quantity}</td>
      <td class="collection-qty-cell collection-col-trade-qty">${item.trade_quantity ?? 0}</td>
      <td>${formatMarketPrice(resolvedCollectionSellPrice(item))}</td>
      <td>${conditionBadgeHtml(item.condition)}</td>
      ${collectionReleaseDateCell(item)}
      ${collectionNotesCell(item)}
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
  setCollectionBusy(false);
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
        showToast(err.message, { variant: "error" });
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
  showCollectionTableLoading();
  $("#collection-pagination")?.classList.add("hidden");

  try {
    const offset = pageIndex * COLLECTION_PAGE_SIZE;
    const page = await api(`/collection?${buildCollectionParams(offset)}`);
    if (seq !== collectionRequestSeq) return;
    state.collectionTotal = page.total;
    syncCollectionTableHeaderSort();
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
    setCollectionBusy(false);
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="12" class="empty-msg">${escapeHtml(err.message)}</td></tr>`;
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
  syncCollectionTableHeaderSort();
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
      setCollectionBusy(false);
      const tbody = $("#collection-tbody");
      if (tbody) {
        tbody.innerHTML = `<tr><td colspan="12" class="empty-msg">${escapeHtml(err.message)}</td></tr>`;
      }
    });
    return;
  }

  try {
    await loadCollectionViewFresh();
  } catch (err) {
    setCollectionBusy(false);
    const tbody = $("#collection-tbody");
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="12" class="empty-msg">${escapeHtml(err.message)}</td></tr>`;
    }
  }
}

async function loadCollectionViewFresh() {
  showCollectionViewLoading();
  await loadCollectionStats();
  renderCollectionStatsLine();
  renderCollectionSidebar();
  initCollectionFilterComboboxes();
  await loadCollectionFilterOptions();
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
  downloadBlob(new Blob(["\ufeff", csvText], { type: "text/csv;charset=utf-8" }), filename);
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function filenameFromContentDisposition(header) {
  if (!header) return null;
  const utfMatch = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header);
  if (utfMatch?.[1]) {
    try {
      return decodeURIComponent(utfMatch[1].trim());
    } catch {
      /* fall through */
    }
  }
  const plainMatch = /filename\s*=\s*"([^"]+)"/i.exec(header)
    || /filename\s*=\s*([^;]+)/i.exec(header);
  return plainMatch?.[1]?.trim() || null;
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
  const headers = {};
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
  const filename =
    filenameFromContentDisposition(res.headers.get("Content-Disposition"))
    || fmt?.filename
    || "collection_export.bin";
  const blob = await res.blob();
  downloadBlob(blob, filename);
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
  return (deck.cards || []).length;
}

function renderDeckStack(previewCards) {
  const cards = previewCards?.length ? previewCards : [{ image_url: null }];
  const stack = cards.slice(0, 3);
  return stack
    .map((c) => cardImgTag(c.image_url || null, 'class="deck-stack-card"'))
    .join("");
}

function closeAllDeckTileMenus() {
  document.querySelectorAll(".deck-tile-menu").forEach((menu) => {
    if (menu.hidden) return;
    menu.hidden = true;
    menu.classList.remove("deck-tile-menu--fixed");
    menu.style.top = "";
    menu.style.left = "";
  });
  document.querySelectorAll(".deck-tile-menu-btn").forEach((btn) => {
    btn.setAttribute("aria-expanded", "false");
  });
}

function openDeckTileMenu(btn) {
  const wrap = btn.closest(".deck-tile-menu-wrap");
  const menu = wrap?.querySelector(".deck-tile-menu");
  if (!menu) return;
  closeAllDeckTileMenus();
  closeSearchToolPanels();
  closeAllCollectionRowMenus();
  menu.hidden = false;
  btn.setAttribute("aria-expanded", "true");
  menu.classList.add("deck-tile-menu--fixed");
  const rect = btn.getBoundingClientRect();
  const menuWidth = menu.offsetWidth;
  const left = Math.min(rect.right - menuWidth, window.innerWidth - menuWidth - 8);
  menu.style.top = `${rect.bottom + 4}px`;
  menu.style.left = `${Math.max(8, left)}px`;
}

function toggleDeckTileMenu(btn) {
  const wrap = btn.closest(".deck-tile-menu-wrap");
  const menu = wrap?.querySelector(".deck-tile-menu");
  if (!menu) return;
  if (!menu.hidden) {
    closeAllDeckTileMenus();
    return;
  }
  openDeckTileMenu(btn);
}

async function renameDeckFromList(deckId, currentName) {
  const newName = await appPrompt({
    title: "Rename deck",
    label: "Deck name",
    defaultValue: currentName,
    submitLabel: "Rename",
  });
  if (!newName?.trim() || newName.trim() === currentName) return;
  try {
    await api(`/decks/${deckId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName.trim() }),
    });
    if (state.activeDeckId === deckId) {
      if (state.deckDraft) state.deckDraft.name = newName.trim();
      if (state.deckSaved) state.deckSaved.name = newName.trim();
      const nameEl = $("#deck-name");
      if (nameEl) nameEl.textContent = newName.trim();
      updateRouteDocumentTitle();
    }
    invalidateDecksCache();
    await loadDecks({ force: true });
    await populateDeckSelect();
    showToast("Deck renamed.");
  } catch (err) {
    showToast(err.message, { variant: "error", durationMs: 5000 });
  }
}

async function deleteDeckFromList(deckId, label) {
  const ok = await appConfirm({
    title: "Delete deck",
    message: `Delete deck "${label}"? This cannot be undone.`,
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  try {
    await api(`/decks/${deckId}`, { method: "DELETE" });
    if (state.activeDeckId === deckId) {
      state.activeDeckId = null;
      closeDeckDetail();
    }
    invalidateDecksCache();
    await loadDecks({ force: true });
    await populateDeckSelect();
    showToast("Deck deleted.");
  } catch (err) {
    showToast(err.message, { variant: "error", durationMs: 5000 });
  }
}

function setupDecksGridDelegation() {
  const grid = $("#decks-grid");
  if (!grid || grid.dataset.delegationBound) return;
  grid.dataset.delegationBound = "1";
  grid.addEventListener("click", async (e) => {
    const menuBtn = e.target.closest(".deck-tile-menu-btn");
    if (menuBtn) {
      e.stopPropagation();
      toggleDeckTileMenu(menuBtn);
      return;
    }
    const renameBtn = e.target.closest(".deck-tile-rename-btn");
    if (renameBtn) {
      e.stopPropagation();
      closeAllDeckTileMenus();
      const deckId = Number(renameBtn.dataset.id);
      const tile = renameBtn.closest(".deck-tile");
      const name = tile?.querySelector(".deck-tile-name")?.textContent || "";
      await renameDeckFromList(deckId, name);
      return;
    }
    const deleteBtn = e.target.closest(".deck-tile-delete-btn");
    if (deleteBtn) {
      e.stopPropagation();
      closeAllDeckTileMenus();
      const deckId = Number(deleteBtn.dataset.id);
      const tile = deleteBtn.closest(".deck-tile");
      const label = tile?.querySelector(".deck-tile-name")?.textContent || "this deck";
      await deleteDeckFromList(deckId, label);
      return;
    }
    if (e.target.closest(".deck-tile-menu-wrap")) return;
    const tile = e.target.closest(".deck-tile");
    if (tile) openDeckDetail(Number(tile.dataset.id));
  });
  grid.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    if (e.target.closest(".deck-tile-menu-wrap")) return;
    const tile = e.target.closest(".deck-tile");
    if (!tile || e.target !== tile) return;
    e.preventDefault();
    openDeckDetail(Number(tile.dataset.id));
  });
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
      const fmtLabel = formatDisplayName(d.format_code);
      const formatLine = fmtLabel
        ? `<span class="deck-tile-format muted">${escapeHtml(fmtLabel)}</span>`
        : "";
      const dateLine =
        state.decksSort === "updated_at" && d.updated_at
          ? `<span class="deck-tile-date muted">${renderDeckTimeHtml(d.updated_at, "Edited")}</span>`
          : "";
      return `
    <article class="deck-tile" data-id="${d.id}" tabindex="0" role="button" aria-label="${escapeHtml(d.name)}, ${countLabel}">
      <div class="deck-tile-menu-wrap preset-menu-wrap">
        <button type="button" class="icon-btn secondary deck-tile-menu-btn preset-menu-btn" data-id="${d.id}" aria-label="Deck actions for ${escapeHtml(d.name)}" title="Deck actions" aria-haspopup="menu" aria-expanded="false">⋯</button>
        <div class="deck-tile-menu preset-menu" hidden role="menu">
          <button type="button" role="menuitem" class="deck-tile-rename-btn" data-id="${d.id}">Rename</button>
          <button type="button" role="menuitem" class="deck-tile-delete-btn preset-menu-danger" data-id="${d.id}">Delete</button>
        </div>
      </div>
      <div class="deck-stack">${renderDeckStack(d.preview_cards)}</div>
      <div class="deck-tile-meta">
        <span class="deck-tile-name">${escapeHtml(d.name)}</span>
        <span class="deck-tile-count">${countLabel}</span>
        ${formatLine}
        ${dateLine}
      </div>
    </article>`;
    })
    .join("");
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

function cloneDeck(deck) {
  return JSON.parse(JSON.stringify(deck));
}

function setDeckDraftFromServer(deck) {
  const normalized = {
    ...deck,
    cards: normalizeDeckCardsForDraft(deck.cards),
  };
  state.deckSaved = cloneDeck(normalized);
  state.deckDraft = cloneDeck(normalized);
  state.deckDirty = false;
  state.activeDeckDetail = state.deckDraft;
  updateDeckActionBar();
}

function normalizeDeckCardsForDraft(cards) {
  const result = [];
  for (const card of cards || []) {
    const qty = Math.max(Number(card.quantity) || 1, 1);
    for (let i = 0; i < qty; i += 1) {
      result.push({ ...card, quantity: 1 });
    }
  }
  return result;
}

function markDeckDirty() {
  state.deckDirty = true;
  state.activeDeckDetail = state.deckDraft;
  updateDeckActionBar();
}

function updateDeckActionBar() {
  const dirty = Boolean(state.deckDirty);
  $("#deck-dirty-indicator")?.classList.toggle("hidden", !dirty);
  const saveBtn = $("#deck-save-btn");
  const discardBtn = $("#deck-discard-btn");
  if (saveBtn) saveBtn.disabled = !dirty;
  if (discardBtn) discardBtn.disabled = !dirty;
}

function deckToSavePayload(draft) {
  return {
    name: draft.name,
    description: draft.description ?? null,
    format_code: draft.format_code || "advanced",
    banlist_revision_id: draft.banlist_revision_id ?? null,
    genesys_point_list_id: draft.genesys_point_list_id ?? null,
    preview_card_id: draft.preview_card_id ?? null,
    cards: (draft.cards || []).map((c) => ({
      card_id: c.card_id,
      zone: c.zone,
      quantity: 1,
    })),
  };
}

function syncDraftFormatFromForm() {
  if (!state.deckDraft) return;
  const fmt = state.formatsList.find((f) => f.code === $("#deck-format")?.value);
  state.deckDraft.format_code = $("#deck-format")?.value || state.deckDraft.format_code;
  state.deckDraft.banlist_revision_id =
    fmt?.banlist_selectable && $("#deck-banlist")?.value
      ? Number($("#deck-banlist").value)
      : null;
  state.deckDraft.genesys_point_list_id = $("#deck-genesys-list")?.value
    ? Number($("#deck-genesys-list").value)
    : null;
}

function refreshDraftCounts() {
  if (!state.deckDraft) return;
  const cards = state.deckDraft.cards || [];
  state.deckDraft.card_count = cards.length;
  state.deckDraft.main_count = cards.filter((c) => c.zone === "main").length;
  state.deckDraft.extra_count = cards.filter((c) => c.zone === "extra").length;
  state.deckDraft.side_count = cards.filter((c) => c.zone === "side").length;
}

function removeDraftCardAtSlot(deckId, slotIndex) {
  if (!state.deckDraft || state.deckDraft.id !== deckId) return;
  const cards = state.deckDraft.cards;
  if (slotIndex < 0 || slotIndex >= cards.length) return;
  const removed = cards[slotIndex];
  cards.splice(slotIndex, 1);
  if (state.deckDraft.preview_card_id === removed.card_id) {
    const stillHasCard = cards.some((c) => c.card_id === removed.card_id);
    if (!stillHasCard) state.deckDraft.preview_card_id = null;
  }
  refreshDraftCounts();
  markDeckDirty();
  renderDeckDetail(deckId);
  runDraftValidationPreview();
}

function insertDraftCardCopy(deckId, slotIndex, card) {
  if (!state.deckDraft || state.deckDraft.id !== deckId) return;
  const cards = state.deckDraft.cards;
  const insertAt = Math.min(Math.max(slotIndex + 1, 0), cards.length);
  cards.splice(insertAt, 0, {
    card_id: card.card_id,
    name: card.name,
    type: card.type ?? null,
    image_url: card.image_url ?? card.image_url_small ?? null,
    image_url_small: card.image_url_small ?? card.image_url ?? null,
    zone: card.zone,
    quantity: 1,
  });
  refreshDraftCounts();
  markDeckDirty();
  renderDeckDetail(deckId);
  runDraftValidationPreview();
}

function mutateDraftCardQuantity(deckId, slotIndex, delta) {
  if (!state.deckDraft || state.deckDraft.id !== deckId) return;
  const cards = state.deckDraft.cards;
  const card = cards[slotIndex];
  if (!card) return;
  if (delta < 0) {
    removeDraftCardAtSlot(deckId, slotIndex);
    return;
  }
  insertDraftCardCopy(deckId, slotIndex, card);
}

function setDraftCover(deckId, cardId) {
  if (!state.deckDraft || state.deckDraft.id !== deckId) return;
  const inDeck = state.deckDraft.cards.some((c) => c.card_id === cardId);
  if (!inDeck) return;
  state.deckDraft.preview_card_id = cardId;
  markDeckDirty();
  renderDeckDetail(deckId);
  runDraftValidationPreview();
}

function addCardToActiveDraft(cardId, zone, cardMeta) {
  if (!state.deckDraft || !state.decksDetailOpen) return false;
  const deckId = state.deckDraft.id;
  const cards = state.deckDraft.cards;
  let insertAt = cards.length;
  for (let i = cards.length - 1; i >= 0; i -= 1) {
    if (cards[i].zone === zone) {
      insertAt = i + 1;
      break;
    }
  }
  cards.splice(insertAt, 0, {
    card_id: cardId,
    name: cardMeta.name,
    type: cardMeta.type ?? null,
    image_url: cardMeta.image_url ?? cardMeta.image_url_small ?? null,
    image_url_small: cardMeta.image_url_small ?? cardMeta.image_url ?? null,
    zone,
    quantity: 1,
    banlist_status: cardMeta.banlist_status ?? null,
    genesys_points: cardMeta.genesys_points ?? null,
  });
  refreshDraftCounts();
  markDeckDirty();
  renderDeckDetail(deckId);
  runDraftValidationPreview();
  return true;
}

async function confirmLeaveDeck() {
  if (!state.deckDirty) return true;
  return appConfirm({
    title: "Unsaved changes",
    message: "You have unsaved changes. Leave without saving?",
    confirmLabel: "Leave",
    danger: true,
  });
}

function runDraftValidationPreview() {
  if (!state.deckDraft || !state.deckDirty) return;
  clearTimeout(deckValidationPreviewTimer);
  deckValidationPreviewTimer = setTimeout(async () => {
    if (!state.deckDraft || !state.deckDirty) return;
    const deckId = state.deckDraft.id;
    const seq = ++deckValidationPreviewSeq;
    try {
      const validation = await api(`/decks/${deckId}/validate-preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(deckToSavePayload(state.deckDraft)),
      });
      if (seq !== deckValidationPreviewSeq || state.activeDeckId !== deckId) return;
      state.deckDraft.validation = validation;
      renderDeckValidation(validation);
    } catch (err) {
      if (seq !== deckValidationPreviewSeq) return;
      showToast(err.message || "Failed to validate deck draft.", { variant: "error" });
    }
  }, 350);
}

async function saveDeck() {
  if (!state.deckDraft || !state.deckDirty) return;
  const deckId = state.deckDraft.id;
  const btn = $("#deck-save-btn");
  try {
    await runModalAction(
      btn,
      async () => {
        syncDraftFormatFromForm();
        const saved = await api(`/decks/${deckId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(deckToSavePayload(state.deckDraft)),
        });
        if (state.activeDeckId !== deckId) return;
        setDeckDraftFromServer(saved);
        renderDeckDetail(deckId);
        invalidateDecksCache();
        await loadDecks({ background: true });
      },
      { busyLabel: "Saving…", successMessage: "Deck saved" }
    );
  } catch {
    // runModalAction already surfaced the error toast
  }
}

function discardDeckChanges() {
  if (!state.deckSaved || !state.deckDirty) return;
  const deckId = state.deckSaved.id;
  setDeckDraftFromServer(state.deckSaved);
  renderDeckDetail(deckId);
  showToast("Changes discarded", { durationMs: 2500 });
}

function closeDeckDetail({ fromRouter = false } = {}) {
  state.activeDeckId = null;
  state.activeDeckDetail = null;
  state.deckSaved = null;
  state.deckDraft = null;
  state.deckDirty = false;
  clearTimeout(deckValidationPreviewTimer);
  updateDeckActionBar();
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
      <h3 class="deck-zone-label">${deckZoneLabelHtml(zone)}</h3>
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
  if (state.deckDirty) {
    metaEl.innerHTML = `
      <span class="deck-meta-stat">${escapeHtml(countLabel)}</span>
      <span class="deck-meta-unsaved muted">Unsaved edits</span>`;
    metaEl.setAttribute("aria-label", `${countLabel}, unsaved edits`);
    return;
  }
  const saved = state.deckSaved || deck;
  const parts = formatRelativeDateParts(saved.updated_at);
  if (parts) {
    metaEl.innerHTML = `
      <span class="deck-meta-stat">${escapeHtml(countLabel)}</span>
      <span class="deck-meta-edited">${renderDeckTimeHtml(saved.updated_at, "Edited")}</span>`;
    metaEl.setAttribute("aria-label", `${countLabel}, edited ${parts.relative}`);
  } else {
    metaEl.innerHTML = `<span class="deck-meta-stat">${escapeHtml(countLabel)}</span>`;
    metaEl.setAttribute("aria-label", countLabel);
  }
}

function formatDisplayName(code) {
  return state.formatsList.find((f) => f.code === code)?.name || code || "";
}

function deckFormatCode(deckId) {
  if (deckId === state.activeDeckId && state.decksDetailOpen) {
    return state.activeDeckDetail?.format_code || "advanced";
  }
  const decks = state.decksListCache?.decks || [];
  return decks.find((d) => d.id === deckId)?.format_code || "advanced";
}

function updateDeckTargetFormat() {
  const badge = $("#deck-target-format");
  const sel = $("#deck-target");
  if (!badge || !sel) return;
  const deckId = Number(sel.value);
  if (!deckId) {
    badge.textContent = "";
    return;
  }
  const fmtName = formatDisplayName(deckFormatCode(deckId));
  badge.textContent = fmtName ? `Format: ${fmtName}` : "";
}

async function populateDeckSelect() {
  const sel = $("#deck-target");
  if (!sel) return;
  if (!state.token) {
    sel.innerHTML = "";
    updateDeckTargetFormat();
    return;
  }
  const decks = await fetchDecksList();
  if (!decks.length) {
    sel.innerHTML =
      '<option value="" disabled selected>No decks — create one in Decks tab</option>';
    updateDeckTargetFormat();
    return;
  }
  sel.innerHTML = decks
    .map((d) => {
      const fmt = formatDisplayName(d.format_code);
      const suffix = fmt ? ` \u00b7 ${fmt}` : "";
      return `<option value="${d.id}">${escapeHtml(d.name)} (#${d.id})${escapeHtml(suffix)}</option>`;
    })
    .join("");
  const preferred =
    state.activeDeckId && decks.some((d) => d.id === state.activeDeckId)
      ? state.activeDeckId
      : decks[0].id;
  sel.value = String(preferred);
  updateDeckTargetFormat();
}

function deckZoneLabel(zone) {
  if (zone === "main") return "Main deck";
  if (zone === "extra") return "Extra deck";
  return "Side deck";
}

function deckZoneTooltip(zone) {
  return state.zoneTooltips?.[zone] || "";
}

function deckZoneLabelHtml(zone) {
  const tip = deckZoneTooltip(zone);
  if (!tip) return escapeHtml(deckZoneLabel(zone));
  const label = deckZoneLabel(zone);
  return `<span class="deck-zone-label-row">${escapeHtml(label)}<button type="button" class="icon-btn supplement-icon-btn formats-info-btn deck-zone-info-btn" data-zone="${zone}" aria-label="${escapeHtml(label)} info" data-tooltip="${escapeHtml(label)} info" aria-haspopup="dialog" aria-controls="deck-zone-info-popover" aria-expanded="false">${INFO_ICON_SVG}</button></span>`;
}

let deckZoneInfoTrigger = null;
let deckZoneInfoOutsideHandler = null;
let deckZoneInfoRepositionHandler = null;

function isDeckZoneInfoOpen() {
  const popover = $("#deck-zone-info-popover");
  return popover && !popover.hidden;
}

function positionDeckZoneInfoPopover() {
  const popover = $("#deck-zone-info-popover");
  const anchor = deckZoneInfoTrigger;
  if (!popover || popover.hidden || !anchor) return;
  const rect = anchor.getBoundingClientRect();
  const width = Math.min(22 * 16, window.innerWidth - 16);
  popover.style.width = `${width}px`;
  popover.style.top = `${rect.bottom + 6}px`;
  popover.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - width - 8))}px`;
}

function detachDeckZoneInfoListeners() {
  if (deckZoneInfoOutsideHandler) {
    document.removeEventListener("click", deckZoneInfoOutsideHandler);
    deckZoneInfoOutsideHandler = null;
  }
  if (deckZoneInfoRepositionHandler) {
    window.removeEventListener("resize", deckZoneInfoRepositionHandler);
    window.removeEventListener("scroll", deckZoneInfoRepositionHandler, true);
    deckZoneInfoRepositionHandler = null;
  }
}

function attachDeckZoneInfoListeners() {
  detachDeckZoneInfoListeners();
  deckZoneInfoOutsideHandler = (e) => {
    if (
      $("#deck-zone-info-popover")?.contains(e.target) ||
      e.target.closest(".deck-zone-info-btn")
    ) {
      return;
    }
    closeDeckZoneInfo();
  };
  deckZoneInfoRepositionHandler = () => {
    if (isDeckZoneInfoOpen()) positionDeckZoneInfoPopover();
  };
  document.addEventListener("click", deckZoneInfoOutsideHandler);
  window.addEventListener("resize", deckZoneInfoRepositionHandler);
  window.addEventListener("scroll", deckZoneInfoRepositionHandler, true);
}

function closeDeckZoneInfo() {
  const popover = $("#deck-zone-info-popover");
  if (!popover || popover.hidden) return;
  popover.hidden = true;
  detachDeckZoneInfoListeners();
  if (deckZoneInfoTrigger) {
    deckZoneInfoTrigger.setAttribute("aria-expanded", "false");
    deckZoneInfoTrigger.focus();
    deckZoneInfoTrigger = null;
  }
}

function openDeckZoneInfo(zone, trigger) {
  const popover = $("#deck-zone-info-popover");
  const tip = deckZoneTooltip(zone);
  if (!popover || !tip) return;
  if (isDeckZoneInfoOpen() && deckZoneInfoTrigger === trigger) {
    closeDeckZoneInfo();
    return;
  }
  closeDeckZoneInfo();
  const title = $("#deck-zone-info-title");
  const body = $("#deck-zone-info-body");
  if (title) title.textContent = deckZoneLabel(zone);
  if (body) body.textContent = tip;
  deckZoneInfoTrigger = trigger;
  trigger?.setAttribute("aria-expanded", "true");
  popover.hidden = false;
  positionDeckZoneInfoPopover();
  attachDeckZoneInfoListeners();
  popover.querySelector(".deck-zone-info-dismiss")?.focus();
}

function setupDeckZoneInfoDelegation() {
  $("#deck-zones")?.addEventListener("click", (e) => {
    const btn = e.target.closest(".deck-zone-info-btn");
    if (!btn) return;
    e.stopPropagation();
    openDeckZoneInfo(btn.dataset.zone, btn);
  });
  $("#deck-zone-info-popover")
    ?.querySelector(".deck-zone-info-dismiss")
    ?.addEventListener("click", closeDeckZoneInfo);
}

function renderDeckCardSlot(deck, card, zone, slotIndex) {
  const imgUrl = card.image_url || card.image_url_small || null;
  const isCover = deck.preview_card_id === card.card_id;
  const formatBadge = formatBadgeHtml(card);
  return `
    <div class="deck-card-slot${isCover ? " is-cover" : ""}" data-card="${card.card_id}" data-zone="${zone}" data-slot-index="${slotIndex}" draggable="true">
      ${cardImgTag(imgUrl)}
      ${formatBadge ? `<div class="deck-card-format-badge">${formatBadge}</div>` : ""}
      <div class="deck-card-actions">
        <button type="button" class="deck-cover-btn${isCover ? " is-active" : ""}" title="Set as deck cover" aria-label="Set as deck cover">★</button>
        <button type="button" class="deck-minus-btn" title="Remove one" aria-label="Remove one">−</button>
      </div>
      <div class="deck-card-actions deck-card-actions--bottom">
        <button type="button" class="deck-plus-btn" title="Add one" aria-label="Add one">+</button>
      </div>
    </div>`;
}

function getDeckZoneInsertIndex(cards, zone, beforeSlotIndex = null) {
  if (beforeSlotIndex != null) return beforeSlotIndex;
  let lastIdx = -1;
  cards.forEach((c, i) => {
    if (c.zone === zone) lastIdx = i;
  });
  return lastIdx + 1;
}

function reorderDraftCard(deckId, fromIndex, toIndex, toZone) {
  if (!state.deckDraft || state.deckDraft.id !== deckId) return;
  const cards = state.deckDraft.cards;
  if (fromIndex < 0 || fromIndex >= cards.length) return;
  if (toIndex < 0) toIndex = 0;
  if (toIndex > cards.length) toIndex = cards.length;

  const [moved] = cards.splice(fromIndex, 1);
  moved.zone = toZone;
  if (fromIndex < toIndex) toIndex -= 1;
  cards.splice(toIndex, 0, moved);

  refreshDraftCounts();
  markDeckDirty();
  renderDeckDetail(deckId);
  runDraftValidationPreview();
}

let deckDragFromIndex = null;

function bindDeckZoneDragDrop(deckId) {
  const zonesEl = $("#deck-zones");
  if (!zonesEl) return;

  zonesEl.querySelectorAll(".deck-card-slot").forEach((slot) => {
    slot.addEventListener("dragstart", (e) => {
      if (e.target.closest("button")) {
        e.preventDefault();
        return;
      }
      deckDragFromIndex = Number(slot.dataset.slotIndex);
      slot.classList.add("is-dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(deckDragFromIndex));
    });
    slot.addEventListener("dragend", () => {
      slot.classList.remove("is-dragging");
      zonesEl.querySelectorAll(".deck-zone-cards").forEach((zoneEl) => {
        zoneEl.classList.remove("is-drop-target");
      });
      deckDragFromIndex = null;
    });
  });

  zonesEl.querySelectorAll(".deck-zone-cards").forEach((zoneEl) => {
    const zone = zoneEl.dataset.zone;
    if (!zone) return;

    zoneEl.addEventListener("dragover", (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      zoneEl.classList.add("is-drop-target");
    });
    zoneEl.addEventListener("dragleave", (e) => {
      if (!zoneEl.contains(e.relatedTarget)) {
        zoneEl.classList.remove("is-drop-target");
      }
    });
    zoneEl.addEventListener("drop", (e) => {
      e.preventDefault();
      zoneEl.classList.remove("is-drop-target");
      const fromIndex = deckDragFromIndex ?? Number(e.dataTransfer.getData("text/plain"));
      if (Number.isNaN(fromIndex)) return;

      const slotTarget = e.target.closest(".deck-card-slot");
      let toIndex;
      if (slotTarget) {
        toIndex = Number(slotTarget.dataset.slotIndex);
        const rect = slotTarget.getBoundingClientRect();
        const after = e.clientX > rect.left + rect.width / 2;
        if (after) toIndex += 1;
      } else {
        toIndex = getDeckZoneInsertIndex(state.deckDraft.cards, zone);
      }
      reorderDraftCard(deckId, fromIndex, toIndex, zone);
    });
  });
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

function renderDeckDetail(deckId) {
  const deck = state.deckDraft;
  if (!deck || deck.id !== deckId) return;
  closeDeckZoneInfo();
  state.activeDeckDetail = deck;
  const nameEl = $("#deck-name");
  if (nameEl) {
    nameEl.textContent = deck.name;
    nameEl.title = "Double-click to rename";
  }
  renderDeckDetailMeta(deck);
  renderDeckFormatBar(deck);
  renderDeckValidation(deck.validation);
  updateRouteDocumentTitle();
  updateDeckActionBar();

  const cards = deck.cards || [];

  $("#deck-zones").innerHTML = ["main", "extra", "side"]
    .map((zone) => {
      const zoneEntries = cards
        .map((c, slotIndex) => ({ card: c, slotIndex }))
        .filter((entry) => entry.card.zone === zone);
      const zoneCount = zoneEntries.length;
      const zoneCountLabel = zoneCount === 1 ? "1 card" : `${zoneCount} cards`;
      const slots = zoneEntries.map(({ card, slotIndex }) =>
        renderDeckCardSlot(deck, card, zone, slotIndex)
      );
      return `
        <section class="deck-zone-row">
          <div class="deck-zone-header">
            <h3 class="deck-zone-label">${deckZoneLabelHtml(zone)}</h3>
            <span class="deck-zone-count">${escapeHtml(zoneCountLabel)}</span>
          </div>
          <div class="deck-zone-cards" data-zone="${zone}">
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
    const slotIndex = Number(slot.dataset.slotIndex);
    slot.querySelector(".deck-minus-btn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      mutateDraftCardQuantity(deckId, slotIndex, -1);
    });
    slot.querySelector(".deck-plus-btn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      mutateDraftCardQuantity(deckId, slotIndex, 1);
    });
    slot.querySelector(".deck-cover-btn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      setDraftCover(deckId, cardId);
    });
    slot.querySelector("img")?.addEventListener("click", () => openCardModal(cardId));
  });

  bindDeckZoneDragDrop(deckId);

  $("#decks-detail-view")?.removeAttribute("aria-busy");
}

async function openDeckDetail(deckId, { fromRouter = false } = {}) {
  if (state.decksDetailOpen && state.activeDeckId === deckId) {
    if (!fromRouter) syncRouteHash();
    return;
  }
  if (state.decksDetailOpen && state.deckDirty) {
    if (!(await confirmLeaveDeck())) {
      if (!fromRouter) syncRouteHash();
      return;
    }
  }
  state.activeDeckId = deckId;
  const seq = ++deckDetailRequestSeq;
  showDecksDetailView();
  showDeckDetailLoading();
  updateDeckActionBar();
  if (!fromRouter) syncRouteHash();
  try {
    const deck = await api(`/decks/${deckId}`);
    if (seq !== deckDetailRequestSeq || state.activeDeckId !== deckId) return;
    setDeckDraftFromServer(deck);
    renderDeckDetail(deckId);
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
    showToast(err.message || "Failed to load deck.", { variant: "error" });
  }
}

async function renameDeck() {
  if (!state.token) {
    showToast("Log in to rename decks.", { variant: "error" });
    return;
  }
  if (!state.deckDraft) {
    showToast("Open a deck to rename it.", { variant: "error" });
    return;
  }
  const currentName = state.deckDraft.name;
  const newName = await appPrompt({
    title: "Rename deck",
    label: "Deck name",
    defaultValue: currentName,
    submitLabel: "Rename",
  });
  if (!newName?.trim() || newName.trim() === currentName) return;
  state.deckDraft.name = newName.trim();
  markDeckDirty();
  renderDeckDetail(state.deckDraft.id);
  runDraftValidationPreview();
}

async function selectDeck(deckId) {
  await openDeckDetail(deckId);
}

function wireEvents() {
  initAppDialogs({ syncModalOpenClass });
  initBulkCollection({
    $,
    API,
    showToast,
    appConfirm,
    readNdjsonStream,
    isLoggedIn: () => Boolean(state.token && state.user),
    authHeaders: () => (state.token ? { Authorization: `Bearer ${state.token}` } : {}),
    onSaved: () => {
      state.collectionViewCache = null;
      refreshCollectionIfActive();
      loadCollectionStats();
    },
    closeCollectionToolbarMenus,
    formatDisplayPrice,
    parsePriceInput,
    displayInputValue,
    getSelectedCurrency,
  });

  $("#app-currency")?.addEventListener("change", (e) => {
    setCurrency(e.target.value);
  });

  setupSearchResultsDelegation();
  setupSearchFilterChipDelegation();
  setupCollectionTableDelegation();
  setupDecksGridDelegation();
  setupDeckZoneInfoDelegation();

  document.querySelectorAll(".tab[data-view]").forEach((tab) => {
    tab.addEventListener("click", async () => {
      if (isModalVisible("#card-modal")) {
        closeCardModalOverlay({ fromRouter: true });
      }
      if (state.decksDetailOpen) {
        if (!(await confirmLeaveDeck())) return;
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
  $("#search-sort")?.addEventListener("change", () => {
    syncSearchSortToggleLabel();
    runSearch().catch((err) => showToast(err.message, { variant: "error" }));
  });
  bindSortDirToggle($("#search-sort-dir"), () => {
    syncSearchSortToggleLabel();
    runSearch().catch((err) => showToast(err.message, { variant: "error" }));
  });
  bindSearchToolPanel("#search-preset-toggle", "#search-presets-panel");
  bindSearchToolPanel("#search-sort-toggle", "#search-sort-panel");
  bindSearchToolPanel("#advanced-filters-toggle", "#advanced-filters", {
    onUserToggle(willOpen) {
      advancedFiltersUserCollapsed = !willOpen;
    },
  });
  syncSearchSortToggleLabel();
  $("#search-preset-list")?.addEventListener("click", (e) => {
    const loadBtn = e.target.closest("[data-preset-load]");
    if (loadBtn) {
      const presetId = Number(loadBtn.dataset.presetLoad);
      if (presetId) {
        if (presetId === state.activePresetId) {
          clearActivePreset();
        } else {
          loadSearchPresetById(presetId).catch((err) =>
            showToast(err.message, { variant: "error", durationMs: 5000 })
          );
        }
      }
      return;
    }
    const renameBtn = e.target.closest("[data-preset-rename]");
    if (renameBtn) {
      const presetId = Number(renameBtn.dataset.presetRename);
      renameSearchPreset(presetId).catch((err) =>
        showToast(err.message, { variant: "error", durationMs: 5000 })
      );
      return;
    }
    const deleteBtn = e.target.closest("[data-preset-delete]");
    if (deleteBtn) {
      const presetId = Number(deleteBtn.dataset.presetDelete);
      deleteSearchPreset(presetId).catch((err) =>
        showToast(err.message, { variant: "error", durationMs: 5000 })
      );
    }
  });
  $("#search-preset-save")?.addEventListener("click", () => {
    saveSearchPreset().catch((err) =>
      showToast(err.message, { variant: "error", durationMs: 5000 })
    );
  });
  $("#collection-manage-menu-btn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleCollectionToolbarMenu("collection-manage-menu", "collection-manage-menu-btn");
  });
  $("#collection-trade-menu-btn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleCollectionToolbarMenu("collection-trade-menu", "collection-trade-menu-btn");
  });
  document.addEventListener("click", (e) => {
    if (
      !e.target.closest(
        ".collection-sidebar-menu-wrap"
      )
    ) {
      closeCollectionToolbarMenus();
    }
    if (!e.target.closest(".account-settings-wrap")) closeAccountSettingsMenu();
    if (!e.target.closest(".collection-row-menu-wrap")) closeAllCollectionRowMenus();
    if (!e.target.closest(".collection-folder-menu-wrap")) closeAllCollectionFolderMenus();
    if (!e.target.closest(".deck-tile-menu-wrap")) closeAllDeckTileMenus();
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

  $("#auth-logout")?.addEventListener("click", confirmLogout);

  $("#account-settings-btn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleAccountSettingsMenu();
  });
  $("#account-export-btn")?.addEventListener("click", () => {
    closeAccountSettingsMenu();
    void exportAccountData();
  });
  $("#account-delete-btn")?.addEventListener("click", () => {
    closeAccountSettingsMenu();
    openDeleteAccountModal();
  });
  $("#delete-account-close")?.addEventListener("click", closeDeleteAccountModal);
  $("#delete-account-cancel")?.addEventListener("click", closeDeleteAccountModal);
  $("#delete-account-confirm")?.addEventListener("click", () => {
    void confirmDeleteAccount();
  });
  $("#delete-account-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#delete-account-modal")) closeDeleteAccountModal();
  });
  $("#storage-notice-dismiss")?.addEventListener("click", dismissStorageNotice);

  $("#import-collection-btn")?.addEventListener("click", () => {
    closeCollectionToolbarMenus();
    if (!state.token) {
      showToast("Log in first.", { variant: "error" });
      return;
    }
    $("#collection-csv-file")?.click();
  });

  $("#export-collection-btn")?.addEventListener("click", async () => {
    closeCollectionToolbarMenus();
    if (!state.token) {
      showToast("Log in first.", { variant: "error" });
      return;
    }
    try {
      const [formats, stats] = await Promise.all([
        loadExportFormats(),
        api("/collection/stats"),
      ]);
      if (!formats.length) {
        showToast("No export formats available.", { variant: "error" });
        return;
      }
      state.collectionStats = stats;
      renderExportFormatOptions(formats);
      renderExportFolderOptions(stats);
      openExportCollectionModal();
    } catch (err) {
      showToast(err.message, { variant: "error" });
    }
  });

  $("#copy-trade-link-btn")?.addEventListener("click", () => {
    closeCollectionToolbarMenus();
    copyTradeLink();
  });

  $("#trade-settings-btn")?.addEventListener("click", async () => {
    closeCollectionToolbarMenus();
    if (!state.token) {
      showToast("Log in first.", { variant: "error" });
      return;
    }
    await loadTradeSettings();
    openTradeSettingsModal();
  });
  $("#trade-settings-close")?.addEventListener("click", closeTradeSettingsModal);
  $("#trade-settings-cancel")?.addEventListener("click", closeTradeSettingsModal);
  $("#trade-settings-save")?.addEventListener("click", saveTradeSettings);
  $("#trade-settings-slug")?.addEventListener("input", () => {
    const url = $("#trade-settings-url");
    const slug = $("#trade-settings-slug")?.value.trim();
    if (url && slug) {
      url.textContent = `Public link: ${window.location.origin}/trade/${slug}`;
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

  $("#import-mode-cancel")?.addEventListener("click", () => closeImportModeModal(null));
  $("#import-mode-close")?.addEventListener("click", () => closeImportModeModal(null));
  $("#import-mode-append")?.addEventListener("click", () => closeImportModeModal("append"));
  $("#import-mode-overwrite")?.addEventListener("click", () => closeImportModeModal("overwrite"));
  $("#import-mode-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#import-mode-modal")) closeImportModeModal(null);
  });

  $("#import-progress-close")?.addEventListener("click", () => {
    void closeImportProgressModal();
  });
  $("#import-progress-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#import-progress-modal") && importProgressCanClose) {
      void closeImportProgressModal();
    }
  });

  $("#search-preset-name-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const name = $("#search-preset-name-input")?.value?.trim();
    if (!name) return;
    closeSearchPresetNameModal(name);
  });
  $("#search-preset-name-cancel")?.addEventListener("click", () =>
    closeSearchPresetNameModal(null)
  );
  $("#search-preset-name-close")?.addEventListener("click", () =>
    closeSearchPresetNameModal(null)
  );
  $("#search-preset-name-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#search-preset-name-modal")) closeSearchPresetNameModal(null);
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
      showToast("Choose an export format.", { variant: "error" });
      return;
    }
    const confirmBtn = $("#export-collection-confirm");
    if (confirmBtn) confirmBtn.disabled = true;
    try {
      const folderIds = getSelectedExportFolders();
      await downloadCollectionExport(selected.value, folderIds);
      closeExportCollectionModal();
    } catch (err) {
      showToast(err.message, { variant: "error" });
    } finally {
      if (confirmBtn) confirmBtn.disabled = false;
    }
  });

  $("#collection-csv-file")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const mode = await promptImportModeChoice(file.name);
    e.target.value = "";
    if (!mode) return;
    await runCollectionImport(file, mode === "overwrite");
  });

  $("#collection-new-folder-btn")?.addEventListener("click", createCollectionFolder);

  $("#collection-filter-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    collectionFilterComboboxes?.cardName?.resolveValue();
    collectionFilterComboboxes?.setCode?.resolveValue();
    collectionFilterComboboxes?.setName?.resolveValue();
    closeCollectionFilterComboboxes();
    state.collectionPage = 0;
    await loadCollectionFilterOptions();
    await loadCollectionPage(0);
  });
  setSortDir($("#collection-sort-dir"), readSortDir($("#collection-sort-dir")));
  bindTableHeaderSort($("#collection-table"), {
    getSort: () => $("#collection-sort")?.value || "set_code",
    getDir: () => readSortDir($("#collection-sort-dir")),
    onSort: async (sort, dir) => {
      const select = $("#collection-sort");
      if (select) select.value = sort;
      setSortDir($("#collection-sort-dir"), dir);
      syncCollectionTableHeaderSort();
      state.collectionPage = 0;
      await loadCollectionPage(0);
    },
  });
  syncCollectionTableHeaderSort();

  initCollectionFilterComboboxes();

  $("#collection-stats-btn")?.addEventListener("click", () => {
    closeCollectionToolbarMenus();
    openCollectionStatsModal();
  });
  $("#collection-stats-close")?.addEventListener("click", closeCollectionStatsModal);
  $("#collection-stats-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#collection-stats-modal")) closeCollectionStatsModal();
  });
  $("#collection-stats-folder")?.addEventListener("change", (e) => {
    const folder = e.target.value || null;
    loadCollectionDetailStats(folder);
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".collection-filter-combobox")) {
      closeCollectionFilterComboboxes();
    }
  });

  $("#modal-close").addEventListener("click", closeCardModalOverlay);
  $("#card-modal").addEventListener("click", (e) => {
    if (e.target === $("#card-modal")) closeCardModalOverlay();
  });
  $("#modal-passcode-copy")?.addEventListener("click", async () => {
    const passcode = state.currentCard?.passcode ?? null;
    if (passcode == null) return;
    const code = formatPasscode(passcode);
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
    if (cancelAppDialog()) {
      return;
    }
    if (document.querySelector(".folder-allocation-popover:not(.move-copy-popover)")) {
      closeFolderAllocationPopover();
    } else if (document.querySelector(".collection-row-menu:not([hidden])")) closeAllCollectionRowMenus();
    else if (document.querySelector(".collection-folder-menu:not([hidden])")) closeAllCollectionFolderMenus();
    else if (document.querySelector(".deck-tile-menu:not([hidden])")) closeAllDeckTileMenus();
    else if (document.querySelector("#collection-manage-menu:not([hidden]), #collection-trade-menu:not([hidden])")) {
      closeCollectionToolbarMenus();
    } else if (document.querySelector("#account-settings-menu:not([hidden])")) {
      closeAccountSettingsMenu();
    } else if (
      $("#search-presets-panel")?.open ||
      $("#search-sort-panel")?.open ||
      $("#advanced-filters")?.open
    ) {
      closeSearchToolPanels();
    } else if (isModalVisible("#search-preset-name-modal")) closeSearchPresetNameModal(null);
    else if (isModalVisible("#search-preset-save-modal")) closeSearchPresetSaveModal(null);
    else if (isModalVisible("#import-mode-modal")) closeImportModeModal(null);
    else if (isModalVisible("#import-progress-modal") && importProgressCanClose) {
      void closeImportProgressModal();
    }
    else if (isModalVisible("#collection-add-modal")) closeAddCollectionModal();
    else if (isModalVisible("#collection-edit-modal")) closeCollectionEditModal();
    else if (isModalVisible("#bulk-collection-modal") && !isBulkCollectionSaving()) {
      void closeBulkCollectionModal();
    }
    else if (isModalVisible("#export-collection-modal")) closeExportCollectionModal();
    else if (isModalVisible("#delete-account-modal")) closeDeleteAccountModal();
    else if (isModalVisible("#trade-settings-modal")) closeTradeSettingsModal();
    else if (isModalVisible("#card-tips-modal")) closeCardTipsModal();
    else if (isModalVisible("#card-errata-modal")) closeCardErrataModal();
    else if (isModalVisible("#card-modal")) closeCardModalOverlay();
    else if (isModalVisible("#collection-stats-modal")) closeCollectionStatsModal();
    else if (isSearchHelpOpen()) closeSearchHelp();
    else if (isDeckZoneInfoOpen()) closeDeckZoneInfo();
    else if (isModalVisible("#formats-info-modal")) closeFormatsInfoModal();
  });

  $("#modal-favorite").addEventListener("click", async () => {
    if (!state.token) {
      showToast("Log in to use favorites.", { variant: "error" });
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
      showToast("Log in to add tags.", { variant: "error" });
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
        showToast("Log in to manage tags.", { variant: "error" });
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

  $("#deck-target")?.addEventListener("change", updateDeckTargetFormat);

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
    const card = state.currentCard;
    if (!card || !state.currentCardId) return;

    let deckName = "";
    if (deckId === state.activeDeckId && state.decksDetailOpen) {
      deckName = state.activeDeckDetail?.name || "";
    }
    if (!deckName) {
      const decks = state.decksListCache?.decks || [];
      deckName = decks.find((d) => d.id === deckId)?.name || "";
    }
    if (!deckName) {
      const optionText = $("#deck-target")?.selectedOptions?.[0]?.textContent?.trim() || "";
      deckName = optionText.replace(/\s*\(#\d+\).*$/, "").trim();
    }
    if (!deckName) deckName = "deck";
    const fmtName = formatDisplayName(deckFormatCode(deckId));
    const fmtSuffix = fmtName ? ` [${fmtName}]` : "";
    const addedMessage = `${card.name} added to ${zone} zone of ${deckName}${fmtSuffix} deck.`;

    if (deckId === state.activeDeckId && state.decksDetailOpen) {
      addCardToActiveDraft(state.currentCardId, zone, {
        name: card.name,
        type: card.type,
        image_url: card.image_url,
        image_url_small: card.image_url_small,
        banlist_status: card.banlist_status ?? null,
        genesys_points: card.genesys_points ?? null,
      });
      showToast(`${addedMessage} (unsaved)`, { durationMs: 3000 });
      return;
    }

    const btn = $("#deck-add-card-btn");
    try {
      await runModalAction(
        btn,
        async () => {
          await api(`/decks/${deckId}/cards`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ card_id: state.currentCardId, zone, quantity: 1 }),
          });
          invalidateDecksCache();
        },
        { busyLabel: "Adding…", successMessage: addedMessage }
      );
    } catch {
      // runModalAction already surfaced the error toast
    }
  });

  $("#decks-back-btn")?.addEventListener("click", async () => {
    if (!(await confirmLeaveDeck())) return;
    closeDeckDetail();
    loadDecks({ background: true });
  });

  $("#deck-save-btn")?.addEventListener("click", () => {
    saveDeck().catch((err) => showToast(err.message, { variant: "error" }));
  });
  $("#deck-discard-btn")?.addEventListener("click", async () => {
    if (!state.deckDirty) return;
    const ok = await appConfirm({
      title: "Discard changes",
      message: "Discard unsaved changes?",
      confirmLabel: "Discard",
      danger: true,
    });
    if (!ok) return;
    discardDeckChanges();
  });

  $("#deck-rename-btn")?.addEventListener("click", () => {
    renameDeck().catch((err) => showToast(err.message, { variant: "error" }));
  });
  $("#deck-name")?.addEventListener("dblclick", () => {
    renameDeck().catch((err) => showToast(err.message, { variant: "error" }));
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
    const name = await appPrompt({
      title: "New deck",
      label: "Deck name",
      submitLabel: "Create",
    });
    if (!name?.trim()) return;
    const deck = await api("/decks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim(), format_code: "advanced" }),
    });
    invalidateDecksCache();
    state.activeDeckId = deck.id;
    await loadDecks({ force: true });
    selectDeck(deck.id);
  });

  $("#search-format")?.addEventListener("change", () => {
    updateSearchFormatUi();
    renderActiveSearchFilters();
  });
  $("#formats-info-btn")?.addEventListener("click", openFormatsInfoModal);
  $("#formats-info-close")?.addEventListener("click", closeFormatsInfoModal);
  $("#formats-info-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#formats-info-modal")) closeFormatsInfoModal();
  });
  $("#deck-format")?.addEventListener("change", () => {
    if (state.deckDraft) {
      renderDeckFormatBar({
        ...state.deckDraft,
        format_code: $("#deck-format")?.value,
      });
    }
    applyDraftFormatSettings();
  });
  $("#deck-banlist")?.addEventListener("change", applyDraftFormatSettings);
  $("#deck-genesys-list")?.addEventListener("change", applyDraftFormatSettings);

  window.addEventListener("beforeunload", (e) => {
    if (!state.deckDirty && !isBulkCollectionSaving()) return;
    e.preventDefault();
    e.returnValue = "";
  });
}

function formatBadgeHtml(card) {
  const parts = [];
  if (card.banlist_status) {
    const cls =
      card.banlist_status === "Forbidden"
        ? "format-badge--forbidden"
        : card.banlist_status === "Limited"
          ? "format-badge--limited"
          : card.banlist_status === "Semi-Limited"
            ? "format-badge--semi"
            : card.banlist_status === "Unlimited"
              ? "format-badge--unlimited"
              : "";
    parts.push(`<span class="format-badge ${cls}">${escapeHtml(card.banlist_status)}</span>`);
  }
  if (card.genesys_points != null) {
    parts.push(
      `<span class="format-badge format-badge--points">${escapeHtml(String(card.genesys_points))} pts</span>`
    );
  }
  return parts.join("");
}

function resolveCardDetailFormatContext() {
  if (state.decksDetailOpen && state.activeDeckDetail?.format_code) {
    const deck = state.activeDeckDetail;
    const banlist =
      $("#deck-banlist")?.value ||
      (deck.banlist_revision_id != null ? String(deck.banlist_revision_id) : "");
    const genesys =
      $("#deck-genesys-list")?.value ||
      (deck.genesys_point_list_id != null ? String(deck.genesys_point_list_id) : "");
    return {
      format: $("#deck-format")?.value || deck.format_code,
      banlist_revision_id: banlist || null,
      genesys_point_list_id: genesys || null,
    };
  }

  const searchFormat = $("#search-format")?.value;
  if (searchFormat) {
    return {
      format: searchFormat,
      banlist_revision_id: $("#search-banlist")?.value || null,
      genesys_point_list_id: $("#search-genesys-list")?.value || null,
    };
  }

  return {
    format: null,
    banlist_revision_id: null,
    genesys_point_list_id: null,
  };
}

function formatContextLabel(ctx) {
  if (!ctx.format) return "";
  const fmt = state.formatsList.find((f) => f.code === ctx.format);
  const formatName = fmt?.name || ctx.format;
  const parts = [formatName];

  if (fmt?.uses_point_list) {
    if (ctx.genesys_point_list_id) {
      const list = state.genesysPointLists.find(
        (g) => String(g.id) === String(ctx.genesys_point_list_id)
      );
      parts.push(list?.label || "Point list");
    } else {
      parts.push("Latest point list");
    }
  } else if (fmt?.uses_banlist && fmt?.banlist_selectable) {
    const lists = state.banlistsByFormat[ctx.format] || [];
    let banlistLabel = "Latest banlist";
    if (ctx.banlist_revision_id) {
      const rev = lists.find((b) => String(b.id) === String(ctx.banlist_revision_id));
      banlistLabel = rev?.label || banlistLabel;
    } else {
      const current = lists.find((b) => b.is_current);
      banlistLabel = current?.label || lists[0]?.label || banlistLabel;
    }
    parts.push(banlistLabel);
  } else if (fmt?.fixed_banlist_label) {
    parts.push(fmt.fixed_banlist_label);
  }

  return parts.join(" · ");
}

function renderModalFormatBadges(card) {
  const ctx = resolveCardDetailFormatContext();
  const label = formatContextLabel(ctx);
  const contextEl = $("#modal-format-context");
  if (contextEl) {
    contextEl.textContent = label;
    contextEl.hidden = !label;
  }
  const badgesEl = $("#modal-format-badges");
  if (badgesEl) badgesEl.innerHTML = formatBadgeHtml(card);
}

function buildCardDetailQuery() {
  const ctx = resolveCardDetailFormatContext();
  const params = new URLSearchParams();
  if (ctx.format) params.set("format", ctx.format);
  const fmt = state.formatsList.find((f) => f.code === ctx.format);
  if (fmt?.banlist_selectable && ctx.banlist_revision_id) {
    params.set("banlist_revision_id", String(ctx.banlist_revision_id));
  }
  if (ctx.genesys_point_list_id) {
    params.set("genesys_point_list_id", String(ctx.genesys_point_list_id));
  }
  return `?${params}`;
}

async function loadFormats() {
  if (!state.token) return;
  try {
    state.formatsList = await api("/formats");
    if (state.formatsList.length) {
      state.zoneTooltips = state.formatsList[0].zone_tooltips || {};
    }
    populateSearchFormatSelect();
    renderFormatsInfoBody();
    const genesys = state.formatsList.find((f) => f.code === "genesys");
    if (genesys) {
      state.genesysPointLists = await api("/formats/genesys/point-lists");
    }
    for (const fmt of state.formatsList.filter((f) => f.uses_banlist)) {
      state.banlistsByFormat[fmt.code] = await api(`/formats/${fmt.code}/banlists`);
    }
    updateSearchFormatUi();
  } catch {
    state.formatsList = [];
  }
}

function populateSearchFormatSelect() {
  const sel = $("#search-format");
  const deckSel = $("#deck-format");
  if (!sel && !deckSel) return;
  const options = state.formatsList
    .map((f) => `<option value="${escapeHtml(f.code)}">${escapeHtml(f.name)}</option>`)
    .join("");
  if (sel) {
    sel.innerHTML = `<option value="">Any format</option>${options}`;
  }
  if (deckSel) {
    deckSel.innerHTML = options;
  }
}

function renderFormatsInfoBody() {
  const body = $("#formats-info-body");
  if (!body) return;
  body.innerHTML = state.formatsList
    .map(
      (f) => `
    <section class="formats-info-item">
      <h3>${escapeHtml(f.name)}</h3>
      <p>${escapeHtml(f.description)}</p>
    </section>`
    )
    .join("");
}

function renderBanlistSelectOptions(selectEl, lists, selectedId) {
  if (!selectEl) return;
  let previous;
  if (selectedId !== undefined) {
    previous = selectedId !== null ? String(selectedId) : "";
  } else {
    previous = selectEl.value;
  }
  selectEl.innerHTML = lists
    .map(
      (b) =>
        `<option value="${b.id}">${escapeHtml(b.label)}${b.is_current ? " (current)" : ""}</option>`
    )
    .join("");
  const current = lists.find((b) => b.is_current);
  const stillValid = previous && lists.some((b) => String(b.id) === String(previous));
  selectEl.value = stillValid
    ? String(previous)
    : current
      ? String(current.id)
      : lists[0]
        ? String(lists[0].id)
        : "";
}

function updateSearchFormatUi() {
  const format = $("#search-format")?.value || "";
  const fmt = state.formatsList.find((f) => f.code === format);
  const showBanlist = Boolean(fmt?.uses_banlist && fmt?.banlist_selectable);
  $("#search-banlist-wrap")?.classList.toggle("hidden", !showBanlist);
  const showBanlistStatus = Boolean(fmt?.uses_banlist);
  $("#search-banlist-status-wrap")?.classList.toggle("hidden", !showBanlistStatus);
  if (!showBanlistStatus) {
    setFilterMultiValues("filter-banlist-status", []);
  }
  $("#search-genesys-points-wrap")?.classList.toggle("hidden", format !== "genesys");
  const banlistSel = $("#search-banlist");
  if (banlistSel && showBanlist) {
    const lists = state.banlistsByFormat[format] || [];
    renderBanlistSelectOptions(banlistSel, lists);
  }
}

function renderDeckFormatBar(deck) {
  const formatSel = $("#deck-format");
  if (!formatSel) return;
  formatSel.value = deck.format_code || "advanced";
  const fmt = state.formatsList.find((f) => f.code === deck.format_code);
  const showBanlist = Boolean(fmt?.uses_banlist && fmt?.banlist_selectable);
  $("#deck-banlist-wrap")?.classList.toggle("hidden", !showBanlist);
  $("#deck-genesys-list-wrap")?.classList.toggle("hidden", !fmt?.uses_point_list);
  const banlistSel = $("#deck-banlist");
  if (banlistSel && showBanlist) {
    const lists = state.banlistsByFormat[deck.format_code] || [];
    renderBanlistSelectOptions(banlistSel, lists, deck.banlist_revision_id);
  }
  const genesysSel = $("#deck-genesys-list");
  if (genesysSel && fmt?.uses_point_list) {
    genesysSel.innerHTML =
      `<option value="">Latest</option>` +
      state.genesysPointLists
        .map((g) => `<option value="${g.id}">${escapeHtml(g.label)}</option>`)
        .join("");
    genesysSel.value = deck.genesys_point_list_id ? String(deck.genesys_point_list_id) : "";
  }
}

function renderDeckValidation(validation) {
  const el = $("#deck-validation");
  if (!el) return;
  if (!validation) {
    el.classList.add("hidden");
    el.innerHTML = "";
    return;
  }
  const issues = [
    ...(validation.errors || []).map((i) => ({ ...i, kind: "error" })),
    ...(validation.warnings || []).map((i) => ({ ...i, kind: "warning" })),
    ...(validation.info || []).map((i) => ({ ...i, kind: "info" })),
  ];
  if (!issues.length && validation.points_total == null) {
    el.classList.add("hidden");
    el.innerHTML = `<p class="muted">Deck looks valid for the selected format.</p>`;
    el.classList.remove("hidden");
    return;
  }
  const points =
    validation.points_total != null
      ? `<p class="muted">Point total: ${validation.points_total}${validation.points_cap != null ? ` / ${validation.points_cap}` : ""}</p>`
      : "";
  const list = issues
    .map((issue) => {
      const link = issue.card_id
        ? ` <button type="button" class="secondary linkish" data-open-card="${issue.card_id}">View card</button>`
        : "";
      return `<li>${escapeHtml(issue.message)}${link}</li>`;
    })
    .join("");
  el.innerHTML = `${points}<ul class="deck-validation-list">${list}</ul>`;
  el.classList.toggle("has-errors", (validation.errors || []).length > 0);
  el.classList.remove("hidden");
  el.querySelectorAll("[data-open-card]").forEach((btn) => {
    btn.addEventListener("click", () => openCardModal(Number(btn.dataset.openCard)));
  });
}

function applyDraftFormatSettings() {
  if (!state.deckDraft) return;
  syncDraftFormatFromForm();
  markDeckDirty();
  renderDeckDetail(state.deckDraft.id);
  runDraftValidationPreview();
}

function openFormatsInfoModal() {
  const modal = $("#formats-info-modal");
  const trigger = $("#formats-info-btn");
  if (!modal) return;
  formatsInfoTrigger = trigger;
  modal.hidden = false;
  trigger?.setAttribute("aria-expanded", "true");
  syncModalOpenClass();
  $("#formats-info-close")?.focus();
}

function closeFormatsInfoModal() {
  const modal = $("#formats-info-modal");
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  syncModalOpenClass();
  $("#formats-info-btn")?.setAttribute("aria-expanded", "false");
  (formatsInfoTrigger ?? $("#formats-info-btn"))?.focus();
  formatsInfoTrigger = null;
}

let tradeSettingsTrigger = null;

function tradePageUrl(settings) {
  if (!settings?.trade_url) return "";
  if (settings.trade_url.startsWith("http")) return settings.trade_url;
  return `${window.location.origin}${settings.trade_url}`;
}

function renderTradeSettingsModal() {
  const settings = state.tradeSettings;
  if (!settings) return;
  const displayName = $("#trade-settings-display-name");
  const slug = $("#trade-settings-slug");
  const url = $("#trade-settings-url");
  if (displayName) displayName.value = settings.display_name || "";
  if (slug) slug.value = settings.slug || "";
  if (url) url.textContent = `Public link: ${tradePageUrl(settings)}`;
}

async function loadTradeSettings() {
  if (!state.token) return;
  try {
    state.tradeSettings = await api("/collection/trade-settings");
  } catch {
    state.tradeSettings = null;
  }
}

function openTradeSettingsModal() {
  const modal = $("#trade-settings-modal");
  const trigger = $("#trade-settings-btn");
  if (!modal) return;
  tradeSettingsTrigger = trigger;
  renderTradeSettingsModal();
  $("#trade-settings-error")?.classList.add("hidden");
  modal.hidden = false;
  syncModalOpenClass();
  $("#trade-settings-display-name")?.focus();
}

function closeTradeSettingsModal() {
  const modal = $("#trade-settings-modal");
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  syncModalOpenClass();
  (tradeSettingsTrigger ?? $("#trade-settings-btn"))?.focus();
  tradeSettingsTrigger = null;
}

async function saveTradeSettings() {
  const errorEl = $("#trade-settings-error");
  errorEl?.classList.add("hidden");
  const displayName = $("#trade-settings-display-name")?.value.trim() || null;
  const slug = $("#trade-settings-slug")?.value.trim();
  if (!slug) {
    errorEl.textContent = "Slug is required.";
    errorEl?.classList.remove("hidden");
    return;
  }
  try {
    state.tradeSettings = await api("/collection/trade-settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slug,
        display_name: displayName,
      }),
    });
    renderTradeSettingsModal();
    closeTradeSettingsModal();
    showToast("Trade settings saved.");
  } catch (err) {
    errorEl.textContent = err.message || "Could not save trade settings.";
    errorEl?.classList.remove("hidden");
  }
}

async function copyTradeLink() {
  if (!state.tradeSettings) {
    await loadTradeSettings();
  }
  const url = tradePageUrl(state.tradeSettings);
  if (!url) {
    showToast("Trade link is not available yet.", { variant: "error" });
    return;
  }
  try {
    await navigator.clipboard.writeText(url);
    showToast("Trade link copied.");
  } catch {
    showToast("Could not copy link.", { variant: "error" });
  }
}

const STORAGE_NOTICE_KEY = "ygo_storage_notice_dismissed";
let deleteAccountTrigger = null;

function initStorageNotice() {
  const banner = $("#storage-notice");
  if (!banner) return;
  if (localStorage.getItem(STORAGE_NOTICE_KEY) === "1") {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
}

function dismissStorageNotice() {
  localStorage.setItem(STORAGE_NOTICE_KEY, "1");
  const banner = $("#storage-notice");
  if (banner) banner.hidden = true;
}

async function exportAccountData() {
  if (!state.token) {
    showToast("Log in first.", { variant: "error" });
    return;
  }
  const btn = $("#account-export-btn");
  setButtonBusy(btn, true, { busyLabel: "Exporting…" });
  try {
    const headers = { Accept: "application/json" };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const res = await fetch(`${API}/auth/data-export`, { headers });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const detail = err.detail;
      throw new Error(typeof detail === "string" ? detail : "Export failed.");
    }
    const blob = await res.blob();
    const disposition = res.headers.get("content-disposition") || "";
    const match = /filename="([^"]+)"/i.exec(disposition);
    const filename = match?.[1] || "ygo-account-export.json";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    showToast("Account data downloaded.");
  } catch (err) {
    showToast(err.message || "Could not export data.", {
      variant: "error",
      durationMs: 5000,
    });
  } finally {
    setButtonBusy(btn, false);
  }
}

function openDeleteAccountModal() {
  if (!state.token || !state.user) {
    showToast("Log in first.", { variant: "error" });
    return;
  }
  deleteAccountTrigger = $("#account-settings-btn");
  const modal = $("#delete-account-modal");
  if (!modal) return;
  const errorEl = $("#delete-account-error");
  errorEl?.classList.add("hidden");
  errorEl.textContent = "";
  const passwordField = $("#delete-account-password-field");
  const emailField = $("#delete-account-email-field");
  const passwordInput = $("#delete-account-password");
  const emailInput = $("#delete-account-email");
  if (passwordInput) passwordInput.value = "";
  if (emailInput) emailInput.value = "";
  const hasPassword = Boolean(state.user.has_password);
  passwordField.hidden = !hasPassword;
  emailField.hidden = hasPassword;
  modal.hidden = false;
  syncModalOpenClass();
  if (hasPassword) passwordInput?.focus();
  else emailInput?.focus();
}

function closeDeleteAccountModal() {
  const modal = $("#delete-account-modal");
  if (!modal || modal.hidden) return;
  modal.hidden = true;
  syncModalOpenClass();
  (deleteAccountTrigger ?? $("#account-settings-btn"))?.focus();
  deleteAccountTrigger = null;
}

async function confirmDeleteAccount() {
  if (!state.user) return;
  const errorEl = $("#delete-account-error");
  errorEl?.classList.add("hidden");
  const btn = $("#delete-account-confirm");
  const body = state.user.has_password
    ? { password: $("#delete-account-password")?.value || "" }
    : { confirm_email: $("#delete-account-email")?.value || "" };
  setButtonBusy(btn, true, { busyLabel: "Deleting…" });
  try {
    await api("/auth/account", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    closeDeleteAccountModal();
    logout();
    showToast("Your account has been deleted.");
  } catch (err) {
    errorEl.textContent = err.message || "Could not delete account.";
    errorEl?.classList.remove("hidden");
    showToast(err.message || "Could not delete account.", {
      variant: "error",
      durationMs: 5000,
    });
  } finally {
    setButtonBusy(btn, false);
  }
}

async function init() {
  wireEvents();
  initStorageNotice();
  await loadAuthConfig();
  updateAuthUI();
  try {
    if (await handleOAuthReturn()) {
      return;
    }
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
      await loadTradeSettings();
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
