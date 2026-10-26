// Scenarios for the financial statements app (get_financials). Every number is synthetic.
import assert from "node:assert/strict";

import { checkHandshake } from "./harness_shim.mjs";

const T = 10 ** 12;
const COMPANY = {
  name: "SAMSUNG ELECTRONICS CO,.LTD",
  korean_name: "삼성전자",
  corp_code: "00126380",
  stock_code: "005930",
  market: "KOSPI",
};
const FILING = {
  filing_number: "20260814003699",
  title: "Semi-Annual Report (2026.06)",
  filed: "2026-08-14",
  dart_url: "https://englishdart.fss.or.kr/dsbh001/main.do?rcpNo=20260814003699",
};
const NOTE = "Quarterly income lines hold three-month amounts; cumulative holds the year to date.";
const ARGS = { company: "005930", fiscal_year: 2026, period: "H1" };
const VIEW_LABELS = [
  "Summary", "Income", "Balance", "Cash flow", "Comprehensive income", "Equity changes", "Ratios", "Investments",
  "Preliminary",
];

function envelope(view) {
  const provenance = { as_of: "2026-10-22", source_filings: [FILING], notes: [NOTE] };
  return { company: COMPANY, ...provenance, view, unit: "million_krw", currency: "KRW" };
}

function summary() {
  return {
    ...envelope("summary"),
    basis_used: "consolidated",
    periods: [
      { label: "H1 2026", end_date: "2026-06-30", fiscal_year: 2026, period: "H1" },
      { label: "FY2025", end_date: "2025-12-31", fiscal_year: 2025, period: "FY" },
      { label: "H1 2025", end_date: "2025-06-30", fiscal_year: 2025, period: "H1" },
    ],
    rows: [
      {
        account: "Sales",
        account_id: "ifrs-full_Revenue",
        values: [170 * T, null, 75 * T],
        cumulative: [300 * T, null, 150 * T],
      },
      { account: "Operating income", values: [-1_250_000_000, 33 * T, 5 * T], cumulative: [145 * T, 33 * T, 11 * T] },
      { account: "Total assets", values: [760 * T, 570 * T, null] },
      { account: "Basic earnings per share", kind: "per_share", values: [1234, 12.5, null] },
      { account: "Debt ratio", kind: "percent", values: [31.03, -4.44, null] },
    ],
    derived: { revenue_growth: 100, operating_margin: 48.33 },
  };
}

function income() {
  const rows = [{ account: "Revenue", values: [170 * T, 300 * T, 75 * T] }];
  return { ...summary(), view: "income", rows, derived: {} };
}

function annual(unit) {
  return {
    ...envelope("income"),
    unit,
    basis_used: "separate",
    periods: [
      { label: "FY2025", end_date: "2025-12-31", fiscal_year: 2025, period: "FY" },
      { label: "FY2024", end_date: "2024-12-31", fiscal_year: 2024, period: "FY" },
      { label: "FY2023", end_date: "2023-12-31", fiscal_year: 2023, period: "FY" },
    ],
    rows: [{ account: "Revenue", values: [1_250_000_000, -1_250_000_000, -40_000_000] }],
    derived: {},
  };
}

function holdings() {
  return {
    ...envelope("equity_investments"),
    source_filings: [],
    notes: [],
    periods: [
      { label: "FY2025", end_date: "2025-12-31", fiscal_year: 2025, period: "FY" },
      { label: "FY2024", end_date: "2024-12-31", fiscal_year: 2024, period: "FY" },
    ],
    rows: [
      { account: "Samsung Display", values: [18 * T, 17 * T] },
      { account: "Total (all investments)", values: [60 * T, 55 * T] },
    ],
    derived: {},
    investments: [
      {
        name: "Samsung Display",
        purpose: "management participation",
        ownership_pct: 84.8,
        shares: 221969719,
        book_value: 18 * T,
      },
      { name: '<img src=x onerror="alert(1)">', ownership_pct: 100, book_value: -5_000_000 },
    ],
  };
}

const result = (structuredContent) => ({
  content: [{ type: "text", text: "**Financial summary**" }],
  structuredContent,
});

