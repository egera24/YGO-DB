/** Bulk collection spreadsheet modal (Tabulator). */

let deps = null;
let table = null;
let meta = null;
let loadedSetCode = "";
let dirtyRowIds = new Set();
let selectedRowIds = new Set();
let highlightedColumnFields = new Set();
let loadRequestSeq = 0;
let fillHandleEl = null;
let fillDrag = null;

const EDITABLE_FIELDS = new Set([
  "folder_name",
  "quantity",
  "trade_quantity",
  "condition",
  "edition",
  "language",
  "price_bought",
  "date_bought",
]);

const COLUMN_DEFS = [
  { field: "folder_name", title: "Folder", editable: true, minWidth: 100 },
  { field: "quantity", title: "Quantity", editable: true, hozAlign: "center", minWidth: 80 },
  { field: "trade_quantity", title: "Trade Quantity", editable: true, hozAlign: "center", minWidth: 100 },
  { field: "total_quantity", title: "Total Quantity", editable: false, hozAlign: "center", minWidth: 100 },
  { field: "card_name", title: "Card Name", editable: false, minWidth: 180 },
  { field: "expansion_code", title: "Set Code", editable: false, minWidth: 80 },
  { field: "set_name", title: "Set Name", editable: false, minWidth: 160 },
  { field: "set_code", title: "Card Number", editable: false, minWidth: 110 },
  { field: "rarity_name", title: "Rarity", editable: false, minWidth: 120 },
  { field: "condition", title: "Condition", editable: true, minWidth: 110 },
  { field: "edition", title: "Edition", editable: true, minWidth: 110 },
  { field: "language", title: "Language", editable: true, minWidth: 100 },
  { field: "price_bought", title: "Price Bought", editable: true, minWidth: 100 },
  { field: "date_bought", title: "Date Bought", editable: true, minWidth: 110 },
  { field: "owned", title: "owned", editable: false, hozAlign: "center", minWidth: 70 },
];

function $(sel) {
  return deps?.$?.(sel) ?? document.querySelector(sel);
}

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}

function cloneRow(row) {
  return JSON.parse(JSON.stringify(row));
}

function recomputeRow(row) {
  const qty = Number(row.quantity) || 0;
  const trade = Number(row.trade_quantity) || 0;
  row.total_quantity = qty + trade;
  row.owned = row.total_quantity > 0 ? "yes" : "no";
}

function rowIdentityKey(row) {
  if (row.collection_item_id) return `item:${row.collection_item_id}`;
  return `p:${row.printing_id}|${row.edition}|${row.condition}`;
}

function snapshotRow(row) {
  return {
    folder_name: row.folder_name || "",
    quantity: Number(row.quantity) || 0,
    trade_quantity: Number(row.trade_quantity) || 0,
    condition: row.condition,
    edition: row.edition,
    language: row.language,
    price_bought: row.price_bought ?? null,
    date_bought: row.date_bought || "",
  };
}

function rowMatchesSnapshot(row) {
  const snap = row._snapshot;
  if (!snap) return true;
  const current = snapshotRow(row);
  return JSON.stringify(current) === JSON.stringify(snap);
}

function markRowDirty(row) {
  if (!row?.row_id) return;
  if (rowMatchesSnapshot(row)) {
    dirtyRowIds.delete(row.row_id);
  } else {
    dirtyRowIds.add(row.row_id);
  }
  updateDirtyUi();
  if (table) {
    const tabRow = table.getRow(row.row_id);
    if (tabRow) {
      tabRow.getElement().classList.toggle("bulk-row-dirty", dirtyRowIds.has(row.row_id));
    }
  }
}

function updateDirtyUi() {
  const dirtyEl = $("#bulk-collection-dirty");
  const saveBtn = $("#bulk-collection-save");
  const hasDirty = dirtyRowIds.size > 0;
  dirtyEl?.classList.toggle("hidden", !hasDirty);
  if (saveBtn && loadedSetCode) saveBtn.disabled = !hasDirty;
}

function rowIsEligibleForSave(row) {
  const qty = Number(row.quantity) || 0;
  const trade = Number(row.trade_quantity) || 0;
  const base = row.baseline || {};
  const baseQty = Number(base.quantity) || 0;
  const baseTrade = Number(base.trade_quantity) || 0;
  if (qty > 0 || trade > 0) return true;
  if (baseQty > 0 || baseTrade > 0) return true;
  return false;
}

