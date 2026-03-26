const state = {
  catalog: null,
  selectedYears: new Set(),
  selectedTypes: new Set(),
  charts: [],
};

const form = document.getElementById("search-form");
const edrpousField = document.getElementById("edrpous");
const yearsField = document.getElementById("years");
const dateFromField = document.getElementById("date-from");
const dateToField = document.getElementById("date-to");
const reportTypesField = document.getElementById("report-types");
const includeDetailsField = document.getElementById("include-details");
const latestOnlyField = document.getElementById("latest-only");
const maxReportsField = document.getElementById("max-reports");
const loadCatalogButton = document.getElementById("load-catalog");
const downloadZipButton = document.getElementById("download-zip");
const resetButton = document.getElementById("reset-form");
const catalogStatus = document.getElementById("catalog-status");
const yearChips = document.getElementById("year-chips");
const typeChips = document.getElementById("type-chips");
const flash = document.getElementById("flash");
const summary = document.getElementById("summary");
const chartDashboard = document.getElementById("chart-dashboard");
const resultMeta = document.getElementById("result-meta");
const emptyState = document.getElementById("empty-state");
const tableWrapper = document.getElementById("table-wrapper");
const resultsBody = document.getElementById("results-body");
const dialog = document.getElementById("details-dialog");
const dialogTitle = document.getElementById("dialog-title");
const detailsJson = document.getElementById("details-json");
const closeDialogButton = document.getElementById("close-dialog");
const chartYearsCanvas = document.getElementById("chart-years");
const chartTypesCanvas = document.getElementById("chart-types");
const chartEdrpouCanvas = document.getElementById("chart-edrpou");
const chartYearTypeCanvas = document.getElementById("chart-year-type");

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

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
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

  catalogStatus.textContent = `Loaded catalog hints for EDRPOU ${catalog.edrpou}.`;
}

