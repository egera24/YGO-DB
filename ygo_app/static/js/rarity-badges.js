/** Rarity badge metadata — keep in sync with ygo_app.rarity_registry.list_rarity_ui_metadata(). */

export const RARITY_UI_ROWS = [
  { sort_order: 1, name: "Common", code: "C", normalized_code: "(C)", display: "C", tone: "common" },
  { sort_order: 2, name: "Normal Rare", code: "N", normalized_code: "(N)", display: "N", tone: "rare" },
  { sort_order: 3, name: "Short Print", code: "SP", normalized_code: "(SP)", display: "SP", tone: "common" },
  { sort_order: 4, name: "Super Short Print", code: "SSP", normalized_code: "(SSP)", display: "SSP", tone: "common" },
  { sort_order: 5, name: "Normal Parallel Rare (Parallel Common)", code: "NPR", normalized_code: "(NPR)", display: "NPR", tone: "parallel-common" },
  { sort_order: 6, name: "Duel Terminal Normal Parallel Rare", code: "DNPR", normalized_code: "(DNPR)", display: "DNPR", tone: "parallel-common" },
  { sort_order: 7, name: "Rare", code: "R", normalized_code: "(R)", display: "R", tone: "rare" },
  { sort_order: 8, name: "Duel Terminal Normal Rare Parallel Rare", code: "DNRPR", normalized_code: "(DNRPR)", display: "DNRPR", tone: "parallel-rare" },
  { sort_order: 9, name: "Duel Terminal Rare Parallel Rare", code: "DRPR", normalized_code: "(DRPR)", display: "DRPR", tone: "parallel-rare" },
  { sort_order: 10, name: "Super Rare", code: "SR", normalized_code: "(SR)", display: "SR", tone: "super" },
  { sort_order: 11, name: "Holofoil Rare", code: "HFR", normalized_code: "(HFR)", display: "HFR", tone: "super" },
  { sort_order: 12, name: "Super Parallel Rare", code: "SPR", normalized_code: "(SPR)", display: "SPR", tone: "super-parallel" },
  { sort_order: 13, name: "Duel Terminal Super Parallel Rare", code: "DSPR", normalized_code: "(DSPR)", display: "DSPR", tone: "super-parallel" },
  { sort_order: 14, name: "Starfoil Rare", code: "SFR", normalized_code: "(SFR)", display: "SFR", tone: "starfoil" },
  { sort_order: 15, name: "Mosaic Rare", code: "MSR", normalized_code: "(MSR)", display: "MSR", tone: "mosaic" },
  { sort_order: 16, name: "Shatterfoil Rare", code: "SHR", normalized_code: "(SHR)", display: "SHR", tone: "shatterfoil" },
  { sort_order: 17, name: "Millennium Rare", code: "MR", normalized_code: "(MR)", display: "MR", tone: "millennium" },
  { sort_order: 18, name: "Ultra Rare", code: "UR", normalized_code: "(UR)", display: "UR", tone: "ultra" },
  { sort_order: 19, name: "Ultra Parallel Rare", code: "UPR", normalized_code: "(UPR)", display: "UPR", tone: "ultra" },
  { sort_order: 20, name: "Duel Terminal Ultra Parallel Rare", code: "DUPR", normalized_code: "(DUPR)", display: "DUPR", tone: "ultra" },
  { sort_order: 21, name: "Gold Rare", code: "GUR", normalized_code: "(GUR)", display: "GUR", tone: "gold" },
  { sort_order: 22, name: "Ultimate Rare", code: "UtR", normalized_code: "(UtR)", display: "UtR", tone: "ultimate" },
  { sort_order: 23, name: "Secret Rare", code: "ScR", normalized_code: "(ScR)", display: "ScR", tone: "secret" },
  { sort_order: 24, name: "Ultra Secret Rare", code: "UScR", normalized_code: "(UScR)", display: "UScR", tone: "secret" },
  { sort_order: 25, name: "Secret Ultra Rare", code: "ScUR", normalized_code: "(ScUR)", display: "ScUR", tone: "secret" },
  { sort_order: 26, name: "Duel Terminal Secret Parallel Rare", code: "DScPR", normalized_code: "(DScPR)", display: "DScPR", tone: "secret" },
  { sort_order: 27, name: "Gold Secret Rare", code: "GScR", normalized_code: "(GScR)", display: "GScR", tone: "gold" },
  { sort_order: 28, name: "Ghost/Gold Rare", code: "GGR", normalized_code: "(GGR)", display: "GGR", tone: "gold" },
  { sort_order: 29, name: "Premium Gold Rare", code: "PGR", normalized_code: "(PGR)", display: "PGR", tone: "gold" },
  { sort_order: 30, name: "Platinum Rare", code: "PL", normalized_code: "(PL)", display: "PL", tone: "platinum" },
  { sort_order: 31, name: "Collector's Rare", code: "CR", normalized_code: "(CR)", display: "CR", tone: "collectors" },
  { sort_order: 32, name: "Ultra Rare (Pharaoh's Rare)", code: "UR(PR)", normalized_code: "(UR(PR))", display: "UR(PR)", tone: "ultra" },
  { sort_order: 33, name: "Ghost Rare", code: "GR", normalized_code: "(GR)", display: "GR", tone: "ghost" },
  { sort_order: 34, name: "Starlight Rare", code: "SLR", normalized_code: "(SLR)", display: "SLR", tone: "starlight" },
  { sort_order: 35, name: "Prismatic Collector's Rare", code: "CR", normalized_code: "(CR)", display: "CR", tone: "prismatic-collectors" },
  { sort_order: 36, name: "Prismatic Ultimate Rare", code: "UtR", normalized_code: "(UtR)", display: "UtR", tone: "prismatic-ultimate" },
  { sort_order: 37, name: "Platinum Secret Rare", code: "PlScR", normalized_code: "(PlScR)", display: "PlScR", tone: "platinum-secret" },
  { sort_order: 38, name: "Extra Secret Rare", code: "EXSE", normalized_code: "(EXSE)", display: "EXSE", tone: "secret" },
  { sort_order: 39, name: "10000 Secret Rare", code: "10000 SE", normalized_code: "(10000 SE)", display: "10000 SE", tone: "10000-secret" },
  { sort_order: 40, name: "Prismatic Secret Rare", code: "PScR", normalized_code: "(PScR)", display: "PScR", tone: "prismatic-secret" },
  { sort_order: 41, name: "Quarter Century Secret Rare", code: "QCSR", normalized_code: "(QCSR)", display: "QCSR", tone: "quarter-century" },
  { sort_order: 42, name: "Grand Master Rare", code: "GMR", normalized_code: "(GMR)", display: "GMR", tone: "grand-master" },
];

