const SORT_DIR_ASC = "asc";
const SORT_DIR_DESC = "desc";

const SORT_DIR_SVG = {
  [SORT_DIR_ASC]:
    '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 8 4-4 4 4"/><path d="M7 4v16"/><path d="M11 12h4"/><path d="M11 16h7"/><path d="M11 20h10"/></svg>',
  [SORT_DIR_DESC]:
    '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 16 4 4 4-4"/><path d="M7 20V4"/><path d="M11 4h10"/><path d="M11 8h7"/><path d="M11 12h4"/></svg>',
};

const SORT_DIR_LABEL = {
  [SORT_DIR_ASC]: "Sort ascending",
  [SORT_DIR_DESC]: "Sort descending",
};

function normalizeSortDir(dir) {
  return dir === SORT_DIR_DESC ? SORT_DIR_DESC : SORT_DIR_ASC;
}

export function readSortDir(btn) {
  return normalizeSortDir(btn?.dataset.sortDir);
}

export function setSortDir(btn, dir) {
  if (!btn) return;
  const normalized = normalizeSortDir(dir);
  btn.dataset.sortDir = normalized;
  btn.innerHTML = SORT_DIR_SVG[normalized];
  const label = SORT_DIR_LABEL[normalized];
  btn.setAttribute("aria-label", label);
  btn.setAttribute("data-tooltip", label);
  btn.setAttribute("aria-pressed", normalized === SORT_DIR_DESC ? "true" : "false");
}

export function bindSortDirToggle(btn, onToggle) {
  if (!btn) return;
  if (btn.dataset.sortDirBound === "true") return;
  btn.dataset.sortDirBound = "true";
  setSortDir(btn, readSortDir(btn));
  btn.addEventListener("click", () => {
    const next = readSortDir(btn) === SORT_DIR_ASC ? SORT_DIR_DESC : SORT_DIR_ASC;
    setSortDir(btn, next);
    onToggle?.(next);
  });
}