function syncTradeQuantity(sourceRow) {
  if (!table) return;
  const trade = Number(sourceRow.trade_quantity) || 0;
  const key = rowIdentityKey(sourceRow);
  table.getRows().forEach((tabRow) => {
    const data = tabRow.getData();
    if (rowIdentityKey(data) === key && data.row_id !== sourceRow.row_id) {
      data.trade_quantity = trade;
      recomputeRow(data);
      tabRow.update(data);
      markRowDirty(data);
    }
  });
}

function onCellEdited(cell) {
  const field = cell.getField();
  const row = cell.getRow().getData();
  if (field === "quantity" || field === "trade_quantity") {
    row[field] = Math.max(0, Number(row[field]) || 0);
  }
  if (field === "price_bought") {
    const raw = row.price_bought;
    row.price_bought = raw === "" || raw == null ? null : Number(raw);
  }
  recomputeRow(row);
  if (field === "trade_quantity") syncTradeQuantity(row);
  markRowDirty(row);
  cell.getRow().update(row);
}

function buildEditor(type, values) {
  if (type === "select") {
    return (cell, onRendered, success, cancel) => {
      const select = document.createElement("select");
      values.forEach((value) => {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = value === "NearMint" ? "Near Mint" : value;
        select.appendChild(opt);
      });
      select.value = cell.getValue() || values[0];
      select.style.width = "100%";
      select.style.boxSizing = "border-box";
      onRendered(() => select.focus());
      select.addEventListener("change", () => success(select.value));
      select.addEventListener("blur", () => success(select.value));
      select.addEventListener("keydown", (e) => {
        if (e.key === "Escape") cancel();
        if (e.key === "Enter") success(select.value);
      });
      return select;
    };
  }
  if (type === "number") {
    return "number";
  }
  if (type === "date") {
    return "date";
  }
  return "input";
}

function tabulatorColumns() {
  const conditions = meta?.conditions || ["NearMint"];
  const editions = meta?.editions || ["1st Edition"];
  const languages = meta?.languages || ["English"];

  return COLUMN_DEFS.map((col) => {
    const def = {
      title: col.title,
      field: col.field,
      minWidth: col.minWidth,
      hozAlign: col.hozAlign || "left",
      headerSort: true,
      headerSortTristate: true,
      headerFilter: col.editable || col.field === "owned" ? "input" : false,
      visible: true,
    };

    if (col.field === "rarity_name") {
      def.sorter = (a, b, aRow, bRow) => {
        return (aRow.getData().rarity_sort_order || 9999) - (bRow.getData().rarity_sort_order || 9999);
      };
    }

    if (!col.editable) {
      def.editor = false;
      return def;
    }

    if (col.field === "condition") {
      def.editor = buildEditor("select", conditions);
    } else if (col.field === "edition") {
      def.editor = buildEditor("select", editions);
    } else if (col.field === "language") {
      def.editor = buildEditor("select", languages);
    } else if (col.field === "quantity" || col.field === "trade_quantity") {
      def.editor = buildEditor("number");
      def.mutatorEdit = (value) => Math.max(0, Number(value) || 0);
    } else if (col.field === "price_bought") {
      def.editor = buildEditor("number");
    } else if (col.field === "date_bought") {
      def.editor = buildEditor("date");
    } else if (col.field === "folder_name") {
      def.editor = "input";
      def.editorParams = { elementAttributes: { list: "bulk-folder-datalist" } };
    } else {
      def.editor = "input";
    }

    return def;
  });
}

function destroyTable() {
  if (table) {
    table.destroy();
    table = null;
  }
  removeFillHandle();
}

function renderColumnMenu() {
  const menu = $("#bulk-collection-columns-menu");
  if (!menu || !table) return;
  menu.innerHTML = "";
  table.getColumns().forEach((column) => {
    const field = column.getField();
    const def = COLUMN_DEFS.find((c) => c.field === field);
    if (!def) return;
    const label = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = column.isVisible();
    cb.addEventListener("change", () => {
      if (cb.checked) column.show();
      else column.hide();
    });
    label.append(cb, document.createTextNode(` ${def.title}`));
    menu.appendChild(label);
  });
}

function toggleColumnHighlight(field) {
  if (!table) return;
  if (highlightedColumnFields.has(field)) highlightedColumnFields.delete(field);
  else highlightedColumnFields.add(field);
  table.getRows().forEach((row) => {
    row.getCells().forEach((cell) => {
      cell.getElement().classList.toggle(
        "bulk-col-highlight",
        highlightedColumnFields.has(cell.getField())
      );
    });
  });
}

function updateRowSelectionUi() {
  if (!table) return;
  table.getRows().forEach((row) => {
    row.getElement().classList.toggle("bulk-row-selected", selectedRowIds.has(row.getData().row_id));
  });
}

