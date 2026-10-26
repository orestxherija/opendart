// Peer comparison app for compare_companies: one row per company, sortable metric columns with
// each column's highest and lowest value marked, companies left out, and a metric-set switch.

const TOOL = "compare_companies";
const METRIC_SETS = [["key_accounts", "Key accounts"], ["ratios", "Ratios"], ["both", "Both"]];
const COMPANY = -1;

// sort: null keeps the server's order; otherwise { column: COMPANY or a column index, descending }.
const state = { args: {}, data: null, sort: null, loading: false };

// For example "FY2025, consolidated basis, 3 companies".
function scope(data) {
  const count = typeof data.company_count === "number" ? data.company_count : (data.rows || []).length;
  const parts = [data.basis + " basis", plural(count, "company", "companies")];
  if (data.fiscal_year != null && data.period) {
    parts.unshift(data.period === "FY" ? "FY" + data.fiscal_year : data.period + " " + data.fiscal_year);
  }
  return parts.join(", ");
}

// Each column's highest and lowest value, when at least two companies differ.
function extremesOf(data) {
  return (data.columns || []).map((_, index) => {
    const values = (data.rows || []).map((row) => (row.values || [])[index])
      .filter((value) => typeof value === "number" && Number.isFinite(value));
    if (values.length < 2) return null;
    const high = Math.max(...values);
    const low = Math.min(...values);
    return high === low ? null : { high, low };
  });
}

// Missing values sort last in both directions.
function compareValues(a, b, descending) {
  const missingA = a === undefined || a === null;
  const missingB = b === undefined || b === null;
  if (missingA || missingB) return Number(missingA) - Number(missingB);
  const order = typeof a === "string" ? a.localeCompare(b) : a - b;
  return descending ? -order : order;
}

function sortedRows(data) {
  const entries = (data.rows || []).map((row, index) => ({ row, index }));
  if (state.sort) {
    const { column, descending } = state.sort;
    const key = (entry) => (column === COMPANY ? (entry.row.company || {}).name : (entry.row.values || [])[column]);
    entries.sort((a, b) => compareValues(key(a), key(b), descending) || a.index - b.index);
  }
  return entries.map((entry) => entry.row);
}

// The first selection sorts numbers from highest and names from A; the next one reverses.
function sortBy(column) {
  const current = state.sort;
  state.sort = current && current.column === column
    ? { column, descending: !current.descending }
    : { column, descending: column !== COMPANY };
  renderTable(state.data);
}

function headerCell(label, column, title) {
  const sort = state.sort && state.sort.column === column ? state.sort : null;
  const direction = sort ? (sort.descending ? "descending" : "ascending") : "none";
  return h("th", { title, attrs: { scope: "col", "aria-sort": direction } }, [
    button(label, () => sortBy(column), { cls: "sort" }),
  ]);
}

function companyCell(row) {
  const company = row.company || {};
  const parts = [h("span", { text: company.name || company.corp_code })];
  if (company.stock_code) parts.push(h("span", { text: " " + company.stock_code, cls: "muted" }));
  if (row.basis_used === "separate") {
    const why = "No consolidated statements: separate statements used";
    parts.push(h("span", { text: "separate", cls: "badge", title: why }));
  }
  const title = [company.name, company.korean_name, company.market].filter(Boolean).join(" · ");
  return h("th", { title, attrs: { scope: "row" } }, parts);
}

function metricCell(value, column, extreme, unit) {
  const text = formatValue(value, column.unit === "pct" ? "percent" : null, unit);
  const classes = text.startsWith("-") ? ["neg"] : [];
  let title = "";
  if (extreme && value === extreme.high) {
    classes.push("hi");
    title = "Highest in this column";
  } else if (extreme && value === extreme.low) {
    classes.push("lo");
    title = "Lowest in this column";
  }
  return h("td", { text, title, cls: classes.join(" ") });
}

