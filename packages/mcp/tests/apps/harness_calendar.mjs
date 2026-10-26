// Scenarios for the corporate-action calendar app (get_corporate_action_calendar).
import assert from "node:assert/strict";

import { checkHandshake } from "./harness_shim.mjs";

const SAMSUNG = {
  name: "SAMSUNG ELECTRONICS CO,.LTD",
  korean_name: "삼성전자",
  corp_code: "00126380",
  stock_code: "005930",
  market: "KOSPI",
};
const HYNIX = { name: "SK hynix Inc.", corp_code: "00164779", stock_code: "000660", market: "KOSPI" };
const ARGS = { companies: ["005930", "000660"], horizon: "90d", include_past: "7d" };
const SAMSUNG_LABEL = "SAMSUNG ELECTRONICS CO,.LTD (005930)";
const HYNIX_LABEL = "SK hynix Inc. (000660)";
const viewer = (number) => "https://englishdart.fss.or.kr/dsbh001/main.do?rcpNo=" + number;

function item(date, company, action, sourceKind, number, details) {
  return { date, company, action, source_kind: sourceKind, filing_number: number, dart_url: viewer(number), details };
}

function calendar() {
  return {
    as_of: "2026-10-22",
    source_filings: [],
    notes: ["Dates come from major-issue and registration filings of the past year."],
    start: "2026-10-15",
    end: "2027-01-20",
    horizon_days: 90,
    companies: [SAMSUNG, HYNIX],
    items: [
      item("2026-10-20", HYNIX, "buyback_start", "treasury_stock_acquisition", "20261019000305", {
        event: "Treasury stock acquisition", shares: 175467,
      }),
      item("2026-10-22", SAMSUNG, "record_date", "merger", "20260901000456", { event: "Merger" }),
      item("2026-11-03", SAMSUNG, "short_sale_ban_start", "rights_issue", "20260801000777", {
        event: "Rights issue", price: 52000.5,
      }),
      item("2026-11-12", SAMSUNG, "subscription", "convertible_bond", "20260915000123", {
        event: "Convertible bond", face_value: 30000000000, series: "3",
      }),
      item("2026-11-13", HYNIX, "debt_maturity", "debt_securities", "20260310002820", {
        event: "Debt maturity", instrument: "Corporate bond", amount: 50000000000, coupon: 3.25,
      }),
    ],
  };
}

function select(page, id, value) {
  const element = page.byId(id);
  element.value = value;
  element.dispatch("change");
}

