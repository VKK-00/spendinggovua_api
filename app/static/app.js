const state = {
  catalog: null,
  selectedYears: new Set(),
  selectedTypes: new Set(),
};

const form = document.getElementById("search-form");
const edrpousField = document.getElementById("edrpous");
const yearsField = document.getElementById("years");
const reportTypesField = document.getElementById("report-types");
const includeDetailsField = document.getElementById("include-details");
const maxReportsField = document.getElementById("max-reports");
const loadCatalogButton = document.getElementById("load-catalog");
const resetButton = document.getElementById("reset-form");
const catalogStatus = document.getElementById("catalog-status");
const yearChips = document.getElementById("year-chips");
const typeChips = document.getElementById("type-chips");
const flash = document.getElementById("flash");
const summary = document.getElementById("summary");
const resultMeta = document.getElementById("result-meta");
const emptyState = document.getElementById("empty-state");
const tableWrapper = document.getElementById("table-wrapper");
const resultsBody = document.getElementById("results-body");
const dialog = document.getElementById("details-dialog");
const dialogTitle = document.getElementById("dialog-title");
const detailsJson = document.getElementById("details-json");
const closeDialogButton = document.getElementById("close-dialog");

function parseList(value) {
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function setFlash(message, type = "info") {
  flash.textContent = message;
  flash.className = `flash ${type}`;
}

function clearFlash() {
  flash.textContent = "";
  flash.className = "flash hidden";
}

function syncFieldsFromState() {
  yearsField.value = Array.from(state.selectedYears).join(", ");
  reportTypesField.value = Array.from(state.selectedTypes).join(", ");
}

function toggleSelection(setRef, value) {
  if (setRef.has(value)) {
    setRef.delete(value);
  } else {
    setRef.add(value);
  }
  syncFieldsFromState();
}

function renderCatalog(catalog) {
  state.catalog = catalog;
  yearChips.innerHTML = "";
  typeChips.innerHTML = "";

  for (const year of catalog.available_years || []) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = String(year);
    chip.addEventListener("click", () => {
      toggleSelection(state.selectedYears, String(year));
      chip.classList.toggle("active", state.selectedYears.has(String(year)));
    });
    yearChips.appendChild(chip);
  }

  for (const item of catalog.report_type_groups || []) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.innerHTML = `<span>${escapeHtml(item.name)}</span><small>${item.reports_count}</small>`;
    chip.addEventListener("click", () => {
      toggleSelection(state.selectedTypes, item.name);
      chip.classList.toggle("active", state.selectedTypes.has(item.name));
    });
    typeChips.appendChild(chip);
  }

  catalogStatus.textContent = `Підказки завантажено для ЄДРПОУ ${catalog.edrpou}`;
}

function joinKeyValue(objectValue = {}, limit = 4) {
  const entries = Object.entries(objectValue);
  if (!entries.length) {
    return "—";
  }
  return entries
    .slice(0, limit)
    .map(([key, value]) => `${key}: ${value}`)
    .join(" · ");
}

function buildSummaryCards(payload) {
  const cards = [
    {
      label: "Знайдено звітів",
      value: payload.summary.total_reports ?? 0,
      subvalue: `ЄДРПОУ: ${(payload.query.edrpous || []).join(", ") || "не вказано"}`,
    },
    {
      label: "Роки",
      value: Object.keys(payload.summary.by_year || {}).length,
      subvalue: joinKeyValue(payload.summary.by_year),
    },
    {
      label: "Типи",
      value: Object.keys(payload.summary.by_type || {}).length,
      subvalue: joinKeyValue(payload.summary.by_type, 3),
    },
    {
      label: "ЄДРПОУ з даними",
      value: Object.keys(payload.summary.by_edrpou || {}).length,
      subvalue: joinKeyValue(payload.summary.by_edrpou),
    },
  ];

  summary.innerHTML = cards
    .map(
      (card) => `
        <article class="summary-card">
          <div class="label">${escapeHtml(card.label)}</div>
          <div class="value">${escapeHtml(String(card.value))}</div>
          <div class="subvalue">${escapeHtml(card.subvalue || "—")}</div>
        </article>
      `
    )
    .join("");
}

