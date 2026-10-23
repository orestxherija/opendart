// Scenarios for the peer comparison app (compare_companies). Every number is synthetic.
import assert from "node:assert/strict";

import { checkHandshake } from "./harness_shim.mjs";

const T = 10 ** 12;
const SAMSUNG = {
  name: "SAMSUNG ELECTRONICS CO,.LTD",
  korean_name: "삼성전자",
  corp_code: "00126380",
  stock_code: "005930",
  market: "KOSPI",
};
const HYNIX = { name: "SK hynix Inc.", corp_code: "00164779", stock_code: "000660", market: "KOSPI" };
const KAKAO = { name: "Kakao Corp.", corp_code: "00258801", stock_code: "035720", market: "KOSDAQ" };
const ARGS = { companies: ["005930", "000660", "035720", "zzzz nothing"], fiscal_year: 2025, basis: "auto" };
const MISSING = [{ company: "zzzz nothing", reason: "No company matches; call find_company." }];

function keyAccounts() {
  return {
    as_of: "2026-10-22",
    source_filings: [],
    notes: ["operating_margin = operating income / revenue (derived)."],
    company_count: 3,
    fiscal_year: 2025,
    period: "FY",
    basis: "auto",
    unit: "million_krw",
    columns: [
      { key: "revenue", label: "Revenue", unit: "krw" },
      { key: "operating_income", label: "Operating profit", unit: "krw" },
      { key: "operating_margin", label: "Operating margin (derived)", unit: "pct" },
      { key: "debt_to_equity", label: "Debt to equity (derived)", unit: "pct" },
    ],
    rows: [
      { company: SAMSUNG, values: [330 * T, 44 * T, 13.33, 28.09], basis_used: "consolidated" },
      { company: HYNIX, values: [660 * T, -8_800_000_000_000, -1.33, 28.09], basis_used: "consolidated" },
      { company: KAKAO, values: [null, 5 * T, 6.1, 45.2], basis_used: "separate" },
    ],
    missing: MISSING,
  };
}

function ratios() {
  return {
    ...keyAccounts(),
    notes: [],
    columns: [
      { key: "gross_margin", label: "Gross margin", unit: "pct" },
      { key: "roe", label: "ROE", unit: "pct" },
    ],
    rows: [
      { company: SAMSUNG, values: [39.4, 8.2] },
      { company: HYNIX, values: [40.4, 12.5] },
    ],
    company_count: 2,
  };
}

const result = (structuredContent) => ({ content: [{ type: "text", text: "**Peer comparison**" }], structuredContent });
const names = (page) => page.table().map((row) => row[0]);

