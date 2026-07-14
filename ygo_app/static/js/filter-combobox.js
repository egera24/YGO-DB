function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function createFilterCombobox(config) {
  let activeIndex = -1;
  let searchTimer = null;

  function inputEl() {
    return document.querySelector(config.inputSel);
  }

  function listEl() {
    return document.querySelector(config.listSel);
  }

  function isOpen() {
    const list = listEl();
    return list && !list.hidden;
  }

  function close() {
    const list = listEl();
    const input = inputEl();
    if (!list || list.hidden) return;
    list.hidden = true;
    activeIndex = -1;
    if (input) input.setAttribute("aria-expanded", "false");
  }

  function labelForValue(value) {
    if (!value) return "";
    const option = config.getOptions().find((row) => config.getValue(row) === value);
    return option ? config.getLabel(option) : value;
  }

  function select(value) {
    const input = inputEl();
    if (!input) return;
    if (!value) {
      input.value = "";
      input.dataset.filterValue = "";
    } else {
      input.dataset.filterValue = value;
      input.value = labelForValue(value);
    }
    close();
    input.focus();
    config.onSelect?.(value);
  }

  function renderList(query) {
    const list = listEl();
    const input = inputEl();
    if (!list) return;

    const q = (query || "").trim();
    const matches = config.filterOptions(q);
    const parts = [];
    const optionClass = config.optionClass || "trade-filter-option";

    if (!q) {
      parts.push(
        `<button type="button" class="${optionClass}" role="option" data-filter-value="">${escapeHtml(config.allLabel)}</button>`
      );
    }

    matches.forEach((option) => {
      const value = config.getValue(option);
      const label = config.getLabel(option);
      parts.push(
        `<button type="button" class="${optionClass}" role="option" data-filter-value="${escapeHtml(value)}">${escapeHtml(label)}</button>`
      );
    });

    if (!parts.length) {
      parts.push(`<p class="trade-filter-empty">${escapeHtml(config.emptyMessage)}</p>`);
    }

    list.innerHTML = parts.join("");
    list.hidden = false;
    activeIndex = -1;
    if (input) input.setAttribute("aria-expanded", "true");
  }

  function open() {
    renderList(inputEl()?.value || "");
  }

  function refreshList(query) {
    renderList(query ?? inputEl()?.value ?? "");
  }

  function scheduleSearch(query) {
    if (!config.onSearch) return;
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      searchTimer = null;
      try {
        await config.onSearch(query);
        if (isOpen()) refreshList(query);
      } catch {
        /* ignore suggestion errors */
      }
    }, config.searchDebounceMs ?? 250);
  }

  function highlightOption(index) {
    const list = listEl();
    if (!list) return;
    const options = list.querySelectorAll(".trade-filter-option, .collection-filter-option");
    if (!options.length) return;
    const next = Math.max(0, Math.min(options.length - 1, index));
    activeIndex = next;
    options.forEach((el, i) => {
      el.classList.toggle("is-active", i === next);
      if (i === next) el.scrollIntoView({ block: "nearest" });
    });
  }

  function resolveValue() {
    const input = inputEl();
    if (!input) return "";
    const text = input.value.trim();
    const stored = input.dataset.filterValue || "";
    const resolved = config.resolveValue(text, stored);
    if (resolved) {
      input.dataset.filterValue = resolved;
      input.value = labelForValue(resolved);
    } else if (!text) {
      input.dataset.filterValue = "";
    }
    return resolved;
  }

  function bindEvents() {
    const input = inputEl();
    const list = listEl();
    if (!input || !list) return;

    input.addEventListener("focus", () => {
      open();
      scheduleSearch(input.value);
    });

    input.addEventListener("click", () => {
      if (!isOpen()) open();
    });

    input.addEventListener("input", () => {
      input.dataset.filterValue = "";
      if (config.onSearch) {
        scheduleSearch(input.value);
      } else {
        renderList(input.value);
      }
    });

    input.addEventListener("keydown", (event) => {
      const options = list.querySelectorAll(".trade-filter-option, .collection-filter-option");
      if (event.key === "Escape") {
        close();
        return;
      }
      if (!options.length) return;
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (!isOpen()) {
          open();
          return;
        }
        highlightOption(activeIndex + 1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        highlightOption(activeIndex <= 0 ? 0 : activeIndex - 1);
        return;
      }
      if (event.key === "Enter" && isOpen() && activeIndex >= 0) {
        event.preventDefault();
        const active = options[activeIndex];
        select(active?.dataset.filterValue ?? "");
      }
    });

    list.addEventListener("mousedown", (event) => {
      if (event.target.closest(".trade-filter-option, .collection-filter-option")) {
        event.preventDefault();
      }
    });

    list.addEventListener("click", (event) => {
      const option = event.target.closest(".trade-filter-option, .collection-filter-option");
      if (!option) return;
      event.preventDefault();
      select(option.dataset.filterValue ?? "");
    });
  }

  return { bindEvents, close, open, isOpen, resolveValue, select, refreshList };
}
