// Helpers shared by the OpenDART apps: DOM building with text only (data from filings is
// untrusted, so nothing is ever parsed as HTML), number formats, status, and the page footer.

const DASH = "–";
const LOCALE = "en-US";
const DIVISORS = { krw: 1, million_krw: 1e6, billion_krw: 1e9 };
const UNIT_SUFFIXES = { krw: "", million_krw: " million", billion_krw: " billion" };

const byId = (id) => document.getElementById(id);

// Create an element. props: { text, cls, title, disabled, attrs: {name: value}, onClick }.
function h(tag, props, children) {
  const node = document.createElement(tag);
  const options = props || {};
  if (options.text !== undefined && options.text !== null) node.textContent = String(options.text);
  if (options.cls) node.className = options.cls;
  if (options.title) node.title = String(options.title);
  if (options.disabled) node.disabled = true;
  for (const [name, value] of Object.entries(options.attrs || {})) node.setAttribute(name, String(value));
  if (options.onClick) node.addEventListener("click", options.onClick);
  for (const child of children || []) if (child) node.appendChild(child);
  return node;
}

function button(label, onClick, props) {
  const options = props || {};
  return h("button", { ...options, text: label, onClick, attrs: { type: "button", ...(options.attrs || {}) } });
}

function emptyRow(span, text) {
  return h("tr", null, [h("td", { text, cls: "empty", attrs: { colspan: span } })]);
}

function plural(count, noun, nouns) {
  return count + " " + (count === 1 ? noun : nouns || noun + "s");
}

function fixed(value, digits) {
  return value.toLocaleString(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

// Won amount in a display unit, rounded half away from zero to one decimal like the text tables.
function scaled(won, unit) {
  const divisor = DIVISORS[unit] || 1;
  if (divisor === 1) return fixed(Math.round(won), 0);
  const tenth = divisor / 10;
  const size = Math.abs(won);
  let tenths = Math.floor(size / tenth);
  let rest = size - tenths * tenth;
  if (rest < 0) {
    tenths -= 1;
    rest += tenth;
  }
  if (rest * 2 >= tenth) tenths += 1;
  return (won < 0 && tenths > 0 ? "-" : "") + fixed(tenths / 10, 1);
}

function percentText(value, signed) {
  return (signed && value > 0 ? "+" : "") + fixed(value, 1) + "%";
}

// A value by its kind: unset for won amounts, "per_share" and "percent" are never scaled.
function formatValue(value, kind, unit) {
  if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
  if (kind === "percent") return percentText(value, false);
  if (kind === "per_share") return fixed(value, Number.isInteger(value) ? 0 : 2);
  return scaled(value, unit);
}

// snake_case codes such as short_sale_ban_start read as "Short sale ban start".
function humanize(code) {
  const words = String(code || "").replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function unitLabel(unit, currency) {
  return (currency || "KRW") + (UNIT_SUFFIXES[unit] || "");
}

function companyLabel(company) {
  const code = company.stock_code || company.corp_code;
  return (company.name || company.corp_code || "") + (code ? " (" + code + ")" : "");
}

function messageOf(error) {
  return error && error.message ? error.message : String(error);
}

function textOf(result) {
  const block = ((result && result.content) || []).find((item) => item && item.type === "text");
  return block ? String(block.text) : "";
}

function setStatus(text, isError) {
  const status = byId("status");
  status.textContent = text || "";
  status.className = isError ? "status error" : "status muted";
}

// Hosts that drop structured content still pass the text view: show it as is.
function showFallback(text) {
  const fallback = byId("fallback");
  fallback.textContent = text || "";
  fallback.hidden = !text;
}

// The structured content of a tool result, or null after explaining why there is none.
function structuredOf(result, listKey) {
  if (!result || result.isError) {
    setStatus(textOf(result) || "The tool reported an error.", true);
    return null;
  }
  const data = result.structuredContent;
  if (!data || !Array.isArray(data[listKey])) {
    setStatus("This result has no table data; its text follows.");
    showFallback(textOf(result));
    return null;
  }
  return data;
}

function isDartUrl(value) {
  try {
    const url = new URL(String(value));
    return url.protocol === "https:" && url.hostname.endsWith(".fss.or.kr");
  } catch {
    return false;
  }
}

// A filing number that opens the DART viewer when the host allows links.
function filingLink(bridge, number, url, title) {
  const label = String(number || "");
  const tip = title ? title + " (" + label + ")" : "Filing " + label;
  if (!bridge.canOpenLinks() || !isDartUrl(url)) return h("span", { text: label, title: tip });
  const failed = (error) => setStatus("Could not open the filing: " + messageOf(error), true);
  return button(label, () => bridge.openLink(url).catch(failed), { cls: "link", title: "Open on DART: " + tip });
}

// Notes, cited filings, and the as-of date, as in the text view's footer.
function renderFooter(data, bridge) {
  byId("notes").replaceChildren(...(data.notes || []).map((note) => h("li", { text: note })));
  const parts = [];
  (data.source_filings || []).forEach((filing, index) => {
    parts.push(h("span", { text: index ? ", " : "Sources: " }));
    parts.push(filingLink(bridge, filing.filing_number, filing.dart_url, filing.title));
  });
  if (parts.length) parts.push(h("span", { text: ". " }));
  if (data.as_of) parts.push(h("span", { text: "As of " + data.as_of + " (KST)." }));
  byId("sources").replaceChildren(...parts);
}