function buildSummaryCards(payload) {
  const summaryPayload = payload.summary || {};
  const totalReports = summaryPayload.total_reports ?? 0;
  const returnedReports = summaryPayload.returned_reports ?? (payload.items || []).length;
  const cards = [
    {
      label: "Matched Reports",
      value: totalReports,
      subvalue: `EDRPOU: ${(payload.query.edrpous || []).join(", ") || "not provided"}`,
    },
    {
      label: "Returned Rows",
      value: returnedReports,
      subvalue: totalReports > returnedReports ? `Visible table is limited from ${totalReports}.` : "Full result set is visible.",
    },
    {
      label: "Years",
      value: Object.keys(summaryPayload.by_year || {}).length,
      subvalue: joinKeyValue(summaryPayload.by_year),
    },
    {
      label: "Types",
      value: Object.keys(summaryPayload.by_type || {}).length,
      subvalue: joinKeyValue(summaryPayload.by_type, 3),
    },
    {
      label: "EDRPOU With Data",
      value: Object.keys(summaryPayload.by_edrpou || {}).length,
      subvalue: joinKeyValue(summaryPayload.by_edrpou),
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

function destroyCharts() {
  for (const chart of state.charts) {
    chart.destroy();
  }
  state.charts = [];
}

function hideCharts() {
  destroyCharts();
  chartDashboard.classList.add("hidden");
}

function chartPalette() {
  return [
    "#0f766e",
    "#155e75",
    "#db8a35",
    "#7c5c3b",
    "#8a4f7d",
    "#5c7c3b",
    "#2f5d8a",
    "#9a3412",
    "#4d7c0f",
    "#7c3aed",
  ];
}

function translucentPalette(alpha = 0.2) {
  return [
    `rgba(15, 118, 110, ${alpha})`,
    `rgba(21, 94, 117, ${alpha})`,
    `rgba(219, 138, 53, ${alpha})`,
    `rgba(124, 92, 59, ${alpha})`,
    `rgba(138, 79, 125, ${alpha})`,
    `rgba(92, 124, 59, ${alpha})`,
    `rgba(47, 93, 138, ${alpha})`,
    `rgba(154, 52, 18, ${alpha})`,
    `rgba(77, 124, 15, ${alpha})`,
    `rgba(124, 58, 237, ${alpha})`,
  ];
}

function registerChart(canvas, config) {
  const chart = new Chart(canvas.getContext("2d"), config);
  state.charts.push(chart);
}

function renderCharts(payload) {
  hideCharts();

  if (typeof Chart !== "function") {
    setFlash("Chart.js failed to load, analytics charts are unavailable.", "error");
    return;
  }

  const series = payload.summary?.series || {};
  const reportsByYear = series.reports_by_year || [];
  const reportsByType = series.reports_by_type || [];
  const reportsByEdrpouTop = series.reports_by_edrpou_top || [];
  const reportsByYearAndType = series.reports_by_year_and_type || {};

  if (!reportsByYear.length && !reportsByType.length && !reportsByEdrpouTop.length) {
    return;
  }

  Chart.defaults.font.family = 'Manrope, "Segoe UI", sans-serif';
  Chart.defaults.color = "#5d6a68";
  Chart.defaults.borderColor = "rgba(31, 42, 43, 0.08)";

  const colors = chartPalette();
  const softColors = translucentPalette();

  registerChart(chartYearsCanvas, {
    type: "bar",
    data: {
      labels: reportsByYear.map((item) => item.label),
      datasets: [
        {
          label: "Reports",
          data: reportsByYear.map((item) => item.count),
          borderColor: colors[0],
          backgroundColor: softColors[0],
          borderWidth: 2,
          borderRadius: 10,
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: { precision: 0 },
        },
      },
    },
  });

  registerChart(chartTypesCanvas, {
    type: "doughnut",
    data: {
      labels: reportsByType.map((item) => item.label),
      datasets: [
        {
          data: reportsByType.map((item) => item.count),
          borderWidth: 1,
          borderColor: "rgba(255, 252, 247, 0.96)",
          backgroundColor: colors.slice(0, reportsByType.length),
        },
      ],
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            boxWidth: 10,
            usePointStyle: true,
          },
        },
      },
    },
  });

  registerChart(chartEdrpouCanvas, {
    type: "bar",
    data: {
      labels: reportsByEdrpouTop.map((item) => item.label),
      datasets: [
        {
          label: "Reports",
          data: reportsByEdrpouTop.map((item) => item.count),
          borderColor: colors[1],
          backgroundColor: softColors[1],
          borderWidth: 2,
          borderRadius: 10,
        },
      ],
    },
    options: {
      indexAxis: "y",
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
      },
      scales: {
        x: {
          beginAtZero: true,
          ticks: { precision: 0 },
        },
      },
    },
  });

  registerChart(chartYearTypeCanvas, {
    type: "bar",
    data: {
      labels: reportsByYearAndType.labels || [],
      datasets: (reportsByYearAndType.datasets || []).map((dataset, index) => ({
        label: dataset.label,
        data: dataset.data,
        borderColor: colors[index % colors.length],
        backgroundColor: softColors[index % softColors.length],
        borderWidth: 1.5,
        borderRadius: 6,
      })),
    },
    options: {
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            boxWidth: 10,
            usePointStyle: true,
          },
        },
      },
      scales: {
        x: { stacked: true },
        y: {
          stacked: true,
          beginAtZero: true,
          ticks: { precision: 0 },
        },
      },
    },
  });

  chartDashboard.classList.remove("hidden");
}

