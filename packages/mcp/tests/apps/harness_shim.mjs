// DOM shim and fake MCP Apps host for running an app page's inline script in node:vm.
// The shim implements only what the apps use; helpers such as findAll are for assertions.
import assert from "node:assert/strict";
import vm from "node:vm";

const PROTOCOL_VERSION = "2026-01-26";
const FORBIDDEN = new RegExp(
  "\\b(innerHTML|outerHTML|insertAdjacentHTML|eval|fetch|XMLHttpRequest|WebSocket)\\b"
    + "|document\\.write|new Function|import\\(",
);

class Style {
  constructor() {
    this.properties = new Map();
  }
  setProperty(name, value) {
    this.properties.set(name, String(value));
  }
  getPropertyValue(name) {
    return this.properties.get(name) || "";
  }
}

export class Element {
  constructor(tagName, id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.listeners = new Map();
    this.style = new Style();
    this.className = "";
    this.title = "";
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.ownText = "";
  }
  get textContent() {
    return this.ownText + this.children.map((child) => child.textContent).join("");
  }
  set textContent(value) {
    this.ownText = String(value);
    this.children = [];
  }
  appendChild(child) {
    assert.ok(child instanceof Element, "only elements are appended");
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  replaceChildren(...nodes) {
    this.ownText = "";
    this.children = [];
    for (const node of nodes) this.appendChild(node);
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }
  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }
  hasAttribute(name) {
    return this.attributes.has(name);
  }
  removeAttribute(name) {
    this.attributes.delete(name);
  }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }
  dispatch(type) {
    for (const listener of this.listeners.get(type) || []) listener({ type, target: this, currentTarget: this });
  }
  click() {
    if (!this.disabled) this.dispatch("click");
  }
  // Assertion helpers below; not part of the DOM.
  findAll(predicate) {
    const found = [];
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      found.push(...child.findAll(predicate));
    }
    return found;
  }
  byTag(tag) {
    return this.findAll((node) => node.tagName === tag.toUpperCase());
  }
  button(label) {
    const found = this.findAll((node) => node.tagName === "BUTTON" && node.textContent === label);
    assert.equal(found.length, 1, "one button labeled " + label);
    return found[0];
  }
  classes() {
    return this.className.split(/\s+/).filter(Boolean);
  }
}

// Check the page-level constraints, then return its inline script and static elements.
export function inspectPage(html) {
  const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map((match) => match[1]);
  assert.equal(scripts.length, 1, "exactly one inline script");
  assert.ok(!/<script[^>]*\bsrc\s*=/i.test(html), "no external scripts");
  assert.ok(!/<link\b/i.test(html), "no linked stylesheets or icons");
  assert.ok(!/https?:\/\//i.test(html), "no absolute URLs: the page is self-contained");
  assert.ok(!/@import|\burl\(/.test(html), "no stylesheet imports or external images");
  assert.ok(!FORBIDDEN.test(html), "no HTML parsing, eval, or network APIs");
  assert.ok(html.startsWith("<!doctype html>"), "an HTML5 document");
  const elements = [];
  for (const [, tag, attributes, text] of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*)>([^<]*)/gi)) {
    const id = /\bid="([^"]+)"/.exec(attributes);
    if (id) elements.push({ tag, id: id[1], hidden: /\shidden\b/.test(attributes), text: text.trim() });
  }
  return { script: scripts[0], elements };
}

// A page under test: its DOM, the messages it sent, and a fake host that answers them.
export class Page {
  constructor(elements, options) {
    this.options = { capabilities: { serverTools: {}, openLinks: {} }, context: {}, ...options };
    this.sent = [];
    this.listeners = [];
    this.observers = [];
    this.root = new Element("html");
    this.root.contentHeight = 300;
    this.root.getBoundingClientRect = () => ({ width: 640, height: this.root.contentHeight });
    this.head = new Element("head");
    this.body = new Element("body");
    for (const { tag, id, hidden, text } of elements) {
      this.body.appendChild(Object.assign(new Element(tag, id), { hidden, ownText: text }));
    }
    this.parent = { postMessage: (message, origin) => this.receive(message, origin) };
  }

