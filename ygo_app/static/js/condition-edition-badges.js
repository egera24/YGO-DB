/** Condition and edition badge helpers — shared by collection and trade UIs. */

export const COLLECTION_CONDITIONS = [
  { value: "Mint", label: "Mint (MT)", full: "Mint", short: "MT", tone: "mint" },
  { value: "NearMint", label: "Near Mint (NM)", full: "Near Mint", short: "NM", tone: "nearmint" },
  { value: "Excellent", label: "Excellent (EX)", full: "Excellent", short: "EX", tone: "excellent" },
  { value: "Good", label: "Good (GD)", full: "Good", short: "GD", tone: "good" },
  { value: "LightPlayed", label: "Light Played (LP)", full: "Light Played", short: "LP", tone: "lightplayed" },
  { value: "Played", label: "Played (PL)", full: "Played", short: "PL", tone: "played" },
  { value: "Poor", label: "Poor (PO)", full: "Poor", short: "PO", tone: "poor" },
];

export const COLLECTION_EDITIONS = ["Unlimited", "1st Edition", "Limited Edition"];

const EDITION_SHORT_LABELS = {
  Unlimited: "UE",
  "1st Edition": "1st",
  "Limited Edition": "LE",
};

const CONDITION_ALIAS_MAP = {
  mint: "Mint",
  mt: "Mint",
  nearmint: "NearMint",
  "near mint": "NearMint",
  "near-mint": "NearMint",
  nm: "NearMint",
  excellent: "Excellent",
  ex: "Excellent",
  good: "Good",
  gd: "Good",
  lightplayed: "LightPlayed",
  "light played": "LightPlayed",
  "light-played": "LightPlayed",
  lp: "LightPlayed",
  played: "Played",
  pl: "Played",
  poor: "Poor",
  po: "Poor",
};

const EDITION_ALIAS_MAP = {
  unlimited: "Unlimited",
  ue: "Unlimited",
  "1st edition": "1st Edition",
  "1st ed": "1st Edition",
  "1st ed.": "1st Edition",
  "first edition": "1st Edition",
  "first ed": "1st Edition",
  "first ed.": "1st Edition",
  "1st": "1st Edition",
  "1stedition": "1st Edition",
  "limited edition": "Limited Edition",
  "limited ed": "Limited Edition",
  "limited ed.": "Limited Edition",
  limited: "Limited Edition",
  le: "Limited Edition",
};

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function aliasKey(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

export function normalizeConditionValue(value) {
  if (value == null || value === "") return null;
  const stripped = String(value).trim();
  if (!stripped) return null;
  if (COLLECTION_CONDITIONS.some((c) => c.value === stripped)) return stripped;
  return CONDITION_ALIAS_MAP[aliasKey(stripped)] || stripped;
}

export function normalizeEditionValue(value) {
  if (value == null || value === "") return "Unlimited";
  const stripped = String(value).trim();
  if (!stripped) return "Unlimited";
  if (COLLECTION_EDITIONS.includes(stripped)) return stripped;
  return EDITION_ALIAS_MAP[aliasKey(stripped)] || stripped;
}

export function conditionLabel(value) {
  if (!value) return "—";
  const canonical = normalizeConditionValue(value);
  const match = COLLECTION_CONDITIONS.find((c) => c.value === canonical);
  return match ? match.label : canonical;
}

export function editionLabel(value) {
  if (!value) return "Unlimited";
  return normalizeEditionValue(value);
}

export function conditionBadgeHtml(value) {
  if (!value) return "—";
  const canonical = normalizeConditionValue(value);
  const match = COLLECTION_CONDITIONS.find((c) => c.value === canonical);
  const short = match ? match.short : canonical;
  const full = match ? match.full : canonical;
  const tone = match ? match.tone : "unknown";
  return `<span class="condition-badge condition-badge--${tone}" title="${escapeHtml(full)}" aria-label="${escapeHtml(full)}">${escapeHtml(short)}</span>`;
}

export function editionBadgeHtml(value) {
  const full = editionLabel(value);
  const short = EDITION_SHORT_LABELS[full] || full;
  return `<span class="edition-badge" title="${escapeHtml(full)}" aria-label="${escapeHtml(full)}">${escapeHtml(short)}</span>`;
}