function renderResults(payload) {
  buildSummaryCards(payload);
  renderCharts(payload);
  resultsBody.innerHTML = "";

  const items = payload.items || [];
  const totalReports = payload.summary?.total_reports ?? items.length;
  const returnedReports = payload.summary?.returned_reports ?? items.length;
  resultMeta.textContent = `Showing ${returnedReports} of ${totalReports} matched reports.`;

  if (!items.length) {
    emptyState.textContent = "No reports matched the current filters.";
    emptyState.classList.remove("hidden");
    tableWrapper.classList.add("hidden");
    hideCharts();
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
          <a class="row-link" href="https://spending.gov.ua/new/en/disposers/${encodeURIComponent(item.edrpou)}/reports" target="_blank" rel="noreferrer">Portal</a>
          <a class="row-link" href="/api/reports/${encodeURIComponent(item.edrpou)}/${encodeURIComponent(item.reportId)}/html" target="_blank" rel="noreferrer">HTML</a>
          <a class="row-link" href="/api/reports/${encodeURIComponent(item.edrpou)}/${encodeURIComponent(item.reportId)}/pdf" target="_blank" rel="noreferrer">PDF</a>
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
    setFlash("Enter at least one EDRPOU first.", "error");
    return;
  }

  catalogStatus.textContent = "Loading catalog hints...";
  loadCatalogButton.disabled = true;

  try {
    const response = await fetch(`/api/catalog/${encodeURIComponent(edrpous[0])}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to load catalog.");
    }
    renderCatalog(payload);
    setFlash("Catalog hints updated.", "info");
  } catch (error) {
    setFlash(error.message, "error");
    catalogStatus.textContent = "";
  } finally {
    loadCatalogButton.disabled = false;
  }
}

function buildSearchPayload() {
  const payload = {
    edrpous: parseList(edrpousField.value),
    years: parseList(yearsField.value)
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value)),
    report_types: parseList(reportTypesField.value),
    include_details: includeDetailsField.checked,
  };

  if (dateFromField.value) {
    payload.date_from = dateFromField.value;
  }
  if (dateToField.value) {
    payload.date_to = dateToField.value;
  }

  const maxReports = Number(maxReportsField.value);
  if (Number.isFinite(maxReports) && maxReports > 0) {
    payload.max_reports = maxReports;
  }

  return payload;
}

async function searchReports(event) {
  event.preventDefault();
  clearFlash();

  const payload = buildSearchPayload();
  if (!payload.edrpous.length) {
    setFlash("Specify at least one EDRPOU.", "error");
    return;
  }

  const submitButton = form.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  submitButton.textContent = "Searching...";
  resultMeta.textContent = "Running query...";

  try {
    const response = await fetch("/api/reports/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Search failed.");
    }
    renderResults(data);
    if (!flash.classList.contains("error")) {
      setFlash("Search completed.", "info");
    }
  } catch (error) {
    summary.innerHTML = "";
    resultsBody.innerHTML = "";
    tableWrapper.classList.add("hidden");
    emptyState.classList.remove("hidden");
    emptyState.textContent = "Failed to load results.";
    hideCharts();
    setFlash(error.message, "error");
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "Find Reports";
  }
}

async function downloadZip() {
  clearFlash();

  const payload = buildSearchPayload();
  if (!payload.edrpous.length) {
    setFlash("Specify at least one EDRPOU for export.", "error");
    return;
  }

  payload.include_details = true;
  payload.latest_only_per_edrpou = latestOnlyField.checked;

  if (!payload.report_types.length) {
    payload.report_types = ["2"];
    reportTypesField.value = payload.report_types.join(", ");
  }

  downloadZipButton.disabled = true;
  downloadZipButton.textContent = "Preparing ZIP...";

  try {
    const response = await fetch("/api/reports/export/zip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      let message = "Failed to generate ZIP.";
      try {
        const errorPayload = await response.json();
        message = errorPayload.detail || message;
      } catch (_error) {
        // Ignore parse failures and keep the fallback message.
      }
      throw new Error(message);
    }

    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="([^"]+)"/i);
    const fileName = match?.[1] || "reports-export.zip";

    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);

    setFlash("ZIP archive generated and downloaded.", "info");
  } catch (error) {
    setFlash(error.message, "error");
  } finally {
    downloadZipButton.disabled = false;
    downloadZipButton.textContent = "Download ZIP";
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
  hideCharts();
  emptyState.classList.remove("hidden");
  emptyState.textContent = "Enter filters and run a search.";
  resultMeta.textContent = "No query has been executed yet.";
  catalogStatus.textContent = "";
  clearFlash();
}

closeDialogButton.addEventListener("click", () => dialog.close());
loadCatalogButton.addEventListener("click", loadCatalog);
downloadZipButton.addEventListener("click", downloadZip);
resetButton.addEventListener("click", resetForm);
form.addEventListener("submit", searchReports);