export default {
  async "handshake, theme, fonts, and size reports"(open) {
    const page = await open({
      context: {
        theme: "dark",
        styles: {
          variables: { "--color-text-primary": "#eeeeee", "--font-sans": "Test Sans", ignored: "x" },
          css: { fonts: "@font-face { font-family: Test Sans; }" },
        },
        containerDimensions: { maxHeight: 600 },
      },
    });
    checkHandshake(page, "opendart-financials");
    assert.equal(page.root.getAttribute("data-theme"), "dark");
    assert.equal(page.root.style.colorScheme, "dark");
    assert.equal(page.root.style.getPropertyValue("--color-text-primary"), "#eeeeee");
    assert.equal(page.root.style.getPropertyValue("--font-sans"), "Test Sans");
    assert.equal(page.root.style.getPropertyValue("ignored"), "");
    assert.equal(page.byId("host-fonts").textContent, "@font-face { font-family: Test Sans; }");
    assert.equal(page.root.style.maxHeight, "600px");
    assert.equal(page.root.hasAttribute("data-fill"), false);
    page.resize(420);
    await page.flush();
    page.resize(420);
    await page.flush();
    const heights = page.messages("ui/notifications/size-changed").map((message) => message.params.height);
    assert.deepEqual(heights, [300, 420]);
    page.notify("ui/notifications/host-context-changed", { theme: "light", containerDimensions: { height: 500 } });
    assert.equal(page.root.getAttribute("data-theme"), "light");
    assert.equal(page.root.hasAttribute("data-fill"), true);
    assert.equal(page.root.style.maxHeight, "");
    assert.equal(page.status(), "Waiting for data…");
  },

  async "line items by period with units, kinds, derived metrics, and sources"(open) {
    const page = await open();
    await page.show(ARGS, summary());
    assert.equal(page.byId("title").textContent, "SAMSUNG ELECTRONICS CO,.LTD · 005930 · KOSPI");
    assert.equal(page.byId("title").title, "삼성전자");
    assert.equal(page.byId("subtitle").textContent, "Financial summary · consolidated · KRW million");
    assert.deepEqual(page.table("head"), [["Account", "Q2 2026", "FY2025", "Q2 2025"]]);
    assert.deepEqual(page.table(), [
      ["Sales", "170,000,000.0", "–", "75,000,000.0"],
      ["Operating income", "-1,250.0", "33,000,000.0", "5,000,000.0"],
      ["Total assets", "760,000,000.0", "570,000,000.0", "–"],
      ["Basic earnings per share (KRW)", "1,234", "12.50", "–"],
      ["Debt ratio", "31.0%", "-4.4%", "–"],
    ]);
    const classes = page.byId("body").byTag("tr").map((row) => row.children.map((cell) => cell.className));
    assert.deepEqual(classes[1], ["", "neg", "", ""]);
    assert.deepEqual(classes[4], ["", "", "neg", ""]);
    assert.equal(page.byId("body").byTag("th")[0].title, "Sales (ifrs-full_Revenue)");
    assert.equal(page.byId("body").byTag("th")[1].title, "Operating income");
    assert.equal(page.byId("head").byTag("th")[1].title, "Period ending 2026-06-30");
    const derived = page.byId("derived");
    assert.equal(derived.hidden, false);
    assert.deepEqual(derived.children.map((chip) => chip.textContent), [
      "Derived (see notes): ", "Revenue growth +100.0%", "Operating margin 48.3%",
    ]);
    assert.deepEqual(page.byId("notes").children.map((item) => item.textContent), [NOTE]);
    assert.equal(page.byId("sources").textContent, "Sources: 20260814003699. As of 2026-10-22 (KST).");
    assert.equal(page.status(), "");
    assert.equal(page.byId("fallback").hidden, true);
    assert.equal(page.byId("filter").hidden, true);
  },

  async "the year-to-date switch changes columns without a tool call"(open) {
    const page = await open();
    await page.show(ARGS, summary());
    const mode = page.byId("period-mode");
    assert.equal(mode.hidden, false);
    assert.equal(mode.button("Three months").getAttribute("aria-pressed"), "true");
    mode.button("Year to date").click();
    assert.deepEqual(page.table("head"), [["Account", "H1 2026", "FY2025", "H1 2025"]]);
    assert.deepEqual(page.table().slice(0, 3), [
      ["Sales", "300,000,000.0", "–", "150,000,000.0"],
      ["Operating income", "145,000,000.0", "33,000,000.0", "11,000,000.0"],
      ["Total assets", "760,000,000.0", "570,000,000.0", "–"],
    ]);
    assert.equal(mode.button("Year to date").getAttribute("aria-pressed"), "true");
    assert.equal(page.messages("tools/call").length, 0);
  },

  async "view tabs call get_financials with the original arguments"(open) {
    let release;
    const page = await open({ onCall: () => new Promise((resolve) => { release = resolve; }) });
    await page.show(ARGS, summary());
    const views = page.byId("views");
    assert.deepEqual(views.children.map((tab) => tab.textContent), VIEW_LABELS);
    assert.equal(views.button("Summary").getAttribute("aria-pressed"), "true");
    views.button("Income").click();
    await page.flush();
    assert.deepEqual(page.messages("tools/call").map((message) => message.params), [
      { name: "get_financials", arguments: { ...ARGS, view: "income" } },
    ]);
    assert.ok(views.children.every((tab) => tab.disabled), "tabs wait for the call");
    assert.equal(page.status(), "Loading income statement…");
    release(result(income()));
    await page.flush();
    assert.ok(views.children.every((tab) => !tab.disabled));
    assert.equal(views.button("Income").getAttribute("aria-pressed"), "true");
    assert.deepEqual(page.table(), [["Revenue", "170,000,000.0", "300,000,000.0", "75,000,000.0"]]);
    assert.equal(page.byId("subtitle").textContent, "Income statement · consolidated · KRW million");
    assert.equal(page.byId("period-mode").hidden, true);
    assert.equal(page.byId("derived").hidden, true);
    const updates = page.messages("ui/update-model-context").map((message) => message.params);
    assert.deepEqual(updates, [{
      content: [{
        type: "text",
        text: "The user is viewing SAMSUNG ELECTRONICS CO,.LTD (005930), Income statement (consolidated), in the "
          + "financial statements app: 1 row for H1 2026, FY2025, H1 2025.",
      }],
      structuredContent: { tool: "get_financials", arguments: { ...ARGS, view: "income" } },
    }]);
  },

  async "failed calls keep the table and explain why"(open) {
    const answers = [
      { content: [{ type: "text", text: "Unknown company zzz: call find_company." }], isError: true },
      { error: { code: -32603, message: "upstream timeout" } },
    ];
    const page = await open({ onCall: () => answers.shift() });
    await page.show(ARGS, summary());
    page.byId("views").button("Ratios").click();
    await page.flush();
    assert.equal(page.status(), "Unknown company zzz: call find_company.");
    assert.equal(page.byId("status").className, "status error");
    assert.equal(page.table()[0][0], "Sales");
    assert.equal(page.byId("views").button("Summary").getAttribute("aria-pressed"), "true");
    assert.ok(page.byId("views").children.every((tab) => !tab.disabled));
    page.byId("views").button("Ratios").click();
    await page.flush();
    assert.equal(page.status(), "Could not load: upstream timeout");
    assert.equal(page.messages("ui/update-model-context").length, 0);
    page.notify("ui/notifications/tool-cancelled", { reason: "user stopped" });
    assert.equal(page.status(), "The call was cancelled: user stopped");
  },

  async "hosts without tool calls or links get a fixed view and plain filing numbers"(open) {
    const page = await open({ capabilities: {} });
    await page.show(ARGS, summary());
    const views = page.byId("views");
    assert.ok(views.children.every((tab) => tab.disabled));
    assert.match(views.title, /does not let apps call tools/);
    views.button("Income").click();
    await page.flush();
    assert.equal(page.messages("tools/call").length, 0);
    assert.equal(page.byId("sources").byTag("button").length, 0);
    assert.equal(page.byId("sources").textContent, "Sources: 20260814003699. As of 2026-10-22 (KST).");
  },

  async "filing numbers open the DART viewer through the host"(open) {
    const page = await open();
    await page.show(ARGS, summary());
    page.byId("sources").button("20260814003699").click();
    await page.flush();
    assert.deepEqual(page.messages("ui/open-link").map((message) => message.params), [{ url: FILING.dart_url }]);
    const denied = await open({ denyLinks: true });
    await denied.show(ARGS, summary());
    denied.byId("sources").button("20260814003699").click();
    await denied.flush();
    assert.equal(denied.status(), "Could not open the filing: Link opening denied by user");
  },

  async "equity investments render as holdings, with untrusted names as text"(open) {
    const page = await open();
    await page.show({ company: "005930", view: "equity_investments" }, holdings());
    assert.equal(page.byId("subtitle").textContent, "Equity investments · KRW million");
    assert.deepEqual(page.table("head"), [["Investee", "Purpose", "Stake", "Shares", "Book value"]]);
    assert.deepEqual(page.table(), [
      ["Samsung Display", "management participation", "84.8%", "221,969,719", "18,000,000.0"],
      ['<img src=x onerror="alert(1)">', "–", "100.0%", "–", "-5.0"],
      ["Total (all investments)", "", "", "", "60,000,000.0"],
    ]);
    assert.equal(page.byId("body").byTag("img").length, 0, "names never become markup");
    assert.equal(page.byId("body").byTag("tr")[1].children[4].className, "neg");
    assert.equal(page.byId("period-mode").hidden, true);
  },

  async "the account filter can be cleared with one call"(open) {
    const page = await open({ onCall: () => result(income()) });
    await page.show({ ...ARGS, view: "income", accounts: ["Revenue", "Operating"] }, income());
    const filter = page.byId("filter");
    assert.equal(filter.hidden, false);
    assert.equal(filter.children[0].textContent, "Accounts matching: Revenue, Operating");
    filter.button("Show all").click();
    await page.flush();
    assert.deepEqual(page.messages("tools/call")[0].params.arguments, { ...ARGS, view: "income" });
    assert.equal(filter.hidden, true);
  },

  async "billions round half away from zero and won stay exact"(open) {
    const page = await open();
    await page.show(ARGS, annual("billion_krw"));
    assert.equal(page.byId("subtitle").textContent, "Income statement · separate · KRW billion");
    assert.deepEqual(page.table(), [["Revenue", "1.3", "-1.3", "0.0"]]);
    assert.deepEqual(page.byId("body").byTag("td").map((cell) => cell.className), ["", "neg", ""]);
    assert.equal(page.byId("period-mode").hidden, true);
    page.notify("ui/notifications/tool-result", result(annual("krw")));
    assert.deepEqual(page.table(), [["Revenue", "1,250,000,000", "-1,250,000,000", "-40,000,000"]]);
    assert.equal(page.byId("subtitle").textContent, "Income statement · separate · KRW");
  },

  async "foreign messages, host requests, and results without table data"(open) {
    const page = await open();
    page.deliver({ method: "ui/notifications/tool-result", params: result(summary()) }, {});
    await page.flush();
    assert.equal(page.table().length, 0, "messages from other windows are ignored");
    page.deliver({ id: 41, method: "ping", params: {} });
    page.deliver({ id: 42, method: "ui/resource-teardown", params: { reason: "closed" } });
    page.deliver({ id: 43, method: "tools/list", params: {} });
    page.deliver({ method: "__proto__", params: {} });
    page.deliver({ id: 999, result: {} });
    const responses = page.responses();
    assert.deepEqual(responses.slice(0, 2), [
      { jsonrpc: "2.0", id: 41, result: {} },
      { jsonrpc: "2.0", id: 42, result: {} },
    ]);
    assert.equal(responses[2].id, 43);
    assert.equal(responses[2].error.code, -32601);
    assert.equal(responses.length, 3);
    page.notify("ui/notifications/tool-result", { content: [{ type: "text", text: "| Account | FY2025 |" }] });
    assert.equal(page.byId("fallback").hidden, false);
    assert.equal(page.byId("fallback").textContent, "| Account | FY2025 |");
    assert.equal(page.status(), "This result has no table data; its text follows.");
    page.notify("ui/notifications/tool-result", result({ ...summary(), rows: [null] }));
    assert.match(page.status(), /^Could not show the result: /);
  },

  async "without tool-input, view switches still name the company"(open) {
    const page = await open({ onCall: () => result(income()) });
    page.notify("ui/notifications/tool-result", result(summary()));
    page.byId("views").button("Balance").click();
    await page.flush();
    assert.deepEqual(page.messages("tools/call")[0].params.arguments, { company: "00126380", view: "balance" });
  },
};
