// Financial statements app for get_financials: line items by period, statement views that call
// the tool again through the host, a three-month or year-to-date switch, and the account filter.

const TOOL = "get_financials";
const VIEWS = [
  ["summary", "Summary"],
  ["income", "Income"],
  ["balance", "Balance"],
  ["cash_flow", "Cash flow"],
  ["comprehensive_income", "Comprehensive income"],
  ["equity_changes", "Equity changes"],
  ["ratios", "Ratios"],
  ["equity_investments", "Investments"],
  ["preliminary", "Preliminary"],
];
const TITLES = {
  summary: "Financial summary",
  income: "Income statement",
  balance: "Balance sheet",
  cash_flow: "Cash flow statement",
  comprehensive_income: "Statement of comprehensive income",
  equity_changes: "Statement of changes in equity",
  ratios: "Financial indicators",
  equity_investments: "Equity investments",
  preliminary: "Preliminary earnings",
};
// Column headings of quarterly periods that hold both amounts, as in the text table.
const QUARTERS = { Q1: "Q1 ", H1: "Q2 ", Q3: "Q3 ", FY: "Q4 " };
const YEAR_TO_DATE = { Q1: "Q1 ", H1: "H1 ", Q3: "9M ", FY: "FY" };
const HOLDINGS = [
  ["name", "Investee", "text"],
  ["purpose", "Purpose", "text"],
  ["ownership_pct", "Stake", "percent"],
  ["shares", "Shares", "count"],
  ["book_value", "Book value", "amount"],
  ["opening_book_value", "Opening", "amount"],
  ["acquired_or_disposed", "Acquired (disposed)", "amount"],
  ["valuation_change", "Valuation", "amount"],
  ["investee_total_assets", "Investee assets", "amount"],
  ["investee_net_income", "Investee profit", "amount"],
  ["first_acquired", "First acquired", "text"],
];

const state = { args: {}, data: null, yearToDate: false, loading: false };

// One column per period; quarterly periods whose year-to-date amounts differ are "split".
function columnsOf(data) {
  const rows = data.rows || [];
  return (data.periods || []).map((period, index) => {
    const split = rows.some((row) => Array.isArray(row.cumulative) && row.cumulative[index] != null
      && row.cumulative[index] !== (row.values || [])[index]);
    const prefix = (state.yearToDate ? YEAR_TO_DATE : QUARTERS)[period.period];
    const label = split && prefix ? prefix + period.fiscal_year : period.label || period.end_date || "";
    return { index, split, label, title: period.end_date ? "Period ending " + period.end_date : "" };
  });
}

function cellValue(row, column) {
  const cumulative = Array.isArray(row.cumulative) ? row.cumulative[column.index] : null;
  if (state.yearToDate && column.split && cumulative != null) return cumulative;
  return (row.values || [])[column.index];
}

function valueCell(value, kind, unit) {
  const text = formatValue(value, kind, unit);
  return h("td", { text, cls: text.startsWith("-") ? "neg" : "" });
}

function rowLabel(row, currency) {
  return row.kind === "per_share" ? row.account + " (" + (currency || "KRW") + ")" : row.account;
}

function renderStatement(data) {
  const columns = columnsOf(data);
  byId("head").replaceChildren(h("tr", null, [
    h("th", { text: "Account", attrs: { scope: "col" } }),
    ...columns.map((column) => h("th", { text: column.label, title: column.title, attrs: { scope: "col" } })),
  ]));
  const rows = (data.rows || []).map((row) => h("tr", null, [
    h("th", {
      text: rowLabel(row, data.currency),
      title: row.account + (row.account_id ? " (" + row.account_id + ")" : ""),
      attrs: { scope: "row" },
    }),
    ...columns.map((column) => valueCell(cellValue(row, column), row.kind, data.unit)),
  ]));
  byId("body").replaceChildren(...(rows.length ? rows : [emptyRow(columns.length + 1, "No rows to show.")]));
}

function holdingText(value, kind, unit) {
  if (value === undefined || value === null) return DASH;
  if (kind === "percent") return formatValue(value, "percent", unit);
  if (kind === "count") return fixed(value, 0);
  if (kind === "amount") return formatValue(value, null, unit);
  return String(value);
}

// equity_investments: one row per holding, with the columns that have any value.
function renderHoldings(data) {
  const items = data.investments;
  const columns = HOLDINGS.filter(([key], index) => index === 0 || items.some((item) => item[key] != null));
  const headings = columns.map(([, label]) => h("th", { text: label, attrs: { scope: "col" } }));
  byId("head").replaceChildren(h("tr", null, headings));
  const rows = items.map((item) => h("tr", null, columns.map(([key, , kind], index) => {
    const text = holdingText(item[key], kind, data.unit);
    if (index === 0) return h("th", { text, attrs: { scope: "row" } });
    return h("td", { text, cls: kind === "text" ? "text" : text.startsWith("-") ? "neg" : "" });
  })));
  const total = (data.rows || []).find((row) => /^Total/.test(row.account || ""));
  if (total) rows.push(totalRow(total, columns, data.unit));
  byId("body").replaceChildren(...rows);
}

