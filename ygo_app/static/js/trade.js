import { createFilterCombobox } from "./filter-combobox.js";
import { rarityBadgeHtml } from "./rarity-badges.js";
import { bindSortDirToggle, readSortDir } from "./sort-controls.js";

const $ = (sel) => document.querySelector(sel);

  const slug = (() => {
    const parts = window.location.pathname.split("/").filter(Boolean);
    if (parts[0] === "trade" && parts[1]) return decodeURIComponent(parts[1]);
    return "";
  })();

  const state = {
    items: [],
    total: 0,
    limit: 100,
    offset: 0,
    view: "list",
    sellerName: null,
    filtersLoaded: false,
    sets: [],
    rarities: [],
    currency: "EUR",
    publicConfig: {
      turnstile_site_key: null,
      eur_huf_rate: 390,
      eur_huf_rate_source: "fallback",
      eur_huf_rate_as_of: null,
    },
    turnstileWidgetId: null,
    addModalItemId: null,
    addModalTrigger: null,
  };

  const cartStorageKey = () => `trade-cart:${slug}`;
  const currencyStorageKey = () => `trade-currency:${slug}`;

  const INFO_ICON_SVG =
    '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10" /><path d="M12 16v-4" /><path d="M12 8h.01" /></svg>';
  const OFFER_INFO_TITLE = "Alternate Offer Price";

  let offerInfoTrigger = null;
  let initStarted = false;
  let turnstileInitPromise = null;

  const TRADE_TABLE_SKELETON_ROWS = 10;
  const TRADE_TILE_SKELETON_COUNT = 12;

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderOfferInfoButtonHtml() {
    return `<button type="button" class="icon-btn supplement-icon-btn trade-offer-info-btn" aria-label="About alternate offer price" aria-haspopup="dialog" aria-controls="trade-offer-info-popover" aria-expanded="false">${INFO_ICON_SVG}</button>`;
  }

  function renderOfferLabelHtml() {
    return `<div class="trade-field-label-row"><span>${OFFER_INFO_TITLE}</span>${renderOfferInfoButtonHtml()}</div>`;
  }

  function isOfferInfoPopoverOpen() {
    const popover = $("#trade-offer-info-popover");
    return popover && !popover.hidden;
  }

  function positionOfferInfoPopover(triggerBtn) {
    const popover = $("#trade-offer-info-popover");
    if (!popover || !triggerBtn) return;

    const margin = 8;
    const maxWidth = Math.min(320, window.innerWidth - margin * 2);
    popover.style.width = `${maxWidth}px`;

    const rect = triggerBtn.getBoundingClientRect();
    const popoverRect = popover.getBoundingClientRect();
    let top = rect.bottom + margin;
    let left = rect.left;

    if (left + popoverRect.width > window.innerWidth - margin) {
      left = window.innerWidth - margin - popoverRect.width;
    }
    if (left < margin) left = margin;
    if (top + popoverRect.height > window.innerHeight - margin) {
      top = rect.top - margin - popoverRect.height;
    }
    if (top < margin) top = margin;

    popover.style.top = `${top}px`;
    popover.style.left = `${left}px`;
  }

  function closeOfferInfoPopover(returnFocus = true) {
    const popover = $("#trade-offer-info-popover");
    if (!popover || popover.hidden) return;

    popover.hidden = true;
    document.querySelectorAll(".trade-offer-info-btn[aria-expanded='true']").forEach((btn) => {
      btn.setAttribute("aria-expanded", "false");
    });

    const trigger = offerInfoTrigger;
    offerInfoTrigger = null;
    if (returnFocus && trigger) trigger.focus();
  }

  function openOfferInfoPopover(triggerBtn) {
    const popover = $("#trade-offer-info-popover");
    if (!popover || !triggerBtn) return;

    document.querySelectorAll(".trade-offer-info-btn[aria-expanded='true']").forEach((btn) => {
      btn.setAttribute("aria-expanded", "false");
    });

    offerInfoTrigger = triggerBtn;
    triggerBtn.setAttribute("aria-expanded", "true");
    popover.hidden = false;
    positionOfferInfoPopover(triggerBtn);
  }

  function toggleOfferInfoPopover(triggerBtn) {
    if (isOfferInfoPopoverOpen() && offerInfoTrigger === triggerBtn) {
      closeOfferInfoPopover(true);
      return;
    }
    openOfferInfoPopover(triggerBtn);
  }

  function getSelectedCurrency() {
    return state.currency === "HUF" ? "HUF" : "EUR";
  }

  function getEurHufRate() {
    const rate = Number(state.publicConfig.eur_huf_rate);
    return Number.isFinite(rate) && rate > 0 ? rate : 390;
  }

  function loadCurrencyPreference() {
    try {
      const stored = localStorage.getItem(currencyStorageKey());
      if (stored === "HUF" || stored === "EUR") return stored;
    } catch {
      /* ignore */
    }
    return "EUR";
  }

  function saveCurrencyPreference(currency) {
    try {
      localStorage.setItem(currencyStorageKey(), currency);
    } catch {
      /* ignore */
    }
  }

  function getCurrencyCode() {
    return getSelectedCurrency();
  }

  function formatItemRarity(item) {
    return item.rarity_name || item.rarity_display || item.rarity_code || "—";
  }

  function formatDisplayPrice(eurValue) {
    if (eurValue == null || Number.isNaN(Number(eurValue))) return "—";
    const eur = Number(eurValue);
    if (getSelectedCurrency() === "HUF") {
      return `${Math.round(eur * getEurHufRate()).toLocaleString("hu-HU")} HUF`;
    }
    return `${eur.toFixed(2).replace(".", ",")} EUR`;
  }

  function formatOfferPlaceholder(eurValue) {
    if (eurValue == null || Number.isNaN(Number(eurValue))) return "";
    const eur = Number(eurValue);
    if (getSelectedCurrency() === "HUF") {
      return Math.round(eur * getEurHufRate()).toLocaleString("hu-HU");
    }
    return eur.toFixed(2).replace(".", ",");
  }

  function syncCurrencySuffixes() {
    const code = getCurrencyCode();
    const modalSuffix = $("#trade-add-offer-currency");
    if (modalSuffix) modalSuffix.textContent = code;
    document.querySelectorAll(".trade-currency-suffix[data-cart-currency]").forEach((el) => {
      el.textContent = code;
    });
  }

  function offerInputStep() {
    return getSelectedCurrency() === "HUF" ? "1" : "0.01";
  }

  function displayOfferValue(eurOffer) {
    if (eurOffer === "" || eurOffer == null) return "";
    const num = Number(eurOffer);
    if (Number.isNaN(num)) return "";
    if (getSelectedCurrency() === "HUF") {
      return String(Math.round(num * getEurHufRate()));
    }
    return String(num);
  }

  function parseOfferInput(raw) {
    const trimmed = String(raw ?? "").trim();
    if (trimmed === "") return "";
    const num = Number(trimmed);
    if (Number.isNaN(num) || num < 0) return Number.NaN;
    if (getSelectedCurrency() === "HUF") {
      const rate = getEurHufRate();
      return Math.round((num / rate) * 100) / 100;
    }
    return num;
  }

  function updateCurrencyRateHint() {
    const hint = $("#trade-currency-rate");
    if (!hint) return;
    if (getSelectedCurrency() !== "HUF") {
      hint.textContent = "";
      hint.classList.add("hidden");
      hint.setAttribute("aria-hidden", "true");
      return;
    }
    const source = state.publicConfig.eur_huf_rate_source;
    const rateText = getEurHufRate().toFixed(2);
    let message = `1 EUR = ${rateText} HUF`;
    if (source === "fallback") {
      message += " · fallback";
    }
    hint.textContent = message;
    hint.classList.remove("hidden");
    hint.removeAttribute("aria-hidden");
  }

  function updateCurrencyNote() {
    const note = $("#trade-rate-note");
    if (!note) return;
    if (getSelectedCurrency() !== "HUF") {
      note.textContent = "";
      note.classList.add("hidden");
      return;
    }
    const asOf = state.publicConfig.eur_huf_rate_as_of;
    const source = state.publicConfig.eur_huf_rate_source;
    const rateText = getEurHufRate().toFixed(2);
    let message = `Prices shown in HUF (1 EUR = ${rateText} HUF`;
    if (asOf) {
      message += `, rate as of ${asOf}`;
    }
    if (source === "fallback") {
      message += ", fallback rate";
    }
    message += "). Offers are converted to EUR for the seller.";
    note.textContent = message;
    note.classList.remove("hidden");
  }

  function syncCurrencySelect() {
    const select = $("#trade-currency");
    if (select) select.value = getSelectedCurrency();
    updateCurrencyRateHint();
    updateCurrencyNote();
  }

  function setCurrency(currency) {
    const next = currency === "HUF" ? "HUF" : "EUR";
    state.currency = next;
    saveCurrencyPreference(next);
    syncCurrencySelect();
    syncCurrencySuffixes();
    renderItems();
    renderCart();
    if (isAddModalOpen() && state.addModalItemId != null) {
      openAddModal(state.addModalItemId);
    }
  }

  function showToast(message, variant) {
    const el = $("#trade-toast");
    if (!el) return;
    el.textContent = message;
    el.classList.remove("hidden", "trade-toast--success", "trade-toast--error");
    if (variant === "error") el.classList.add("trade-toast--error");
    else el.classList.add("trade-toast--success");
    window.clearTimeout(showToast._timer);
    showToast._timer = window.setTimeout(() => {
      el.classList.add("hidden");
    }, 4000);
  }

  function readCart() {
    try {
      const raw = sessionStorage.getItem(cartStorageKey());
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  function writeCart(cart) {
    sessionStorage.setItem(cartStorageKey(), JSON.stringify(cart));
    updateCartCount();
    renderCart();
  }

  function clearCart() {
    sessionStorage.removeItem(cartStorageKey());
    updateCartCount();
    renderCart();
  }

  function cartCount(cart) {
    return Object.values(cart).reduce((sum, line) => sum + (line.quantity || 0), 0);
  }

  function updateCartCount() {
    const count = cartCount(readCart());
    const badge = $("#trade-cart-count");
    const toggle = $("#trade-cart-toggle");
    if (badge) {
      badge.textContent = String(count);
      badge.classList.toggle("hidden", count <= 0);
      badge.setAttribute("aria-hidden", count <= 0 ? "true" : "false");
    }
    if (toggle) {
      const label = count > 0 ? `Open cart, ${count} item${count === 1 ? "" : "s"}` : "Open cart";
      toggle.setAttribute("aria-label", label);
    }
  }

  function itemById(itemId) {
    return state.items.find((item) => item.item_id === itemId);
  }

  function cartLineDisplay(line) {
    const item = itemById(line.item_id) || {};
    return {
      card_name: line.card_name || item.card_name || "Card",
      set_code: line.set_code ?? item.set_code ?? "",
      rarity_code: line.rarity_code ?? item.rarity_code ?? "",
      rarity_display: line.rarity_display || item.rarity_display || item.rarity_code || "",
      rarity_name: line.rarity_name || item.rarity_name || "",
      sell_price: line.sell_price ?? item.sell_price,
      image_url_small: line.image_url_small ?? item.image_url_small,
      trade_quantity: line.trade_quantity ?? item.trade_quantity ?? line.quantity ?? 1,
    };
  }

  function buildCartSnapshot(item) {
    return {
      card_name: item.card_name,
      set_code: item.set_code,
      rarity_code: item.rarity_code,
      rarity_display: item.rarity_display || item.rarity_code || "",
      rarity_name: item.rarity_name || "",
      sell_price: item.sell_price,
      image_url_small: item.image_url_small,
      trade_quantity: item.trade_quantity,
    };
  }

  function isAddModalOpen() {
    const modal = $("#trade-add-modal");
    return modal && !modal.hidden;
  }

  function openAddModal(itemId, trigger) {
    const item = itemById(itemId);
    if (!item) return;

    const modal = $("#trade-add-modal");
    const preview = $("#trade-add-preview");
    const qtyInput = $("#trade-add-qty");
    const offerInput = $("#trade-add-offer");
    const errorEl = $("#trade-add-error");
    if (!modal || !preview || !qtyInput || !offerInput) return;

    state.addModalItemId = itemId;
    state.addModalTrigger = trigger || null;

    const existing = readCart()[itemId];
    const maxQty = item.trade_quantity || 1;
    qtyInput.min = "1";
    qtyInput.max = String(maxQty);
    qtyInput.value = String(existing?.quantity || 1);
    offerInput.value = displayOfferValue(existing?.offer_price);
    offerInput.step = offerInputStep();
    offerInput.placeholder = formatOfferPlaceholder(item.sell_price);
    syncCurrencySuffixes();

    preview.innerHTML = `
      <div class="trade-add-preview-thumb">${cardImgTag(item.image_url_small, item.card_name)}</div>
      <div class="trade-add-preview-info">
        <p class="trade-add-preview-name">${escapeHtml(item.card_name)}</p>
        <p class="trade-add-preview-meta">${escapeHtml(item.set_code)} · ${escapeHtml(formatItemRarity(item))} · List ${formatDisplayPrice(item.sell_price)}</p>
      </div>
    `;

    if (errorEl) {
      errorEl.textContent = "";
      errorEl.classList.add("hidden");
    }

    modal.hidden = false;
    qtyInput.focus();
    qtyInput.select();
  }

  function closeAddModal() {
    const modal = $("#trade-add-modal");
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    state.addModalItemId = null;
    const trigger = state.addModalTrigger;
    state.addModalTrigger = null;
    trigger?.focus();
  }

  function confirmAddToCart() {
    const itemId = state.addModalItemId;
    if (itemId == null) return;

    const item = itemById(itemId);
    const qtyInput = $("#trade-add-qty");
    const offerInput = $("#trade-add-offer");
    const errorEl = $("#trade-add-error");
    if (!item || !qtyInput || !offerInput) return;

    const quantity = Number(qtyInput.value) || 0;
    const maxQty = item.trade_quantity || 1;
    const offerRaw = offerInput.value.trim();
    const offerPrice = parseOfferInput(offerRaw);

    if (errorEl) {
      errorEl.textContent = "";
      errorEl.classList.add("hidden");
    }

    if (quantity < 1 || quantity > maxQty) {
      if (errorEl) {
        errorEl.textContent = `Quantity must be between 1 and ${maxQty}.`;
        errorEl.classList.remove("hidden");
      }
      return;
    }
    if (offerRaw !== "" && Number.isNaN(offerPrice)) {
      if (errorEl) {
        errorEl.textContent = "Alternate offer price must be zero or greater.";
        errorEl.classList.remove("hidden");
      }
      return;
    }

    const cart = readCart();
    const existing = cart[itemId] || { item_id: itemId, comment: "" };
    cart[itemId] = {
      ...existing,
      item_id: itemId,
      quantity,
      offer_price: offerRaw === "" ? "" : offerPrice,
      comment: existing.comment || "",
      ...buildCartSnapshot(item),
    };
    writeCart(cart);
    closeAddModal();
    showToast("Added to cart.");
  }

  function removeFromCart(itemId) {
    const cart = readCart();
    delete cart[itemId];
    writeCart(cart);
  }

  function updateCartLine(itemId, field, value) {
    const cart = readCart();
    const line = cart[itemId];
    if (!line) return;
    line[field] = value;
    writeCart(cart);
  }

  function renderCart() {
    const cart = readCart();
    const linesEl = $("#trade-cart-lines");
    const emptyEl = $("#trade-cart-empty");
    if (!linesEl || !emptyEl) return;

    const entries = Object.values(cart);
    if (!entries.length) {
      linesEl.innerHTML = "";
      emptyEl.classList.remove("hidden");
      return;
    }
    emptyEl.classList.add("hidden");

    linesEl.innerHTML = entries
      .map((line) => {
        const display = cartLineDisplay(line);
        const maxQty = display.trade_quantity || line.quantity || 1;
        return `
          <article class="trade-cart-line" data-item-id="${line.item_id}">
            <div class="trade-cart-line-main">
              <div class="trade-cart-line-thumb">${cardImgTag(display.image_url_small, display.card_name)}</div>
              <div class="trade-cart-line-info">
                <p class="trade-cart-line-title">${escapeHtml(display.card_name)}</p>
                <p class="trade-cart-line-meta">${escapeHtml(display.set_code)} · ${escapeHtml(formatItemRarity(display))} · List ${formatDisplayPrice(display.sell_price)}</p>
              </div>
            </div>
            <div class="trade-cart-line-fields">
              <label>
                <span>Quantity (max ${maxQty})</span>
                <input type="number" min="1" max="${maxQty}" value="${line.quantity}" data-cart-qty="${line.item_id}" />
              </label>
              <label>
                <span>Comment (optional)</span>
                <textarea rows="2" maxlength="500" data-cart-comment="${line.item_id}">${escapeHtml(line.comment || "")}</textarea>
              </label>
              <label>
                ${renderOfferLabelHtml()}
                <div class="trade-price-input-wrap">
                  <input type="number" min="0" step="${offerInputStep()}" value="${escapeHtml(displayOfferValue(line.offer_price))}" data-cart-offer="${line.item_id}" placeholder="${escapeHtml(formatOfferPlaceholder(display.sell_price))}" />
                  <span class="trade-currency-suffix" data-cart-currency aria-hidden="true">${escapeHtml(getCurrencyCode())}</span>
                </div>
              </label>
            </div>
            <button type="button" class="secondary trade-cart-line-remove" data-cart-remove="${line.item_id}">Remove</button>
          </article>
        `;
      })
      .join("");
  }

  function setCartOpen(open) {
    const panel = $("#trade-cart-panel");
    const backdrop = $("#trade-cart-backdrop");
    const toggle = $("#trade-cart-toggle");
    if (!panel || !backdrop || !toggle) return;
    panel.classList.toggle("hidden", !open);
    backdrop.classList.toggle("hidden", !open);
    backdrop.hidden = !open;
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      renderCart();
      void ensureTurnstile();
    }
  }

  function setViewMode(mode) {
    state.view = mode;
    const listView = $("#trade-list-view");
    const tileView = $("#trade-tile-view");
    const listBtn = $("#trade-view-list");
    const tileBtn = $("#trade-view-tiles");
    if (listView) listView.classList.toggle("hidden", mode !== "list");
    if (tileView) tileView.classList.toggle("hidden", mode !== "tiles");
    if (listBtn) {
      listBtn.classList.toggle("active", mode === "list");
      listBtn.setAttribute("aria-pressed", mode === "list" ? "true" : "false");
    }
    if (tileBtn) {
      tileBtn.classList.toggle("active", mode === "tiles");
      tileBtn.setAttribute("aria-pressed", mode === "tiles" ? "true" : "false");
    }
  }

  function cardImgTag(url, alt) {
    if (!url) {
      return `<div class="card-img-placeholder" aria-hidden="true"></div>`;
    }
    return `<img src="${escapeHtml(url)}" alt="${escapeHtml(alt || "Card")}" loading="lazy" />`;
  }

  function renderTradeTableSkeletonRow() {
    return `
    <tr class="collection-row collection-row--skeleton" aria-hidden="true">
      <td class="collection-thumb"><div class="skeleton collection-skel-thumb"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--narrow"></div></td>
      <td><div class="skeleton collection-skel-badge"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--narrow"></div></td>
      <td><div class="skeleton collection-skel-cell"></div></td>
      <td><div class="skeleton skeleton-line collection-skel-line--narrow"></div></td>
      <td><div class="skeleton collection-skel-actions"></div></td>
    </tr>`;
  }

  function renderTradeTableLoadingSkeleton() {
    const rows = Array.from({ length: TRADE_TABLE_SKELETON_ROWS }, () =>
      renderTradeTableSkeletonRow()
    ).join("");
    return `<tr class="collection-skel-sr-only"><td colspan="8"><p class="sr-only" role="status">Loading cards…</p></td></tr>${rows}`;
  }

  function renderTradeTileLoadingSkeleton() {
    const tiles = Array.from({ length: TRADE_TILE_SKELETON_COUNT }, () => `
    <article class="card-tile card-tile--skeleton" aria-hidden="true">
      <div class="skeleton search-card-skeleton-img"></div>
      <div class="info">
        <div class="skeleton skeleton-line"></div>
        <div class="skeleton skeleton-line skeleton-line--short"></div>
      </div>
    </article>`).join("");
    return `<p class="sr-only" role="status">Loading cards…</p>${tiles}`;
  }

  function clearTradeLoading() {
    $("#trade-list-view")?.removeAttribute("aria-busy");
    $("#trade-grid")?.removeAttribute("aria-busy");
  }

  function showTradeLoading() {
    $("#trade-empty")?.classList.add("hidden");
    $("#trade-error")?.classList.add("hidden");
    $("#trade-pagination")?.classList.add("hidden");

    const stats = $("#trade-stats");
    if (stats) {
      stats.innerHTML =
        '<span class="skeleton skeleton-line trade-stats-skeleton" aria-hidden="true"></span>';
    }

    const tbody = $("#trade-tbody");
    const grid = $("#trade-grid");
    if (state.view === "tiles") {
      if (grid) {
        grid.innerHTML = renderTradeTileLoadingSkeleton();
        grid.setAttribute("aria-busy", "true");
      }
      if (tbody) tbody.innerHTML = "";
      $("#trade-list-view")?.removeAttribute("aria-busy");
    } else {
      if (tbody) {
        tbody.innerHTML = renderTradeTableLoadingSkeleton();
      }
      if (grid) grid.innerHTML = "";
      $("#trade-list-view")?.setAttribute("aria-busy", "true");
      $("#trade-grid")?.removeAttribute("aria-busy");
    }
  }

  function renderItems() {
    const tbody = $("#trade-tbody");
    const grid = $("#trade-grid");
    const empty = $("#trade-empty");
    const stats = $("#trade-stats");
    if (!tbody || !grid || !empty || !stats) return;

    stats.textContent = `${state.total} card${state.total === 1 ? "" : "s"} for trade`;
    if (!state.items.length) {
      tbody.innerHTML = "";
      grid.innerHTML = "";
      empty.classList.remove("hidden");
      clearTradeLoading();
      return;
    }
    empty.classList.add("hidden");

    tbody.innerHTML = state.items
      .map(
        (item) => `
        <tr>
          <td>${cardImgTag(item.image_url_small, item.card_name)}</td>
          <td>${escapeHtml(item.card_name)}</td>
          <td>${escapeHtml(item.set_code)}</td>
          <td>${rarityBadgeHtml(item)}</td>
          <td>${escapeHtml(item.condition || "—")}</td>
          <td>${item.trade_quantity}</td>
          <td>${formatDisplayPrice(item.sell_price)}</td>
          <td><button type="button" class="secondary" data-add-cart="${item.item_id}">Add</button></td>
        </tr>
      `
      )
      .join("");

    grid.innerHTML = state.items
      .map(
        (item) => `
        <article class="card-tile">
          <div class="card-tile-image-wrap">${cardImgTag(item.image_url_small, item.card_name)}</div>
          <div class="info">
            <div class="name" title="${escapeHtml(item.card_name)}">${escapeHtml(item.card_name)}</div>
            <div>${escapeHtml(item.set_code)} · ${rarityBadgeHtml(item)} · Qty ${item.trade_quantity}</div>
            <div>Price ${formatDisplayPrice(item.sell_price)}</div>
            <button type="button" class="secondary" data-add-cart="${item.item_id}">Add to cart</button>
          </div>
        </article>
      `
      )
      .join("");
    clearTradeLoading();
  }

  function renderPagination() {
    const el = $("#trade-pagination");
    if (!el) return;
    if (state.total <= state.limit) {
      el.classList.add("hidden");
      el.innerHTML = "";
      return;
    }
    el.classList.remove("hidden");
    const page = Math.floor(state.offset / state.limit) + 1;
    const pages = Math.max(1, Math.ceil(state.total / state.limit));
    el.innerHTML = `
      <button type="button" class="secondary" data-page-prev ${state.offset <= 0 ? "disabled" : ""}>Previous</button>
      <span>Page ${page} of ${pages}</span>
      <button type="button" class="secondary" data-page-next ${state.offset + state.limit >= state.total ? "disabled" : ""}>Next</button>
    `;
  }

  function showLoadError(message) {
    clearTradeLoading();
    const tbody = $("#trade-tbody");
    const grid = $("#trade-grid");
    if (tbody) tbody.innerHTML = "";
    if (grid) grid.innerHTML = "";
    const stats = $("#trade-stats");
    if (stats) stats.textContent = "";
    const err = $("#trade-error");
    if (err) {
      err.textContent = message;
      err.classList.remove("hidden");
    }
    const subtitle = $("#trade-subtitle");
    if (subtitle) subtitle.textContent = message;
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail;
      const message =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((row) => row.msg || row).join(", ")
            : "Request failed";
      throw new Error(message);
    }
    return data;
  }

  function currentQueryParams() {
    return {
      q: $("#trade-q")?.value.trim() || undefined,
      set_code: setCombobox.resolveValue() || undefined,
      rarity: rarityCombobox.resolveValue() || undefined,
      sort: $("#trade-sort")?.value || "set_code",
      sort_dir: readSortDir($("#trade-sort-dir")),
      limit: state.limit,
      offset: state.offset,
    };
  }

  function buildQuery(params) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        search.set(key, String(value));
      }
    });
    const qs = search.toString();
    return qs ? `?${qs}` : "";
  }

  function formatSetOptionLabel(set) {
    const name = (set.set_name || "").trim();
    const code = set.expansion_code;
    return name ? `${name} (${code})` : code;
  }

  function formatRarityOptionLabel(rarity) {
    return rarity.rarity_name || rarity.rarity_code || "—";
  }

  function expansionCodeFromSetCode(setCode) {
    const text = String(setCode ?? "").trim();
    const idx = text.indexOf("-");
    return idx > 0 ? text.slice(0, idx) : text;
  }

  function normalizeFiltersSets(data) {
    if (Array.isArray(data.sets) && data.sets.length) {
      return data.sets.map((set) => ({
        expansion_code: set.expansion_code,
        set_name: set.set_name || null,
      }));
    }
    if (Array.isArray(data.set_codes)) {
      return data.set_codes.map((code) => ({
        expansion_code: code,
        set_name: null,
      }));
    }
    return [];
  }

  function enrichSetsFromItems() {
    if (!state.items.length) return;
    const byCode = new Map(state.sets.map((set) => [set.expansion_code, { ...set }]));
    for (const item of state.items) {
      const code = expansionCodeFromSetCode(item.set_code);
      if (!code) continue;
      const existing = byCode.get(code);
      const setName = (item.set_name || "").trim() || null;
      if (!existing) {
        byCode.set(code, { expansion_code: code, set_name: setName });
      } else if (!existing.set_name && setName) {
        existing.set_name = setName;
      }
    }
    state.sets = [...byCode.values()].sort((a, b) =>
      (a.set_name || a.expansion_code).localeCompare(b.set_name || b.expansion_code, undefined, {
        sensitivity: "base",
      })
    );
  }

  function filterSetOptions(query) {
    const q = (query || "").trim().toLowerCase();
    if (!q) return state.sets.slice();
    return state.sets.filter((set) => {
      const label = formatSetOptionLabel(set).toLowerCase();
      const code = set.expansion_code.toLowerCase();
      const name = (set.set_name || "").toLowerCase();
      return label.includes(q) || code.includes(q) || name.includes(q);
    });
  }

  function filterRarityOptions(query) {
    const q = (query || "").trim().toLowerCase();
    if (!q) return state.rarities.slice();
    return state.rarities.filter((row) => {
      const label = formatRarityOptionLabel(row).toLowerCase();
      const code = row.rarity_code.toLowerCase();
      return label.includes(q) || code.includes(q);
    });
  }

  function resolveSetFilterValue(text, storedValue) {
    const trimmed = (text || "").trim();
    if (!trimmed) return "";
    const q = trimmed.toLowerCase();
    if (storedValue) {
      const stored = state.sets.find((set) => set.expansion_code === storedValue);
      if (stored && formatSetOptionLabel(stored) === trimmed) {
        return storedValue;
      }
    }
    for (const set of state.sets) {
      const label = formatSetOptionLabel(set);
      const code = set.expansion_code;
      const name = (set.set_name || "").trim();
      if (
        trimmed === label ||
        q === code.toLowerCase() ||
        (name && q === name.toLowerCase())
      ) {
        return code;
      }
    }
    const partial = filterSetOptions(trimmed);
    if (partial.length === 1) return partial[0].expansion_code;
    return "";
  }

  function resolveRarityFilterValue(text, storedValue) {
    const trimmed = (text || "").trim();
    if (!trimmed) return "";
    const q = trimmed.toLowerCase();
    if (storedValue) {
      const stored = state.rarities.find((row) => row.rarity_code === storedValue);
      if (stored && formatRarityOptionLabel(stored) === trimmed) {
        return storedValue;
      }
    }
    for (const row of state.rarities) {
      const label = formatRarityOptionLabel(row);
      if (trimmed === label || q === row.rarity_code.toLowerCase()) {
        return row.rarity_code;
      }
    }
    const partial = filterRarityOptions(trimmed);
    if (partial.length === 1) return partial[0].rarity_code;
    return "";
  }

  const setCombobox = createFilterCombobox({
    inputSel: "#trade-set-code",
    listSel: "#trade-set-list",
    allLabel: "All sets",
    emptyMessage: "No matching sets",
    getOptions: () => state.sets,
    getLabel: formatSetOptionLabel,
    getValue: (set) => set.expansion_code,
    filterOptions: filterSetOptions,
    resolveValue: resolveSetFilterValue,
  });

  const rarityCombobox = createFilterCombobox({
    inputSel: "#trade-rarity",
    listSel: "#trade-rarity-list",
    allLabel: "All rarities",
    emptyMessage: "No matching rarities",
    getOptions: () => state.rarities,
    getLabel: formatRarityOptionLabel,
    getValue: (row) => row.rarity_code,
    filterOptions: filterRarityOptions,
    resolveValue: resolveRarityFilterValue,
    renderOption: (row, label) =>
      `<span class="rarity-badge-option">${rarityBadgeHtml(row)}<span>${escapeHtml(label)}</span></span>`,
  });

  async function loadFilters() {
    if (!slug || state.filtersLoaded) return;
    const data = await api(`/api/public/trade/${encodeURIComponent(slug)}/filters`);

    const setInput = $("#trade-set-code");
    const currentSetValue = setInput?.dataset.filterValue || "";
    state.sets = normalizeFiltersSets(data);

    if (setInput) {
      if (currentSetValue && state.sets.some((set) => set.expansion_code === currentSetValue)) {
        setCombobox.select(currentSetValue);
      } else {
        setInput.value = setInput.value.trim();
        setInput.dataset.filterValue = "";
      }
    }

    const rarityInput = $("#trade-rarity");
    const currentRarityValue = rarityInput?.dataset.filterValue || "";
    state.rarities = data.rarities || [];
    if (rarityInput) {
      if (
        currentRarityValue &&
        state.rarities.some((row) => row.rarity_code === currentRarityValue)
      ) {
        rarityCombobox.select(currentRarityValue);
      } else {
        rarityInput.value = rarityInput.value.trim();
        rarityInput.dataset.filterValue = "";
      }
    }

    state.filtersLoaded = true;
  }

  async function loadItems() {
    if (!slug) {
      showLoadError("Missing trade list slug in URL.");
      return;
    }
    showTradeLoading();
    const params = currentQueryParams();
    const data = await api(
      `/api/public/trade/${encodeURIComponent(slug)}${buildQuery(params)}`
    );
    state.items = data.items || [];
    state.total = data.total || 0;
    state.limit = data.limit || state.limit;
    state.offset = data.offset || 0;
    state.sellerName = data.seller?.display_name || null;

    enrichSetsFromItems();

    const title = $("#trade-title");
    const subtitle = $("#trade-subtitle");
    if (title) {
      title.textContent = state.sellerName || "Trade list";
    }
    if (subtitle) {
      subtitle.textContent = state.sellerName
        ? "Browse cards available for trade"
        : "Cards available for trade";
    }
    document.title = `${state.sellerName || "Trade list"} — YGO Trade`;

    renderItems();
    renderPagination();
    renderCart();
  }

  function loadTurnstileScript() {
    return new Promise((resolve) => {
      if (window.turnstile) {
        resolve(true);
        return;
      }
      const timeoutId = setTimeout(() => resolve(false), 5000);
      const script = document.createElement("script");
      script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      script.async = true;
      script.defer = true;
      script.onload = () => {
        clearTimeout(timeoutId);
        resolve(true);
      };
      script.onerror = () => {
        clearTimeout(timeoutId);
        resolve(false);
      };
      document.head.appendChild(script);
    });
  }

  async function initTurnstile() {
    const scriptOk = await loadTurnstileScript();
    const container = $("#trade-turnstile");
    if (!container || !state.publicConfig.turnstile_site_key || !scriptOk || !window.turnstile) return;
    if (state.turnstileWidgetId != null) return;
    state.turnstileWidgetId = window.turnstile.render(container, {
      sitekey: state.publicConfig.turnstile_site_key,
    });
  }

  function ensureTurnstile() {
    if (!state.publicConfig.turnstile_site_key) return Promise.resolve();
    if (turnstileInitPromise) return turnstileInitPromise;
    turnstileInitPromise = initTurnstile().catch(() => {});
    return turnstileInitPromise;
  }

  function getTurnstileToken() {
    if (!state.publicConfig.turnstile_site_key) return null;
    if (!window.turnstile || state.turnstileWidgetId == null) return "";
    return window.turnstile.getResponse(state.turnstileWidgetId) || "";
  }

  function resetTurnstile() {
    if (window.turnstile && state.turnstileWidgetId != null) {
      window.turnstile.reset(state.turnstileWidgetId);
    }
  }

  async function submitOrder(event) {
    event.preventDefault();
    const errorEl = $("#trade-order-error");
    if (errorEl) {
      errorEl.classList.add("hidden");
      errorEl.textContent = "";
    }

    const cart = readCart();
    const lines = Object.values(cart).map((line) => ({
      item_id: line.item_id,
      quantity: Number(line.quantity),
      comment: line.comment || undefined,
      offer_price:
        line.offer_price === "" ||
        line.offer_price == null ||
        Number.isNaN(Number(line.offer_price))
          ? undefined
          : Number(line.offer_price),
    }));
    if (!lines.length) {
      if (errorEl) {
        errorEl.textContent = "Add at least one card to your cart.";
        errorEl.classList.remove("hidden");
      }
      return;
    }

    const consent = $("#trade-gdpr-consent");
    if (!consent?.checked) {
      if (errorEl) {
        errorEl.textContent = "Please accept the privacy policy to continue.";
        errorEl.classList.remove("hidden");
      }
      return;
    }

    const turnstileToken = getTurnstileToken();
    if (state.publicConfig.turnstile_site_key && !turnstileToken) {
      await ensureTurnstile();
    }

    const turnstileTokenAfterInit = getTurnstileToken();
    if (state.publicConfig.turnstile_site_key && !turnstileTokenAfterInit) {
      if (errorEl) {
        errorEl.textContent = "Please complete the captcha.";
        errorEl.classList.remove("hidden");
      }
      return;
    }

    const submitBtn = $("#trade-order-submit");
    if (submitBtn) submitBtn.disabled = true;

    try {
      const body = {
        lines,
        name: $("#trade-contact-name")?.value.trim() || undefined,
        email: $("#trade-contact-email")?.value.trim() || undefined,
        phone: $("#trade-contact-phone")?.value.trim() || undefined,
        address: $("#trade-contact-address")?.value.trim() || undefined,
        gdpr_consent: true,
      };
      if (turnstileTokenAfterInit) body.turnstile_token = turnstileTokenAfterInit;

      await api(`/api/public/trade/${encodeURIComponent(slug)}/order-request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      clearCart();
      $("#trade-order-form")?.reset();
      resetTurnstile();
      setCartOpen(false);
      showToast("Order request sent. The seller will contact you if needed.", "success");
    } catch (err) {
      if (errorEl) {
        errorEl.textContent = err.message || "Could not send order request.";
        errorEl.classList.remove("hidden");
      }
      resetTurnstile();
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  function bindEvents() {
    setCombobox.bindEvents();
    rarityCombobox.bindEvents();

    bindSortDirToggle($("#trade-sort-dir"));

    $("#trade-filter-form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      setCombobox.close();
      rarityCombobox.close();
      state.offset = 0;
      loadItems().catch((err) => showLoadError(err.message));
    });

    $("#trade-view-list")?.addEventListener("click", () => setViewMode("list"));
    $("#trade-view-tiles")?.addEventListener("click", () => setViewMode("tiles"));
    $("#trade-currency")?.addEventListener("change", (event) => {
      setCurrency(event.target.value);
    });

    document.body.addEventListener("click", (event) => {
      if (!event.target.closest("#trade-set-combobox") && setCombobox.isOpen()) {
        setCombobox.close();
      }
      if (!event.target.closest("#trade-rarity-combobox") && rarityCombobox.isOpen()) {
        rarityCombobox.close();
      }

      const infoBtn = event.target.closest(".trade-offer-info-btn");
      if (infoBtn) {
        event.preventDefault();
        event.stopPropagation();
        toggleOfferInfoPopover(infoBtn);
        return;
      }
      if (isOfferInfoPopoverOpen()) {
        const popover = $("#trade-offer-info-popover");
        if (!popover?.contains(event.target)) {
          closeOfferInfoPopover(true);
        }
      }

      const addBtn = event.target.closest("[data-add-cart]");
      if (addBtn) {
        openAddModal(Number(addBtn.dataset.addCart), addBtn);
        return;
      }
      const removeBtn = event.target.closest("[data-cart-remove]");
      if (removeBtn) {
        removeFromCart(Number(removeBtn.dataset.cartRemove));
        return;
      }
      if (event.target.closest("[data-page-prev]") && state.offset > 0) {
        state.offset = Math.max(0, state.offset - state.limit);
        loadItems().catch((err) => showLoadError(err.message));
        return;
      }
      if (
        event.target.closest("[data-page-next]") &&
        state.offset + state.limit < state.total
      ) {
        state.offset += state.limit;
        loadItems().catch((err) => showLoadError(err.message));
      }
    });

    document.body.addEventListener("input", (event) => {
      const qty = event.target.closest("[data-cart-qty]");
      if (qty) {
        const itemId = Number(qty.dataset.cartQty);
        const cart = readCart();
        const line = cart[itemId];
        const display = line ? cartLineDisplay(line) : {};
        let value = Number(qty.value) || 1;
        const maxQty = display.trade_quantity || value;
        value = Math.max(1, Math.min(maxQty, value));
        qty.value = String(value);
        updateCartLine(itemId, "quantity", value);
        return;
      }
      const comment = event.target.closest("[data-cart-comment]");
      if (comment) {
        updateCartLine(Number(comment.dataset.cartComment), "comment", comment.value);
        return;
      }
      const offer = event.target.closest("[data-cart-offer]");
      if (offer) {
        const parsed = parseOfferInput(offer.value);
        updateCartLine(
          Number(offer.dataset.cartOffer),
          "offer_price",
          offer.value.trim() === "" ? "" : parsed
        );
      }
    });

    $("#trade-cart-toggle")?.addEventListener("click", () => {
      const panel = $("#trade-cart-panel");
      setCartOpen(panel?.classList.contains("hidden"));
    });
    $("#trade-cart-close")?.addEventListener("click", () => setCartOpen(false));
    $("#trade-cart-backdrop")?.addEventListener("click", () => setCartOpen(false));
    $("#trade-order-form")?.addEventListener("submit", submitOrder);

    $("#trade-add-close")?.addEventListener("click", closeAddModal);
    $("#trade-add-cancel")?.addEventListener("click", closeAddModal);
    $("#trade-add-confirm")?.addEventListener("click", confirmAddToCart);
    $("#trade-add-modal")?.addEventListener("click", (event) => {
      if (event.target.id === "trade-add-modal") closeAddModal();
    });

    window.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (setCombobox.isOpen()) {
        setCombobox.close();
        return;
      }
      if (rarityCombobox.isOpen()) {
        rarityCombobox.close();
        return;
      }
      if (isOfferInfoPopoverOpen()) {
        closeOfferInfoPopover(true);
        return;
      }
      if (isAddModalOpen()) {
        closeAddModal();
        return;
      }
      const panel = $("#trade-cart-panel");
      if (panel && !panel.classList.contains("hidden")) {
        setCartOpen(false);
      }
    });

    window.addEventListener("resize", () => {
      if (isOfferInfoPopoverOpen() && offerInfoTrigger) {
        positionOfferInfoPopover(offerInfoTrigger);
      }
    });
  }

  async function init() {
    if (initStarted) return;
    initStarted = true;

    bindEvents();
    updateCartCount();
    setViewMode("list");
    state.currency = loadCurrencyPreference();
    syncCurrencySelect();
    syncCurrencySuffixes();

    const subtitle = $("#trade-subtitle");
    if (subtitle) subtitle.textContent = "Loading cards…";

    showTradeLoading();

    try {
      state.publicConfig = await api("/api/public/config");
      syncCurrencySelect();
      syncCurrencySuffixes();
      await Promise.all([loadFilters(), loadItems()]);
    } catch (err) {
      showLoadError(err.message || "Could not load trade list.");
    }
  }

init();
