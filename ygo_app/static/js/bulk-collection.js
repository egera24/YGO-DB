/** Bulk collection spreadsheet modal (Tabulator). */

let deps = null;
let table = null;
let meta = null;
let loadedSetCode = "";
let dirtyRowIds = new Set();
let rangeAnchorCell = null;
let loadRequestSeq = 0;
let fillHandleEl = null;
let fillDrag = null;
let pendingTypeahead = null;

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

const FILLABLE_FIELDS = EDITABLE_FIELDS;

const CLEARABLE_FIELDS = new Set([
  "folder_name",
  "quantity",
  "trade_quantity",
  "price_bought",
  "date_bought",
]);

const HEADER_FILTER_FIELDS = new Set([
  "folder_name",
  "quantity",
  "trade_quantity",
  "card_name",
  "condition",
  "edition",
  "language",
  "price_bought",
  "date_bought",
  "owned",
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

function applyFieldValue(row, field, value) {
  if (field === "folder_name" || field === "date_bought") {
    row[field] = value ?? "";
  } else if (field === "price_bought") {
    row.price_bought = value == null || value === "" ? null : Number(value);
  } else if (field === "quantity" || field === "trade_quantity") {
    row[field] = Math.max(0, Number(value) || 0);
  } else {
    row[field] = value;
  }
  recomputeRow(row);
  if (field === "trade_quantity") syncTradeQuantity(row);
}

function onCellEdited(cell) {
  const field = cell.getField();
  const row = cell.getRow().getData();
  applyFieldValue(row, field, row[field]);
  markRowDirty(row);
  cell.getRow().update(row);
}

function listEditorValues(values, labelFor = (value) => value) {
  return values.map((value) => ({ label: labelFor(value), value }));
}

function buildEditor(type) {
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
      headerFilter: HEADER_FILTER_FIELDS.has(col.field) ? "input" : false,
      visible: true,
    };

    if (col.field === "rarity_name") {
      def.sorter = (a, b, aRow, bRow) => {
        return (aRow.getData().rarity_sort_order || 9999) - (bRow.getData().rarity_sort_order || 9999);
      };
    }

    if (col.field === "total_quantity") {
      def.editor = false;
      def.cssClass = "bulk-cell-computed";
      return def;
    }

    if (!col.editable) {
      def.editor = false;
      return def;
    }

    if (col.field === "condition") {
      def.editor = "list";
      def.editorParams = {
        values: listEditorValues(conditions, (value) =>
          value === "NearMint" ? "Near Mint" : value
        ),
      };
    } else if (col.field === "edition") {
      def.editor = "list";
      def.editorParams = { values: listEditorValues(editions) };
    } else if (col.field === "language") {
      def.editor = "list";
      def.editorParams = { values: listEditorValues(languages) };
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
  rangeAnchorCell = null;
  pendingTypeahead = null;
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

function getSingleSelectedRow() {
  if (!table) return null;
  const ranges = table.getRanges?.() || [];
  if (ranges.length !== 1) return null;
  const rows = ranges[0].getRows();
  if (rows.length !== 1) return null;
  return rows[0];
}

function getSingleSelectedRowData() {
  return getSingleSelectedRow()?.getData() ?? null;
}

function clearFieldValue(row, field) {
  if (field === "folder_name" || field === "date_bought") {
    applyFieldValue(row, field, "");
  } else if (field === "price_bought") {
    applyFieldValue(row, field, null);
  } else {
    applyFieldValue(row, field, 0);
  }
}

function clearSelectedValues() {
  if (!table) return;
  const range = table.getRanges?.()?.[0];
  if (!range) return;

  const rows = range.getRows();
  const cols = range.getColumns();

  for (const tabRow of rows) {
    const data = tabRow.getData();
    let rowChanged = false;
    for (const col of cols) {
      const field = col.getField();
      if (!field || !CLEARABLE_FIELDS.has(field)) continue;
      clearFieldValue(data, field);
      rowChanged = true;
    }
    if (!rowChanged) continue;
    tabRow.update(data);
    markRowDirty(data);
  }
}

function getFocusedEditableCell() {
  const range = table?.getRanges?.()?.[0];
  if (!range) return null;
  const rows = range.getRows();
  const cols = range.getColumns();
  if (rows.length !== 1 || cols.length !== 1) return null;
  const field = cols[0].getField();
  if (!field || field === "_rownum" || !EDITABLE_FIELDS.has(field)) return null;
  return rows[0].getCell(field);
}

function injectPendingTypeahead(cell) {
  if (!pendingTypeahead) return;
  const key = pendingTypeahead;
  pendingTypeahead = null;
  requestAnimationFrame(() => {
    const el = cell.getElement()?.querySelector("input, textarea");
    if (!el) return;
    el.value = key;
    el.focus();
    el.select?.();
  });
}

function onBulkGridKeydown(e) {
  const dlg = $("#bulk-collection-modal");
  if (!dlg || dlg.hidden) return;
  if (!table) return;
  if (e.target.closest(".tabulator-editing")) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;

  if (e.key === "Delete" || e.key === "Backspace") {
    e.preventDefault();
    clearSelectedValues();
    return;
  }

  if (e.key.length !== 1) return;

  const cell = getFocusedEditableCell();
  if (!cell) return;
  const field = cell.getField();
  if (field === "condition" || field === "edition" || field === "language") return;

  e.preventDefault();
  pendingTypeahead = e.key;
  cell.edit();
}

function updateDuplicateRowUi() {
  const btn = $("#bulk-collection-duplicate-row");
  if (!btn || !table) return;
  btn.disabled = !getSingleSelectedRowData();
}

function duplicateSelectedRow() {
  const sourceRow = getSingleSelectedRow();
  const source = sourceRow?.getData();
  if (!table || !sourceRow || !source) return;
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
  sourceRow.addRow(copy, true).then((row) => {
    table.getRanges().forEach((range) => range.remove());
    const anchorCell =
      row?.getCells?.().find((cell) => cell.getField() === "folder_name") || row?.getCells?.()[0];
    if (anchorCell) {
      table.addRange(anchorCell, anchorCell);
      rangeAnchorCell = anchorCell;
    }
    updateDuplicateRowUi();
    repositionFillHandle();
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

function onRangeChanged() {
  repositionFillHandle();
  updateDuplicateRowUi();
}

function buildTable(rows) {
  destroyTable();
  const gridEl = $("#bulk-collection-grid");
  if (!gridEl) return;

  ensureFolderDatalist();
  dirtyRowIds.clear();
  updateDirtyUi();

  const preparedRows = prepareRows(rows);

  table = new Tabulator(gridEl, {
    data: preparedRows,
    index: "row_id",
    layout: "fitDataStretch",
    height: "100%",
    popupContainer: "#bulk-collection-card",
    clipboard: "copy",
    clipboardCopyRowRange: "range",
    clipboardCopyStyled: false,
    clipboardCopyConfig: {
      rowHeaders: false,
      columnHeaders: false,
      formatCells: false,
    },
    selectableRange: 1,
    selectableRangeColumns: true,
    selectableRangeRows: true,
    selectableRangeClearCells: false,
    editTriggerEvent: "dblclick",
    rowHeader: {
      resizable: false,
      frozen: true,
      width: 44,
      hozAlign: "center",
      formatter: "rownum",
      field: "_rownum",
      headerSort: false,
      editor: false,
    },
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

  table.on("cellEditing", (cell) => {
    injectPendingTypeahead(cell);
  });

  table.on("cellClick", (e, cell) => {
    if (cell.getField() === "_rownum") return;
    if (e.shiftKey && rangeAnchorCell) {
      table.getRanges().forEach((range) => range.remove());
      table.addRange(rangeAnchorCell, cell);
    } else if (!e.shiftKey) {
      rangeAnchorCell = cell;
    }
    onRangeChanged();
    const field = cell.getField();
    if (!e.shiftKey && (field === "quantity" || field === "trade_quantity")) {
      cell.edit();
    }
  });

  table.on("rangeAdded", onRangeChanged);
  table.on("rangeRemoved", onRangeChanged);

  table.on("tableBuilt", () => {
    renderColumnMenu();
    $("#bulk-collection-columns-btn")?.removeAttribute("disabled");
    updateDuplicateRowUi();
  });

  table.on("columnVisibilityChanged", renderColumnMenu);
}

function removeFillHandle() {
  fillHandleEl?.remove();
  fillHandleEl = null;
  fillDrag = null;
}

function getFillHandleCell(range) {
  const rows = range.getRows();
  const cols = range.getColumns();
  if (!rows.length || !cols.length) return null;
  const bottomRow = rows[rows.length - 1];
  for (let i = cols.length - 1; i >= 0; i--) {
    const col = cols[i];
    const field = col.getField();
    if (!field || field === "_rownum") continue;
    if (FILLABLE_FIELDS.has(field) && col.getDefinition().editor) {
      return bottomRow.getCell(field);
    }
  }
  return null;
}

function attachFillHandleDrag(cell) {
  if (!fillHandleEl) return;
  fillHandleEl.addEventListener("mousedown", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const field = cell.getField();
    const startRow = cell.getRow();
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
        if (!FILLABLE_FIELDS.has(field)) return;
        applyFieldValue(data, field, fillDrag.value);
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

function repositionFillHandle() {
  removeFillHandle();
  if (!table) return;
  const ranges = table.getRanges?.() || [];
  if (!ranges.length) return;

  const cell = getFillHandleCell(ranges[0]);
  if (!cell) return;

  const cellEl = cell.getElement();
  const gridEl = $("#bulk-collection-grid");
  if (!cellEl || !gridEl) return;

  fillHandleEl = document.createElement("div");
  fillHandleEl.className = "bulk-collection-fill-handle";
  fillHandleEl.setAttribute("aria-hidden", "true");
  gridEl.appendChild(fillHandleEl);

  const gridRect = gridEl.getBoundingClientRect();
  const rect = cellEl.getBoundingClientRect();
  fillHandleEl.style.left = `${rect.right - gridRect.left - 5}px`;
  fillHandleEl.style.top = `${rect.bottom - gridRect.top - 5}px`;

  attachFillHandleDrag(cell);
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
      subtitle.textContent = `${payload.total} printing rows loaded for ${payload.set_code}. Type to edit · Click quantity to edit · Double-click list cells · Shift+click to extend · Delete to clear · Ctrl+C to copy.`;
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
}

export function initBulkCollection(options) {
  deps = options;

  $("#bulk-collection-btn")?.addEventListener("click", () => {
    deps.closeCollectionToolbarMenus?.();
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
    const dlg = $("#bulk-collection-modal");
    if (dlg?.hidden) return;
    if (e.key === "Escape") {
      closeBulkCollectionModal();
      return;
    }
    onBulkGridKeydown(e);
  });
}

export function refreshBulkCollectionAuthVisibility(_loggedIn) {
  /* Collection toolbar visibility is handled in updateAuthUI(). */
}