// The filing's total line holds closing and opening book values, aligned with the periods.
function totalRow(total, columns, unit) {
  const [closing, opening] = total.values || [];
  const values = { book_value: closing, opening_book_value: opening };
  return h("tr", { cls: "total" }, columns.map(([key], index) => {
    if (index === 0) return h("th", { text: total.account, attrs: { scope: "row" } });
    return Object.hasOwn(values, key) ? valueCell(values[key], null, unit) : h("td");
  }));
}

function renderDerived(derived) {
  const entries = Object.entries(derived || {}).filter(([, value]) => typeof value === "number");
  const box = byId("derived");
  box.hidden = entries.length === 0;
  box.replaceChildren(
    h("span", { text: "Derived (see notes): ", cls: "muted" }),
    ...entries.map(([key, value]) => h("span", {
      cls: "chip",
      text: humanize(key) + " " + percentText(value, key.endsWith("_growth")),
    })),
  );
}

// The original call's arguments; without them (no tool-input), at least the company.
function baseArgs() {
  const company = (state.data && state.data.company) || {};
  if (state.args.company || !company.corp_code) return state.args;
  return { ...state.args, company: company.corp_code };
}

function renderControls() {
  const data = state.data;
  if (!data) return;
  const canCall = bridge.canCallTools();
  const enabled = canCall && !state.loading;
  const views = byId("views");
  views.title = canCall ? "" : "This host does not let apps call tools, so the view cannot change here.";
  views.replaceChildren(...VIEWS.map(([view, label]) => button(label, () => load({ ...baseArgs(), view }), {
    disabled: !enabled,
    attrs: { "aria-pressed": String(view === data.view) },
  })));
  renderPeriodMode(data);
  renderFilter(enabled);
}

// Quarterly income lines hold three-month and year-to-date amounts; show either.
function renderPeriodMode(data) {
  const mode = byId("period-mode");
  mode.hidden = !columnsOf(data).some((column) => column.split);
  const choose = (yearToDate) => () => {
    state.yearToDate = yearToDate;
    render();
  };
  mode.replaceChildren(...[[false, "Three months"], [true, "Year to date"]].map(([yearToDate, label]) => button(
    label, choose(yearToDate), { attrs: { "aria-pressed": String(state.yearToDate === yearToDate) } },
  )));
}

function renderFilter(enabled) {
  const accounts = Array.isArray(state.args.accounts) ? state.args.accounts : [];
  const filter = byId("filter");
  filter.hidden = accounts.length === 0;
  filter.replaceChildren(
    h("span", { text: "Accounts matching: " + accounts.join(", ") }),
    button("Show all", () => {
      const args = { ...baseArgs() };
      delete args.accounts;
      load(args);
    }, { cls: "link", disabled: !enabled }),
  );
}

function amountNote(data) {
  const amounts = (data.investments || []).length > 0 || (data.rows || []).some((row) => !row.kind);
  return amounts ? unitLabel(data.unit, data.currency) : "";
}

function render() {
  const data = state.data;
  const company = data.company || {};
  const title = byId("title");
  const identity = [company.name, company.stock_code, company.market].filter(Boolean).join(" · ");
  title.textContent = identity || "Financial statements";
  title.title = company.korean_name || "";
  byId("subtitle").textContent = [TITLES[data.view] || humanize(data.view), data.basis_used, amountNote(data)]
    .filter(Boolean).join(" · ");
  if (Array.isArray(data.investments) && data.investments.length) renderHoldings(data);
  else renderStatement(data);
  renderDerived(data.derived);
  renderControls();
  renderFooter(data, bridge);
  showFallback("");
  setStatus("");
}

function summary(data) {
  const periods = (data.periods || []).map((period) => period.label).filter(Boolean).join(", ");
  return "The user is viewing " + companyLabel(data.company || {}) + ", " + (TITLES[data.view] || data.view)
    + (data.basis_used ? " (" + data.basis_used + ")" : "") + ", in the financial statements app: "
    + plural((data.rows || []).length, "row") + (periods ? " for " + periods : "") + ".";
}

// Call get_financials again with new arguments; the result replaces the table.
async function load(args) {
  state.loading = true;
  renderControls();
  setStatus("Loading " + (TITLES[args.view] || "statements").toLowerCase() + "…");
  try {
    const data = structuredOf(await bridge.callTool(TOOL, args), "rows");
    if (data) {
      state.args = args;
      state.data = data;
      render();
      bridge.setModelContext(summary(data), { tool: TOOL, arguments: args });
    }
  } catch (error) {
    setStatus("Could not load: " + messageOf(error), true);
  } finally {
    state.loading = false;
    renderControls();
  }
}

const bridge = connectHost({
  name: "opendart-financials",
  version: "1.0.0",
  onInput(args) {
    state.args = args;
  },
  onResult(result) {
    const data = structuredOf(result, "rows");
    if (!data) return;
    state.data = data;
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