export default {
  async "handshake and size reports"(open) {
    const page = await open();
    checkHandshake(page, "opendart-calendar");
  },

  async "dates grouped by week with humanized actions, terms, and past dates muted"(open) {
    const page = await open();
    await page.show(ARGS, calendar());
    assert.equal(page.byId("subtitle").textContent, "2026-10-15 to 2027-01-20 · 2 companies · horizon 90 days");
    assert.equal(page.byId("count").textContent, "5 dates");
    assert.deepEqual(page.table(), [
      ["Week of Mon 2026-10-19 · 2 dates"],
      [
        "Tue 2026-10-20", HYNIX_LABEL, "Buyback start", "Treasury stock acquisition", "Shares 175,467",
        "20261019000305",
      ],
      ["Thu 2026-10-22", SAMSUNG_LABEL, "Record date", "Merger", "", "20260901000456"],
      ["Week of Mon 2026-11-02 · 1 date"],
      ["Tue 2026-11-03", SAMSUNG_LABEL, "Short sale ban start", "Rights issue", "Price 52,000.50", "20260801000777"],
      ["Week of Mon 2026-11-09 · 2 dates"],
      [
        "Thu 2026-11-12", SAMSUNG_LABEL, "Subscription", "Convertible bond", "Face value 30,000,000,000; Series 3",
        "20260915000123",
      ],
      [
        "Fri 2026-11-13", HYNIX_LABEL, "Debt maturity", "Debt maturity",
        "Instrument Corporate bond; Amount 50,000,000,000; Coupon 3.25", "20260310002820",
      ],
    ]);
    const rows = page.byId("body").byTag("tr");
    assert.deepEqual(rows.map((row) => row.className), ["week", "past", "today", "week", "", "week", "", ""]);
    assert.equal(rows[0].children[0].getAttribute("colspan"), "6");
    assert.equal(rows[2].children[1].title, "삼성전자");
    assert.equal(rows[4].children[2].title, "short_sale_ban_start");
    assert.deepEqual(page.byId("notes").children.map((note) => note.textContent), [
      "Dates come from major-issue and registration filings of the past year.",
    ]);
    assert.equal(page.byId("sources").textContent, "As of 2026-10-22 (KST).");
  },

  async "company and action filters narrow the dates and tell the model"(open) {
    const page = await open();
    await page.show(ARGS, calendar());
    const options = (id) => page.byId(id).children.map((option) => [option.getAttribute("value"), option.textContent]);
    assert.deepEqual(options("company"), [
      ["", "All companies"],
      ["00126380", SAMSUNG_LABEL],
      ["00164779", HYNIX_LABEL],
    ]);
    assert.deepEqual(options("action"), [
      ["", "All actions"],
      ["buyback_start", "Buyback start"],
      ["debt_maturity", "Debt maturity"],
      ["record_date", "Record date"],
      ["short_sale_ban_start", "Short sale ban start"],
      ["subscription", "Subscription"],
    ]);
    select(page, "company", "00164779");
    assert.deepEqual(page.table().map((row) => row[0]), [
      "Week of Mon 2026-10-19 · 1 date", "Tue 2026-10-20", "Week of Mon 2026-11-09 · 1 date", "Fri 2026-11-13",
    ]);
    assert.equal(page.byId("count").textContent, "2 of 5 dates");
    select(page, "action", "debt_maturity");
    assert.deepEqual(page.table().map((row) => row[0]), ["Week of Mon 2026-11-09 · 1 date", "Fri 2026-11-13"]);
    select(page, "company", "00126380");
    assert.deepEqual(page.table(), [["No dates match these filters."]]);
    select(page, "company", "");
    select(page, "action", "");
    assert.equal(page.byId("count").textContent, "5 dates");
    await page.flush();
    const updates = page.messages("ui/update-model-context").map((message) => message.params);
    assert.equal(updates.length, 5);
    assert.deepEqual(updates[1], {
      content: [{
        type: "text",
        text: "The user is viewing the corporate-action calendar filtered to SK hynix Inc. and Debt maturity: "
          + "1 of 5 dates.",
      }],
      structuredContent: { company: "00164779", action: "debt_maturity", shown: 1, total: 5 },
    });
    assert.equal(
      updates[4].content[0].text,
      "The user is viewing the corporate-action calendar with every company and action: 5 of 5 dates.",
    );
    select(page, "company", "00164779");
    page.notify("ui/notifications/tool-result", { content: [], structuredContent: calendar() });
    assert.equal(page.byId("company").value, "00164779", "selections survive a new result");
    assert.equal(page.byId("count").textContent, "2 of 5 dates");
  },

  async "filing numbers open the DART viewer only for DART links and only when allowed"(open) {
    const data = calendar();
    data.items[0].dart_url = "javascript:alert(1)";
    data.items[1].dart_url = "https://example.com/dsbh001/main.do";
    const page = await open();
    await page.show(ARGS, data);
    const links = page.byId("body").byTag("button");
    assert.deepEqual(links.map((link) => link.textContent), ["20260801000777", "20260915000123", "20260310002820"]);
    assert.equal(links[0].className, "link");
    links[0].click();
    await page.flush();
    const opened = page.messages("ui/open-link").map((message) => message.params);
    assert.deepEqual(opened, [{ url: viewer("20260801000777") }]);
    const plain = await open({ capabilities: { serverTools: {} } });
    await plain.show(ARGS, calendar());
    assert.equal(plain.byId("body").byTag("button").length, 0, "no links without the openLinks capability");
    assert.equal(plain.table()[1][5], "20261019000305");
  },

  async "an empty window, companies from items, and a missing result"(open) {
    const page = await open();
    await page.show(ARGS, { ...calendar(), items: [], notes: [] });
    assert.deepEqual(page.table(), [["No corporate-action dates in this window."]]);
    assert.equal(page.byId("count").textContent, "0 dates");
    const data = calendar();
    delete data.companies;
    await page.show(ARGS, data);
    assert.equal(page.byId("company").children.length, 3, "companies come from the items");
    page.notify("ui/notifications/tool-result", { content: [{ type: "text", text: "boom" }], isError: true });
    assert.equal(page.status(), "boom");
    assert.equal(page.byId("status").className, "status error");
  },
};
