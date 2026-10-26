// Offline harness for the OpenDART MCP Apps: runs each page's inline script against a DOM shim
// and a fake host. No browser, network, or packages; needs Node 20 or later.
// Usage: node harness.mjs path/to/financials.html path/to/peers.html path/to/calendar.html
// Each page is matched to its scenarios by file name; the exit code is 1 when any fails.
import { readFileSync } from "node:fs";
import { basename } from "node:path";

import calendar from "./harness_calendar.mjs";
import financials from "./harness_financials.mjs";
import peers from "./harness_peers.mjs";
import { boot } from "./harness_shim.mjs";

const SUITES = { financials, peers, calendar };

const paths = process.argv.slice(2);
if (paths.length === 0) {
  console.error("usage: node harness.mjs <app>.html ... (apps: " + Object.keys(SUITES).join(", ") + ")");
  process.exit(2);
}

let passed = 0;
let failed = 0;
for (const path of paths) {
  const app = basename(path, ".html");
  const suite = SUITES[app];
  if (!suite) {
    console.log("not ok - no scenarios for " + path);
    failed += 1;
    continue;
  }
  const html = readFileSync(path, "utf8");
  for (const [name, scenario] of Object.entries(suite)) {
    try {
      await scenario((options) => boot(html, { filename: app + ".js", ...options }));
      passed += 1;
      console.log("ok - " + app + ": " + name);
    } catch (error) {
      failed += 1;
      console.log("not ok - " + app + ": " + name + "\n" + (error && error.stack ? error.stack : error));
    }
  }
}
console.log(passed + " passed, " + failed + " failed");
// Exit now: requests the fake host never answered would otherwise keep their timers alive.
process.exit(failed ? 1 : 0);