export const RARITY_UI_BY_NAME = Object.fromEntries(
  RARITY_UI_ROWS.map((row) => [row.name, row])
);

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function normalizeRarityCode(value) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  if (text.startsWith("(") && text.endsWith(")")) return text;
  return `(${text})`;
}

function bareRarityCode(value) {
  const text = String(value ?? "").trim();
  if (text.startsWith("(") && text.endsWith(")")) return text.slice(1, -1).trim();
  return text;
}

function findRowByName(name) {
  const key = String(name ?? "").trim();
  if (!key) return null;
  return RARITY_UI_BY_NAME[key] || null;
}

function findRowByCode(code) {
  const normalized = normalizeRarityCode(code);
  const bare = bareRarityCode(code);
  if (!normalized && !bare) return null;
  const matches = RARITY_UI_ROWS.filter(
    (row) =>
      row.normalized_code === normalized ||
      row.code === bare ||
      row.normalized_code === normalizeRarityCode(bare)
  );
  if (!matches.length) return null;
  return matches.sort((a, b) => a.sort_order - b.sort_order)[0];
}

export function resolveRarityUi({ rarity_name, rarity_code, rarity_display } = {}) {
  if (rarity_name) {
    const byName = findRowByName(rarity_name);
    if (byName) return byName;
  }
  const codeCandidate = rarity_code || rarity_display;
  if (codeCandidate) {
    const byCode = findRowByCode(codeCandidate);
    if (byCode) return byCode;
  }
  if (rarity_name) {
    const byNameAsCode = findRowByCode(rarity_name);
    if (byNameAsCode) return byNameAsCode;
  }
  return null;
}

export function resolveRarityTone({ rarity_name, rarity_code, rarity_display } = {}) {
  return resolveRarityUi({ rarity_name, rarity_code, rarity_display })?.tone || "unknown";
}

export function rarityBadgeHtml({ rarity_name, rarity_code, rarity_display, set_rarity, set_rarity_code } = {}) {
  const name = rarity_name || set_rarity || null;
  const code = rarity_code || set_rarity_code || null;
  const display = rarity_display || null;
  const row = resolveRarityUi({ rarity_name: name, rarity_code: code, rarity_display: display });
  const label = display || row?.display || bareRarityCode(code) || bareRarityCode(name) || "";
  if (!label) return "—";
  const tone = row?.tone || "unknown";
  const fullName = name || row?.name || label;
  const longClass = label.length > 5 ? " rarity-badge--long" : "";
  return `<span class="rarity-badge rarity-badge--${escapeHtml(tone)}${longClass}" title="${escapeHtml(fullName)}" aria-label="${escapeHtml(fullName)}">${escapeHtml(label)}</span>`;
}