export default {
  async "handshake and size reports"(open) {
    const page = await open({ context: { theme: "dark" } });
    checkHandshake(page, "opendart-peers");
    assert.equal(page.root.getAttribute("data-theme"), "dark");
  },

  async "a peer table with highs, lows, negatives, basis badges, and companies left out"(open) {
    const page = await open();
    await page.show(ARGS, keyAccounts());
    assert.equal(page.byId("title").textContent, "Peer comparison: FY2025, auto basis, 3 companies");
    assert.equal(page.byId("subtitle").textContent, "Amounts in KRW million; percentages as shown");
    assert.deepEqual(page.table("head"), [[
      "Company", "Revenue", "Operating profit", "Operating margin (derived)", "Debt to equity (derived)",
    ]]);
    assert.deepEqual(page.table(), [
      ["SAMSUNG ELECTRONICS CO,.LTD 005930", "330,000,000.0", "44,000,000.0", "13.3%", "28.1%"],
      ["SK hynix Inc. 000660", "660,000,000.0", "-8,800,000.0", "-1.3%", "28.1%"],
      ["Kakao Corp. 035720separate", "–", "5,000,000.0", "6.1%", "45.2%"],
    ]);
    const classes = page.byId("body").byTag("tr").map((row) => row.children.slice(1).map((cell) => cell.className));
    assert.deepEqual(classes, [
      ["lo", "hi", "hi", "lo"],
      ["hi", "neg lo", "neg lo", "lo"],
      ["", "", "", "hi"],
    ]);
    assert.equal(page.byId("body").byTag("td")[0].title, "Lowest in this column");
    assert.equal(page.byId("body").byTag("th")[0].title, "SAMSUNG ELECTRONICS CO,.LTD · 삼성전자 · KOSPI");
    const missing = page.byId("missing");
    assert.equal(missing.hidden, false);
    assert.equal(missing.textContent, "Not included (1)zzzz nothing: No company matches; call find_company.");
    assert.deepEqual(page.byId("notes").children.map((item) => item.textContent), [
      "operating_margin = operating income / revenue (derived).",
    ]);
    assert.equal(page.byId("sources").textContent, "As of 2026-10-22 (KST).");
  },

  async "headings sort numbers from highest and names from A, missing values last"(open) {
    const page = await open();
    await page.show(ARGS, keyAccounts());
    const head = page.byId("head");
    const heading = (label) => head.byTag("th").find((cell) => cell.textContent === label);
    const [samsung, hynix, kakao] = names(page);
    assert.equal(heading("Revenue").getAttribute("aria-sort"), "none");
    heading("Revenue").children[0].click();
    assert.deepEqual(names(page), [hynix, samsung, kakao]);
    assert.equal(heading("Revenue").getAttribute("aria-sort"), "descending");
    heading("Revenue").children[0].click();
    assert.deepEqual(names(page), [samsung, hynix, kakao]);
    assert.equal(heading("Revenue").getAttribute("aria-sort"), "ascending");
    heading("Company").children[0].click();
    assert.deepEqual(names(page), [kakao, samsung, hynix]);
    assert.equal(heading("Company").getAttribute("aria-sort"), "ascending");
    assert.equal(heading("Revenue").getAttribute("aria-sort"), "none");
    heading("Company").children[0].click();
    assert.deepEqual(names(page), [hynix, samsung, kakao]);
    assert.equal(heading("Company").getAttribute("aria-sort"), "descending");
    heading("Debt to equity (derived)").children[0].click();
    assert.deepEqual(names(page), [kakao, samsung, hynix]);
    assert.equal(page.byId("body").byTag("tr")[0].children[4].className, "hi", "highlights follow the values");
    assert.equal(page.messages("tools/call").length, 0);
  },

  async "the metric set switch calls compare_companies with the original arguments"(open) {
    const page = await open({ onCall: () => result(ratios()) });
    await page.show(ARGS, keyAccounts());
    const metrics = page.byId("metrics");
    assert.deepEqual(metrics.children.map((choice) => choice.textContent), ["Key accounts", "Ratios", "Both"]);
    assert.equal(metrics.button("Key accounts").getAttribute("aria-pressed"), "true");
    page.byId("head").byTag("button")[1].click();
    metrics.button("Ratios").click();
    assert.ok(metrics.children.every((choice) => choice.disabled), "choices wait for the call");
    assert.equal(page.status(), "Loading…");
    await page.flush();
    assert.deepEqual(page.messages("tools/call").map((message) => message.params), [
      { name: "compare_companies", arguments: { ...ARGS, metrics: "ratios" } },
    ]);
    assert.equal(metrics.button("Ratios").getAttribute("aria-pressed"), "true");
    assert.ok(metrics.children.every((choice) => !choice.disabled));
    assert.deepEqual(page.table("head"), [["Company", "Gross margin", "ROE"]]);
    const sorts = page.byId("head").byTag("th").map((cell) => cell.getAttribute("aria-sort"));
    assert.deepEqual(sorts, ["none", "none", "none"], "sorting resets");
    assert.equal(page.byId("subtitle").textContent, "");
    assert.equal(page.byId("title").textContent, "Peer comparison: FY2025, auto basis, 2 companies");
    const updates = page.messages("ui/update-model-context").map((message) => message.params);
    assert.deepEqual(updates, [{
      content: [{
        type: "text",
        text: "The user is viewing ratios in the peer comparison app: FY2025, auto basis, 2 companies, "
          + "1 company not included.",
      }],
      structuredContent: { tool: "compare_companies", arguments: { ...ARGS, metrics: "ratios" } },
    }]);
  },

  async "errors and hosts without tool calls"(open) {
    const refusal = { content: [{ type: "text", text: "Quota exhausted." }], isError: true };
    const page = await open({ onCall: () => refusal });
    await page.show(ARGS, keyAccounts());
    page.byId("metrics").button("Both").click();
    await page.flush();
    assert.equal(page.status(), "Quota exhausted.");
    assert.equal(page.table().length, 3, "the table stays");
    assert.equal(page.byId("metrics").button("Key accounts").getAttribute("aria-pressed"), "true");
    const fixed = await open({ capabilities: {} });
    await fixed.show(ARGS, keyAccounts());
    assert.ok(fixed.byId("metrics").children.every((choice) => choice.disabled));
    assert.match(fixed.byId("metrics").title, /does not let apps call tools/);
  },

  async "without tool-input the switch names the companies shown and left out"(open) {
    const page = await open({ onCall: () => result(ratios()) });
    page.notify("ui/notifications/tool-result", result(keyAccounts()));
    page.byId("metrics").button("Ratios").click();
    await page.flush();
    assert.deepEqual(page.messages("tools/call")[0].params.arguments, {
      companies: ["00126380", "00164779", "00258801", "zzzz nothing"],
      metrics: "ratios",
    });
  },

  async "an empty table and a period-less heading"(open) {
    const page = await open();
    await page.show(ARGS, { ...keyAccounts(), rows: [], company_count: 0, fiscal_year: undefined, period: undefined });
    assert.equal(page.byId("title").textContent, "Peer comparison: auto basis, 0 companies");
    assert.deepEqual(page.table(), [["No company has data for this period."]]);
    await page.show(ARGS, { ...keyAccounts(), missing: [] });
    assert.equal(page.byId("missing").hidden, true);
  },
};