function renderTable(data) {
  const columns = data.columns || [];
  const extremes = extremesOf(data);
  const unitOf = (column) => (column.unit === "pct" ? "Percent" : unitLabel(data.unit));
  byId("head").replaceChildren(h("tr", null, [
    headerCell("Company", COMPANY, "Sort by company name"),
    ...columns.map((column, index) => headerCell(column.label, index, unitOf(column))),
  ]));
  const rows = sortedRows(data).map((row) => h("tr", null, [
    companyCell(row),
    ...columns.map((column, index) => metricCell((row.values || [])[index], column, extremes[index], data.unit)),
  ]));
  const empty = emptyRow(columns.length + 1, "No company has data for this period.");
  byId("body").replaceChildren(...(rows.length ? rows : [empty]));
}

function renderMissing(missing) {
  const items = Array.isArray(missing) ? missing : [];
  const box = byId("missing");
  box.hidden = items.length === 0;
  box.replaceChildren(
    h("strong", { text: "Not included (" + items.length + ")" }),
    h("ul", null, items.map((item) => h("li", null, [
      h("strong", { text: String(item.company) }),
      h("span", { text: ": " + item.reason }),
    ]))),
  );
}

function currentMetrics() {
  return state.args.metrics || "key_accounts";
}

// The original call's arguments; without them (no tool-input), the companies shown or left out.
function baseArgs() {
  if (Array.isArray(state.args.companies) && state.args.companies.length) return state.args;
  const data = state.data || {};
  const shown = (data.rows || []).map((row) => (row.company || {}).corp_code).filter(Boolean);
  const missing = (data.missing || []).map((item) => item.company).filter(Boolean);
  return { ...state.args, companies: [...shown, ...missing] };
}

function renderControls() {
  if (!state.data) return;
  const canCall = bridge.canCallTools();
  const enabled = canCall && !state.loading;
  const metrics = byId("metrics");
  metrics.title = canCall ? "" : "This host does not let apps call tools, so the metric set cannot change here.";
  const choose = (key) => () => load({ ...baseArgs(), metrics: key });
  metrics.replaceChildren(...METRIC_SETS.map(([key, label]) => button(label, choose(key), {
    disabled: !enabled,
    attrs: { "aria-pressed": String(key === currentMetrics()) },
  })));
}

function render() {
  const data = state.data;
  byId("title").textContent = "Peer comparison: " + scope(data);
  const amounts = (data.columns || []).some((column) => column.unit === "krw");
  byId("subtitle").textContent = amounts ? "Amounts in " + unitLabel(data.unit) + "; percentages as shown" : "";
  renderControls();
  renderTable(data);
  renderMissing(data.missing);
  renderFooter(data, bridge);
  showFallback("");
  setStatus("");
}

function summary(data, metrics) {
  const label = (METRIC_SETS.find(([key]) => key === metrics) || [metrics, String(metrics)])[1];
  const missing = (data.missing || []).length;
  return "The user is viewing " + label.toLowerCase() + " in the peer comparison app: " + scope(data)
    + (missing ? ", " + plural(missing, "company", "companies") + " not included" : "") + ".";
}

// Call compare_companies again with another metric set; the result replaces the table.
async function load(args) {
  state.loading = true;
  renderControls();
  setStatus("Loading…");
  try {
    const data = structuredOf(await bridge.callTool(TOOL, args), "rows");
    if (data) {
      state.args = args;
      state.data = data;
      state.sort = null;
      render();
      bridge.setModelContext(summary(data, args.metrics), { tool: TOOL, arguments: args });
    }
  } catch (error) {
    setStatus("Could not load: " + messageOf(error), true);
  } finally {
    state.loading = false;
    renderControls();
  }
}

const bridge = connectHost({
  name: "opendart-peers",
  version: "1.0.0",
  onInput(args) {
    state.args = args;
  },
  onResult(result) {
    const data = structuredOf(result, "rows");
    if (!data) return;
    state.data = data;
    state.sort = null;
    render();
  },
  onCancel(reason) {
    setStatus("The call was cancelled" + (reason ? ": " + reason : "."), true);
  },
  onReady() {
    if (state.data) render();
  },
  onError(text) {
    setStatus(text, true);
  },
});
