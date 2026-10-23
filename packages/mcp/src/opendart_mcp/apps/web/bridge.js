// MCP Apps host bridge (SEP-1865, protocol 2026-01-26): JSON-RPC 2.0 over postMessage.
// Shared by every OpenDART app page. The server inlines it, so a page loads no other code.

const PROTOCOL_VERSION = "2026-01-26";
const REQUEST_TIMEOUT_MS = 120000;
const METHOD_NOT_FOUND = -32601;
const DISPLAY_MODES = ["inline", "fullscreen"];

// Connect to the host. `app` names the page and receives its data:
// { name, version, onInput(args), onResult(callToolResult), onCancel(reason), onReady(), onError(text) }.
function connectHost(app) {
  const pending = new Map();
  const host = { capabilities: {}, context: {}, ready: false };
  let nextId = 1;

  const send = (message) => window.parent.postMessage({ jsonrpc: "2.0", ...message }, "*");
  const notify = (method, params) => send({ method, params: params || {} });

  function request(method, params) {
    return new Promise((resolve, reject) => {
      const id = nextId++;
      const timer = setTimeout(() => {
        pending.delete(id);
        reject(new Error("the host did not answer " + method));
      }, REQUEST_TIMEOUT_MS);
      pending.set(id, { resolve, reject, timer });
      send({ id, method, params: params || {} });
    });
  }

  // A response to one of our requests.
  function settle(message) {
    const entry = pending.get(message.id);
    if (!entry) return;
    pending.delete(message.id);
    clearTimeout(entry.timer);
    if (message.error) entry.reject(new Error(message.error.message || "the host reported an error"));
    else entry.resolve(message.result);
  }

  // A request from the host: answer liveness and teardown, refuse anything else.
  function answer(message) {
    if (message.method === "ping" || message.method === "ui/resource-teardown") {
      send({ id: message.id, result: {} });
      return;
    }
    send({ id: message.id, error: { code: METHOD_NOT_FOUND, message: "Method not found: " + message.method } });
  }

  const handlers = {
    "ui/notifications/tool-input": (params) => app.onInput(params.arguments || {}),
    "ui/notifications/tool-result": (params) => app.onResult(params),
    "ui/notifications/tool-cancelled": (params) => app.onCancel(params.reason || ""),
    "ui/notifications/host-context-changed": (params) => applyContext(params),
  };

  window.addEventListener("message", (event) => {
    const message = event.data;
    if (event.source !== window.parent || !message || message.jsonrpc !== "2.0") return;
    if (message.method === undefined) {
      settle(message);
    } else if (message.id !== undefined) {
      answer(message);
    } else if (Object.hasOwn(handlers, message.method)) {
      try {
        handlers[message.method](message.params || {});
      } catch (error) {
        app.onError("Could not show the result: " + (error && error.message ? error.message : error));
      }
    }
  });

  // Theme, host styles and fonts, and container size; updates are partial and merged.
  function applyContext(update) {
    const context = update || {};
    Object.assign(host.context, context);
    const root = document.documentElement;
    if (context.theme === "light" || context.theme === "dark") {
      root.setAttribute("data-theme", context.theme);
      root.style.colorScheme = context.theme;
    }
    const styles = context.styles || {};
    for (const [name, value] of Object.entries(styles.variables || {})) {
      if (name.startsWith("--") && typeof value === "string") root.style.setProperty(name, value);
    }
    if (styles.css && typeof styles.css.fonts === "string") useFonts(styles.css.fonts);
    if (context.containerDimensions) fit(context.containerDimensions);
  }

  function useFonts(css) {
    let style = document.getElementById("host-fonts");
    if (!style) {
      style = document.createElement("style");
      style.id = "host-fonts";
      document.head.appendChild(style);
    }
    style.textContent = css;
  }

  // A fixed container height means fill it; a maximum height caps the page.
  function fit(box) {
    const root = document.documentElement;
    if (typeof box.height === "number") root.setAttribute("data-fill", "");
    else root.removeAttribute("data-fill");
    root.style.maxHeight = typeof box.maxHeight === "number" ? box.maxHeight + "px" : "";
  }

  // Report the content size whenever it changes; a page of height zero is invisible.
  function watchSize() {
    let scheduled = false;
    let last = "";
    const measure = () => {
      scheduled = false;
      const root = document.documentElement;
      const saved = root.style.height;
      root.style.height = "max-content";
      const height = Math.ceil(root.getBoundingClientRect().height);
      root.style.height = saved;
      const width = Math.ceil(window.innerWidth);
      if (width + "x" + height === last) return;
      last = width + "x" + height;
      notify("ui/notifications/size-changed", { width, height });
    };
    const schedule = () => {
      if (scheduled) return;
      scheduled = true;
      setTimeout(measure, 0);
    };
    schedule();
    if (typeof ResizeObserver === "function") {
      const observer = new ResizeObserver(schedule);
      observer.observe(document.documentElement);
      observer.observe(document.body);
    }
  }

  request("ui/initialize", {
    appInfo: { name: app.name, version: app.version },
    appCapabilities: { availableDisplayModes: DISPLAY_MODES },
    protocolVersion: PROTOCOL_VERSION,
  }).then((result) => {
    const init = result || {};
    host.capabilities = init.hostCapabilities || {};
    host.ready = true;
    applyContext(init.hostContext);
    notify("ui/notifications/initialized");
    watchSize();
    app.onReady();
  }).catch((error) => app.onError("Could not connect to the host: " + error.message));

  return {
    canCallTools: () => host.ready && Boolean(host.capabilities.serverTools),
    canOpenLinks: () => host.ready && Boolean(host.capabilities.openLinks),
    callTool: (name, args) => request("tools/call", { name, arguments: args }),
    openLink: (url) => request("ui/open-link", { url }),
    // Tell the model what the user now sees; the host sends the latest update with the next turn.
    setModelContext(text, data) {
      const params = { content: [{ type: "text", text }] };
      if (data) params.structuredContent = data;
      request("ui/update-model-context", params).catch(() => {});
    },
  };
}
