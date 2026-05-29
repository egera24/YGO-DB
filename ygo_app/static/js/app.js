const API = "/api";

const state = {
  activeView: "search",
  currentCardId: null,
  activeDeckId: null,
  filters: {},
};

async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { Accept: "application/json", ...(options.headers || {}) },
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

async function loadStatus() {
  const status = await api("/status");
  const line = $("#status-line");
  if (!status.ready) {
    line.textContent =
      "Database empty — run: python -m ygo_app.import_data";
    line.style.color = "#f87171";
    return;
  }
  line.textContent = `${status.cards.toLocaleString()} cards · ${status.collection_items.toLocaleString()} owned printings · ${status.decks} decks`;
}

async function loadFilters() {
  const data = await api("/filters");
  state.filters = data;
  for (const [id, key] of [
    ["#frame-type", "frame_types"],
    ["#attribute", "attributes"],
    ["#race", "races"],
  ]) {
    const sel = $(id);
    data[key].forEach((v) => {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = v;
      sel.appendChild(o);
    });
  }
  const folderSel = $("#collection-folder");
  data.folders.forEach((f) => {
    const o = document.createElement("option");
    o.value = f;
    o.textContent = f;
    folderSel.appendChild(o);
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

const SEARCH_PAGE_SIZE = 1000;

async function fetchAllSearchCards(baseParams) {
  const all = [];
  let offset = 0;
  let total = 0;
  while (true) {
    const pageParams = new URLSearchParams(baseParams);
    pageParams.set("limit", String(SEARCH_PAGE_SIZE));
    pageParams.set("offset", String(offset));
    const page = await api(`/cards/search?${pageParams}`);
    all.push(...page.items);
    total = page.total;
    if (!page.items.length || all.length >= total) break;
    offset += page.items.length;
  }
  return { cards: all, total };
}

function renderSearchResults(cards, total) {
  const grid = $("#search-results");
  if (!cards.length) {
    grid.innerHTML = '<p class="empty-msg">No cards found.</p>';
    return;
  }
  grid.innerHTML =
    `<p class="empty-msg search-count">${cards.length.toLocaleString()} of ${total.toLocaleString()} cards</p>` +
    cards
      .map(
        (c) => `
      <article class="card-tile ${c.owned ? "owned" : ""}" data-id="${c.id}">
        ${c.owned ? `<span class="badge">×${c.owned_quantity}</span>` : ""}
        <img src="${escapeHtml(c.image_url_small)}" alt="" loading="lazy" />
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

async function runSearch(e) {
  e?.preventDefault();
  const params = new URLSearchParams();
  const q = $("#q").value.trim();
  const setCode = $("#set-code").value.trim();
  if (q) params.set("q", q);
  if (setCode) params.set("set_code", setCode);
  const frame = $("#frame-type").value;
  const attr = $("#attribute").value;
  const race = $("#race").value;
  if (frame) params.set("frame_type", frame);
  if (attr) params.set("attribute", attr);
  if (race) params.set("race", race);
  if ($("#owned-only").checked) params.set("owned_only", "true");
  if ($("#favorites-only").checked) params.set("favorites_only", "true");

  const grid = $("#search-results");
  grid.innerHTML = '<p class="empty-msg">Searching…</p>';

  try {
    const { cards, total } = await fetchAllSearchCards(params);
    renderSearchResults(cards, total);
  } catch (err) {
    grid.innerHTML = `<p class="empty-msg">${escapeHtml(err.message)}</p>`;
  }
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
  document.body.classList.add("modal-open");
  applyModalReadableColors();
}

function closeCardModalOverlay() {
  const dlg = $("#card-modal");
  dlg.hidden = true;
  document.body.classList.remove("modal-open");
}

async function openCardModal(cardId) {
  state.currentCardId = cardId;
  const card = await api(`/cards/${cardId}`);
  const dlg = $("#card-modal");
  $("#modal-name").textContent = card.name;
  $("#modal-image").src = card.image_url || card.image_url_small || "";
  $("#modal-image").alt = card.name;
  const stats = [
    card.type,
    card.attribute,
    card.race,
    card.level != null ? `Level ${card.level}` : null,
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
            <td>${i.image_url_small ? `<img src="${escapeHtml(i.image_url_small)}" width="36" height="52" />` : ""}</td>
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
                  <img src="${escapeHtml(c.image_url_small)}" alt="" />
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
  $("#collection-filter")?.addEventListener("submit", (e) => {
    e.preventDefault();
    loadCollection();
  });

  $("#reimport-collection")?.addEventListener("click", async () => {
    if (!confirm("Re-import my_collection.csv from project root? This replaces collection data.")) return;
    const res = await api("/collection/import-csv", { method: "POST" });
    alert(`Imported ${res.imported} rows`);
    loadCollection();
    loadStatus();
  });

  $("#modal-close").addEventListener("click", closeCardModalOverlay);
  $("#card-modal").addEventListener("click", (e) => {
    if (e.target === $("#card-modal")) closeCardModalOverlay();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#card-modal").hidden) closeCardModalOverlay();
  });

  $("#modal-favorite").addEventListener("click", async () => {
    await api(`/cards/${state.currentCardId}/favorite`, { method: "POST" });
    openCardModal(state.currentCardId);
  });

  $("#tag-add-btn").addEventListener("click", async () => {
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
  try {
    await loadStatus();
    await loadFilters();
    await runSearch();
  } catch (err) {
    $("#status-line").textContent = err.message;
  }
}

init();
