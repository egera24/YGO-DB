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
  activeDeckId: null,
  filters: {},
  token: localStorage.getItem("ygo_token") || null,
  user: null,
  searchPage: 0,
  searchTotal: 0,
  searchParams: new URLSearchParams(),
};

async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(`${API}${path}`, {
    headers,
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  if (res.status === 204) return null;
  return res.json();
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

function updateAuthUI() {
  const loggedIn = Boolean(state.token && state.user);
  $("#auth-login-form")?.classList.toggle("hidden", loggedIn);
  $("#auth-register-form")?.classList.toggle("hidden", loggedIn);
  $("#auth-logout")?.classList.toggle("hidden", !loggedIn);
  const userEl = $("#auth-user");
  if (loggedIn) {
    userEl.textContent = state.user.email;
    userEl.classList.remove("hidden");
  } else {
    userEl.classList.add("hidden");
  }
}

async function login(email, password) {
  const data = await api("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  state.token = data.access_token;
  localStorage.setItem("ygo_token", state.token);
  state.user = await api("/auth/me");
  updateAuthUI();
  await loadStatus();
  await loadFilters();
}

async function register(email, password) {
  const data = await api("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  state.token = data.access_token;
  localStorage.setItem("ygo_token", state.token);
  state.user = await api("/auth/me");
  updateAuthUI();
}

function logout() {
  state.token = null;
  state.user = null;
  localStorage.removeItem("ygo_token");
  updateAuthUI();
  loadStatus();
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

  const folderSel = $("#collection-folder");
  if (folderSel && state.token) {
    folderSel.querySelectorAll("option:not([value=''])").forEach((o) => o.remove());
    (data.folders || []).forEach((f) => {
      const o = document.createElement("option");
      o.value = f;
      o.textContent = f;
      folderSel.appendChild(o);
    });
  }
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

function initStatRangeSelects() {
  const ranges = [
    { min: "#level-min", max: "#level-max", lo: 1, hi: 12 },
    { min: "#rank-min", max: "#rank-max", lo: 1, hi: 13 },
    { min: "#link-rating-min", max: "#link-rating-max", lo: 1, hi: 6 },
    { min: "#pendulum-scale-min", max: "#pendulum-scale-max", lo: 0, hi: 13 },
  ];
  for (const { min, max, lo, hi } of ranges) {
    for (const sel of [min, max]) {
      const el = $(sel);
      if (!el) continue;
      for (let v = lo; v <= hi; v++) {
        const opt = document.createElement("option");
        opt.value = String(v);
        opt.textContent = String(v);
        el.appendChild(opt);
      }
    }
    const minEl = $(min);
    const maxEl = $(max);
    if (!minEl || !maxEl) continue;
    const syncMax = () => {
      const minVal = minEl.value;
      const maxVal = maxEl.value;
      if (minVal !== "" && maxVal !== "" && Number(minVal) > Number(maxVal)) {
        maxEl.value = minVal;
      }
    };
    minEl.addEventListener("change", syncMax);
    maxEl.addEventListener("change", syncMax);
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
    });
  });
}

function switchView(name) {
  state.activeView = name;
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  $(`#view-${name}`).classList.add("active");
  document.querySelector(`.tab[data-view="${name}"]`).classList.add("active");
  if (name === "collection") loadCollection();
  if (name === "decks") loadDecks();
}

const SEARCH_PAGE_SIZE = 500;

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
  return params;
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

  const start = page * SEARCH_PAGE_SIZE + 1;
  const end = Math.min((page + 1) * SEARCH_PAGE_SIZE, total);

  bar.classList.remove("hidden");
  bar.innerHTML = `
    <button type="button" id="search-prev" class="secondary"${page === 0 ? " disabled" : ""}>← Previous</button>
    <span class="search-page-info">Page ${page + 1} of ${totalPages} · ${start.toLocaleString()}–${end.toLocaleString()} of ${total.toLocaleString()}</span>
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
    return;
  }
  grid.innerHTML = cards
      .map(
        (c) => `
      <article class="card-tile ${c.owned ? "owned" : ""}" data-id="${c.id}">
        ${c.owned ? `<span class="badge">×${c.owned_quantity}</span>` : ""}
        ${cardImgTag(c.image_url_small)}
        <div class="info">
          <div class="name">${escapeHtml(c.name)}</div>
          <div class="muted">${escapeHtml(c.type || "")}</div>
        </div>
      </article>`
      )
      .join("");
  grid.querySelectorAll(".card-tile").forEach((el) => {
    el.addEventListener("click", () => openCardModal(Number(el.dataset.id)));
  });
}

async function loadSearchPage(pageIndex) {
  state.searchPage = pageIndex;
  const offset = pageIndex * SEARCH_PAGE_SIZE;
  const grid = $("#search-results");
  grid.innerHTML = '<p class="empty-msg">Searching…</p>';
  $("#search-pagination")?.classList.add("hidden");

  try {
    const page = await fetchSearchPage(state.searchParams, offset);
    state.searchTotal = page.total;
    renderSearchResults(page.items);
    renderSearchPagination();
    $("#search-pagination")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    grid.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  }
}

async function runSearch(e) {
  e?.preventDefault();
  state.searchParams = buildSearchParams();
  state.searchPage = 0;
  await loadSearchPage(0);
}

const MODAL_TEXT = "#e8eef7";
const MODAL_MUTED = "#94a3b8";

function applyModalReadableColors() {
  const dlg = $("#card-modal");
  const card = dlg?.querySelector(".modal-card");
  if (!card) return;
  card.style.color = MODAL_TEXT;
  const setLight = (el, color) => el?.style.setProperty("color", color, "important");
  dlg.querySelectorAll(
    ".modal-info h2, .modal-info h3, .modal-info p, .modal-info label, #modal-desc, .printings-list, .printing-row, .printing-row span, .tag"
  ).forEach((el) => {
    if (!el.classList.contains("set-code")) setLight(el, MODAL_TEXT);
  });
  setLight($("#modal-name"), MODAL_TEXT);
  setLight($("#modal-desc"), MODAL_TEXT);
  dlg.querySelectorAll(".modal-info h3").forEach((el) => setLight(el, MODAL_TEXT));
  setLight($("#modal-meta"), MODAL_MUTED);
  dlg.querySelectorAll(".printing-row .set-code").forEach((el) => setLight(el, "#d4a017"));
}

function openCardModalOverlay() {
  const dlg = $("#card-modal");
  dlg.hidden = false;
  syncModalOpenClass();
  applyModalReadableColors();
}

function closeCardModalOverlay() {
  const dlg = $("#card-modal");
  dlg.hidden = true;
  syncModalOpenClass();
}

function isModalVisible(id) {
  const el = $(id);
  return el && !el.hidden;
}

function syncModalOpenClass() {
  if (isModalVisible("#card-modal") || isModalVisible("#search-help-modal")) {
    document.body.classList.add("modal-open");
  } else {
    document.body.classList.remove("modal-open");
  }
}

let searchHelpTrigger = null;

function openSearchHelpModal() {
  const dlg = $("#search-help-modal");
  const trigger = $("#search-help-btn");
  if (!dlg) return;
  searchHelpTrigger = trigger;
  dlg.hidden = false;
  trigger?.setAttribute("aria-expanded", "true");
  syncModalOpenClass();
  $("#search-help-close")?.focus();
}

function closeSearchHelpModal() {
  const dlg = $("#search-help-modal");
  if (!dlg || dlg.hidden) return;
  dlg.hidden = true;
  $("#search-help-btn")?.setAttribute("aria-expanded", "false");
  syncModalOpenClass();
  (searchHelpTrigger ?? $("#search-help-btn"))?.focus();
  searchHelpTrigger = null;
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

async function openCardModal(cardId) {
  state.currentCardId = cardId;
  const imageToken = beginModalImagePending();
  const card = await api(`/cards/${cardId}`);
  if (state.currentCardId !== cardId) return;

  $("#modal-name").textContent = card.name;
  setModalImage(card.image_url || card.image_url_small || null, card.name, imageToken);
  const stats = [
    card.category,
    (card.types || []).join(" / "),
    card.mechanic,
    card.attribute,
    card.archetype,
    card.level != null ? `Level ${card.level}` : null,
    card.rank != null ? `Rank ${card.rank}` : null,
    card.link_rating != null ? `Link-${card.link_rating}` : null,
    card.pendulum_scale != null ? `Scale ${card.pendulum_scale}` : null,
    (card.link_markers || []).length ? `Markers: ${card.link_markers.join(", ")}` : null,
    card.summoning_condition,
    card.atk != null ? `ATK ${card.atk}` : null,
    card.def != null ? `DEF ${card.def}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  $("#modal-meta").textContent = stats;
  $("#modal-desc").textContent = card.desc || "";
  $("#modal-favorite").textContent = card.is_favorite ? "★ Favorited" : "☆ Favorite";

  $("#modal-tags").innerHTML = (card.tags || [])
    .map((t) => `<span class="tag">${escapeHtml(t)}</span>`)
    .join("");

  const printingSel = $("#owned-printing");
  printingSel.innerHTML = (card.printings || [])
    .map(
      (p) =>
        `<option value="${escapeHtml(p.set_code)}|${escapeHtml(p.set_rarity_code)}">
          ${escapeHtml(p.set_code)} ${escapeHtml(p.set_rarity)} ${p.owned_quantity ? `(owned ${p.owned_quantity})` : ""}
        </option>`
    )
    .join("");

  $("#modal-printings").innerHTML = (card.printings || [])
    .map(
      (p) => `
      <div class="printing-row ${p.owned_quantity ? "owned" : ""}">
        <span class="set-code">${escapeHtml(p.set_code)}</span>
        <span>${escapeHtml(p.set_rarity)} ${p.owned_quantity ? `· owned ×${p.owned_quantity}` : ""}</span>
      </div>`
    )
    .join("");

  openCardModalOverlay();
}

async function loadCollection() {
  if (!state.token) {
    $("#collection-list").innerHTML =
      '<p class="empty-msg">Log in to view your collection.</p>';
    return;
  }
  const params = new URLSearchParams({ limit: "500" });
  const q = $("#collection-q")?.value.trim();
  const folder = $("#collection-folder")?.value;
  if (q) params.set("q", q);
  if (folder) params.set("folder", folder);

  const items = await api(`/collection?${params}`);
  $("#collection-stats").textContent = `${items.length} rows shown (max 500 per page)`;

  const wrap = $("#collection-list");
  if (!items.length) {
    wrap.innerHTML = '<p class="empty-msg">No collection items. Import my_collection.csv first.</p>';
    return;
  }

  wrap.innerHTML = `
    <table>
      <thead>
        <tr>
          <th></th>
          <th>Set code</th>
          <th>Rarity</th>
          <th>Name</th>
          <th>Qty</th>
          <th>Folder</th>
          <th>Condition</th>
        </tr>
      </thead>
      <tbody>
        ${items
          .map(
            (i) => `
          <tr data-id="${i.id}" ${i.card_id ? `data-card="${i.card_id}"` : ""} class="${i.card_id ? "clickable" : ""}">
            <td>${cardImgTag(i.image_url_small, 'width="36" height="52"')}</td>
            <td class="set-code">${escapeHtml(i.set_code)}</td>
            <td>${escapeHtml((i.rarity_code || "").replace(/[()]/g, ""))}</td>
            <td>${escapeHtml(i.card_name || "")}</td>
            <td>${i.quantity}</td>
            <td>${escapeHtml(i.folder_name || "")}</td>
            <td>${escapeHtml(i.condition || "")}</td>
          </tr>`
          )
          .join("")}
      </tbody>
    </table>`;

  wrap.querySelectorAll("tr[data-card]").forEach((row) => {
    row.style.cursor = "pointer";
    row.addEventListener("click", () => openCardModal(Number(row.dataset.card)));
  });
}

async function loadDecks() {
  if (!state.token) {
    $("#deck-list").innerHTML =
      '<li class="empty-msg">Log in to manage decks.</li>';
    return;
  }
  const decks = await api("/decks");
  const list = $("#deck-list");
  list.innerHTML = decks
    .map(
      (d) => `
    <li data-id="${d.id}" class="${d.id === state.activeDeckId ? "active" : ""}">
      <strong>${escapeHtml(d.name)}</strong><br />
      <small class="muted">Main ${d.main_count} · Extra ${d.extra_count} · Side ${d.side_count}</small>
    </li>`
    )
    .join("");

  list.querySelectorAll("li").forEach((li) => {
    li.addEventListener("click", () => selectDeck(Number(li.dataset.id)));
  });
}

async function selectDeck(deckId) {
  state.activeDeckId = deckId;
  const deck = await api(`/decks/${deckId}`);
  $("#deck-empty").classList.add("hidden");
  $("#deck-editor").classList.remove("hidden");
  $("#deck-name").textContent = deck.name;
  $("#count-main").textContent = deck.main_count;
  $("#count-extra").textContent = deck.extra_count;
  $("#count-side").textContent = deck.side_count;

  const zones = { main: [], extra: [], side: [] };
  deck.cards.forEach((c) => zones[c.zone]?.push(c));

  $("#deck-zones").innerHTML = ["main", "extra", "side"]
    .map((zone) => {
      const cards = zones[zone];
      return `
        <div class="zone-block">
          <h3>${zone.charAt(0).toUpperCase() + zone.slice(1)} deck</h3>
          <div class="zone-cards">
            ${
              cards.length
                ? cards
                    .map(
                      (c) => `
                <div class="deck-card-chip" data-card="${c.card_id}" data-zone="${zone}">
                  ${cardImgTag(c.image_url_small)}
                  <span>${escapeHtml(c.name)} ×${c.quantity}</span>
                  <button type="button" class="deck-minus" title="Remove one">−</button>
                </div>`
                    )
                    .join("")
                : '<span class="muted">Empty</span>'
            }
          </div>
        </div>`;
    })
    .join("");

  $("#deck-zones").querySelectorAll(".deck-card-chip").forEach((chip) => {
    chip.querySelector(".deck-minus")?.addEventListener("click", async (e) => {
      e.stopPropagation();
      const cardId = Number(chip.dataset.card);
      const zone = chip.dataset.zone;
      const card = deck.cards.find((c) => c.card_id === cardId && c.zone === zone);
      const newQty = (card?.quantity || 1) - 1;
      await api(
        `/decks/${deckId}/cards/${cardId}?zone=${zone}&quantity=${newQty}`,
        { method: "PATCH" }
      );
      selectDeck(deckId);
    });
    chip.addEventListener("click", () => openCardModal(Number(chip.dataset.card)));
  });

  loadDecks();
}

function wireEvents() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
  });

  $("#search-form").addEventListener("submit", runSearch);
  $("#search-reset")?.addEventListener("click", async () => {
    resetSearchFilters();
    await runSearch();
  });
  $("#collection-filter")?.addEventListener("submit", (e) => {
    e.preventDefault();
    loadCollection();
  });

  $("#auth-login-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await login($("#login-email").value, $("#login-password").value);
    } catch (err) {
      alert(err.message);
    }
  });

  $("#auth-register-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await register($("#register-email").value, $("#register-password").value);
      await loadStatus();
      await loadFilters();
      alert("Account created. You are logged in.");
    } catch (err) {
      alert(err.message);
    }
  });

  $("#auth-logout")?.addEventListener("click", logout);

  $("#reimport-collection")?.addEventListener("click", () => {
    if (!state.token) {
      alert("Log in first.");
      return;
    }
    $("#collection-csv-file")?.click();
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
    const importBtn = $("#reimport-collection");
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
      alert(`Imported ${done.imported} rows`);
      loadCollection();
      await loadStatus();
    } catch (err) {
      alert(err.message);
      await loadStatus();
    } finally {
      clearImportStatusLine();
      if (importBtn) importBtn.disabled = false;
      e.target.value = "";
    }
  });

  $("#modal-close").addEventListener("click", closeCardModalOverlay);
  $("#card-modal").addEventListener("click", (e) => {
    if (e.target === $("#card-modal")) closeCardModalOverlay();
  });

  $("#search-help-btn")?.addEventListener("click", openSearchHelpModal);
  $("#search-help-close")?.addEventListener("click", closeSearchHelpModal);
  $("#search-help-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#search-help-modal")) closeSearchHelpModal();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (isModalVisible("#search-help-modal")) closeSearchHelpModal();
    else if (isModalVisible("#card-modal")) closeCardModalOverlay();
  });

  $("#modal-favorite").addEventListener("click", async () => {
    if (!state.token) {
      alert("Log in to use favorites.");
      return;
    }
    await api(`/cards/${state.currentCardId}/favorite`, { method: "POST" });
    openCardModal(state.currentCardId);
  });

  $("#tag-add-btn").addEventListener("click", async () => {
    if (!state.token) {
      alert("Log in to add tags.");
      return;
    }
    const tag = $("#tag-input").value.trim();
    if (!tag) return;
    await api(`/cards/${state.currentCardId}/tags`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tag }),
    });
    $("#tag-input").value = "";
    openCardModal(state.currentCardId);
  });

  $("#owned-add-btn").addEventListener("click", async () => {
    if (!state.token) {
      alert("Log in to add to your collection.");
      return;
    }
    const val = $("#owned-printing").value;
    const [set_code, rarity] = val.split("|");
    const qty = Number($("#owned-qty").value) || 1;
    await api("/collection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ set_code, rarity, quantity: qty }),
    });
    alert(`Added ${qty}× ${set_code}`);
    openCardModal(state.currentCardId);
    loadStatus();
  });

  $("#deck-add-card-btn").addEventListener("click", async () => {
    if (!state.activeDeckId) {
      alert("Select a deck first (Decks tab).");
      return;
    }
    const zone = $("#deck-zone").value;
    await api(`/decks/${state.activeDeckId}/cards`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: state.currentCardId, zone, quantity: 1 }),
    });
    alert("Added to deck.");
  });

  $("#new-deck-btn").addEventListener("click", async () => {
    const name = prompt("Deck name:");
    if (!name?.trim()) return;
    const deck = await api("/decks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim() }),
    });
    state.activeDeckId = deck.id;
    await loadDecks();
    selectDeck(deck.id);
  });
}

async function init() {
  wireEvents();
  updateAuthUI();
  try {
    if (state.token) {
      try {
        state.user = await api("/auth/me");
      } catch {
        state.token = null;
        state.user = null;
        localStorage.removeItem("ygo_token");
      }
    }
    updateAuthUI();
    await loadStatus();
    initFilterMultiWidgets();
    initStatRangeSelects();
    await loadFilters();
    setupLinkMarkerGrid();
    setupSummoningSuggestions();
    await runSearch();
  } catch (err) {
    $("#status-line").textContent = err.message;
  }
}

init();
