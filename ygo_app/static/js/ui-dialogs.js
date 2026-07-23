/** Shared app-styled confirm / prompt dialogs (replaces window.confirm / prompt). */

let syncModalOpenClass = () => {};
let confirmResolve = null;
let confirmTrigger = null;
let promptResolve = null;
let promptTrigger = null;
let listenersBound = false;

function $(sel) {
  return document.querySelector(sel);
}

function isVisible(id) {
  const el = $(id);
  return Boolean(el && !el.hidden);
}

export function isAppDialogOpen() {
  return isVisible("#app-confirm-modal") || isVisible("#app-prompt-modal");
}

export function isAppConfirmOpen() {
  return isVisible("#app-confirm-modal");
}

export function isAppPromptOpen() {
  return isVisible("#app-prompt-modal");
}

function closeConfirmModal(result = false) {
  const dlg = $("#app-confirm-modal");
  if (!dlg || dlg.hidden) {
    if (confirmResolve) {
      const resolve = confirmResolve;
      confirmResolve = null;
      resolve(result);
    }
    return;
  }
  dlg.hidden = true;
  syncModalOpenClass();
  (confirmTrigger instanceof HTMLElement ? confirmTrigger : null)?.focus?.();
  confirmTrigger = null;
  if (confirmResolve) {
    const resolve = confirmResolve;
    confirmResolve = null;
    resolve(result);
  }
}

function closePromptModal(result = null) {
  const dlg = $("#app-prompt-modal");
  if (!dlg || dlg.hidden) {
    if (promptResolve) {
      const resolve = promptResolve;
      promptResolve = null;
      resolve(result);
    }
    return;
  }
  dlg.hidden = true;
  syncModalOpenClass();
  (promptTrigger instanceof HTMLElement ? promptTrigger : null)?.focus?.();
  promptTrigger = null;
  if (promptResolve) {
    const resolve = promptResolve;
    promptResolve = null;
    resolve(result);
  }
}

/** Cancel the topmost app dialog (Escape / backdrop). Returns true if handled. */
export function cancelAppDialog() {
  if (isAppPromptOpen()) {
    closePromptModal(null);
    return true;
  }
  if (isAppConfirmOpen()) {
    closeConfirmModal(false);
    return true;
  }
  return false;
}

/**
 * @param {{ title?: string, message: string, confirmLabel?: string, cancelLabel?: string, danger?: boolean }} opts
 * @returns {Promise<boolean>}
 */
export function appConfirm({
  title = "Confirm",
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
} = {}) {
  const dlg = $("#app-confirm-modal");
  if (!dlg) return Promise.resolve(false);
  return new Promise((resolve) => {
    if (confirmResolve) {
      const prev = confirmResolve;
      confirmResolve = null;
      prev(false);
    }
    confirmResolve = resolve;
    confirmTrigger = document.activeElement;
    const titleEl = $("#app-confirm-title");
    if (titleEl) titleEl.textContent = title;
    const msgEl = $("#app-confirm-message");
    if (msgEl) msgEl.textContent = message ?? "";
    const cancelBtn = $("#app-confirm-cancel");
    if (cancelBtn) cancelBtn.textContent = cancelLabel;
    const okBtn = $("#app-confirm-ok");
    if (okBtn) {
      okBtn.textContent = confirmLabel;
      okBtn.classList.toggle("btn-danger", Boolean(danger));
    }
    dlg.hidden = false;
    syncModalOpenClass();
    (danger ? cancelBtn : okBtn)?.focus();
  });
}

/**
 * @param {{ title?: string, label?: string, defaultValue?: string, submitLabel?: string, maxLength?: number }} opts
 * @returns {Promise<string|null>}
 */
export function appPrompt({
  title = "Enter a value",
  label = "Name",
  defaultValue = "",
  submitLabel = "OK",
  maxLength = 128,
} = {}) {
  const dlg = $("#app-prompt-modal");
  if (!dlg) return Promise.resolve(null);
  return new Promise((resolve) => {
    if (promptResolve) {
      const prev = promptResolve;
      promptResolve = null;
      prev(null);
    }
    promptResolve = resolve;
    promptTrigger = document.activeElement;
    const titleEl = $("#app-prompt-title");
    if (titleEl) titleEl.textContent = title;
    const labelEl = $("#app-prompt-label");
    if (labelEl) labelEl.textContent = label;
    const input = $("#app-prompt-input");
    if (input) {
      input.value = defaultValue ?? "";
      input.maxLength = maxLength > 0 ? maxLength : 524288;
    }
    const submitBtn = $("#app-prompt-submit");
    if (submitBtn) submitBtn.textContent = submitLabel;
    dlg.hidden = false;
    syncModalOpenClass();
    input?.focus();
    input?.select();
  });
}

export function initAppDialogs(options = {}) {
  if (typeof options.syncModalOpenClass === "function") {
    syncModalOpenClass = options.syncModalOpenClass;
  }
  if (listenersBound) return;
  listenersBound = true;

  $("#app-confirm-close")?.addEventListener("click", () => closeConfirmModal(false));
  $("#app-confirm-cancel")?.addEventListener("click", () => closeConfirmModal(false));
  $("#app-confirm-ok")?.addEventListener("click", () => closeConfirmModal(true));
  $("#app-confirm-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#app-confirm-modal")) closeConfirmModal(false);
  });

  $("#app-prompt-close")?.addEventListener("click", () => closePromptModal(null));
  $("#app-prompt-cancel")?.addEventListener("click", () => closePromptModal(null));
  $("#app-prompt-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("#app-prompt-input");
    const value = (input?.value ?? "").trim();
    if (!value) {
      input?.focus();
      return;
    }
    closePromptModal(value);
  });
  $("#app-prompt-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#app-prompt-modal")) closePromptModal(null);
  });
}