function renderResults(payload) {
  buildSummaryCards(payload);
  resultsBody.innerHTML = "";

  const items = payload.items || [];
  resultMeta.textContent = `Отримано ${items.length} записів`;

  if (!items.length) {
    emptyState.textContent = "За цими параметрами звітів не знайдено.";
    emptyState.classList.remove("hidden");
    tableWrapper.classList.add("hidden");
    return;
  }

  emptyState.classList.add("hidden");
  tableWrapper.classList.remove("hidden");

  for (const item of items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>
        <div class="row-title">${escapeHtml(item.edrpou || "—")}</div>
        <div class="row-subtle">reportId: ${escapeHtml(String(item.reportId || ""))}</div>
      </td>
      <td>
        <div class="row-title">${escapeHtml(item.reportTypeShortName || item.reportName || "—")}</div>
        <div class="row-subtle">${escapeHtml(item.reportName || "")}</div>
      </td>
      <td>${escapeHtml(item.year ? String(item.year) : "—")}</td>
      <td>${escapeHtml(item.period?.name || "—")}</td>
      <td>${escapeHtml(item.publishDate || "—")}</td>
      <td>${escapeHtml([item.budget, item.fund].filter(Boolean).join(" / ") || "—")}</td>
      <td>
        <div class="row-actions">
          <a class="row-link" href="https://spending.gov.ua/new/en/disposers/${encodeURIComponent(item.edrpou)}/reports" target="_blank" rel="noreferrer">Портал</a>
          ${item.details ? '<button type="button" class="ghost-button details-button">JSON</button>' : ""}
        </div>
      </td>
    `;

    const detailsButton = tr.querySelector(".details-button");
    if (detailsButton) {
      detailsButton.addEventListener("click", () => {
        dialogTitle.textContent = `${item.reportTypeShortName || item.reportName} / ${item.edrpou}`;
        detailsJson.textContent = JSON.stringify(item.details, null, 2);
        dialog.showModal();
      });
    }

    resultsBody.appendChild(tr);
  }
}

async function loadCatalog() {
  clearFlash();
  const edrpous = parseList(edrpousField.value);
  if (!edrpous.length) {
    setFlash("Спочатку введіть хоча б один ЄДРПОУ.", "error");
    return;
  }

  catalogStatus.textContent = "Завантаження підказок...";
  loadCatalogButton.disabled = true;

  try {
    const response = await fetch(`/api/catalog/${encodeURIComponent(edrpous[0])}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Не вдалося завантажити каталог.");
    }
    renderCatalog(payload);
    setFlash("Підказки по роках і типах форм оновлено.", "info");
  } catch (error) {
    setFlash(error.message, "error");
    catalogStatus.textContent = "";
  } finally {
    loadCatalogButton.disabled = false;
  }
}

async function searchReports(event) {
  event.preventDefault();
  clearFlash();

  const edrpous = parseList(edrpousField.value);
  if (!edrpous.length) {
    setFlash("Вкажіть хоча б один ЄДРПОУ.", "error");
    return;
  }

  const payload = {
    edrpous,
    years: parseList(yearsField.value).map((value) => Number(value)).filter((value) => Number.isFinite(value)),
    report_types: parseList(reportTypesField.value),
    include_details: includeDetailsField.checked,
  };

  const maxReports = Number(maxReportsField.value);
  if (Number.isFinite(maxReports) && maxReports > 0) {
    payload.max_reports = maxReports;
  }

  const submitButton = form.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  submitButton.textContent = "Пошук...";
  resultMeta.textContent = "Запит виконується...";

  try {
    const response = await fetch("/api/reports/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Пошук завершився з помилкою.");
    }
    renderResults(data);
    setFlash("Пошук завершено.", "info");
  } catch (error) {
    summary.innerHTML = "";
    resultsBody.innerHTML = "";
    tableWrapper.classList.add("hidden");
    emptyState.classList.remove("hidden");
    emptyState.textContent = "Не вдалося отримати результат.";
    setFlash(error.message, "error");
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Знайти звіти";
  }
}

function resetForm() {
  form.reset();
  state.catalog = null;
  state.selectedYears.clear();
  state.selectedTypes.clear();
  syncFieldsFromState();
  yearChips.innerHTML = "";
  typeChips.innerHTML = "";
  summary.innerHTML = "";
  resultsBody.innerHTML = "";
  tableWrapper.classList.add("hidden");
  emptyState.classList.remove("hidden");
  emptyState.textContent = "Введіть параметри й натисніть «Знайти звіти».";
  resultMeta.textContent = "Ще немає запиту.";
  catalogStatus.textContent = "";
  clearFlash();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

closeDialogButton.addEventListener("click", () => dialog.close());
loadCatalogButton.addEventListener("click", loadCatalog);
resetButton.addEventListener("click", resetForm);
form.addEventListener("submit", searchReports);
