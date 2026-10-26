// Corporate-action calendar app for get_corporate_action_calendar: dates grouped by week
// (Monday first), company and action filters, and filing numbers that open the DART viewer.

const DAY_MS = 86400000;
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// company and action hold the selected corp_code and action code; "" shows all.
const state = { data: null, company: "", action: "" };

function utcDate(iso) {
  const [year, month, day] = String(iso).split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function weekday(iso) {
  return WEEKDAYS[utcDate(iso).getUTCDay()] || "";
}

// ISO date of the Monday that starts the date's week.
function weekOf(iso) {
  const date = utcDate(iso);
  if (Number.isNaN(date.getTime())) return String(iso);
  const monday = new Date(date.getTime() - ((date.getUTCDay() + 6) % 7) * DAY_MS);
  return monday.toISOString().slice(0, 10);
}

function companiesOf(data) {
  if (Array.isArray(data.companies) && data.companies.length) return data.companies;
  const seen = new Map();
  for (const item of data.items || []) {
    const company = item.company || {};
    if (company.corp_code && !seen.has(company.corp_code)) seen.set(company.corp_code, company);
  }
  return [...seen.values()];
}

function visibleItems(data) {
  return (data.items || []).filter((item) => (!state.company || (item.company || {}).corp_code === state.company)
    && (!state.action || item.action === state.action));
}

// Options for a filter; a selection that no longer exists falls back to "all".
function fillSelect(select, allLabel, options, key) {
  if (!options.some(([value]) => value === state[key])) state[key] = "";
  select.replaceChildren(
    h("option", { text: allLabel, attrs: { value: "" } }),
    ...options.map(([value, label]) => h("option", { text: label, attrs: { value } })),
  );
  select.value = state[key];
}

function renderFilters(data) {
  const companies = companiesOf(data).map((company) => [company.corp_code, companyLabel(company)]);
  const actions = [...new Set((data.items || []).map((item) => item.action))]
    .map((action) => [action, humanize(action)])
    .sort((a, b) => a[1].localeCompare(b[1]));
  fillSelect(byId("company"), "All companies", companies, "company");
  fillSelect(byId("action"), "All actions", actions, "action");
}

function detailText(value) {
  if (typeof value === "number") return fixed(value, Number.isInteger(value) ? 0 : 2);
  return value === undefined || value === null ? DASH : String(value);
}

// Key terms other than the event label, for example "Face value 30,000,000,000; Series 3".
function terms(details) {
  return Object.entries(details).filter(([key]) => key !== "event")
    .map(([key, value]) => humanize(key) + " " + detailText(value)).join("; ");
}

function itemRow(item, today) {
  const company = item.company || {};
  const details = item.details || {};
  let when = "";
  if (today && item.date < today) when = "past";
  else if (item.date === today) when = "today";
  return h("tr", { cls: when }, [
    h("th", { text: weekday(item.date) + " " + item.date, attrs: { scope: "row" } }),
    h("td", { text: companyLabel(company), title: company.korean_name || "" }),
    h("td", { text: humanize(item.action), title: item.action }),
    h("td", { text: details.event || humanize(item.source_kind) }),
    h("td", { text: terms(details), cls: "text terms" }),
    h("td", null, [filingLink(bridge, item.filing_number, item.dart_url)]),
  ]);
}

function groupByWeek(items) {
  const weeks = new Map();
  for (const item of items) {
    const week = weekOf(item.date);
    if (!weeks.has(week)) weeks.set(week, []);
    weeks.get(week).push(item);
  }
  return weeks;
}

function renderItems(data) {
  const items = visibleItems(data);
  const total = (data.items || []).length;
  const rows = [];
  for (const [week, entries] of groupByWeek(items)) {
    const label = "Week of " + weekday(week) + " " + week + " · " + plural(entries.length, "date");
    rows.push(h("tr", { cls: "week" }, [h("th", { text: label, attrs: { colspan: 6, scope: "colgroup" } })]));
    for (const item of entries) rows.push(itemRow(item, data.as_of));
  }
  const empty = total ? "No dates match these filters." : "No corporate-action dates in this window.";
  byId("body").replaceChildren(...(rows.length ? rows : [emptyRow(6, empty)]));
  const dates = plural(total, "date");
  byId("count").textContent = items.length === total ? dates : items.length + " of " + dates;
}

function render() {
  const data = state.data;
  const span = data.start && data.end ? data.start + " to " + data.end : "";
  const horizon = typeof data.horizon_days === "number" ? "horizon " + plural(data.horizon_days, "day") : "";
  const companies = plural(companiesOf(data).length, "company", "companies");
  byId("subtitle").textContent = [span, companies, horizon].filter(Boolean).join(" · ");
  renderFilters(data);
  renderItems(data);
  renderFooter(data, bridge);
  showFallback("");
  setStatus("");
}

// Tell the model which dates the user is looking at after a filter change.
function announce() {
  const data = state.data;
  const shown = visibleItems(data).length;
  const total = (data.items || []).length;
  const company = companiesOf(data).find((entry) => entry.corp_code === state.company);
  const filters = [company && company.name, state.action && humanize(state.action)].filter(Boolean);
  const scope = filters.length ? "filtered to " + filters.join(" and ") : "with every company and action";
  bridge.setModelContext(
    "The user is viewing the corporate-action calendar " + scope + ": " + shown + " of " + plural(total, "date") + ".",
    { company: state.company || null, action: state.action || null, shown, total },
  );
}

function onFilter(key, select) {
  select.addEventListener("change", () => {
    state[key] = select.value;
    if (!state.data) return;
    renderItems(state.data);
    announce();
  });
}

onFilter("company", byId("company"));
onFilter("action", byId("action"));

const bridge = connectHost({
  name: "opendart-calendar",
  version: "1.0.0",
  onInput() {},
  onResult(result) {
    const data = structuredOf(result, "items");
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