function duplicateSelectedRow() {
  if (!table || selectedRowIds.size !== 1) return;
  const sourceId = [...selectedRowIds][0];
  const source = table.getData().find((row) => row.row_id === sourceId);
  if (!source) return;
  const copy = cloneRow(source);
  copy.row_id = `dup-${crypto.randomUUID()}`;
  copy.collection_item_id = source.collection_item_id;
  copy.allocation_id = null;
  copy.folder_id = null;
  copy.folder_name = "";
  copy.quantity = 0;
  copy.trade_quantity = source.trade_quantity || 0;
  copy.is_client_duplicate = true;
  copy.baseline = {
    quantity: 0,
    trade_quantity: 0,
    folder_name: null,
    collection_item_id: source.collection_item_id || null,
  };
  recomputeRow(copy);
  copy._snapshot = snapshotRow(copy);
  table.addRow(copy, false).then((row) => {
    selectedRowIds.clear();
    selectedRowIds.add(copy.row_id);
    updateRowSelectionUi();
    row?.scrollTo?.();
  });
}

function ensureFolderDatalist() {
  let list = $("#bulk-folder-datalist");
  if (!list) {
    list = document.createElement("datalist");
    list.id = "bulk-folder-datalist";
    document.body.appendChild(list);
  }
  list.innerHTML = "";
  (meta?.folders || []).forEach((folder) => {
    const opt = document.createElement("option");
    opt.value = folder.name;
    list.appendChild(opt);
  });
}

function prepareRows(rows) {
  return rows.map((row) => {
    const prepared = { ...row };
    recomputeRow(prepared);
    prepared._snapshot = snapshotRow(prepared);
    return prepared;
  });
}

function buildTable(rows) {
  destroyTable();
  const gridEl = $("#bulk-collection-grid");
  if (!gridEl) return;

  ensureFolderDatalist();
  dirtyRowIds.clear();
  selectedRowIds.clear();
  highlightedColumnFields.clear();
  updateDirtyUi();

  const preparedRows = prepareRows(rows);

  table = new Tabulator(gridEl, {
    data: preparedRows,
    index: "row_id",
    layout: "fitDataStretch",
    height: "100%",
    selectableRows: false,
    columnDefaults: {
      headerSortClickElement: "icon",
    },
    columns: tabulatorColumns(),
    initialSort: [
      { column: "set_code", dir: "asc" },
      { column: "rarity_name", dir: "asc" },
    ],
    cellEdited: onCellEdited,
  });

  table.on("headerClick", (e, column) => {
    if (e.shiftKey) toggleColumnHighlight(column.getField());
  });

  table.on("rowClick", (e, row) => {
    const id = row.getData().row_id;
    if (e.ctrlKey || e.metaKey) {
      if (selectedRowIds.has(id)) selectedRowIds.delete(id);
      else selectedRowIds.add(id);
    } else {
      selectedRowIds.clear();
      selectedRowIds.add(id);
    }
    updateRowSelectionUi();
    setupFillHandle(row);
  });

  table.on("tableBuilt", () => {
    renderColumnMenu();
    $("#bulk-collection-columns-btn")?.removeAttribute("disabled");
    $("#bulk-collection-duplicate-row")?.removeAttribute("disabled");
    $("#bulk-collection-q")?.removeAttribute("disabled");
  });

  table.on("columnVisibilityChanged", renderColumnMenu);
}

function removeFillHandle() {
  fillHandleEl?.remove();
  fillHandleEl = null;
  fillDrag = null;
}