  globals() {
    const page = this;
    class ResizeObserver {
      constructor(callback) {
        this.callback = callback;
        this.targets = [];
        page.observers.push(this);
      }
      observe(target) {
        this.targets.push(target);
      }
    }
    const window = {
      parent: this.parent,
      innerWidth: 640,
      addEventListener: (type, listener) => type === "message" && this.listeners.push(listener),
    };
    const document = {
      documentElement: this.root,
      head: this.head,
      body: this.body,
      createElement: (tag) => new Element(tag),
      getElementById: (id) => this.byId(id, false),
    };
    return { window, document, ResizeObserver, URL, setTimeout, clearTimeout, console };
  }

  byId(id, required = true) {
    const found = [this.head, this.body].flatMap((root) => root.findAll((node) => node.id === id));
    if (required) assert.equal(found.length, 1, "one element with id " + id);
    return found[0] || null;
  }

  // App to host: record a copy, then answer requests asynchronously, like postMessage.
  receive(message, origin) {
    assert.equal(origin, "*", "messages target the host's unknown origin");
    const copy = structuredClone(message);
    assert.equal(copy.jsonrpc, "2.0");
    this.sent.push(copy);
    if (copy.id !== undefined && copy.method !== undefined) setImmediate(() => this.answer(copy));
  }

  async answer(message) {
    const reply = (body) => this.deliver({ id: message.id, ...body });
    if (message.method === "ui/initialize") {
      reply({ result: {
        protocolVersion: PROTOCOL_VERSION,
        hostInfo: { name: "harness", version: "1.0.0" },
        hostCapabilities: this.options.capabilities,
        hostContext: this.options.context,
      } });
    } else if (message.method === "tools/call") {
      const call = this.options.onCall || (() => ({ error: { code: -32601, message: "no tools" } }));
      const outcome = await call(message.params);
      reply(outcome && outcome.error ? { error: outcome.error } : { result: outcome });
    } else if (message.method === "ui/open-link" && this.options.denyLinks) {
      reply({ error: { code: -32000, message: "Link opening denied by user" } });
    } else {
      reply({ result: {} });
    }
  }

  // Host to app.
  deliver(data, source = this.parent) {
    for (const listener of this.listeners) listener({ source, data: { jsonrpc: "2.0", ...data } });
  }

  notify(method, params) {
    this.deliver({ method, params });
  }

  messages(method) {
    return this.sent.filter((message) => message.method === method);
  }

  responses() {
    return this.sent.filter((message) => message.method === undefined);
  }

  resize(height) {
    this.root.contentHeight = height;
    for (const observer of this.observers) observer.callback([]);
  }

  async flush() {
    for (let turn = 0; turn < 5; turn += 1) await new Promise((resolve) => setTimeout(resolve, 1));
  }

  // Deliver the tool call that created the view: its arguments, then its result.
  async show(args, structuredContent, text = "| text view |") {
    this.notify("ui/notifications/tool-input", { arguments: args });
    this.notify("ui/notifications/tool-result", { content: [{ type: "text", text }], structuredContent });
    await this.flush();
  }

  // Cell texts of the table body, one array per row.
  table(id = "body") {
    return this.byId(id).byTag("tr").map((row) => row.children.map((cell) => cell.textContent));
  }

  status() {
    return this.byId("status").textContent;
  }
}

export async function boot(html, options = {}) {
  const { script, elements } = inspectPage(html);
  const page = new Page(elements, options);
  vm.runInNewContext(script, page.globals(), { filename: options.filename || "app.js" });
  await page.flush();
  return page;
}

// The handshake every app performs: initialize, initialized, then size reports.
export function checkHandshake(page, appName) {
  const [first] = page.sent;
  assert.equal(first.method, "ui/initialize", "the first message is ui/initialize");
  assert.equal(first.params.protocolVersion, PROTOCOL_VERSION);
  assert.deepEqual(first.params.appInfo, { name: appName, version: "1.0.0" });
  assert.deepEqual(first.params.appCapabilities, { availableDisplayModes: ["inline", "fullscreen"] });
  const methods = page.sent.map((message) => message.method);
  assert.equal(methods[1], "ui/notifications/initialized", "initialized follows the handshake");
  assert.equal(methods[2], "ui/notifications/size-changed", "the size is reported once initialized");
  assert.deepEqual(page.sent[2].params, { width: 640, height: 300 });
  assert.equal(page.observers.length, 1, "one resize observer");
  assert.deepEqual(page.observers[0].targets, [page.root, page.body]);
}