function setupFillHandle(row) {
  removeFillHandle();
  if (!row) return;
  const cell = row.getCells().find((c) => EDITABLE_FIELDS.has(c.getField()) && c.getColumn().getDefinition().editor);
  if (!cell) return;
  const cellEl = cell.getElement();
  const gridEl = $("#bulk-collection-grid");
  if (!cellEl || !gridEl) return;

  fillHandleEl = document.createElement("div");
  fillHandleEl.className = "bulk-collection-fill-handle";
  fillHandleEl.setAttribute("aria-hidden", "true");
  gridEl.appendChild(fillHandleEl);

  const reposition = () => {
    const gridRect = gridEl.getBoundingClientRect();
    const rect = cellEl.getBoundingClientRect();
    fillHandleEl.style.left = `${rect.right - gridRect.left - 5}px`;
    fillHandleEl.style.top = `${rect.bottom - gridRect.top - 5}px`;
  };
  reposition();

  fillHandleEl.addEventListener("mousedown", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const field = cell.getField();
    const startRow = row;
    const value = startRow.getData()[field];
    fillDrag = { field, startRow, value };

    const onMove = (moveEvent) => {
      if (!fillDrag || !table) return;
      const target = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY);
      const rowEl = target?.closest(".tabulator-row");
      if (!rowEl) return;
      const tabRow = table.getRows().find((r) => r.getElement() === rowEl);
      if (!tabRow) return;
      const startIdx = fillDrag.startRow.getPosition();
      const endIdx = tabRow.getPosition();
      const [from, to] = startIdx <= endIdx ? [startIdx, endIdx] : [endIdx, startIdx];
      table.getRows().forEach((r) => {
        const pos = r.getPosition();
        if (pos < from || pos > to) return;
        const data = r.getData();
        if (!EDITABLE_FIELDS.has(field)) return;
        data[field] = fillDrag.value;
        if (field === "quantity" || field === "trade_quantity") {
          data[field] = Math.max(0, Number(data[field]) || 0);
        }
        recomputeRow(data);
        if (field === "trade_quantity") syncTradeQuantity(data);
        r.update(data);
        markRowDirty(data);
      });
    };

    const onUp = () => {
      fillDrag = null;
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
}

async function loadMeta() {
  const res = await fetch(`${deps.API}/collection/bulk-grid/meta`, {
    headers: deps.authHeaders?.() || {},
  });
  if (!res.ok) throw new Error("Failed to load bulk grid metadata");
  meta = await res.json();
}

async function loadGrid(setCode) {
  const code = (setCode || "").trim();
  if (!code) {
    deps.showToast?.("Enter a set code first.", { variant: "error" });
    return;
  }

  const seq = ++loadRequestSeq;
  const loadingEl = $("#bulk-collection-loading");
  const emptyEl = $("#bulk-collection-empty");
  const gridEl = $("#bulk-collection-grid");
  loadingEl?.classList.remove("hidden");
  emptyEl?.classList.add("hidden");
  gridEl?.classList.add("hidden");

  try {
    if (!meta) await loadMeta();
    const params = new URLSearchParams({ set_code: code });
    const res = await fetch(`${deps.API}/collection/bulk-grid?${params}`, {
      headers: deps.authHeaders?.() || {},
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to load bulk grid");
    }
    if (seq !== loadRequestSeq) return;
    const payload = await res.json();
    loadedSetCode = payload.set_code;
    const subtitle = $("#bulk-collection-subtitle");
    if (subtitle) {
      subtitle.textContent = `${payload.total} printing rows loaded for ${payload.set_code}.`;
    }
    buildTable(payload.rows);
    gridEl?.classList.remove("hidden");
    $("#bulk-collection-save")?.removeAttribute("disabled");
    updateDirtyUi();
  } catch (err) {
    deps.showToast?.(err.message || "Failed to load bulk grid.", { variant: "error" });
  } finally {
    if (seq === loadRequestSeq) loadingEl?.classList.add("hidden");
  }
}

function identityKey(row) {
  return `${row.set_code}|${row.rarity_code}|${row.edition}|${row.condition}`;
}

function collectChanges() {
  if (!table) return [];
  const all = table.getData();
  const dirtyGroups = new Set();
  all.forEach((row) => {
    if (dirtyRowIds.has(row.row_id)) dirtyGroups.add(identityKey(row));
  });
  const changes = [];
  all.forEach((row) => {
    if (!dirtyGroups.has(identityKey(row))) return;
    if (!rowIsEligibleForSave(row)) return;
    changes.push({
      row_id: row.row_id,
      printing_id: row.printing_id,
      collection_item_id: row.collection_item_id,
      allocation_id: row.allocation_id,
      set_code: row.set_code,
      rarity_code: row.rarity_code,
      folder_name: row.folder_name || null,
      quantity: Number(row.quantity) || 0,
      trade_quantity: Number(row.trade_quantity) || 0,
      condition: row.condition,
      edition: row.edition,
      language: row.language,
      price_bought: row.price_bought ?? null,
      date_bought: row.date_bought || todayIsoDate(),
      baseline: row.baseline,
      is_client_duplicate: Boolean(row.is_client_duplicate),
    });
  });
  return changes;
}

async function saveGrid() {
  const changes = collectChanges();
  if (!changes.length) {
    deps.showToast?.("No quantity changes to save.", { variant: "error" });
    return;
  }

  for (const change of changes) {
    const qty = change.quantity;
    const trade = change.trade_quantity;
    if (qty > 0 && !(change.folder_name || "").trim()) {
      deps.showToast?.(`Folder name is required for ${change.set_code}.`, { variant: "error" });
      return;
    }
    if (qty <= 0 && trade <= 0) continue;
    if (qty <= 0 && trade > 0) {
      deps.showToast?.(`Quantity is required when setting trade qty for ${change.set_code}.`, {
        variant: "error",
      });
      return;
    }
  }

  const saveBtn = $("#bulk-collection-save");
  saveBtn?.setAttribute("disabled", "disabled");
  try {
    const res = await fetch(`${deps.API}/collection/bulk-grid/save`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(deps.authHeaders?.() || {}),
      },
      body: JSON.stringify({ set_code: loadedSetCode, changes }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Save failed");
    }
    const result = await res.json();
    const parts = [];
    if (result.printings_updated) parts.push(`${result.printings_updated} printings updated`);
    if (result.quantities_added) parts.push(`${result.quantities_added} quantities added`);
    if (result.trade_quantities_added) {
      parts.push(`${result.trade_quantities_added} trade quantities added`);
    }
    deps.showToast?.(
      parts.length
        ? `${parts.join(" — ")} to your collection.`
        : "Collection updated.",
      { variant: "success", durationMs: 5000 }
    );
    deps.onSaved?.();
    await loadGrid(loadedSetCode);
  } catch (err) {
    deps.showToast?.(err.message || "Save failed.", { variant: "error" });
    updateDirtyUi();
  }
}

function hasUnsavedChanges() {
  return dirtyRowIds.size > 0;
}

export function openBulkCollectionModal() {
  const dlg = $("#bulk-collection-modal");
  if (!dlg) return;
  dlg.hidden = false;
  $("#bulk-collection-set-code")?.focus();
}

export function closeBulkCollectionModal(force = false) {
  if (!force && hasUnsavedChanges()) {
    if (!confirm("Discard unsaved bulk collection changes?")) return;
  }
  const dlg = $("#bulk-collection-modal");
  if (dlg) dlg.hidden = true;
  destroyTable();
  loadedSetCode = "";
  dirtyRowIds.clear();
  $("#bulk-collection-columns-menu")?.classList.add("hidden");
  const qInput = $("#bulk-collection-q");
  if (qInput) qInput.value = "";
}

export function initBulkCollection(options) {
  deps = options;

  $("#bulk-collection-btn")?.classList.toggle("hidden", !deps.isLoggedIn?.());

  $("#bulk-collection-btn")?.addEventListener("click", () => {
    openBulkCollectionModal();
  });

  $("#bulk-collection-close")?.addEventListener("click", () => closeBulkCollectionModal());

  $("#bulk-collection-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#bulk-collection-modal")) closeBulkCollectionModal();
  });

  $("#bulk-collection-load")?.addEventListener("click", () => {
    const code = $("#bulk-collection-set-code")?.value;
    if (hasUnsavedChanges() && !confirm("Reload and discard unsaved changes?")) return;
    loadGrid(code);
  });

  $("#bulk-collection-set-code")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      $("#bulk-collection-load")?.click();
    }
  });

  $("#bulk-collection-save")?.addEventListener("click", saveGrid);

  $("#bulk-collection-duplicate-row")?.addEventListener("click", duplicateSelectedRow);

  $("#bulk-collection-q")?.addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    if (!table) return;
    if (!q) {
      table.clearFilter(true);
      return;
    }
    table.setFilter((row) => {
      return COLUMN_DEFS.some((col) => {
        const val = row[col.field];
        return val != null && String(val).toLowerCase().includes(q);
      });
    });
  });

  const columnsBtn = $("#bulk-collection-columns-btn");
  const columnsMenu = $("#bulk-collection-columns-menu");
  columnsBtn?.addEventListener("click", () => {
    const open = columnsMenu?.classList.toggle("hidden");
    columnsBtn.setAttribute("aria-expanded", open ? "false" : "true");
    if (!open) renderColumnMenu();
  });

  document.addEventListener("click", (e) => {
    if (!columnsMenu || columnsMenu.classList.contains("hidden")) return;
    if (e.target === columnsBtn || columnsBtn?.contains(e.target)) return;
    if (columnsMenu.contains(e.target)) return;
    columnsMenu.classList.add("hidden");
    columnsBtn?.setAttribute("aria-expanded", "false");
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const dlg = $("#bulk-collection-modal");
    if (dlg?.hidden) return;
    closeBulkCollectionModal();
  });
}

export function refreshBulkCollectionAuthVisibility(loggedIn) {
  $("#bulk-collection-btn")?.classList.toggle("hidden", !loggedIn);
}
