import { connectSSE, EventType } from "./sse/sse-client.js";
function toKebabCase(str) {
  return str.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`);
}
function fromAttribute(value, type) {
  switch (type) {
    case Boolean:
      return value !== null;
    case Number:
      return value === null ? null : Number(value);
    default:
      return value;
  }
}
function toAttribute(value, type) {
  switch (type) {
    case Boolean:
      return value ? "" : null;
    case Number:
      return value == null ? null : String(value);
    default:
      return value == null ? null : String(value);
  }
}
class CkBase extends HTMLElement {
  static properties = {};
  /** Shared stylesheets adopted by all instances of this component. */
  static styles = [];
  #cleanups = [];
  #updateRequested = false;
  #connected = false;
  // Property values stored here (keyed by property name)
  #values = /* @__PURE__ */ new Map();
  static get observedAttributes() {
    return Object.entries(this.properties).map(
      ([name, decl]) => decl.attribute ?? toKebabCase(name)
    );
  }
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.#defineReactiveProperties();
    const ctor = this.constructor;
    if (ctor.styles.length > 0) {
      this.shadowRoot.adoptedStyleSheets = [...ctor.styles];
    }
  }
  #defineReactiveProperties() {
    const ctor = this.constructor;
    for (const [name, decl] of Object.entries(ctor.properties)) {
      let initialValue = this[name];
      this.#values.set(name, initialValue);
      Object.defineProperty(this, name, {
        get: () => this.#values.get(name),
        set: (newValue) => {
          const oldValue = this.#values.get(name);
          if (Object.is(oldValue, newValue)) return;
          this.#values.set(name, newValue);
          if (decl.reflect) {
            this.#reflectToAttribute(name, newValue, decl);
          }
          if (this.#connected) {
            this.requestUpdate();
          }
        },
        configurable: true,
        enumerable: true
      });
    }
  }
  #reflectToAttribute(name, value, decl) {
    const attrName = decl.attribute ?? toKebabCase(name);
    const attrValue = toAttribute(value, decl.type);
    if (attrValue === null) {
      this.removeAttribute(attrName);
    } else {
      this.setAttribute(attrName, attrValue);
    }
  }
  attributeChangedCallback(name, _old, value) {
    const ctor = this.constructor;
    for (const [prop, decl] of Object.entries(ctor.properties)) {
      const attrName = decl.attribute ?? toKebabCase(prop);
      if (attrName === name) {
        this[prop] = fromAttribute(value, decl.type);
        break;
      }
    }
  }
  connectedCallback() {
    this.#connected = true;
    this.requestUpdate();
  }
  disconnectedCallback() {
    this.#connected = false;
    for (const fn of this.#cleanups) {
      try {
        fn();
      } catch {
      }
    }
    this.#cleanups.length = 0;
  }
  /** Register a cleanup function that runs on disconnectedCallback. */
  addCleanup(fn) {
    this.#cleanups.push(fn);
  }
  /** Add an event listener with automatic cleanup on disconnect. */
  listen(target, event, handler, options) {
    target.addEventListener(event, handler, options);
    this.#cleanups.push(
      () => target.removeEventListener(event, handler, options)
    );
  }
  /** Request a batched update via queueMicrotask. */
  requestUpdate() {
    if (this.#updateRequested) return;
    this.#updateRequested = true;
    queueMicrotask(() => {
      this.#updateRequested = false;
      if (this.#connected) {
        this.update();
      }
    });
  }
}
const StreamState = {
  IDLE: "idle",
  SENDING: "sending",
  STREAMING: "streaming",
  FINALIZING: "finalizing"
};
class StreamStateMachine {
  #state = StreamState.IDLE;
  #callbacks;
  #abortController = null;
  constructor(callbacks) {
    this.#callbacks = callbacks;
  }
  get state() {
    return this.#state;
  }
  get signal() {
    return this.#abortController?.signal ?? null;
  }
  get isIdle() {
    return this.#state === StreamState.IDLE;
  }
  get isStreaming() {
    return this.#state === StreamState.SENDING || this.#state === StreamState.STREAMING;
  }
  /** Transition to SENDING state. Returns false if not idle. */
  startSending() {
    if (this.#state !== StreamState.IDLE) return false;
    this.#abortController = new AbortController();
    this.#transition(StreamState.SENDING);
    return true;
  }
  /** Transition to STREAMING state. Returns false if not in SENDING. */
  startStreaming() {
    if (this.#state !== StreamState.SENDING) return false;
    this.#transition(StreamState.STREAMING);
    return true;
  }
  /**
   * Finalize the stream. Idempotent — first caller wins, subsequent calls are no-ops.
   * Aborts the controller if not already aborted, then transitions to IDLE.
   */
  finalize(reason, error) {
    if (this.#state !== StreamState.SENDING && this.#state !== StreamState.STREAMING) {
      return;
    }
    this.#transition(StreamState.FINALIZING);
    if (this.#abortController && !this.#abortController.signal.aborted) {
      this.#abortController.abort();
    }
    this.#callbacks.onFinalize(reason, error);
    this.#abortController = null;
    this.#transition(StreamState.IDLE);
  }
  /** Force-reset to IDLE (for disconnectedCallback cleanup). */
  reset() {
    if (this.#abortController && !this.#abortController.signal.aborted) {
      this.#abortController.abort();
    }
    this.#abortController = null;
    this.#state = StreamState.IDLE;
  }
  #transition(to) {
    const from = this.#state;
    this.#state = to;
    this.#callbacks.onStateChange(from, to);
  }
}
const resetSheet = new CSSStyleSheet();
resetSheet.replaceSync(`
  *, *::before, *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }
  :host {
    display: block;
    font-family: var(--ck-font, system-ui, sans-serif);
    font-size: var(--ck-font-size, 0.9375rem);
    line-height: var(--ck-line-height, 1.6);
    color: var(--ck-text, #ececec);
  }
  :host([hidden]) {
    display: none;
  }
`);
const animationsSheet = new CSSStyleSheet();
animationsSheet.replaceSync(`
  @keyframes ck-fade-in {
    from { opacity: 0; transform: translateY(8px) scale(0.98); }
    to   { opacity: 1; transform: translateY(0) scale(1); }
  }
  @keyframes ck-pulse-dot {
    0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
    40% { opacity: 1; transform: scale(1); }
  }
  @keyframes ck-spin {
    to { transform: rotate(360deg); }
  }
  @keyframes ck-glow-pulse {
    0%, 100% { box-shadow: 0 0 0 0 var(--ck-accent-glow, rgba(34, 197, 94, 0.25)); }
    50% { box-shadow: 0 0 16px 2px var(--ck-accent-glow, rgba(34, 197, 94, 0.25)); }
  }
`);
const markdownSheet = new CSSStyleSheet();
markdownSheet.replaceSync(`
  .ck-markdown {
    line-height: var(--ck-line-height, 1.6);
    word-wrap: break-word;
    overflow-wrap: break-word;
  }
  .ck-markdown p { margin-bottom: 0.75em; }
  .ck-markdown p:last-child { margin-bottom: 0; }
  .ck-markdown h1, .ck-markdown h2, .ck-markdown h3,
  .ck-markdown h4, .ck-markdown h5, .ck-markdown h6 {
    margin-top: 1em;
    margin-bottom: 0.5em;
    font-weight: 600;
    line-height: 1.3;
  }
  .ck-markdown h1 { font-size: 1.4em; }
  .ck-markdown h2 { font-size: 1.25em; }
  .ck-markdown h3 { font-size: 1.1em; }
  .ck-markdown ul, .ck-markdown ol {
    padding-left: 1.5em;
    margin-bottom: 0.75em;
  }
  .ck-markdown li { margin-bottom: 0.25em; }
  .ck-markdown code {
    background: var(--ck-bg-code, #0d1117);
    padding: 0.15em 0.4em;
    border-radius: 4px;
    font-family: var(--ck-font-mono, monospace);
    font-size: 0.85em;
    border: 1px solid var(--ck-border, #1e1e1e);
  }
  .ck-markdown pre {
    background: var(--ck-bg-code, #0d1117);
    padding: 1em;
    border-radius: var(--ck-radius, 0.75rem);
    overflow-x: auto;
    margin-bottom: 0.75em;
    border: 1px solid var(--ck-border, #1e1e1e);
  }
  .ck-markdown pre code {
    background: none;
    padding: 0;
    font-size: 0.85em;
    border: none;
  }
  .ck-markdown blockquote {
    border-left: 3px solid var(--ck-accent, #22c55e);
    padding-left: 1em;
    margin-bottom: 0.75em;
    color: var(--ck-text-secondary, #A1A1A1);
  }
  .ck-markdown table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 0.75em;
    font-size: 0.875em;
  }
  .ck-markdown th, .ck-markdown td {
    padding: 0.5em 0.75em;
    border: 1px solid var(--ck-border, #3d3d3d);
    text-align: left;
  }
  .ck-markdown th {
    background: var(--ck-table-header, #2a2a2a);
    font-weight: 600;
  }
  .ck-markdown a {
    color: var(--ck-accent, #22c55e);
    text-decoration: none;
  }
  .ck-markdown a:hover {
    text-decoration: underline;
  }
  .ck-markdown hr {
    border: none;
    border-top: 1px solid var(--ck-border, #3d3d3d);
    margin: 1em 0;
  }
  .ck-markdown strong { font-weight: 600; }
`);
const componentSheet$6 = new CSSStyleSheet();
componentSheet$6.replaceSync(`
  :host {
    display: flex;
    flex-direction: row;
    height: 100%;
    width: 100%;
    overflow: hidden;
    background:
      radial-gradient(ellipse at 70% 20%, var(--ck-accent-glow, rgba(34, 197, 94, 0.25)) 0%, transparent 50%),
      radial-gradient(ellipse at 20% 80%, rgba(5, 150, 105, 0.06) 0%, transparent 40%),
      var(--ck-bg, #0A0A0A);
    color: var(--ck-text, #F0F0F0);
  }
  .sidebar-area {
    flex-shrink: 0;
  }
  .main-area {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 0;
    height: 100%;
    overflow: hidden;
  }
  ::slotted(ck-messages) {
    flex: 1;
    min-height: 0;
  }
`);
class CkApp extends CkBase {
  static properties = {
    apiBase: { type: String, attribute: "api-base" },
    theme: { type: String, attribute: "theme", reflect: true }
  };
  static styles = [resetSheet, componentSheet$6];
  /** Optional callback to inject custom headers before each fetch. */
  onBeforeFetch = null;
  #stream;
  #threadId = null;
  #currentConnection = null;
  #currentAssistantMsg = null;
  constructor() {
    super();
    this.#stream = new StreamStateMachine({
      onStateChange: (from, to) => {
        this.#onStreamStateChange(from, to);
      },
      onFinalize: (reason, error) => {
        this.#onStreamFinalize(reason, error);
      }
    });
  }
  /** The current thread ID, if any. */
  get threadId() {
    return this.#threadId;
  }
  connectedCallback() {
    super.connectedCallback();
    const stored = localStorage.getItem("ck-theme");
    if (stored === "light" || stored === "dark") {
      this.setTheme(stored);
    } else {
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      this.setTheme(prefersDark ? "dark" : "light");
    }
    this.listen(this, "ck-submit", ((e) => {
      this.#handleSubmit(e.detail.message);
    }));
    this.listen(this, "ck-stop", (() => {
      this.#stream.finalize("aborted");
    }));
    this.listen(this, "ck-thread-select", ((e) => {
      this.loadThread(e.detail.threadId);
    }));
    this.listen(this, "ck-thread-delete", ((e) => {
      this.deleteThread(e.detail.threadId);
    }));
    this.listen(this, "ck-new-chat", (() => {
      this.newChat();
    }));
    this.loadThreads();
  }
  disconnectedCallback() {
    this.#stream.reset();
    super.disconnectedCallback();
  }
  // ── Theme ─────────────────────────────────────────────────────────
  /** Toggle between light and dark themes. */
  toggleTheme() {
    this.setTheme(this.theme === "light" ? "dark" : "light");
  }
  /** Set the theme explicitly. */
  setTheme(theme) {
    this.theme = theme;
    if (theme === "light") {
      document.documentElement.classList.add("light");
    } else {
      document.documentElement.classList.remove("light");
    }
    localStorage.setItem("ck-theme", theme);
  }
  // ── DOM Queries ───────────────────────────────────────────────────
  #getMessages() {
    return this.querySelector("ck-messages");
  }
  #getInput() {
    return this.querySelector("ck-input");
  }
  #getSidebar() {
    return this.querySelector("ck-sidebar");
  }
  // ── Conversation CRUD ─────────────────────────────────────────────
  /** Load the thread list into the sidebar. */
  async loadThreads() {
    if (!this.apiBase) return;
    try {
      const headers = await this.#getHeaders(this.apiBase + "/conversations");
      const res = await fetch(this.apiBase + "/conversations", { headers });
      if (!res.ok) return;
      const data = await res.json();
      const sidebar = this.#getSidebar();
      if (sidebar && "setThreads" in sidebar && typeof sidebar.setThreads === "function") {
        sidebar.setThreads(data);
      }
    } catch {
    }
  }
  /** Load a specific thread's messages. */
  async loadThread(id) {
    if (!this.apiBase) return;
    const messages = this.#getMessages();
    if (!messages) return;
    if (this.#stream.isStreaming) {
      this.#stream.finalize("aborted");
    }
    try {
      const headers = await this.#getHeaders(this.apiBase + "/conversations/" + id);
      const res = await fetch(this.apiBase + "/conversations/" + id, { headers });
      if (!res.ok) return;
      const data = await res.json();
      this.#threadId = id;
      messages.clear();
      if (data.messages) {
        for (const msg of data.messages) {
          const el = document.createElement("ck-message");
          el.role = msg.role;
          el.setContent(msg.content);
          if (msg.role === "user") {
            messages.addMessage(el);
          } else {
            messages.addTurnPhase(el);
            messages.resetTurn();
          }
        }
      }
    } catch {
    }
  }
  /** Delete a thread. */
  async deleteThread(id) {
    if (!this.apiBase) return;
    if (this.#threadId === id && this.#stream.isStreaming) {
      this.#stream.finalize("deleted");
    }
    try {
      const headers = await this.#getHeaders(this.apiBase + "/conversations/" + id);
      await fetch(this.apiBase + "/conversations/" + id, {
        method: "DELETE",
        headers
      });
      await this.loadThreads();
      if (this.#threadId === id) {
        this.newChat();
      }
    } catch {
    }
  }
  /** Start a new chat — clear messages and thread ID. */
  newChat() {
    if (this.#stream.isStreaming) {
      this.#stream.finalize("aborted");
    }
    this.#threadId = null;
    this.#currentAssistantMsg = null;
    const messages = this.#getMessages();
    messages?.clear();
    const input = this.#getInput();
    input?.focusInput();
  }
  // ── Message Sending ───────────────────────────────────────────────
  async #handleSubmit(message) {
    const beforeSend = new CustomEvent("ck-before-send", {
      bubbles: true,
      composed: true,
      cancelable: true,
      detail: { message, metadata: {} }
    });
    this.dispatchEvent(beforeSend);
    if (beforeSend.defaultPrevented) return;
    const metadata = beforeSend.detail.metadata;
    const messages = this.#getMessages();
    if (!messages) return;
    const userMsg = document.createElement("ck-message");
    userMsg.role = "user";
    userMsg.setContent(message);
    messages.addMessage(userMsg);
    if (!this.#stream.startSending()) return;
    const signal = this.#stream.signal;
    if (!signal) return;
    try {
      if (signal.aborted) return;
      const url = this.apiBase + "/chat";
      const customHeaders = await this.#getHeaders(url);
      this.#currentConnection = connectSSE(url, {
        body: {
          thread_id: this.#threadId,
          message,
          metadata
        },
        signal,
        headers: customHeaders
      });
      if (signal.aborted) return;
      for await (const event of this.#currentConnection) {
        if (signal.aborted) break;
        this.#handleSSEEvent(event.event, event.data, messages);
      }
      if (!signal.aborted) {
        this.#stream.finalize("complete");
        this.dispatchEvent(
          new CustomEvent("ck-stream-end", { bubbles: true, composed: true })
        );
        this.loadThreads();
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        return;
      }
      this.#stream.finalize("error", err instanceof Error ? err : new Error(String(err)));
    } finally {
      this.#currentConnection = null;
    }
  }
  #handleSSEEvent(type, data, messages) {
    switch (type) {
      case EventType.INIT: {
        const parsed = this.#parseJSON(data);
        if (parsed?.thread_id) {
          this.#threadId = parsed.thread_id;
        }
        this.#stream.startStreaming();
        this.dispatchEvent(
          new CustomEvent("ck-stream-start", { bubbles: true, composed: true })
        );
        break;
      }
      case EventType.TEXT: {
        if (!this.#currentAssistantMsg) {
          this.#currentAssistantMsg = document.createElement("ck-message");
          this.#currentAssistantMsg.role = "assistant";
          this.#currentAssistantMsg.startStreaming();
          messages.addTurnPhase(this.#currentAssistantMsg);
        }
        this.#currentAssistantMsg.appendText(data);
        break;
      }
      case EventType.STATUS: {
        messages.showStatus(data);
        break;
      }
      case EventType.CODE: {
        if (this.#currentAssistantMsg) {
          this.#currentAssistantMsg.endStreaming();
          this.#currentAssistantMsg = null;
        }
        const codeMsg = document.createElement("ck-message");
        codeMsg.role = "assistant";
        codeMsg.appendCodeBlock(data);
        messages.addTurnPhase(codeMsg);
        break;
      }
      case EventType.TOOL_USE: {
        if (this.#currentAssistantMsg) {
          this.#currentAssistantMsg.endStreaming();
          this.#currentAssistantMsg = null;
        }
        const parsed = this.#parseJSON(data);
        const card = document.createElement("ck-tool-card");
        card.toolName = parsed?.tool_name ?? "Tool";
        card.status = "running";
        if (parsed?.tool_id) {
          card.dataset.toolId = parsed.tool_id;
        }
        messages.addTurnPhase(card);
        break;
      }
      case EventType.TOOL_DONE: {
        const parsed = this.#parseJSON(data);
        if (parsed?.tool_id) {
          const card = messages.findRendered(
            `ck-tool-card[data-tool-id="${CSS.escape(parsed.tool_id)}"]`
          );
          if (card) {
            card.status = "done";
            if (parsed.summary) card.summary = parsed.summary;
          }
        }
        break;
      }
      case EventType.ARTIFACT: {
        if (this.#currentAssistantMsg) {
          this.#currentAssistantMsg.endStreaming();
          this.#currentAssistantMsg = null;
        }
        const parsed = this.#parseJSON(data);
        if (parsed) {
          const artifact = document.createElement("ck-artifact");
          artifact.setData(parsed);
          messages.addTurnPhase(artifact);
        }
        break;
      }
      case EventType.ERROR: {
        const errorMsg = document.createElement("ck-message");
        errorMsg.role = "error";
        errorMsg.setContent(data);
        messages.addTurnPhase(errorMsg);
        break;
      }
      case EventType.DONE: {
        this.#currentAssistantMsg?.endStreaming();
        this.#currentAssistantMsg = null;
        messages.hideStatus();
        messages.resetTurn();
        break;
      }
    }
  }
  // ── Stream State Callbacks ────────────────────────────────────────
  #onStreamStateChange(_from, to) {
    const input = this.#getInput();
    if (input) {
      input.streaming = to !== "idle";
    }
  }
  #onStreamFinalize(reason, error) {
    const messages = this.#getMessages();
    this.#currentAssistantMsg?.endStreaming();
    this.#currentAssistantMsg = null;
    messages?.hideStatus();
    messages?.resetTurn();
    if (reason === "error" && error && messages) {
      const errorMsg = document.createElement("ck-message");
      errorMsg.role = "error";
      errorMsg.setContent(error.message);
      messages.addMessage(errorMsg);
    }
    const input = this.#getInput();
    input?.focusInput();
  }
  // ── Helpers ───────────────────────────────────────────────────────
  async #getHeaders(url) {
    if (!this.onBeforeFetch) return {};
    try {
      const origin = window.location.origin;
      return await this.onBeforeFetch({ url, origin });
    } catch {
      return {};
    }
  }
  #parseJSON(data) {
    try {
      return JSON.parse(data);
    } catch {
      return null;
    }
  }
  // ── Render ────────────────────────────────────────────────────────
  update() {
    const shadow = this.shadowRoot;
    if (shadow.querySelector(".main-area")) return;
    shadow.innerHTML = "";
    const sidebarArea = document.createElement("div");
    sidebarArea.className = "sidebar-area";
    const sidebarSlot = document.createElement("slot");
    sidebarSlot.name = "sidebar";
    sidebarArea.appendChild(sidebarSlot);
    const mainArea = document.createElement("div");
    mainArea.className = "main-area";
    const messagesSlot = document.createElement("slot");
    messagesSlot.name = "messages";
    mainArea.appendChild(messagesSlot);
    const inputSlot = document.createElement("slot");
    inputSlot.name = "input";
    mainArea.appendChild(inputSlot);
    shadow.appendChild(sidebarArea);
    shadow.appendChild(mainArea);
  }
}
const componentSheet$5 = new CSSStyleSheet();
componentSheet$5.replaceSync(`
  :host {
    display: block;
    width: var(--ck-sidebar-width, 16rem);
    height: 100%;
    background: var(--ck-bg-sidebar, #050505);
    border-right: 1px solid var(--ck-border, #1e1e1e);
    overflow: hidden;
    flex-shrink: 0;
  }
  .sidebar {
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  .header {
    padding: 0.75rem;
    flex-shrink: 0;
  }
  .new-chat-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    width: 100%;
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--ck-border, #1e1e1e);
    border-radius: 0.5rem;
    background: transparent;
    color: var(--ck-text, #F0F0F0);
    font-family: var(--ck-font, system-ui, sans-serif);
    font-size: 0.875rem;
    cursor: pointer;
    transition: background 0.2s, border-color 0.2s, box-shadow 0.2s;
  }
  .new-chat-btn:hover {
    background: var(--ck-bg-surface-hover, #1e1e1e);
    border-color: var(--ck-accent, #22c55e);
    box-shadow: 0 0 12px var(--ck-accent-glow, rgba(34, 197, 94, 0.25));
  }
  .new-chat-btn:active {
    transform: scale(0.98);
  }
  .new-chat-btn svg {
    width: 1rem;
    height: 1rem;
    flex-shrink: 0;
  }
  .thread-list {
    flex: 1;
    overflow-y: auto;
    padding: 0.25rem 0.5rem;
  }
  .thread-list::-webkit-scrollbar {
    width: 4px;
  }
  .thread-list::-webkit-scrollbar-thumb {
    background: var(--ck-border, #1e1e1e);
    border-radius: 2px;
  }
  .thread-item {
    display: flex;
    align-items: center;
    padding: 0.5rem 0.75rem;
    border-radius: 0.5rem;
    cursor: pointer;
    transition: background 0.15s, transform 0.1s;
    position: relative;
    margin-bottom: 2px;
  }
  .thread-item:hover {
    background: var(--ck-bg-surface-hover, #1e1e1e);
  }
  .thread-item:active {
    transform: scale(0.98);
  }
  .thread-item.active {
    background: var(--ck-accent-soft, rgba(34, 197, 94, 0.10));
    border-left: 2px solid var(--ck-accent, #22c55e);
  }
  .thread-title {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.8125rem;
    color: var(--ck-text-secondary, #A1A1A1);
  }
  .thread-item.active .thread-title {
    color: var(--ck-text, #F0F0F0);
    font-weight: 500;
  }
  .delete-btn {
    display: none;
    align-items: center;
    justify-content: center;
    width: 1.5rem;
    height: 1.5rem;
    border: none;
    border-radius: 0.25rem;
    background: transparent;
    color: var(--ck-text-muted, #5a5a5a);
    cursor: pointer;
    flex-shrink: 0;
    transition: color 0.15s, background 0.15s;
  }
  .thread-item:hover .delete-btn {
    display: flex;
  }
  .delete-btn:hover {
    color: var(--ck-text-error, #ff6b6b);
    background: var(--ck-bg-error, #2a0a0a);
  }
  .delete-btn svg {
    width: 0.875rem;
    height: 0.875rem;
  }
  .empty-state {
    padding: 1.5rem 0.75rem;
    text-align: center;
    color: var(--ck-text-muted, #5a5a5a);
    font-size: 0.8125rem;
  }

  /* Backdrop for mobile drawer */
  .backdrop {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px);
    z-index: 99;
  }

  /* Mobile drawer behavior */
  @media (max-width: 767px) {
    :host {
      position: fixed;
      top: 0;
      left: 0;
      height: 100%;
      z-index: 100;
      transform: translateX(-100%);
      transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
      box-shadow: none;
    }
    :host([open]) {
      transform: translateX(0);
      box-shadow: 4px 0 32px rgba(0, 0, 0, 0.5);
    }
    :host([open]) .backdrop {
      display: block;
    }
  }
`);
const PLUS_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>`;
const TRASH_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>`;
class CkSidebar extends CkBase {
  static properties = {
    activeThreadId: { type: String, attribute: "active-thread-id" },
    open: { type: Boolean, reflect: true }
  };
  static styles = [resetSheet, componentSheet$5];
  #threads = [];
  #listEl = null;
  #backdrop = null;
  #initialized = false;
  /** Replace the displayed thread list. */
  setThreads(threads) {
    this.#threads = [...threads];
    this.requestUpdate();
  }
  /** Open the sidebar drawer (mobile). */
  show() {
    this.open = true;
  }
  /** Close the sidebar drawer (mobile). */
  close() {
    this.open = false;
  }
  update() {
    const shadow = this.shadowRoot;
    if (!this.#initialized) {
      this.#initialized = true;
      shadow.innerHTML = "";
      this.#backdrop = document.createElement("div");
      this.#backdrop.className = "backdrop";
      shadow.appendChild(this.#backdrop);
      const sidebar = document.createElement("div");
      sidebar.className = "sidebar";
      const header = document.createElement("div");
      header.className = "header";
      const newChatBtn = document.createElement("button");
      newChatBtn.className = "new-chat-btn";
      newChatBtn.type = "button";
      newChatBtn.innerHTML = `${PLUS_ICON}<span>New Chat</span>`;
      header.appendChild(newChatBtn);
      this.#listEl = document.createElement("div");
      this.#listEl.className = "thread-list";
      sidebar.appendChild(header);
      sidebar.appendChild(this.#listEl);
      shadow.appendChild(sidebar);
      this.listen(newChatBtn, "click", () => {
        this.dispatchEvent(
          new CustomEvent("ck-new-chat", { bubbles: true, composed: true })
        );
        this.close();
      });
      this.listen(this.#backdrop, "click", () => {
        this.close();
      });
    }
    this.#renderThreads();
  }
  #renderThreads() {
    if (!this.#listEl) return;
    this.#listEl.innerHTML = "";
    if (this.#threads.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No conversations yet";
      this.#listEl.appendChild(empty);
      return;
    }
    for (const thread of this.#threads) {
      const item = document.createElement("div");
      item.className = "thread-item";
      if (thread.id === this.activeThreadId) {
        item.classList.add("active");
      }
      item.dataset.threadId = thread.id;
      const title = document.createElement("span");
      title.className = "thread-title";
      title.textContent = thread.title;
      title.title = thread.title;
      const deleteBtn = document.createElement("button");
      deleteBtn.className = "delete-btn";
      deleteBtn.type = "button";
      deleteBtn.innerHTML = TRASH_ICON;
      deleteBtn.title = "Delete conversation";
      item.appendChild(title);
      item.appendChild(deleteBtn);
      this.#listEl.appendChild(item);
      item.addEventListener("click", (e) => {
        if (e.target.closest(".delete-btn")) return;
        this.dispatchEvent(
          new CustomEvent("ck-thread-select", {
            bubbles: true,
            composed: true,
            detail: { threadId: thread.id }
          })
        );
        this.close();
      });
      deleteBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this.dispatchEvent(
          new CustomEvent("ck-thread-delete", {
            bubbles: true,
            composed: true,
            cancelable: true,
            detail: { threadId: thread.id }
          })
        );
      });
    }
  }
}
/*! @license DOMPurify 3.3.3 | (c) Cure53 and other contributors | Released under the Apache license 2.0 and Mozilla Public License 2.0 | github.com/cure53/DOMPurify/blob/3.3.3/LICENSE */
const {
  entries,
  setPrototypeOf,
  isFrozen,
  getPrototypeOf,
  getOwnPropertyDescriptor
} = Object;
let {
  freeze,
  seal,
  create
} = Object;
let {
  apply,
  construct
} = typeof Reflect !== "undefined" && Reflect;
if (!freeze) {
  freeze = function freeze2(x) {
    return x;
  };
}
if (!seal) {
  seal = function seal2(x) {
    return x;
  };
}
if (!apply) {
  apply = function apply2(func, thisArg) {
    for (var _len = arguments.length, args = new Array(_len > 2 ? _len - 2 : 0), _key = 2; _key < _len; _key++) {
      args[_key - 2] = arguments[_key];
    }
    return func.apply(thisArg, args);
  };
}
if (!construct) {
  construct = function construct2(Func) {
    for (var _len2 = arguments.length, args = new Array(_len2 > 1 ? _len2 - 1 : 0), _key2 = 1; _key2 < _len2; _key2++) {
      args[_key2 - 1] = arguments[_key2];
    }
    return new Func(...args);
  };
}
const arrayForEach = unapply(Array.prototype.forEach);
const arrayLastIndexOf = unapply(Array.prototype.lastIndexOf);
const arrayPop = unapply(Array.prototype.pop);
const arrayPush = unapply(Array.prototype.push);
const arraySplice = unapply(Array.prototype.splice);
const stringToLowerCase = unapply(String.prototype.toLowerCase);
const stringToString = unapply(String.prototype.toString);
const stringMatch = unapply(String.prototype.match);
const stringReplace = unapply(String.prototype.replace);
const stringIndexOf = unapply(String.prototype.indexOf);
const stringTrim = unapply(String.prototype.trim);
const objectHasOwnProperty = unapply(Object.prototype.hasOwnProperty);
const regExpTest = unapply(RegExp.prototype.test);
const typeErrorCreate = unconstruct(TypeError);
function unapply(func) {
  return function(thisArg) {
    if (thisArg instanceof RegExp) {
      thisArg.lastIndex = 0;
    }
    for (var _len3 = arguments.length, args = new Array(_len3 > 1 ? _len3 - 1 : 0), _key3 = 1; _key3 < _len3; _key3++) {
      args[_key3 - 1] = arguments[_key3];
    }
    return apply(func, thisArg, args);
  };
}
function unconstruct(Func) {
  return function() {
    for (var _len4 = arguments.length, args = new Array(_len4), _key4 = 0; _key4 < _len4; _key4++) {
      args[_key4] = arguments[_key4];
    }
    return construct(Func, args);
  };
}
function addToSet(set, array) {
  let transformCaseFunc = arguments.length > 2 && arguments[2] !== void 0 ? arguments[2] : stringToLowerCase;
  if (setPrototypeOf) {
    setPrototypeOf(set, null);
  }
  let l = array.length;
  while (l--) {
    let element = array[l];
    if (typeof element === "string") {
      const lcElement = transformCaseFunc(element);
      if (lcElement !== element) {
        if (!isFrozen(array)) {
          array[l] = lcElement;
        }
        element = lcElement;
      }
    }
    set[element] = true;
  }
  return set;
}
function cleanArray(array) {
  for (let index = 0; index < array.length; index++) {
    const isPropertyExist = objectHasOwnProperty(array, index);
    if (!isPropertyExist) {
      array[index] = null;
    }
  }
  return array;
}
function clone(object) {
  const newObject = create(null);
  for (const [property, value] of entries(object)) {
    const isPropertyExist = objectHasOwnProperty(object, property);
    if (isPropertyExist) {
      if (Array.isArray(value)) {
        newObject[property] = cleanArray(value);
      } else if (value && typeof value === "object" && value.constructor === Object) {
        newObject[property] = clone(value);
      } else {
        newObject[property] = value;
      }
    }
  }
  return newObject;
}
function lookupGetter(object, prop) {
  while (object !== null) {
    const desc = getOwnPropertyDescriptor(object, prop);
    if (desc) {
      if (desc.get) {
        return unapply(desc.get);
      }
      if (typeof desc.value === "function") {
        return unapply(desc.value);
      }
    }
    object = getPrototypeOf(object);
  }
  function fallbackValue() {
    return null;
  }
  return fallbackValue;
}
const html$1 = freeze(["a", "abbr", "acronym", "address", "area", "article", "aside", "audio", "b", "bdi", "bdo", "big", "blink", "blockquote", "body", "br", "button", "canvas", "caption", "center", "cite", "code", "col", "colgroup", "content", "data", "datalist", "dd", "decorator", "del", "details", "dfn", "dialog", "dir", "div", "dl", "dt", "element", "em", "fieldset", "figcaption", "figure", "font", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hgroup", "hr", "html", "i", "img", "input", "ins", "kbd", "label", "legend", "li", "main", "map", "mark", "marquee", "menu", "menuitem", "meter", "nav", "nobr", "ol", "optgroup", "option", "output", "p", "picture", "pre", "progress", "q", "rp", "rt", "ruby", "s", "samp", "search", "section", "select", "shadow", "slot", "small", "source", "spacer", "span", "strike", "strong", "style", "sub", "summary", "sup", "table", "tbody", "td", "template", "textarea", "tfoot", "th", "thead", "time", "tr", "track", "tt", "u", "ul", "var", "video", "wbr"]);
const svg$1 = freeze(["svg", "a", "altglyph", "altglyphdef", "altglyphitem", "animatecolor", "animatemotion", "animatetransform", "circle", "clippath", "defs", "desc", "ellipse", "enterkeyhint", "exportparts", "filter", "font", "g", "glyph", "glyphref", "hkern", "image", "inputmode", "line", "lineargradient", "marker", "mask", "metadata", "mpath", "part", "path", "pattern", "polygon", "polyline", "radialgradient", "rect", "stop", "style", "switch", "symbol", "text", "textpath", "title", "tref", "tspan", "view", "vkern"]);
const svgFilters = freeze(["feBlend", "feColorMatrix", "feComponentTransfer", "feComposite", "feConvolveMatrix", "feDiffuseLighting", "feDisplacementMap", "feDistantLight", "feDropShadow", "feFlood", "feFuncA", "feFuncB", "feFuncG", "feFuncR", "feGaussianBlur", "feImage", "feMerge", "feMergeNode", "feMorphology", "feOffset", "fePointLight", "feSpecularLighting", "feSpotLight", "feTile", "feTurbulence"]);
const svgDisallowed = freeze(["animate", "color-profile", "cursor", "discard", "font-face", "font-face-format", "font-face-name", "font-face-src", "font-face-uri", "foreignobject", "hatch", "hatchpath", "mesh", "meshgradient", "meshpatch", "meshrow", "missing-glyph", "script", "set", "solidcolor", "unknown", "use"]);
const mathMl$1 = freeze(["math", "menclose", "merror", "mfenced", "mfrac", "mglyph", "mi", "mlabeledtr", "mmultiscripts", "mn", "mo", "mover", "mpadded", "mphantom", "mroot", "mrow", "ms", "mspace", "msqrt", "mstyle", "msub", "msup", "msubsup", "mtable", "mtd", "mtext", "mtr", "munder", "munderover", "mprescripts"]);
const mathMlDisallowed = freeze(["maction", "maligngroup", "malignmark", "mlongdiv", "mscarries", "mscarry", "msgroup", "mstack", "msline", "msrow", "semantics", "annotation", "annotation-xml", "mprescripts", "none"]);
const text = freeze(["#text"]);
const html = freeze(["accept", "action", "align", "alt", "autocapitalize", "autocomplete", "autopictureinpicture", "autoplay", "background", "bgcolor", "border", "capture", "cellpadding", "cellspacing", "checked", "cite", "class", "clear", "color", "cols", "colspan", "controls", "controlslist", "coords", "crossorigin", "datetime", "decoding", "default", "dir", "disabled", "disablepictureinpicture", "disableremoteplayback", "download", "draggable", "enctype", "enterkeyhint", "exportparts", "face", "for", "headers", "height", "hidden", "high", "href", "hreflang", "id", "inert", "inputmode", "integrity", "ismap", "kind", "label", "lang", "list", "loading", "loop", "low", "max", "maxlength", "media", "method", "min", "minlength", "multiple", "muted", "name", "nonce", "noshade", "novalidate", "nowrap", "open", "optimum", "part", "pattern", "placeholder", "playsinline", "popover", "popovertarget", "popovertargetaction", "poster", "preload", "pubdate", "radiogroup", "readonly", "rel", "required", "rev", "reversed", "role", "rows", "rowspan", "spellcheck", "scope", "selected", "shape", "size", "sizes", "slot", "span", "srclang", "start", "src", "srcset", "step", "style", "summary", "tabindex", "title", "translate", "type", "usemap", "valign", "value", "width", "wrap", "xmlns", "slot"]);
const svg = freeze(["accent-height", "accumulate", "additive", "alignment-baseline", "amplitude", "ascent", "attributename", "attributetype", "azimuth", "basefrequency", "baseline-shift", "begin", "bias", "by", "class", "clip", "clippathunits", "clip-path", "clip-rule", "color", "color-interpolation", "color-interpolation-filters", "color-profile", "color-rendering", "cx", "cy", "d", "dx", "dy", "diffuseconstant", "direction", "display", "divisor", "dur", "edgemode", "elevation", "end", "exponent", "fill", "fill-opacity", "fill-rule", "filter", "filterunits", "flood-color", "flood-opacity", "font-family", "font-size", "font-size-adjust", "font-stretch", "font-style", "font-variant", "font-weight", "fx", "fy", "g1", "g2", "glyph-name", "glyphref", "gradientunits", "gradienttransform", "height", "href", "id", "image-rendering", "in", "in2", "intercept", "k", "k1", "k2", "k3", "k4", "kerning", "keypoints", "keysplines", "keytimes", "lang", "lengthadjust", "letter-spacing", "kernelmatrix", "kernelunitlength", "lighting-color", "local", "marker-end", "marker-mid", "marker-start", "markerheight", "markerunits", "markerwidth", "maskcontentunits", "maskunits", "max", "mask", "mask-type", "media", "method", "mode", "min", "name", "numoctaves", "offset", "operator", "opacity", "order", "orient", "orientation", "origin", "overflow", "paint-order", "path", "pathlength", "patterncontentunits", "patterntransform", "patternunits", "points", "preservealpha", "preserveaspectratio", "primitiveunits", "r", "rx", "ry", "radius", "refx", "refy", "repeatcount", "repeatdur", "restart", "result", "rotate", "scale", "seed", "shape-rendering", "slope", "specularconstant", "specularexponent", "spreadmethod", "startoffset", "stddeviation", "stitchtiles", "stop-color", "stop-opacity", "stroke-dasharray", "stroke-dashoffset", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "stroke-opacity", "stroke", "stroke-width", "style", "surfacescale", "systemlanguage", "tabindex", "tablevalues", "targetx", "targety", "transform", "transform-origin", "text-anchor", "text-decoration", "text-rendering", "textlength", "type", "u1", "u2", "unicode", "values", "viewbox", "visibility", "version", "vert-adv-y", "vert-origin-x", "vert-origin-y", "width", "word-spacing", "wrap", "writing-mode", "xchannelselector", "ychannelselector", "x", "x1", "x2", "xmlns", "y", "y1", "y2", "z", "zoomandpan"]);
const mathMl = freeze(["accent", "accentunder", "align", "bevelled", "close", "columnsalign", "columnlines", "columnspan", "denomalign", "depth", "dir", "display", "displaystyle", "encoding", "fence", "frame", "height", "href", "id", "largeop", "length", "linethickness", "lspace", "lquote", "mathbackground", "mathcolor", "mathsize", "mathvariant", "maxsize", "minsize", "movablelimits", "notation", "numalign", "open", "rowalign", "rowlines", "rowspacing", "rowspan", "rspace", "rquote", "scriptlevel", "scriptminsize", "scriptsizemultiplier", "selection", "separator", "separators", "stretchy", "subscriptshift", "supscriptshift", "symmetric", "voffset", "width", "xmlns"]);
const xml = freeze(["xlink:href", "xml:id", "xlink:title", "xml:space", "xmlns:xlink"]);
const MUSTACHE_EXPR = seal(/\{\{[\w\W]*|[\w\W]*\}\}/gm);
const ERB_EXPR = seal(/<%[\w\W]*|[\w\W]*%>/gm);
const TMPLIT_EXPR = seal(/\$\{[\w\W]*/gm);
const DATA_ATTR = seal(/^data-[\-\w.\u00B7-\uFFFF]+$/);
const ARIA_ATTR = seal(/^aria-[\-\w]+$/);
const IS_ALLOWED_URI = seal(
  /^(?:(?:(?:f|ht)tps?|mailto|tel|callto|sms|cid|xmpp|matrix):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i
  // eslint-disable-line no-useless-escape
);
const IS_SCRIPT_OR_DATA = seal(/^(?:\w+script|data):/i);
const ATTR_WHITESPACE = seal(
  /[\u0000-\u0020\u00A0\u1680\u180E\u2000-\u2029\u205F\u3000]/g
  // eslint-disable-line no-control-regex
);
const DOCTYPE_NAME = seal(/^html$/i);
const CUSTOM_ELEMENT = seal(/^[a-z][.\w]*(-[.\w]+)+$/i);
var EXPRESSIONS = /* @__PURE__ */ Object.freeze({
  __proto__: null,
  ARIA_ATTR,
  ATTR_WHITESPACE,
  CUSTOM_ELEMENT,
  DATA_ATTR,
  DOCTYPE_NAME,
  ERB_EXPR,
  IS_ALLOWED_URI,
  IS_SCRIPT_OR_DATA,
  MUSTACHE_EXPR,
  TMPLIT_EXPR
});
const NODE_TYPE = {
  element: 1,
  text: 3,
  // Deprecated
  progressingInstruction: 7,
  comment: 8,
  document: 9
};
const getGlobal = function getGlobal2() {
  return typeof window === "undefined" ? null : window;
};
const _createTrustedTypesPolicy = function _createTrustedTypesPolicy2(trustedTypes, purifyHostElement) {
  if (typeof trustedTypes !== "object" || typeof trustedTypes.createPolicy !== "function") {
    return null;
  }
  let suffix = null;
  const ATTR_NAME = "data-tt-policy-suffix";
  if (purifyHostElement && purifyHostElement.hasAttribute(ATTR_NAME)) {
    suffix = purifyHostElement.getAttribute(ATTR_NAME);
  }
  const policyName = "dompurify" + (suffix ? "#" + suffix : "");
  try {
    return trustedTypes.createPolicy(policyName, {
      createHTML(html2) {
        return html2;
      },
      createScriptURL(scriptUrl) {
        return scriptUrl;
      }
    });
  } catch (_) {
    console.warn("TrustedTypes policy " + policyName + " could not be created.");
    return null;
  }
};
const _createHooksMap = function _createHooksMap2() {
  return {
    afterSanitizeAttributes: [],
    afterSanitizeElements: [],
    afterSanitizeShadowDOM: [],
    beforeSanitizeAttributes: [],
    beforeSanitizeElements: [],
    beforeSanitizeShadowDOM: [],
    uponSanitizeAttribute: [],
    uponSanitizeElement: [],
    uponSanitizeShadowNode: []
  };
};
function createDOMPurify() {
  let window2 = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : getGlobal();
  const DOMPurify = (root) => createDOMPurify(root);
  DOMPurify.version = "3.3.3";
  DOMPurify.removed = [];
  if (!window2 || !window2.document || window2.document.nodeType !== NODE_TYPE.document || !window2.Element) {
    DOMPurify.isSupported = false;
    return DOMPurify;
  }
  let {
    document: document2
  } = window2;
  const originalDocument = document2;
  const currentScript = originalDocument.currentScript;
  const {
    DocumentFragment,
    HTMLTemplateElement,
    Node,
    Element,
    NodeFilter,
    NamedNodeMap = window2.NamedNodeMap || window2.MozNamedAttrMap,
    HTMLFormElement,
    DOMParser,
    trustedTypes
  } = window2;
  const ElementPrototype = Element.prototype;
  const cloneNode = lookupGetter(ElementPrototype, "cloneNode");
  const remove = lookupGetter(ElementPrototype, "remove");
  const getNextSibling = lookupGetter(ElementPrototype, "nextSibling");
  const getChildNodes = lookupGetter(ElementPrototype, "childNodes");
  const getParentNode = lookupGetter(ElementPrototype, "parentNode");
  if (typeof HTMLTemplateElement === "function") {
    const template = document2.createElement("template");
    if (template.content && template.content.ownerDocument) {
      document2 = template.content.ownerDocument;
    }
  }
  let trustedTypesPolicy;
  let emptyHTML = "";
  const {
    implementation,
    createNodeIterator,
    createDocumentFragment,
    getElementsByTagName
  } = document2;
  const {
    importNode
  } = originalDocument;
  let hooks = _createHooksMap();
  DOMPurify.isSupported = typeof entries === "function" && typeof getParentNode === "function" && implementation && implementation.createHTMLDocument !== void 0;
  const {
    MUSTACHE_EXPR: MUSTACHE_EXPR2,
    ERB_EXPR: ERB_EXPR2,
    TMPLIT_EXPR: TMPLIT_EXPR2,
    DATA_ATTR: DATA_ATTR2,
    ARIA_ATTR: ARIA_ATTR2,
    IS_SCRIPT_OR_DATA: IS_SCRIPT_OR_DATA2,
    ATTR_WHITESPACE: ATTR_WHITESPACE2,
    CUSTOM_ELEMENT: CUSTOM_ELEMENT2
  } = EXPRESSIONS;
  let {
    IS_ALLOWED_URI: IS_ALLOWED_URI$1
  } = EXPRESSIONS;
  let ALLOWED_TAGS = null;
  const DEFAULT_ALLOWED_TAGS = addToSet({}, [...html$1, ...svg$1, ...svgFilters, ...mathMl$1, ...text]);
  let ALLOWED_ATTR = null;
  const DEFAULT_ALLOWED_ATTR = addToSet({}, [...html, ...svg, ...mathMl, ...xml]);
  let CUSTOM_ELEMENT_HANDLING = Object.seal(create(null, {
    tagNameCheck: {
      writable: true,
      configurable: false,
      enumerable: true,
      value: null
    },
    attributeNameCheck: {
      writable: true,
      configurable: false,
      enumerable: true,
      value: null
    },
    allowCustomizedBuiltInElements: {
      writable: true,
      configurable: false,
      enumerable: true,
      value: false
    }
  }));
  let FORBID_TAGS = null;
  let FORBID_ATTR = null;
  const EXTRA_ELEMENT_HANDLING = Object.seal(create(null, {
    tagCheck: {
      writable: true,
      configurable: false,
      enumerable: true,
      value: null
    },
    attributeCheck: {
      writable: true,
      configurable: false,
      enumerable: true,
      value: null
    }
  }));
  let ALLOW_ARIA_ATTR = true;
  let ALLOW_DATA_ATTR = true;
  let ALLOW_UNKNOWN_PROTOCOLS = false;
  let ALLOW_SELF_CLOSE_IN_ATTR = true;
  let SAFE_FOR_TEMPLATES = false;
  let SAFE_FOR_XML = true;
  let WHOLE_DOCUMENT = false;
  let SET_CONFIG = false;
  let FORCE_BODY = false;
  let RETURN_DOM = false;
  let RETURN_DOM_FRAGMENT = false;
  let RETURN_TRUSTED_TYPE = false;
  let SANITIZE_DOM = true;
  let SANITIZE_NAMED_PROPS = false;
  const SANITIZE_NAMED_PROPS_PREFIX = "user-content-";
  let KEEP_CONTENT = true;
  let IN_PLACE = false;
  let USE_PROFILES = {};
  let FORBID_CONTENTS = null;
  const DEFAULT_FORBID_CONTENTS = addToSet({}, ["annotation-xml", "audio", "colgroup", "desc", "foreignobject", "head", "iframe", "math", "mi", "mn", "mo", "ms", "mtext", "noembed", "noframes", "noscript", "plaintext", "script", "style", "svg", "template", "thead", "title", "video", "xmp"]);
  let DATA_URI_TAGS = null;
  const DEFAULT_DATA_URI_TAGS = addToSet({}, ["audio", "video", "img", "source", "image", "track"]);
  let URI_SAFE_ATTRIBUTES = null;
  const DEFAULT_URI_SAFE_ATTRIBUTES = addToSet({}, ["alt", "class", "for", "id", "label", "name", "pattern", "placeholder", "role", "summary", "title", "value", "style", "xmlns"]);
  const MATHML_NAMESPACE = "http://www.w3.org/1998/Math/MathML";
  const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
  const HTML_NAMESPACE = "http://www.w3.org/1999/xhtml";
  let NAMESPACE = HTML_NAMESPACE;
  let IS_EMPTY_INPUT = false;
  let ALLOWED_NAMESPACES = null;
  const DEFAULT_ALLOWED_NAMESPACES = addToSet({}, [MATHML_NAMESPACE, SVG_NAMESPACE, HTML_NAMESPACE], stringToString);
  let MATHML_TEXT_INTEGRATION_POINTS = addToSet({}, ["mi", "mo", "mn", "ms", "mtext"]);
  let HTML_INTEGRATION_POINTS = addToSet({}, ["annotation-xml"]);
  const COMMON_SVG_AND_HTML_ELEMENTS = addToSet({}, ["title", "style", "font", "a", "script"]);
  let PARSER_MEDIA_TYPE = null;
  const SUPPORTED_PARSER_MEDIA_TYPES = ["application/xhtml+xml", "text/html"];
  const DEFAULT_PARSER_MEDIA_TYPE = "text/html";
  let transformCaseFunc = null;
  let CONFIG = null;
  const formElement = document2.createElement("form");
  const isRegexOrFunction = function isRegexOrFunction2(testValue) {
    return testValue instanceof RegExp || testValue instanceof Function;
  };
  const _parseConfig = function _parseConfig2() {
    let cfg = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : {};
    if (CONFIG && CONFIG === cfg) {
      return;
    }
    if (!cfg || typeof cfg !== "object") {
      cfg = {};
    }
    cfg = clone(cfg);
    PARSER_MEDIA_TYPE = // eslint-disable-next-line unicorn/prefer-includes
    SUPPORTED_PARSER_MEDIA_TYPES.indexOf(cfg.PARSER_MEDIA_TYPE) === -1 ? DEFAULT_PARSER_MEDIA_TYPE : cfg.PARSER_MEDIA_TYPE;
    transformCaseFunc = PARSER_MEDIA_TYPE === "application/xhtml+xml" ? stringToString : stringToLowerCase;
    ALLOWED_TAGS = objectHasOwnProperty(cfg, "ALLOWED_TAGS") ? addToSet({}, cfg.ALLOWED_TAGS, transformCaseFunc) : DEFAULT_ALLOWED_TAGS;
    ALLOWED_ATTR = objectHasOwnProperty(cfg, "ALLOWED_ATTR") ? addToSet({}, cfg.ALLOWED_ATTR, transformCaseFunc) : DEFAULT_ALLOWED_ATTR;
    ALLOWED_NAMESPACES = objectHasOwnProperty(cfg, "ALLOWED_NAMESPACES") ? addToSet({}, cfg.ALLOWED_NAMESPACES, stringToString) : DEFAULT_ALLOWED_NAMESPACES;
    URI_SAFE_ATTRIBUTES = objectHasOwnProperty(cfg, "ADD_URI_SAFE_ATTR") ? addToSet(clone(DEFAULT_URI_SAFE_ATTRIBUTES), cfg.ADD_URI_SAFE_ATTR, transformCaseFunc) : DEFAULT_URI_SAFE_ATTRIBUTES;
    DATA_URI_TAGS = objectHasOwnProperty(cfg, "ADD_DATA_URI_TAGS") ? addToSet(clone(DEFAULT_DATA_URI_TAGS), cfg.ADD_DATA_URI_TAGS, transformCaseFunc) : DEFAULT_DATA_URI_TAGS;
    FORBID_CONTENTS = objectHasOwnProperty(cfg, "FORBID_CONTENTS") ? addToSet({}, cfg.FORBID_CONTENTS, transformCaseFunc) : DEFAULT_FORBID_CONTENTS;
    FORBID_TAGS = objectHasOwnProperty(cfg, "FORBID_TAGS") ? addToSet({}, cfg.FORBID_TAGS, transformCaseFunc) : clone({});
    FORBID_ATTR = objectHasOwnProperty(cfg, "FORBID_ATTR") ? addToSet({}, cfg.FORBID_ATTR, transformCaseFunc) : clone({});
    USE_PROFILES = objectHasOwnProperty(cfg, "USE_PROFILES") ? cfg.USE_PROFILES : false;
    ALLOW_ARIA_ATTR = cfg.ALLOW_ARIA_ATTR !== false;
    ALLOW_DATA_ATTR = cfg.ALLOW_DATA_ATTR !== false;
    ALLOW_UNKNOWN_PROTOCOLS = cfg.ALLOW_UNKNOWN_PROTOCOLS || false;
    ALLOW_SELF_CLOSE_IN_ATTR = cfg.ALLOW_SELF_CLOSE_IN_ATTR !== false;
    SAFE_FOR_TEMPLATES = cfg.SAFE_FOR_TEMPLATES || false;
    SAFE_FOR_XML = cfg.SAFE_FOR_XML !== false;
    WHOLE_DOCUMENT = cfg.WHOLE_DOCUMENT || false;
    RETURN_DOM = cfg.RETURN_DOM || false;
    RETURN_DOM_FRAGMENT = cfg.RETURN_DOM_FRAGMENT || false;
    RETURN_TRUSTED_TYPE = cfg.RETURN_TRUSTED_TYPE || false;
    FORCE_BODY = cfg.FORCE_BODY || false;
    SANITIZE_DOM = cfg.SANITIZE_DOM !== false;
    SANITIZE_NAMED_PROPS = cfg.SANITIZE_NAMED_PROPS || false;
    KEEP_CONTENT = cfg.KEEP_CONTENT !== false;
    IN_PLACE = cfg.IN_PLACE || false;
    IS_ALLOWED_URI$1 = cfg.ALLOWED_URI_REGEXP || IS_ALLOWED_URI;
    NAMESPACE = cfg.NAMESPACE || HTML_NAMESPACE;
    MATHML_TEXT_INTEGRATION_POINTS = cfg.MATHML_TEXT_INTEGRATION_POINTS || MATHML_TEXT_INTEGRATION_POINTS;
    HTML_INTEGRATION_POINTS = cfg.HTML_INTEGRATION_POINTS || HTML_INTEGRATION_POINTS;
    CUSTOM_ELEMENT_HANDLING = cfg.CUSTOM_ELEMENT_HANDLING || {};
    if (cfg.CUSTOM_ELEMENT_HANDLING && isRegexOrFunction(cfg.CUSTOM_ELEMENT_HANDLING.tagNameCheck)) {
      CUSTOM_ELEMENT_HANDLING.tagNameCheck = cfg.CUSTOM_ELEMENT_HANDLING.tagNameCheck;
    }
    if (cfg.CUSTOM_ELEMENT_HANDLING && isRegexOrFunction(cfg.CUSTOM_ELEMENT_HANDLING.attributeNameCheck)) {
      CUSTOM_ELEMENT_HANDLING.attributeNameCheck = cfg.CUSTOM_ELEMENT_HANDLING.attributeNameCheck;
    }
    if (cfg.CUSTOM_ELEMENT_HANDLING && typeof cfg.CUSTOM_ELEMENT_HANDLING.allowCustomizedBuiltInElements === "boolean") {
      CUSTOM_ELEMENT_HANDLING.allowCustomizedBuiltInElements = cfg.CUSTOM_ELEMENT_HANDLING.allowCustomizedBuiltInElements;
    }
    if (SAFE_FOR_TEMPLATES) {
      ALLOW_DATA_ATTR = false;
    }
    if (RETURN_DOM_FRAGMENT) {
      RETURN_DOM = true;
    }
    if (USE_PROFILES) {
      ALLOWED_TAGS = addToSet({}, text);
      ALLOWED_ATTR = create(null);
      if (USE_PROFILES.html === true) {
        addToSet(ALLOWED_TAGS, html$1);
        addToSet(ALLOWED_ATTR, html);
      }
      if (USE_PROFILES.svg === true) {
        addToSet(ALLOWED_TAGS, svg$1);
        addToSet(ALLOWED_ATTR, svg);
        addToSet(ALLOWED_ATTR, xml);
      }
      if (USE_PROFILES.svgFilters === true) {
        addToSet(ALLOWED_TAGS, svgFilters);
        addToSet(ALLOWED_ATTR, svg);
        addToSet(ALLOWED_ATTR, xml);
      }
      if (USE_PROFILES.mathMl === true) {
        addToSet(ALLOWED_TAGS, mathMl$1);
        addToSet(ALLOWED_ATTR, mathMl);
        addToSet(ALLOWED_ATTR, xml);
      }
    }
    if (!objectHasOwnProperty(cfg, "ADD_TAGS")) {
      EXTRA_ELEMENT_HANDLING.tagCheck = null;
    }
    if (!objectHasOwnProperty(cfg, "ADD_ATTR")) {
      EXTRA_ELEMENT_HANDLING.attributeCheck = null;
    }
    if (cfg.ADD_TAGS) {
      if (typeof cfg.ADD_TAGS === "function") {
        EXTRA_ELEMENT_HANDLING.tagCheck = cfg.ADD_TAGS;
      } else {
        if (ALLOWED_TAGS === DEFAULT_ALLOWED_TAGS) {
          ALLOWED_TAGS = clone(ALLOWED_TAGS);
        }
        addToSet(ALLOWED_TAGS, cfg.ADD_TAGS, transformCaseFunc);
      }
    }
    if (cfg.ADD_ATTR) {
      if (typeof cfg.ADD_ATTR === "function") {
        EXTRA_ELEMENT_HANDLING.attributeCheck = cfg.ADD_ATTR;
      } else {
        if (ALLOWED_ATTR === DEFAULT_ALLOWED_ATTR) {
          ALLOWED_ATTR = clone(ALLOWED_ATTR);
        }
        addToSet(ALLOWED_ATTR, cfg.ADD_ATTR, transformCaseFunc);
      }
    }
    if (cfg.ADD_URI_SAFE_ATTR) {
      addToSet(URI_SAFE_ATTRIBUTES, cfg.ADD_URI_SAFE_ATTR, transformCaseFunc);
    }
    if (cfg.FORBID_CONTENTS) {
      if (FORBID_CONTENTS === DEFAULT_FORBID_CONTENTS) {
        FORBID_CONTENTS = clone(FORBID_CONTENTS);
      }
      addToSet(FORBID_CONTENTS, cfg.FORBID_CONTENTS, transformCaseFunc);
    }
    if (cfg.ADD_FORBID_CONTENTS) {
      if (FORBID_CONTENTS === DEFAULT_FORBID_CONTENTS) {
        FORBID_CONTENTS = clone(FORBID_CONTENTS);
      }
      addToSet(FORBID_CONTENTS, cfg.ADD_FORBID_CONTENTS, transformCaseFunc);
    }
    if (KEEP_CONTENT) {
      ALLOWED_TAGS["#text"] = true;
    }
    if (WHOLE_DOCUMENT) {
      addToSet(ALLOWED_TAGS, ["html", "head", "body"]);
    }
    if (ALLOWED_TAGS.table) {
      addToSet(ALLOWED_TAGS, ["tbody"]);
      delete FORBID_TAGS.tbody;
    }
    if (cfg.TRUSTED_TYPES_POLICY) {
      if (typeof cfg.TRUSTED_TYPES_POLICY.createHTML !== "function") {
        throw typeErrorCreate('TRUSTED_TYPES_POLICY configuration option must provide a "createHTML" hook.');
      }
      if (typeof cfg.TRUSTED_TYPES_POLICY.createScriptURL !== "function") {
        throw typeErrorCreate('TRUSTED_TYPES_POLICY configuration option must provide a "createScriptURL" hook.');
      }
      trustedTypesPolicy = cfg.TRUSTED_TYPES_POLICY;
      emptyHTML = trustedTypesPolicy.createHTML("");
    } else {
      if (trustedTypesPolicy === void 0) {
        trustedTypesPolicy = _createTrustedTypesPolicy(trustedTypes, currentScript);
      }
      if (trustedTypesPolicy !== null && typeof emptyHTML === "string") {
        emptyHTML = trustedTypesPolicy.createHTML("");
      }
    }
    if (freeze) {
      freeze(cfg);
    }
    CONFIG = cfg;
  };
  const ALL_SVG_TAGS = addToSet({}, [...svg$1, ...svgFilters, ...svgDisallowed]);
  const ALL_MATHML_TAGS = addToSet({}, [...mathMl$1, ...mathMlDisallowed]);
  const _checkValidNamespace = function _checkValidNamespace2(element) {
    let parent = getParentNode(element);
    if (!parent || !parent.tagName) {
      parent = {
        namespaceURI: NAMESPACE,
        tagName: "template"
      };
    }
    const tagName = stringToLowerCase(element.tagName);
    const parentTagName = stringToLowerCase(parent.tagName);
    if (!ALLOWED_NAMESPACES[element.namespaceURI]) {
      return false;
    }
    if (element.namespaceURI === SVG_NAMESPACE) {
      if (parent.namespaceURI === HTML_NAMESPACE) {
        return tagName === "svg";
      }
      if (parent.namespaceURI === MATHML_NAMESPACE) {
        return tagName === "svg" && (parentTagName === "annotation-xml" || MATHML_TEXT_INTEGRATION_POINTS[parentTagName]);
      }
      return Boolean(ALL_SVG_TAGS[tagName]);
    }
    if (element.namespaceURI === MATHML_NAMESPACE) {
      if (parent.namespaceURI === HTML_NAMESPACE) {
        return tagName === "math";
      }
      if (parent.namespaceURI === SVG_NAMESPACE) {
        return tagName === "math" && HTML_INTEGRATION_POINTS[parentTagName];
      }
      return Boolean(ALL_MATHML_TAGS[tagName]);
    }
    if (element.namespaceURI === HTML_NAMESPACE) {
      if (parent.namespaceURI === SVG_NAMESPACE && !HTML_INTEGRATION_POINTS[parentTagName]) {
        return false;
      }
      if (parent.namespaceURI === MATHML_NAMESPACE && !MATHML_TEXT_INTEGRATION_POINTS[parentTagName]) {
        return false;
      }
      return !ALL_MATHML_TAGS[tagName] && (COMMON_SVG_AND_HTML_ELEMENTS[tagName] || !ALL_SVG_TAGS[tagName]);
    }
    if (PARSER_MEDIA_TYPE === "application/xhtml+xml" && ALLOWED_NAMESPACES[element.namespaceURI]) {
      return true;
    }
    return false;
  };
  const _forceRemove = function _forceRemove2(node) {
    arrayPush(DOMPurify.removed, {
      element: node
    });
    try {
      getParentNode(node).removeChild(node);
    } catch (_) {
      remove(node);
    }
  };
  const _removeAttribute = function _removeAttribute2(name, element) {
    try {
      arrayPush(DOMPurify.removed, {
        attribute: element.getAttributeNode(name),
        from: element
      });
    } catch (_) {
      arrayPush(DOMPurify.removed, {
        attribute: null,
        from: element
      });
    }
    element.removeAttribute(name);
    if (name === "is") {
      if (RETURN_DOM || RETURN_DOM_FRAGMENT) {
        try {
          _forceRemove(element);
        } catch (_) {
        }
      } else {
        try {
          element.setAttribute(name, "");
        } catch (_) {
        }
      }
    }
  };
  const _initDocument = function _initDocument2(dirty) {
    let doc = null;
    let leadingWhitespace = null;
    if (FORCE_BODY) {
      dirty = "<remove></remove>" + dirty;
    } else {
      const matches = stringMatch(dirty, /^[\r\n\t ]+/);
      leadingWhitespace = matches && matches[0];
    }
    if (PARSER_MEDIA_TYPE === "application/xhtml+xml" && NAMESPACE === HTML_NAMESPACE) {
      dirty = '<html xmlns="http://www.w3.org/1999/xhtml"><head></head><body>' + dirty + "</body></html>";
    }
    const dirtyPayload = trustedTypesPolicy ? trustedTypesPolicy.createHTML(dirty) : dirty;
    if (NAMESPACE === HTML_NAMESPACE) {
      try {
        doc = new DOMParser().parseFromString(dirtyPayload, PARSER_MEDIA_TYPE);
      } catch (_) {
      }
    }
    if (!doc || !doc.documentElement) {
      doc = implementation.createDocument(NAMESPACE, "template", null);
      try {
        doc.documentElement.innerHTML = IS_EMPTY_INPUT ? emptyHTML : dirtyPayload;
      } catch (_) {
      }
    }
    const body = doc.body || doc.documentElement;
    if (dirty && leadingWhitespace) {
      body.insertBefore(document2.createTextNode(leadingWhitespace), body.childNodes[0] || null);
    }
    if (NAMESPACE === HTML_NAMESPACE) {
      return getElementsByTagName.call(doc, WHOLE_DOCUMENT ? "html" : "body")[0];
    }
    return WHOLE_DOCUMENT ? doc.documentElement : body;
  };
  const _createNodeIterator = function _createNodeIterator2(root) {
    return createNodeIterator.call(
      root.ownerDocument || root,
      root,
      // eslint-disable-next-line no-bitwise
      NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_COMMENT | NodeFilter.SHOW_TEXT | NodeFilter.SHOW_PROCESSING_INSTRUCTION | NodeFilter.SHOW_CDATA_SECTION,
      null
    );
  };
  const _isClobbered = function _isClobbered2(element) {
    return element instanceof HTMLFormElement && (typeof element.nodeName !== "string" || typeof element.textContent !== "string" || typeof element.removeChild !== "function" || !(element.attributes instanceof NamedNodeMap) || typeof element.removeAttribute !== "function" || typeof element.setAttribute !== "function" || typeof element.namespaceURI !== "string" || typeof element.insertBefore !== "function" || typeof element.hasChildNodes !== "function");
  };
  const _isNode = function _isNode2(value) {
    return typeof Node === "function" && value instanceof Node;
  };
  function _executeHooks(hooks2, currentNode, data) {
    arrayForEach(hooks2, (hook) => {
      hook.call(DOMPurify, currentNode, data, CONFIG);
    });
  }
  const _sanitizeElements = function _sanitizeElements2(currentNode) {
    let content = null;
    _executeHooks(hooks.beforeSanitizeElements, currentNode, null);
    if (_isClobbered(currentNode)) {
      _forceRemove(currentNode);
      return true;
    }
    const tagName = transformCaseFunc(currentNode.nodeName);
    _executeHooks(hooks.uponSanitizeElement, currentNode, {
      tagName,
      allowedTags: ALLOWED_TAGS
    });
    if (SAFE_FOR_XML && currentNode.hasChildNodes() && !_isNode(currentNode.firstElementChild) && regExpTest(/<[/\w!]/g, currentNode.innerHTML) && regExpTest(/<[/\w!]/g, currentNode.textContent)) {
      _forceRemove(currentNode);
      return true;
    }
    if (currentNode.nodeType === NODE_TYPE.progressingInstruction) {
      _forceRemove(currentNode);
      return true;
    }
    if (SAFE_FOR_XML && currentNode.nodeType === NODE_TYPE.comment && regExpTest(/<[/\w]/g, currentNode.data)) {
      _forceRemove(currentNode);
      return true;
    }
    if (!(EXTRA_ELEMENT_HANDLING.tagCheck instanceof Function && EXTRA_ELEMENT_HANDLING.tagCheck(tagName)) && (!ALLOWED_TAGS[tagName] || FORBID_TAGS[tagName])) {
      if (!FORBID_TAGS[tagName] && _isBasicCustomElement(tagName)) {
        if (CUSTOM_ELEMENT_HANDLING.tagNameCheck instanceof RegExp && regExpTest(CUSTOM_ELEMENT_HANDLING.tagNameCheck, tagName)) {
          return false;
        }
        if (CUSTOM_ELEMENT_HANDLING.tagNameCheck instanceof Function && CUSTOM_ELEMENT_HANDLING.tagNameCheck(tagName)) {
          return false;
        }
      }
      if (KEEP_CONTENT && !FORBID_CONTENTS[tagName]) {
        const parentNode = getParentNode(currentNode) || currentNode.parentNode;
        const childNodes = getChildNodes(currentNode) || currentNode.childNodes;
        if (childNodes && parentNode) {
          const childCount = childNodes.length;
          for (let i = childCount - 1; i >= 0; --i) {
            const childClone = cloneNode(childNodes[i], true);
            childClone.__removalCount = (currentNode.__removalCount || 0) + 1;
            parentNode.insertBefore(childClone, getNextSibling(currentNode));
          }
        }
      }
      _forceRemove(currentNode);
      return true;
    }
    if (currentNode instanceof Element && !_checkValidNamespace(currentNode)) {
      _forceRemove(currentNode);
      return true;
    }
    if ((tagName === "noscript" || tagName === "noembed" || tagName === "noframes") && regExpTest(/<\/no(script|embed|frames)/i, currentNode.innerHTML)) {
      _forceRemove(currentNode);
      return true;
    }
    if (SAFE_FOR_TEMPLATES && currentNode.nodeType === NODE_TYPE.text) {
      content = currentNode.textContent;
      arrayForEach([MUSTACHE_EXPR2, ERB_EXPR2, TMPLIT_EXPR2], (expr) => {
        content = stringReplace(content, expr, " ");
      });
      if (currentNode.textContent !== content) {
        arrayPush(DOMPurify.removed, {
          element: currentNode.cloneNode()
        });
        currentNode.textContent = content;
      }
    }
    _executeHooks(hooks.afterSanitizeElements, currentNode, null);
    return false;
  };
  const _isValidAttribute = function _isValidAttribute2(lcTag, lcName, value) {
    if (FORBID_ATTR[lcName]) {
      return false;
    }
    if (SANITIZE_DOM && (lcName === "id" || lcName === "name") && (value in document2 || value in formElement)) {
      return false;
    }
    if (ALLOW_DATA_ATTR && !FORBID_ATTR[lcName] && regExpTest(DATA_ATTR2, lcName)) ;
    else if (ALLOW_ARIA_ATTR && regExpTest(ARIA_ATTR2, lcName)) ;
    else if (EXTRA_ELEMENT_HANDLING.attributeCheck instanceof Function && EXTRA_ELEMENT_HANDLING.attributeCheck(lcName, lcTag)) ;
    else if (!ALLOWED_ATTR[lcName] || FORBID_ATTR[lcName]) {
      if (
        // First condition does a very basic check if a) it's basically a valid custom element tagname AND
        // b) if the tagName passes whatever the user has configured for CUSTOM_ELEMENT_HANDLING.tagNameCheck
        // and c) if the attribute name passes whatever the user has configured for CUSTOM_ELEMENT_HANDLING.attributeNameCheck
        _isBasicCustomElement(lcTag) && (CUSTOM_ELEMENT_HANDLING.tagNameCheck instanceof RegExp && regExpTest(CUSTOM_ELEMENT_HANDLING.tagNameCheck, lcTag) || CUSTOM_ELEMENT_HANDLING.tagNameCheck instanceof Function && CUSTOM_ELEMENT_HANDLING.tagNameCheck(lcTag)) && (CUSTOM_ELEMENT_HANDLING.attributeNameCheck instanceof RegExp && regExpTest(CUSTOM_ELEMENT_HANDLING.attributeNameCheck, lcName) || CUSTOM_ELEMENT_HANDLING.attributeNameCheck instanceof Function && CUSTOM_ELEMENT_HANDLING.attributeNameCheck(lcName, lcTag)) || // Alternative, second condition checks if it's an `is`-attribute, AND
        // the value passes whatever the user has configured for CUSTOM_ELEMENT_HANDLING.tagNameCheck
        lcName === "is" && CUSTOM_ELEMENT_HANDLING.allowCustomizedBuiltInElements && (CUSTOM_ELEMENT_HANDLING.tagNameCheck instanceof RegExp && regExpTest(CUSTOM_ELEMENT_HANDLING.tagNameCheck, value) || CUSTOM_ELEMENT_HANDLING.tagNameCheck instanceof Function && CUSTOM_ELEMENT_HANDLING.tagNameCheck(value))
      ) ;
      else {
        return false;
      }
    } else if (URI_SAFE_ATTRIBUTES[lcName]) ;
    else if (regExpTest(IS_ALLOWED_URI$1, stringReplace(value, ATTR_WHITESPACE2, ""))) ;
    else if ((lcName === "src" || lcName === "xlink:href" || lcName === "href") && lcTag !== "script" && stringIndexOf(value, "data:") === 0 && DATA_URI_TAGS[lcTag]) ;
    else if (ALLOW_UNKNOWN_PROTOCOLS && !regExpTest(IS_SCRIPT_OR_DATA2, stringReplace(value, ATTR_WHITESPACE2, ""))) ;
    else if (value) {
      return false;
    } else ;
    return true;
  };
  const _isBasicCustomElement = function _isBasicCustomElement2(tagName) {
    return tagName !== "annotation-xml" && stringMatch(tagName, CUSTOM_ELEMENT2);
  };
  const _sanitizeAttributes = function _sanitizeAttributes2(currentNode) {
    _executeHooks(hooks.beforeSanitizeAttributes, currentNode, null);
    const {
      attributes
    } = currentNode;
    if (!attributes || _isClobbered(currentNode)) {
      return;
    }
    const hookEvent = {
      attrName: "",
      attrValue: "",
      keepAttr: true,
      allowedAttributes: ALLOWED_ATTR,
      forceKeepAttr: void 0
    };
    let l = attributes.length;
    while (l--) {
      const attr = attributes[l];
      const {
        name,
        namespaceURI,
        value: attrValue
      } = attr;
      const lcName = transformCaseFunc(name);
      const initValue = attrValue;
      let value = name === "value" ? initValue : stringTrim(initValue);
      hookEvent.attrName = lcName;
      hookEvent.attrValue = value;
      hookEvent.keepAttr = true;
      hookEvent.forceKeepAttr = void 0;
      _executeHooks(hooks.uponSanitizeAttribute, currentNode, hookEvent);
      value = hookEvent.attrValue;
      if (SANITIZE_NAMED_PROPS && (lcName === "id" || lcName === "name")) {
        _removeAttribute(name, currentNode);
        value = SANITIZE_NAMED_PROPS_PREFIX + value;
      }
      if (SAFE_FOR_XML && regExpTest(/((--!?|])>)|<\/(style|script|title|xmp|textarea|noscript|iframe|noembed|noframes)/i, value)) {
        _removeAttribute(name, currentNode);
        continue;
      }
      if (lcName === "attributename" && stringMatch(value, "href")) {
        _removeAttribute(name, currentNode);
        continue;
      }
      if (hookEvent.forceKeepAttr) {
        continue;
      }
      if (!hookEvent.keepAttr) {
        _removeAttribute(name, currentNode);
        continue;
      }
      if (!ALLOW_SELF_CLOSE_IN_ATTR && regExpTest(/\/>/i, value)) {
        _removeAttribute(name, currentNode);
        continue;
      }
      if (SAFE_FOR_TEMPLATES) {
        arrayForEach([MUSTACHE_EXPR2, ERB_EXPR2, TMPLIT_EXPR2], (expr) => {
          value = stringReplace(value, expr, " ");
        });
      }
      const lcTag = transformCaseFunc(currentNode.nodeName);
      if (!_isValidAttribute(lcTag, lcName, value)) {
        _removeAttribute(name, currentNode);
        continue;
      }
      if (trustedTypesPolicy && typeof trustedTypes === "object" && typeof trustedTypes.getAttributeType === "function") {
        if (namespaceURI) ;
        else {
          switch (trustedTypes.getAttributeType(lcTag, lcName)) {
            case "TrustedHTML": {
              value = trustedTypesPolicy.createHTML(value);
              break;
            }
            case "TrustedScriptURL": {
              value = trustedTypesPolicy.createScriptURL(value);
              break;
            }
          }
        }
      }
      if (value !== initValue) {
        try {
          if (namespaceURI) {
            currentNode.setAttributeNS(namespaceURI, name, value);
          } else {
            currentNode.setAttribute(name, value);
          }
          if (_isClobbered(currentNode)) {
            _forceRemove(currentNode);
          } else {
            arrayPop(DOMPurify.removed);
          }
        } catch (_) {
          _removeAttribute(name, currentNode);
        }
      }
    }
    _executeHooks(hooks.afterSanitizeAttributes, currentNode, null);
  };
  const _sanitizeShadowDOM = function _sanitizeShadowDOM2(fragment) {
    let shadowNode = null;
    const shadowIterator = _createNodeIterator(fragment);
    _executeHooks(hooks.beforeSanitizeShadowDOM, fragment, null);
    while (shadowNode = shadowIterator.nextNode()) {
      _executeHooks(hooks.uponSanitizeShadowNode, shadowNode, null);
      _sanitizeElements(shadowNode);
      _sanitizeAttributes(shadowNode);
      if (shadowNode.content instanceof DocumentFragment) {
        _sanitizeShadowDOM2(shadowNode.content);
      }
    }
    _executeHooks(hooks.afterSanitizeShadowDOM, fragment, null);
  };
  DOMPurify.sanitize = function(dirty) {
    let cfg = arguments.length > 1 && arguments[1] !== void 0 ? arguments[1] : {};
    let body = null;
    let importedNode = null;
    let currentNode = null;
    let returnNode = null;
    IS_EMPTY_INPUT = !dirty;
    if (IS_EMPTY_INPUT) {
      dirty = "<!-->";
    }
    if (typeof dirty !== "string" && !_isNode(dirty)) {
      if (typeof dirty.toString === "function") {
        dirty = dirty.toString();
        if (typeof dirty !== "string") {
          throw typeErrorCreate("dirty is not a string, aborting");
        }
      } else {
        throw typeErrorCreate("toString is not a function");
      }
    }
    if (!DOMPurify.isSupported) {
      return dirty;
    }
    if (!SET_CONFIG) {
      _parseConfig(cfg);
    }
    DOMPurify.removed = [];
    if (typeof dirty === "string") {
      IN_PLACE = false;
    }
    if (IN_PLACE) {
      if (dirty.nodeName) {
        const tagName = transformCaseFunc(dirty.nodeName);
        if (!ALLOWED_TAGS[tagName] || FORBID_TAGS[tagName]) {
          throw typeErrorCreate("root node is forbidden and cannot be sanitized in-place");
        }
      }
    } else if (dirty instanceof Node) {
      body = _initDocument("<!---->");
      importedNode = body.ownerDocument.importNode(dirty, true);
      if (importedNode.nodeType === NODE_TYPE.element && importedNode.nodeName === "BODY") {
        body = importedNode;
      } else if (importedNode.nodeName === "HTML") {
        body = importedNode;
      } else {
        body.appendChild(importedNode);
      }
    } else {
      if (!RETURN_DOM && !SAFE_FOR_TEMPLATES && !WHOLE_DOCUMENT && // eslint-disable-next-line unicorn/prefer-includes
      dirty.indexOf("<") === -1) {
        return trustedTypesPolicy && RETURN_TRUSTED_TYPE ? trustedTypesPolicy.createHTML(dirty) : dirty;
      }
      body = _initDocument(dirty);
      if (!body) {
        return RETURN_DOM ? null : RETURN_TRUSTED_TYPE ? emptyHTML : "";
      }
    }
    if (body && FORCE_BODY) {
      _forceRemove(body.firstChild);
    }
    const nodeIterator = _createNodeIterator(IN_PLACE ? dirty : body);
    while (currentNode = nodeIterator.nextNode()) {
      _sanitizeElements(currentNode);
      _sanitizeAttributes(currentNode);
      if (currentNode.content instanceof DocumentFragment) {
        _sanitizeShadowDOM(currentNode.content);
      }
    }
    if (IN_PLACE) {
      return dirty;
    }
    if (RETURN_DOM) {
      if (RETURN_DOM_FRAGMENT) {
        returnNode = createDocumentFragment.call(body.ownerDocument);
        while (body.firstChild) {
          returnNode.appendChild(body.firstChild);
        }
      } else {
        returnNode = body;
      }
      if (ALLOWED_ATTR.shadowroot || ALLOWED_ATTR.shadowrootmode) {
        returnNode = importNode.call(originalDocument, returnNode, true);
      }
      return returnNode;
    }
    let serializedHTML = WHOLE_DOCUMENT ? body.outerHTML : body.innerHTML;
    if (WHOLE_DOCUMENT && ALLOWED_TAGS["!doctype"] && body.ownerDocument && body.ownerDocument.doctype && body.ownerDocument.doctype.name && regExpTest(DOCTYPE_NAME, body.ownerDocument.doctype.name)) {
      serializedHTML = "<!DOCTYPE " + body.ownerDocument.doctype.name + ">\n" + serializedHTML;
    }
    if (SAFE_FOR_TEMPLATES) {
      arrayForEach([MUSTACHE_EXPR2, ERB_EXPR2, TMPLIT_EXPR2], (expr) => {
        serializedHTML = stringReplace(serializedHTML, expr, " ");
      });
    }
    return trustedTypesPolicy && RETURN_TRUSTED_TYPE ? trustedTypesPolicy.createHTML(serializedHTML) : serializedHTML;
  };
  DOMPurify.setConfig = function() {
    let cfg = arguments.length > 0 && arguments[0] !== void 0 ? arguments[0] : {};
    _parseConfig(cfg);
    SET_CONFIG = true;
  };
  DOMPurify.clearConfig = function() {
    CONFIG = null;
    SET_CONFIG = false;
  };
  DOMPurify.isValidAttribute = function(tag, attr, value) {
    if (!CONFIG) {
      _parseConfig({});
    }
    const lcTag = transformCaseFunc(tag);
    const lcName = transformCaseFunc(attr);
    return _isValidAttribute(lcTag, lcName, value);
  };
  DOMPurify.addHook = function(entryPoint, hookFunction) {
    if (typeof hookFunction !== "function") {
      return;
    }
    arrayPush(hooks[entryPoint], hookFunction);
  };
  DOMPurify.removeHook = function(entryPoint, hookFunction) {
    if (hookFunction !== void 0) {
      const index = arrayLastIndexOf(hooks[entryPoint], hookFunction);
      return index === -1 ? void 0 : arraySplice(hooks[entryPoint], index, 1)[0];
    }
    return arrayPop(hooks[entryPoint]);
  };
  DOMPurify.removeHooks = function(entryPoint) {
    hooks[entryPoint] = [];
  };
  DOMPurify.removeAllHooks = function() {
    hooks = _createHooksMap();
  };
  return DOMPurify;
}
var purify = createDOMPurify();
const DOCUMENT = 1, PARAGRAPH = 2, HEADING_1 = 3, HEADING_2 = 4, HEADING_3 = 5, HEADING_4 = 6, HEADING_5 = 7, HEADING_6 = 8, CODE_BLOCK = 9, CODE_FENCE = 10, CODE_INLINE = 11, ITALIC_AST = 12, ITALIC_UND = 13, STRONG_AST = 14, STRONG_UND = 15, STRIKE = 16, LINK = 17, RAW_URL = 18, IMAGE = 19, BLOCKQUOTE = 20, LINE_BREAK = 21, RULE = 22, LIST_UNORDERED = 23, LIST_ORDERED = 24, LIST_ITEM = 25, CHECKBOX = 26, TABLE = 27, TABLE_ROW = 28, TABLE_CELL = 29, EQUATION_BLOCK = 30, EQUATION_INLINE = 31, NEWLINE = 101, MAYBE_URL = 102, MAYBE_TASK = 103, MAYBE_BR = 104, MAYBE_EQ_BLOCK = 105;
const HREF = 1, SRC = 2, LANG = 4, CHECKED = 8, START = 16;
function attr_to_html_attr(type) {
  switch (type) {
    case HREF:
      return "href";
    case SRC:
      return "src";
    case LANG:
      return "class";
    case CHECKED:
      return "checked";
    case START:
      return "start";
  }
}
const level_to_heading = (level) => {
  switch (level) {
    case 1:
      return HEADING_1;
    case 2:
      return HEADING_2;
    case 3:
      return HEADING_3;
    case 4:
      return HEADING_4;
    case 5:
      return HEADING_5;
    default:
      return HEADING_6;
  }
};
const heading_from_level = level_to_heading;
const TOKEN_ARRAY_CAP = 24;
function parser(renderer) {
  const tokens = new Uint32Array(TOKEN_ARRAY_CAP);
  tokens[0] = DOCUMENT;
  return {
    renderer,
    text: "",
    pending: "",
    tokens,
    len: 0,
    token: DOCUMENT,
    fence_end: 0,
    blockquote_idx: 0,
    hr_char: "",
    hr_chars: 0,
    fence_start: 0,
    spaces: new Uint8Array(TOKEN_ARRAY_CAP),
    indent: "",
    indent_len: 0,
    table_state: 0
  };
}
function parser_end(p) {
  if (p.pending.length > 0) {
    parser_write(p, "\n");
  }
}
function add_text(p) {
  if (p.text.length === 0) return;
  console.assert(p.len > 0, "Never adding text to root");
  p.renderer.add_text(p.renderer.data, p.text);
  p.text = "";
}
function end_token(p) {
  console.assert(p.len > 0, "No nodes to end");
  p.len -= 1;
  p.token = /** @type {Token} */
  p.tokens[p.len];
  p.renderer.end_token(p.renderer.data);
}
function add_token(p, token) {
  if ((p.tokens[p.len] === LIST_ORDERED || p.tokens[p.len] === LIST_UNORDERED) && token !== LIST_ITEM) {
    end_token(p);
  }
  p.len += 1;
  p.tokens[p.len] = token;
  p.token = token;
  p.renderer.add_token(p.renderer.data, token);
}
function idx_of_token(p, token, start_idx) {
  while (start_idx <= p.len) {
    if (p.tokens[start_idx] === token) {
      return start_idx;
    }
    start_idx += 1;
  }
  return -1;
}
function end_tokens_to_len(p, len) {
  p.fence_start = 0;
  while (p.len > len) {
    end_token(p);
  }
}
function end_tokens_to_indent(p, indent) {
  let idx = 0;
  for (let i = 0; i <= p.len; i += 1) {
    indent -= p.spaces[i];
    if (indent < 0) {
      break;
    }
    switch (p.tokens[i]) {
      case CODE_BLOCK:
      case CODE_FENCE:
      case BLOCKQUOTE:
      case LIST_ITEM:
        idx = i;
        break;
    }
  }
  while (p.len > idx) {
    end_token(p);
  }
  return indent;
}
function continue_or_add_list(p, list_token) {
  let list_idx = -1;
  let item_idx = -1;
  for (let i = p.blockquote_idx + 1; i <= p.len; i += 1) {
    if (p.tokens[i] === LIST_ITEM) {
      if (p.indent_len < p.spaces[i]) {
        item_idx = -1;
        break;
      }
      item_idx = i;
    } else if (p.tokens[i] === list_token) {
      list_idx = i;
    }
  }
  if (item_idx === -1) {
    if (list_idx === -1) {
      end_tokens_to_len(p, p.blockquote_idx);
      add_token(p, list_token);
      return true;
    }
    end_tokens_to_len(p, list_idx);
    return false;
  }
  end_tokens_to_len(p, item_idx);
  add_token(p, list_token);
  return true;
}
function add_list_item(p, prefix_length) {
  add_token(p, LIST_ITEM);
  p.spaces[p.len] = p.indent_len + prefix_length;
  clear_root_pending(p);
  p.token = MAYBE_TASK;
}
function clear_root_pending(p) {
  p.indent = "";
  p.indent_len = 0;
  p.pending = "";
}
function is_digit(charcode) {
  switch (charcode) {
    case 48:
    case 49:
    case 50:
    case 51:
    case 52:
    case 53:
    case 54:
    case 55:
    case 56:
    case 57:
      return true;
    default:
      return false;
  }
}
function is_delimeter(charcode) {
  switch (charcode) {
    //   " "      ":"      ";"      ")"      ","      "!"      "."      "?"      "]"      "\n"
    case 32:
    case 58:
    case 59:
    case 41:
    case 44:
    case 33:
    case 46:
    case 63:
    case 93:
    case 10:
      return true;
    default:
      return false;
  }
}
function is_delimeter_or_number(charcode) {
  return is_digit(charcode) || is_delimeter(charcode);
}
function parser_write(p, chunk) {
  for (const char of chunk) {
    if (p.token === NEWLINE) {
      switch (char) {
        case " ":
          p.indent_len += 1;
          continue;
        case "	":
          p.indent_len += 4;
          continue;
      }
      let indent = end_tokens_to_indent(p, p.indent_len);
      p.indent_len = 0;
      p.token = p.tokens[p.len];
      if (indent > 0) {
        parser_write(p, " ".repeat(indent));
      }
    }
    const pending_with_char = p.pending + char;
    switch (p.token) {
      case LINE_BREAK:
      case DOCUMENT:
      case BLOCKQUOTE:
      case LIST_ORDERED:
      case LIST_UNORDERED:
        console.assert(p.text.length === 0, "Root should not have any text");
        switch (p.pending[0]) {
          case void 0:
            p.pending = char;
            continue;
          case " ":
            console.assert(p.pending.length === 1);
            p.pending = char;
            p.indent += " ";
            p.indent_len += 1;
            continue;
          case "	":
            console.assert(p.pending.length === 1);
            p.pending = char;
            p.indent += "	";
            p.indent_len += 4;
            continue;
          case "\n":
            console.assert(p.pending.length === 1);
            if (p.tokens[p.len] === LIST_ITEM && p.token === LINE_BREAK) {
              end_token(p);
              clear_root_pending(p);
              p.pending = char;
              continue;
            }
            end_tokens_to_len(p, p.blockquote_idx);
            clear_root_pending(p);
            p.blockquote_idx = 0;
            p.fence_start = 0;
            p.pending = char;
            continue;
          /* Heading */
          case "#":
            switch (char) {
              case "#":
                if (p.pending.length < 6) {
                  p.pending = pending_with_char;
                  continue;
                }
                break;
              // fail
              case " ":
                end_tokens_to_indent(p, p.indent_len);
                add_token(p, heading_from_level(p.pending.length));
                clear_root_pending(p);
                continue;
            }
            break;
          // fail
          /* Blockquote */
          case ">": {
            const next_blockquote_idx = idx_of_token(p, BLOCKQUOTE, p.blockquote_idx + 1);
            if (next_blockquote_idx === -1) {
              end_tokens_to_len(p, p.blockquote_idx);
              p.blockquote_idx += 1;
              p.fence_start = 0;
              add_token(p, BLOCKQUOTE);
            } else {
              p.blockquote_idx = next_blockquote_idx;
            }
            clear_root_pending(p);
            p.pending = char;
            continue;
          }
          /* Horizontal Rule
             "-- - --- - --"
          */
          case "-":
          case "*":
          case "_":
            if (p.hr_chars === 0) {
              console.assert(p.pending.length === 1, "Pending should be one character");
              p.hr_chars = 1;
              p.hr_char = p.pending;
            }
            if (p.hr_chars > 0) {
              switch (char) {
                case p.hr_char:
                  p.hr_chars += 1;
                  p.pending = pending_with_char;
                  continue;
                case " ":
                  p.pending = pending_with_char;
                  continue;
                case "\n":
                  if (p.hr_chars < 3) break;
                  end_tokens_to_indent(p, p.indent_len);
                  p.renderer.add_token(p.renderer.data, RULE);
                  p.renderer.end_token(p.renderer.data);
                  clear_root_pending(p);
                  p.hr_chars = 0;
                  continue;
              }
              p.hr_chars = 0;
            }
            if ("_" !== p.pending[0] && " " === p.pending[1]) {
              continue_or_add_list(p, LIST_UNORDERED);
              add_list_item(p, 2);
              parser_write(p, pending_with_char.slice(2));
              continue;
            }
            break;
          // fail
          /* Code Fence */
          case "`":
            if (p.pending.length < 3) {
              if ("`" === char) {
                p.pending = pending_with_char;
                p.fence_start = pending_with_char.length;
                continue;
              }
              p.fence_start = 0;
              break;
            }
            switch (char) {
              case "`":
                if (p.pending.length === p.fence_start) {
                  p.pending = pending_with_char;
                  p.fence_start = pending_with_char.length;
                } else {
                  add_token(p, PARAGRAPH);
                  clear_root_pending(p);
                  p.fence_start = 0;
                  parser_write(p, pending_with_char);
                }
                continue;
              case "\n": {
                end_tokens_to_indent(p, p.indent_len);
                add_token(p, CODE_FENCE);
                if (p.pending.length > p.fence_start) {
                  p.renderer.set_attr(p.renderer.data, LANG, p.pending.slice(p.fence_start));
                }
                clear_root_pending(p);
                p.token = NEWLINE;
                continue;
              }
              default:
                p.pending = pending_with_char;
                continue;
            }
          /*
          List Unordered for '+'
          The other list types are handled with HORIZONTAL_RULE
          */
          case "+":
            if (" " !== char) break;
            continue_or_add_list(p, LIST_UNORDERED);
            add_list_item(p, 2);
            continue;
          /* List Ordered */
          case "0":
          case "1":
          case "2":
          case "3":
          case "4":
          case "5":
          case "6":
          case "7":
          case "8":
          case "9":
            if ("." === p.pending[p.pending.length - 1]) {
              if (" " !== char) break;
              if (continue_or_add_list(p, LIST_ORDERED) && p.pending !== "1.") {
                p.renderer.set_attr(p.renderer.data, START, p.pending.slice(0, -1));
              }
              add_list_item(p, p.pending.length + 1);
              continue;
            } else {
              const char_code = char.charCodeAt(0);
              if (46 === char_code || // '.'
              is_digit(char_code)) {
                p.pending = pending_with_char;
                continue;
              }
            }
            break;
          // fail
          /* Table */
          case "|":
            end_tokens_to_len(p, p.blockquote_idx);
            add_token(p, TABLE);
            add_token(p, TABLE_ROW);
            p.pending = "";
            parser_write(p, char);
            continue;
        }
        let to_write = pending_with_char;
        if (p.token === LINE_BREAK) {
          p.token = p.tokens[p.len];
          p.renderer.add_token(p.renderer.data, LINE_BREAK);
          p.renderer.end_token(p.renderer.data);
        } else if (p.indent_len >= 4) {
          let code_start = 0;
          for (; code_start < 4; code_start += 1) {
            if (p.indent[code_start] === "	") {
              code_start = code_start + 1;
              break;
            }
          }
          to_write = p.indent.slice(code_start) + pending_with_char;
          add_token(p, CODE_BLOCK);
        } else {
          add_token(p, PARAGRAPH);
        }
        clear_root_pending(p);
        parser_write(p, to_write);
        continue;
      case TABLE:
        if (p.table_state === 1) {
          switch (char) {
            case "-":
            case " ":
            case "|":
            case ":":
              p.pending = pending_with_char;
              continue;
            case "\n":
              p.table_state = 2;
              p.pending = "";
              continue;
            default:
              end_token(p);
              p.table_state = 0;
              break;
          }
        } else {
          switch (p.pending) {
            case "|":
              add_token(p, TABLE_ROW);
              p.pending = "";
              parser_write(p, char);
              continue;
            case "\n":
              end_token(p);
              p.pending = "";
              p.table_state = 0;
              parser_write(p, char);
              continue;
          }
        }
        break;
      case TABLE_ROW:
        switch (p.pending) {
          case "":
            break;
          case "|":
            add_token(p, TABLE_CELL);
            end_token(p);
            p.pending = "";
            parser_write(p, char);
            continue;
          case "\n":
            end_token(p);
            p.table_state = Math.min(p.table_state + 1, 2);
            p.pending = "";
            parser_write(p, char);
            continue;
          default:
            add_token(p, TABLE_CELL);
            parser_write(p, char);
            continue;
        }
        break;
      case TABLE_CELL:
        if (p.pending === "|") {
          add_text(p);
          end_token(p);
          p.pending = "";
          parser_write(p, char);
          continue;
        }
        break;
      case CODE_BLOCK:
        switch (pending_with_char) {
          case "\n    ":
          case "\n   	":
          case "\n  	":
          case "\n 	":
          case "\n	":
            p.text += "\n";
            p.pending = "";
            continue;
          case "\n":
          case "\n ":
          case "\n  ":
          case "\n   ":
            p.pending = pending_with_char;
            continue;
          default:
            if (p.pending.length !== 0) {
              add_text(p);
              end_token(p);
              p.pending = char;
            } else {
              p.text += char;
            }
            continue;
        }
      case CODE_FENCE:
        switch (char) {
          case "`":
            p.pending = pending_with_char;
            continue;
          case "\n":
            if (pending_with_char.length === p.fence_start + p.fence_end + 1) {
              add_text(p);
              end_token(p);
              p.pending = "";
              p.fence_start = 0;
              p.fence_end = 0;
              p.token = NEWLINE;
              continue;
            }
            p.token = NEWLINE;
            break;
          case " ":
            if (p.pending[0] === "\n") {
              p.pending = pending_with_char;
              p.fence_end += 1;
              continue;
            }
            break;
        }
        p.text += p.pending;
        p.pending = char;
        p.fence_end = 1;
        continue;
      case CODE_INLINE:
        switch (char) {
          case "`":
            if (pending_with_char.length === p.fence_start + Number(p.pending[0] === " ")) {
              add_text(p);
              end_token(p);
              p.pending = "";
              p.fence_start = 0;
            } else {
              p.pending = pending_with_char;
            }
            continue;
          case "\n":
            p.text += p.pending;
            p.pending = "";
            p.token = LINE_BREAK;
            p.blockquote_idx = 0;
            add_text(p);
            continue;
          /* Trim space before ` */
          case " ":
            p.text += p.pending;
            p.pending = char;
            continue;
          default:
            p.text += pending_with_char;
            p.pending = "";
            continue;
        }
      /* Checkboxes */
      case MAYBE_TASK:
        switch (p.pending.length) {
          case 0:
            if ("[" !== char) break;
            p.pending = pending_with_char;
            continue;
          case 1:
            if (" " !== char && "x" !== char) break;
            p.pending = pending_with_char;
            continue;
          case 2:
            if ("]" !== char) break;
            p.pending = pending_with_char;
            continue;
          case 3:
            if (" " !== char) break;
            p.renderer.add_token(p.renderer.data, CHECKBOX);
            if ("x" === p.pending[1]) {
              p.renderer.set_attr(p.renderer.data, CHECKED, "");
            }
            p.renderer.end_token(p.renderer.data);
            p.pending = " ";
            continue;
        }
        p.token = p.tokens[p.len];
        p.pending = "";
        parser_write(p, pending_with_char);
        continue;
      case STRONG_AST:
      case STRONG_UND: {
        let symbol = "*";
        let italic = ITALIC_AST;
        if (p.token === STRONG_UND) {
          symbol = "_";
          italic = ITALIC_UND;
        }
        if (symbol === p.pending) {
          add_text(p);
          if (symbol === char) {
            end_token(p);
            p.pending = "";
            continue;
          }
          add_token(p, italic);
          p.pending = char;
          continue;
        }
        break;
      }
      case ITALIC_AST:
      case ITALIC_UND: {
        let symbol = "*";
        let strong = STRONG_AST;
        if (p.token === ITALIC_UND) {
          symbol = "_";
          strong = STRONG_UND;
        }
        switch (p.pending) {
          case symbol:
            if (symbol === char) {
              if (p.tokens[p.len - 1] === strong) {
                p.pending = pending_with_char;
              } else {
                add_text(p);
                add_token(p, strong);
                p.pending = "";
              }
            } else {
              add_text(p);
              end_token(p);
              p.pending = char;
            }
            continue;
          case symbol + symbol:
            const italic = p.token;
            add_text(p);
            end_token(p);
            end_token(p);
            if (symbol !== char) {
              add_token(p, italic);
              p.pending = char;
            } else {
              p.pending = "";
            }
            continue;
        }
        break;
      }
      case STRIKE:
        if ("~~" === pending_with_char) {
          add_text(p);
          end_token(p);
          p.pending = "";
          continue;
        }
        break;
      case MAYBE_EQ_BLOCK:
        if (char === "\n") {
          add_text(p);
          add_token(p, EQUATION_BLOCK);
          p.pending = "";
        } else {
          p.token = p.tokens[p.len];
          if (p.pending[0] === "\\") {
            p.text += "[";
          } else {
            p.text += "$$";
          }
          p.pending = "";
          parser_write(p, char);
        }
        continue;
      case EQUATION_BLOCK:
        if ("\\]" === pending_with_char || "$$" === pending_with_char) {
          add_text(p);
          end_token(p);
          p.pending = "";
          continue;
        }
        break;
      case EQUATION_INLINE:
        if ("\\)" === pending_with_char || "$" === p.pending[0]) {
          add_text(p);
          end_token(p);
          if (char === ")") {
            p.pending = "";
          } else {
            p.pending = char;
          }
          continue;
        }
        break;
      /* Raw URLs */
      case MAYBE_URL:
        if ("http://" === pending_with_char || "https://" === pending_with_char) {
          add_text(p);
          add_token(p, RAW_URL);
          p.pending = pending_with_char;
          p.text = pending_with_char;
        } else if ("http:/"[p.pending.length] === char || "https:/"[p.pending.length] === char) {
          p.pending = pending_with_char;
        } else {
          p.token = p.tokens[p.len];
          parser_write(p, char);
        }
        continue;
      case LINK:
      case IMAGE:
        if ("]" === p.pending) {
          add_text(p);
          if ("(" === char) {
            p.pending = pending_with_char;
          } else {
            end_token(p);
            p.pending = char;
          }
          continue;
        }
        if ("]" === p.pending[0] && "(" === p.pending[1]) {
          if (")" === char) {
            const type = p.token === LINK ? HREF : SRC;
            const url = p.pending.slice(2);
            p.renderer.set_attr(p.renderer.data, type, url);
            end_token(p);
            p.pending = "";
          } else {
            p.pending += char;
          }
          continue;
        }
        break;
      case RAW_URL:
        if (" " === char || "\n" === char || "\\" === char) {
          p.renderer.set_attr(p.renderer.data, HREF, p.pending);
          add_text(p);
          end_token(p);
          p.pending = char;
        } else {
          p.text += char;
          p.pending = pending_with_char;
        }
        continue;
      case MAYBE_BR:
        if (pending_with_char.startsWith("<br")) {
          if (
            /* "<br" */
            pending_with_char.length === 3 || /* "<br " */
            char === " " || /* "<br/" | "<br /" */
            char === "/" && (pending_with_char.length === 4 || p.pending[p.pending.length - 1] === " ")
          ) {
            p.pending = pending_with_char;
            continue;
          }
          if (char === ">") {
            add_text(p);
            p.token = p.tokens[p.len];
            p.renderer.add_token(p.renderer.data, LINE_BREAK);
            p.renderer.end_token(p.renderer.data);
            p.pending = "";
            continue;
          }
        }
        p.token = p.tokens[p.len];
        p.text += "<";
        p.pending = p.pending.slice(1);
        parser_write(p, char);
        continue;
    }
    switch (p.pending[0]) {
      /* Escape character */
      case "\\":
        if (p.token === IMAGE || p.token === EQUATION_BLOCK || p.token === EQUATION_INLINE)
          break;
        switch (char) {
          case "(":
            add_text(p);
            add_token(p, EQUATION_INLINE);
            p.pending = "";
            continue;
          case "[":
            p.token = MAYBE_EQ_BLOCK;
            p.pending = pending_with_char;
            continue;
          case "\n":
            p.pending = char;
            continue;
          default:
            let charcode = char.charCodeAt(0);
            p.pending = "";
            p.text += is_digit(charcode) || // 0-9
            charcode >= 65 && charcode <= 90 || // A-Z
            charcode >= 97 && charcode <= 122 ? pending_with_char : char;
            continue;
        }
      /* Newline */
      case "\n":
        switch (p.token) {
          case IMAGE:
          case EQUATION_BLOCK:
          case EQUATION_INLINE:
            break;
          case HEADING_1:
          case HEADING_2:
          case HEADING_3:
          case HEADING_4:
          case HEADING_5:
          case HEADING_6:
            add_text(p);
            end_tokens_to_len(p, p.blockquote_idx);
            p.blockquote_idx = 0;
            p.pending = char;
            continue;
          default:
            add_text(p);
            p.pending = char;
            p.token = LINE_BREAK;
            p.blockquote_idx = 0;
            continue;
        }
        break;
      /* <br> */
      case "<":
        if (p.token !== IMAGE && p.token !== EQUATION_BLOCK && p.token !== EQUATION_INLINE) {
          add_text(p);
          p.pending = pending_with_char;
          p.token = MAYBE_BR;
          continue;
        }
        break;
      /* `Code Inline` */
      case "`":
        if (p.token === IMAGE) break;
        if ("`" === char) {
          p.fence_start += 1;
          p.pending = pending_with_char;
        } else {
          p.fence_start += 1;
          add_text(p);
          add_token(p, CODE_INLINE);
          p.text = " " === char || "\n" === char ? "" : char;
          p.pending = "";
        }
        continue;
      case "_":
      case "*": {
        if (p.token === IMAGE || p.token === EQUATION_BLOCK || p.token === EQUATION_INLINE || p.token === STRONG_AST)
          break;
        let italic = ITALIC_AST;
        let strong = STRONG_AST;
        const symbol = p.pending[0];
        if ("_" === symbol) {
          italic = ITALIC_UND;
          strong = STRONG_UND;
        }
        if (p.pending.length === 1) {
          if (symbol === char) {
            p.pending = pending_with_char;
            continue;
          }
          if (" " !== char && "\n" !== char) {
            add_text(p);
            add_token(p, italic);
            p.pending = char;
            continue;
          }
        } else {
          if (symbol === char) {
            add_text(p);
            add_token(p, strong);
            add_token(p, italic);
            p.pending = "";
            continue;
          }
          if (" " !== char && "\n" !== char) {
            add_text(p);
            add_token(p, strong);
            p.pending = char;
            continue;
          }
        }
        break;
      }
      case "~":
        if (p.token !== IMAGE && p.token !== STRIKE) {
          if ("~" === p.pending) {
            if ("~" === char) {
              p.pending = pending_with_char;
              continue;
            }
          } else {
            if (" " !== char && "\n" !== char) {
              add_text(p);
              add_token(p, STRIKE);
              p.pending = char;
              continue;
            }
          }
        }
        break;
      /* $eq$ | $$eq$$ */
      case "$":
        if (p.token !== IMAGE && p.token !== STRIKE && "$" === p.pending) {
          if ("$" === char) {
            p.token = MAYBE_EQ_BLOCK;
            p.pending = pending_with_char;
            continue;
          } else if (is_delimeter_or_number(char.charCodeAt(0))) {
            break;
          } else {
            add_text(p);
            add_token(p, EQUATION_INLINE);
            p.pending = char;
            continue;
          }
        }
        break;
      /* [Image](url) */
      case "[":
        if (p.token !== IMAGE && p.token !== LINK && p.token !== EQUATION_BLOCK && p.token !== EQUATION_INLINE && "]" !== char) {
          add_text(p);
          add_token(p, LINK);
          p.pending = char;
          continue;
        }
        break;
      /* ![Image](url) */
      case "!":
        if (!(p.token === IMAGE) && "[" === char) {
          add_text(p);
          add_token(p, IMAGE);
          p.pending = "";
          continue;
        }
        break;
      /* Trim spaces */
      case " ":
        if (p.pending.length === 1 && " " === char) {
          continue;
        }
        break;
    }
    if (p.token !== IMAGE && p.token !== LINK && p.token !== EQUATION_BLOCK && p.token !== EQUATION_INLINE && "h" === char && (" " === p.pending || "" === p.pending)) {
      p.text += p.pending;
      p.pending = char;
      p.token = MAYBE_URL;
      continue;
    }
    p.text += p.pending;
    p.pending = char;
  }
  add_text(p);
}
function default_renderer(root) {
  return {
    add_token: default_add_token,
    end_token: default_end_token,
    add_text: default_add_text,
    set_attr: default_set_attr,
    data: {
      nodes: (
        /**@type {*}*/
        [root, , , , ,]
      ),
      index: 0
    }
  };
}
function default_add_token(data, type) {
  let parent = data.nodes[data.index];
  let slot;
  switch (type) {
    case DOCUMENT:
      return;
    // document is provided
    case BLOCKQUOTE:
      slot = document.createElement("blockquote");
      break;
    case PARAGRAPH:
      slot = document.createElement("p");
      break;
    case LINE_BREAK:
      slot = document.createElement("br");
      break;
    case RULE:
      slot = document.createElement("hr");
      break;
    case HEADING_1:
      slot = document.createElement("h1");
      break;
    case HEADING_2:
      slot = document.createElement("h2");
      break;
    case HEADING_3:
      slot = document.createElement("h3");
      break;
    case HEADING_4:
      slot = document.createElement("h4");
      break;
    case HEADING_5:
      slot = document.createElement("h5");
      break;
    case HEADING_6:
      slot = document.createElement("h6");
      break;
    case ITALIC_AST:
    case ITALIC_UND:
      slot = document.createElement("em");
      break;
    case STRONG_AST:
    case STRONG_UND:
      slot = document.createElement("strong");
      break;
    case STRIKE:
      slot = document.createElement("s");
      break;
    case CODE_INLINE:
      slot = document.createElement("code");
      break;
    case RAW_URL:
    case LINK:
      slot = document.createElement("a");
      break;
    case IMAGE:
      slot = document.createElement("img");
      break;
    case LIST_UNORDERED:
      slot = document.createElement("ul");
      break;
    case LIST_ORDERED:
      slot = document.createElement("ol");
      break;
    case LIST_ITEM:
      slot = document.createElement("li");
      break;
    case CHECKBOX:
      let checkbox = slot = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.disabled = true;
      break;
    case CODE_BLOCK:
    case CODE_FENCE:
      parent = parent.appendChild(document.createElement("pre"));
      slot = document.createElement("code");
      break;
    case TABLE:
      slot = document.createElement("table");
      break;
    case TABLE_ROW:
      switch (parent.children.length) {
        case 0:
          parent = parent.appendChild(document.createElement("thead"));
          break;
        case 1:
          parent = parent.appendChild(document.createElement("tbody"));
          break;
        default:
          parent = parent.children[1];
      }
      slot = document.createElement("tr");
      break;
    case TABLE_CELL:
      slot = document.createElement(parent.parentElement?.tagName === "THEAD" ? "th" : "td");
      break;
    case EQUATION_BLOCK:
      slot = document.createElement("equation-block");
      break;
    case EQUATION_INLINE:
      slot = document.createElement("equation-inline");
      break;
  }
  data.nodes[++data.index] = parent.appendChild(slot);
}
function default_end_token(data) {
  data.index -= 1;
}
function default_add_text(data, text2) {
  data.nodes[data.index].appendChild(document.createTextNode(text2));
}
function default_set_attr(data, type, value) {
  data.nodes[data.index].setAttribute(attr_to_html_attr(type), value);
}
const componentSheet$4 = new CSSStyleSheet();
componentSheet$4.replaceSync(`
  :host {
    display: block;
    animation: ck-fade-in 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  }
  .bubble {
    padding: 0.75rem 1rem;
    border-radius: var(--ck-radius-lg, 1.25rem);
    max-width: var(--ck-max-message-width, 48rem);
    word-wrap: break-word;
    overflow-wrap: break-word;
    transition: box-shadow 0.2s ease;
  }
  .bubble.user {
    background: linear-gradient(135deg, var(--ck-accent, #22c55e) 0%, #059669 100%);
    color: #fff;
    margin-left: auto;
    border-bottom-right-radius: 4px;
    max-width: 80%;
    box-shadow: 0 2px 16px var(--ck-shadow-accent, rgba(34, 197, 94, 0.15));
  }
  .bubble.assistant {
    background: var(--ck-bg-surface, #141414);
    border: 1px solid var(--ck-border, #1e1e1e);
    border-bottom-left-radius: 4px;
  }
  .bubble.error {
    background: var(--ck-bg-error, #2a0a0a);
    color: var(--ck-text-error, #ff6b6b);
    border: 1px solid var(--ck-border-error, #4c1d1d);
  }
  .code-block {
    margin: 0.5rem 0;
  }
  .code-block summary {
    cursor: pointer;
    color: var(--ck-text-muted, #5a5a5a);
    font-size: var(--ck-font-size-sm, 0.8125rem);
    font-family: var(--ck-font-mono, monospace);
    padding: 0.25rem 0;
    transition: color 0.15s;
  }
  .code-block summary:hover {
    color: var(--ck-text-secondary, #A1A1A1);
  }
  .code-block pre {
    background: var(--ck-bg-code, #0d1117);
    padding: 0.75rem 1rem;
    border-radius: var(--ck-radius, 0.75rem);
    overflow-x: auto;
    font-family: var(--ck-font-mono, monospace);
    font-size: 0.85em;
    line-height: 1.5;
    border: 1px solid var(--ck-border, #1e1e1e);
  }
`);
class CkMessage extends CkBase {
  static properties = {
    role: { type: String, reflect: true }
  };
  static styles = [
    resetSheet,
    animationsSheet,
    markdownSheet,
    componentSheet$4
  ];
  // Streaming state
  #parser = null;
  #container = null;
  #pendingText = "";
  #rafScheduled = false;
  #streaming = false;
  #finalContent = "";
  /** Start streaming mode — subsequent appendText() calls render incrementally. */
  startStreaming() {
    this.#streaming = true;
    this.#pendingText = "";
    this.#finalContent = "";
    this.requestUpdate();
  }
  /** Append a chunk of streaming text (for assistant messages). */
  appendText(chunk) {
    if (!this.#streaming) return;
    this.#pendingText += chunk;
    this.#finalContent += chunk;
    if (!this.#rafScheduled) {
      this.#rafScheduled = true;
      requestAnimationFrame(() => {
        this.#rafScheduled = false;
        if (this.#parser && this.#pendingText) {
          parser_write(this.#parser, this.#pendingText);
          this.#pendingText = "";
        }
      });
    }
  }
  /** End streaming and finalize the message content. */
  endStreaming() {
    if (this.#parser) {
      if (this.#pendingText) {
        parser_write(this.#parser, this.#pendingText);
        this.#pendingText = "";
      }
      parser_end(this.#parser);
      this.#parser = null;
      this.#sanitizeContainer();
    }
    this.#streaming = false;
  }
  /** Set full message content (for loading history, not streaming). */
  setContent(content) {
    this.#streaming = false;
    this.#finalContent = content;
    this.requestUpdate();
  }
  /** Append a collapsible code block to the message. */
  appendCodeBlock(code, label = "Code") {
    this.#ensureContainer();
    const details = document.createElement("details");
    details.className = "code-block";
    const summary = document.createElement("summary");
    summary.textContent = `${label}`;
    const pre = document.createElement("pre");
    const codeEl = document.createElement("code");
    codeEl.textContent = code;
    pre.appendChild(codeEl);
    details.appendChild(summary);
    details.appendChild(pre);
    this.#container.appendChild(details);
  }
  /** Eagerly create the container if update() hasn't run yet. */
  #ensureContainer() {
    if (this.#container) return;
    const shadow = this.shadowRoot;
    shadow.innerHTML = "";
    const bubble = document.createElement("div");
    const role = this.role ?? "assistant";
    bubble.className = `bubble ${role}`;
    if (role === "user") {
      this.#container = bubble;
    } else {
      const markdown = document.createElement("div");
      markdown.className = "ck-markdown";
      bubble.appendChild(markdown);
      this.#container = markdown;
    }
    shadow.appendChild(bubble);
  }
  #sanitizeContainer() {
    if (!this.#container) return;
    const clean = purify.sanitize(this.#container.innerHTML, {
      ALLOWED_TAGS: [
        "p",
        "strong",
        "em",
        "code",
        "pre",
        "ul",
        "ol",
        "li",
        "a",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "br",
        "hr",
        "details",
        "summary",
        "span",
        "div",
        "del",
        "s"
      ],
      ALLOWED_ATTR: ["href", "class", "open"],
      ALLOW_DATA_ATTR: false
    });
    if (clean !== this.#container.innerHTML) {
      this.#container.innerHTML = clean;
    }
  }
  update() {
    const shadow = this.shadowRoot;
    const role = this.role ?? "assistant";
    if (!this.#container) {
      shadow.innerHTML = "";
      const bubble = document.createElement("div");
      bubble.className = `bubble ${role}`;
      if (role === "user") {
        this.#container = bubble;
      } else {
        const markdown = document.createElement("div");
        markdown.className = "ck-markdown";
        bubble.appendChild(markdown);
        this.#container = markdown;
      }
      shadow.appendChild(bubble);
    }
    if (role === "user" && this.#container) {
      this.#container.textContent = this.#finalContent;
      return;
    }
    if (this.#streaming && !this.#parser && this.#container) {
      this.#container.innerHTML = "";
      const renderer = default_renderer(this.#container);
      this.#parser = parser(renderer);
    }
    if (!this.#streaming && !this.#parser && this.#container && this.#finalContent) {
      const renderer = default_renderer(this.#container);
      const parser$1 = parser(renderer);
      parser_write(parser$1, this.#finalContent);
      parser_end(parser$1);
      this.#sanitizeContainer();
    }
  }
}
const componentSheet$3 = new CSSStyleSheet();
componentSheet$3.replaceSync(`
  :host {
    display: flex;
    flex-direction: column;
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 1rem;
    scroll-behavior: auto;
  }
  :host::-webkit-scrollbar {
    width: 6px;
  }
  :host::-webkit-scrollbar-track {
    background: transparent;
  }
  :host::-webkit-scrollbar-thumb {
    background: var(--ck-scrollbar, #2a2a2a);
    border-radius: 3px;
  }
  :host::-webkit-scrollbar-thumb:hover {
    background: var(--ck-text-muted, #5a5a5a);
  }
  .messages-inner {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    max-width: var(--ck-max-message-width, 48rem);
    width: 100%;
    margin: 0 auto;
    padding-bottom: 1rem;
  }
  .ck-turn {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .ck-turn + .ck-turn {
    margin-top: 0.25rem;
  }
  .turn-phase + .turn-phase {
    padding-top: 0.5rem;
  }
  .status-bubble {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 1rem;
    background: var(--ck-bg-status, #0f0d2e);
    color: var(--ck-text-status, #818cf8);
    border-radius: var(--ck-radius, 0.75rem);
    border: 1px solid var(--ck-border-status, #312e81);
    font-size: var(--ck-font-size-sm, 0.8125rem);
    animation: ck-fade-in 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  }
  .pulse-dots {
    display: flex;
    gap: 3px;
  }
  .pulse-dots span {
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--ck-text-status, #818cf8);
    animation: ck-pulse-dot 1.4s ease-in-out infinite;
  }
  .pulse-dots span:nth-child(2) { animation-delay: 0.2s; }
  .pulse-dots span:nth-child(3) { animation-delay: 0.4s; }
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    flex: 1;
    color: var(--ck-text-muted, #5a5a5a);
    gap: 0.75rem;
    padding: 2rem;
  }
  .empty-state-title {
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--ck-text-secondary, #A1A1A1);
    letter-spacing: -0.01em;
  }
  .empty-state-subtitle {
    font-size: 0.875rem;
  }
  .scroll-sentinel {
    height: 0;
    width: 0;
    flex-shrink: 0;
  }
`);
class CkMessages extends CkBase {
  static styles = [resetSheet, animationsSheet, componentSheet$3];
  #inner = null;
  #sentinel = null;
  #statusEl = null;
  #emptyState = null;
  #currentTurn = null;
  #scrollScheduled = false;
  #userScrolledAway = false;
  /** Get or create the current assistant turn container. */
  getOrCreateTurn() {
    if (this.#currentTurn) return this.#currentTurn;
    this.#hideEmptyShowMessages();
    const turn = document.createElement("div");
    turn.className = "ck-turn";
    this.#inner.insertBefore(turn, this.#sentinel);
    this.#currentTurn = turn;
    return turn;
  }
  /** Reset the current turn (call after "done" event). */
  resetTurn() {
    this.#currentTurn = null;
  }
  /** Add a child element to the current turn as a new phase. */
  addTurnPhase(element) {
    const turn = this.getOrCreateTurn();
    element.classList.add("turn-phase");
    turn.appendChild(element);
    this.scheduleScroll();
  }
  /** Find a rendered element by selector. Content lives in the shadow root,
   * so external `querySelector` calls cannot reach it — use this instead. */
  findRendered(selector) {
    return this.shadowRoot?.querySelector(selector) ?? null;
  }
  /** Add a standalone element outside of turns (e.g., user messages). */
  addMessage(element) {
    this.#hideEmptyShowMessages();
    this.#inner.insertBefore(element, this.#sentinel);
    this.scheduleScroll();
  }
  /** Show a status message with pulsing dots. */
  showStatus(message) {
    if (!this.#statusEl) {
      this.#statusEl = document.createElement("div");
      this.#statusEl.className = "status-bubble";
      this.#statusEl.innerHTML = `
        <div class="pulse-dots"><span></span><span></span><span></span></div>
        <span class="status-text"></span>
      `;
    }
    const textEl = this.#statusEl.querySelector(".status-text");
    if (textEl) textEl.textContent = message;
    const parent = this.#currentTurn ?? this.#inner;
    if (this.#statusEl.parentElement !== parent) {
      if (parent === this.#inner) {
        parent.insertBefore(this.#statusEl, this.#sentinel);
      } else {
        parent.appendChild(this.#statusEl);
      }
    }
    this.scheduleScroll();
  }
  /** Remove the status indicator. */
  hideStatus() {
    this.#statusEl?.remove();
  }
  /** Clear all messages and show empty state. */
  clear() {
    if (this.#inner) {
      const children = Array.from(this.#inner.children);
      for (const child of children) {
        if (child !== this.#sentinel) child.remove();
      }
    }
    this.#currentTurn = null;
    this.#statusEl = null;
    if (this.#emptyState) this.#emptyState.style.display = "";
    if (this.#inner) this.#inner.style.display = "none";
  }
  /** Schedule a scroll-to-bottom on next animation frame. */
  scheduleScroll() {
    if (this.#userScrolledAway || this.#scrollScheduled) return;
    this.#scrollScheduled = true;
    requestAnimationFrame(() => {
      this.#scrollScheduled = false;
      this.#sentinel?.scrollIntoView({ block: "end", behavior: "instant" });
    });
  }
  #hideEmptyShowMessages() {
    if (this.#emptyState) this.#emptyState.style.display = "none";
    if (this.#inner) this.#inner.style.display = "";
  }
  update() {
    const shadow = this.shadowRoot;
    if (this.#inner) return;
    shadow.innerHTML = "";
    this.#emptyState = document.createElement("div");
    this.#emptyState.className = "empty-state";
    this.#emptyState.innerHTML = `
      <div class="empty-state-title">Start a conversation</div>
      <div class="empty-state-subtitle">Send a message to begin</div>
    `;
    shadow.appendChild(this.#emptyState);
    this.#inner = document.createElement("div");
    this.#inner.className = "messages-inner";
    this.#inner.style.display = "none";
    this.#sentinel = document.createElement("div");
    this.#sentinel.className = "scroll-sentinel";
    this.#inner.appendChild(this.#sentinel);
    shadow.appendChild(this.#inner);
    this.listen(this, "scroll", () => {
      const distanceFromBottom = this.scrollHeight - this.scrollTop - this.clientHeight;
      this.#userScrolledAway = distanceFromBottom > 50;
    }, { passive: true });
  }
}
const componentSheet$2 = new CSSStyleSheet();
componentSheet$2.replaceSync(`
  :host {
    display: block;
    padding: 0.75rem 1rem;
    background: var(--ck-bg, #0A0A0A);
  }
  .input-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    background: var(--ck-bg-input, #141414);
    border: 1px solid var(--ck-border, #1e1e1e);
    border-radius: 1.5rem;
    padding: 0.375rem 0.375rem 0.375rem 1rem;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
  }
  .input-row:focus-within {
    border-color: var(--ck-accent, #22c55e);
    box-shadow: 0 0 0 3px var(--ck-accent-glow, rgba(34, 197, 94, 0.25)), 0 0 20px var(--ck-accent-glow, rgba(34, 197, 94, 0.25));
  }
  input {
    flex: 1;
    border: none;
    outline: none;
    background: transparent;
    color: var(--ck-text, #F0F0F0);
    font-family: var(--ck-font, system-ui, sans-serif);
    font-size: var(--ck-font-size, 0.9375rem);
    line-height: 1.4;
  }
  input::placeholder {
    color: var(--ck-text-muted, #5a5a5a);
  }
  .btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2.25rem;
    height: 2.25rem;
    border-radius: 50%;
    border: none;
    cursor: pointer;
    flex-shrink: 0;
    transition: background 0.15s, transform 0.15s, box-shadow 0.15s;
  }
  .send-btn {
    background: var(--ck-accent, #22c55e);
    color: #fff;
  }
  .send-btn:hover {
    background: var(--ck-accent-hover, #16a34a);
    transform: scale(1.08);
    box-shadow: 0 0 12px var(--ck-accent-glow, rgba(34, 197, 94, 0.25));
  }
  .send-btn:active {
    transform: scale(0.95);
  }
  .send-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
  }
  .stop-btn {
    background: var(--ck-text-error, #ff6b6b);
    color: #fff;
  }
  .stop-btn:hover {
    transform: scale(1.08);
  }
  .stop-btn:active {
    transform: scale(0.95);
  }
  .btn svg {
    width: 1rem;
    height: 1rem;
  }
`);
class CkInput extends CkBase {
  static properties = {
    streaming: { type: Boolean, reflect: true },
    disabled: { type: Boolean, reflect: true },
    placeholder: { type: String }
  };
  static styles = [resetSheet, componentSheet$2];
  #input = null;
  #sendBtn = null;
  #stopBtn = null;
  /** Focus the input field. */
  focusInput() {
    this.#input?.focus();
  }
  update() {
    const shadow = this.shadowRoot;
    if (!this.#input) {
      shadow.innerHTML = "";
      const row = document.createElement("div");
      row.className = "input-row";
      this.#input = document.createElement("input");
      this.#input.type = "text";
      this.#input.placeholder = this.placeholder ?? "Send a message...";
      this.#input.autocomplete = "off";
      this.#sendBtn = document.createElement("button");
      this.#sendBtn.className = "btn send-btn";
      this.#sendBtn.type = "button";
      this.#sendBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>`;
      this.#stopBtn = document.createElement("button");
      this.#stopBtn.className = "btn stop-btn";
      this.#stopBtn.type = "button";
      this.#stopBtn.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>`;
      this.#stopBtn.style.display = "none";
      row.appendChild(this.#input);
      row.appendChild(this.#sendBtn);
      row.appendChild(this.#stopBtn);
      shadow.appendChild(row);
      this.listen(this.#input, "keydown", ((e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          this.#submit();
        }
      }));
      this.listen(this.#sendBtn, "click", () => this.#submit());
      this.listen(this.#stopBtn, "click", () => {
        this.dispatchEvent(
          new CustomEvent("ck-stop", { bubbles: true, composed: true })
        );
      });
    }
    const isStreaming = this.streaming ?? false;
    const isDisabled = this.disabled ?? false;
    this.#input.disabled = isStreaming || isDisabled;
    this.#sendBtn.disabled = isStreaming || isDisabled;
    this.#sendBtn.style.display = isStreaming ? "none" : "";
    this.#stopBtn.style.display = isStreaming ? "" : "none";
    if (this.placeholder) {
      this.#input.placeholder = this.placeholder;
    }
  }
  #submit() {
    if (!this.#input || this.streaming || this.disabled) return;
    const text2 = this.#input.value.trim();
    if (!text2) return;
    this.#input.value = "";
    this.dispatchEvent(
      new CustomEvent("ck-submit", {
        bubbles: true,
        composed: true,
        detail: { message: text2 }
      })
    );
  }
}
const componentSheet$1 = new CSSStyleSheet();
componentSheet$1.replaceSync(`
  :host {
    display: block;
    animation: ck-fade-in 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  }
  .card {
    display: flex;
    align-items: center;
    gap: 0.625rem;
    padding: 0.5rem 0.875rem;
    background: var(--ck-bg-surface, #141414);
    border: 1px solid var(--ck-border, #1e1e1e);
    border-radius: var(--ck-radius, 0.75rem);
    font-size: var(--ck-font-size-sm, 0.8125rem);
    transition: border-color 0.2s;
  }
  .card.running {
    border-color: var(--ck-accent, #22c55e);
    box-shadow: 0 0 8px var(--ck-accent-glow, rgba(34, 197, 94, 0.25));
  }
  .card.done {
    border-color: var(--ck-border, #1e1e1e);
  }
  .spinner {
    width: 14px;
    height: 14px;
    border: 2px solid var(--ck-border, #1e1e1e);
    border-top-color: var(--ck-accent, #22c55e);
    border-radius: 50%;
    animation: ck-spin 0.7s linear infinite;
    flex-shrink: 0;
  }
  .check {
    color: var(--ck-text-success, #34d399);
    flex-shrink: 0;
    font-size: 1rem;
    line-height: 1;
  }
  .tool-name {
    font-weight: 500;
    color: var(--ck-text, #F0F0F0);
    font-family: var(--ck-font-mono, monospace);
    font-size: 0.8em;
  }
  .summary {
    color: var(--ck-text-secondary, #A1A1A1);
  }
`);
class CkToolCard extends CkBase {
  static properties = {
    toolName: { type: String, attribute: "tool-name" },
    status: { type: String, reflect: true },
    summary: { type: String }
  };
  static styles = [resetSheet, animationsSheet, componentSheet$1];
  update() {
    const shadow = this.shadowRoot;
    const isRunning = (this.status ?? "running") === "running";
    shadow.innerHTML = "";
    const card = document.createElement("div");
    card.className = `card ${isRunning ? "running" : "done"}`;
    if (isRunning) {
      card.innerHTML = `
        <div class="spinner"></div>
        <span class="tool-name">${this.#escape(this.toolName ?? "Tool")}</span>
      `;
    } else {
      card.innerHTML = `
        <span class="check">✓</span>
        <span class="tool-name">${this.#escape(this.toolName ?? "Tool")}</span>
        ${this.summary ? `<span class="summary">— ${this.#escape(this.summary)}</span>` : ""}
      `;
    }
    shadow.appendChild(card);
  }
  #escape(text2) {
    const div = document.createElement("div");
    div.textContent = text2;
    return div.innerHTML;
  }
}
const componentSheet = new CSSStyleSheet();
componentSheet.replaceSync(`
  :host {
    display: block;
    animation: ck-fade-in 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  }
  .card {
    border: 1px solid var(--ck-border, #1e1e1e);
    border-radius: var(--ck-radius, 0.75rem);
    overflow: hidden;
    background: var(--ck-bg-surface, #141414);
  }
  .tab-bar {
    display: flex;
    gap: 0;
    border-bottom: 1px solid var(--ck-border, #1e1e1e);
    background: var(--ck-table-header, #111111);
    overflow-x: auto;
  }
  .tab-btn {
    padding: 0.5rem 1rem;
    border: none;
    background: transparent;
    color: var(--ck-text-muted, #5a5a5a);
    font-size: var(--ck-font-size-sm, 0.8125rem);
    font-family: var(--ck-font, system-ui, sans-serif);
    cursor: pointer;
    white-space: nowrap;
    border-bottom: 2px solid transparent;
    transition: color 0.15s, border-color 0.15s;
  }
  .tab-btn:hover {
    color: var(--ck-text, #F0F0F0);
  }
  .tab-btn.active {
    color: var(--ck-accent, #22c55e);
    border-bottom-color: var(--ck-accent, #22c55e);
  }
  .tab-content {
    padding: 0.75rem 1rem;
    max-height: 24rem;
    overflow: auto;
  }
  .tab-content::-webkit-scrollbar {
    width: 4px;
    height: 4px;
  }
  .tab-content::-webkit-scrollbar-thumb {
    background: var(--ck-scrollbar, #2a2a2a);
    border-radius: 2px;
  }
  .tab-content pre {
    margin: 0;
    font-family: var(--ck-font-mono, monospace);
    font-size: 0.85em;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85em;
  }
  .data-table th, .data-table td {
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--ck-border, #1e1e1e);
    text-align: left;
  }
  .data-table th {
    background: var(--ck-table-header, #111111);
    font-weight: 600;
    position: sticky;
    top: 0;
    color: var(--ck-text-secondary, #A1A1A1);
    text-transform: uppercase;
    font-size: 0.75em;
    letter-spacing: 0.05em;
  }
  .data-table tr:nth-child(even) td {
    background: var(--ck-table-stripe, #0e0e0e);
  }
  .data-table tr:hover td {
    background: var(--ck-table-hover, #1a1540);
  }
  .error-text {
    color: var(--ck-text-error, #ff6b6b);
  }
`);
class CkArtifact extends CkBase {
  static styles = [resetSheet, animationsSheet, componentSheet];
  #tabs = [];
  #activeTab = 0;
  /** Set the artifact data and auto-generate tabs. */
  setData(data) {
    this.#tabs = this.#generateTabs(data);
    this.#activeTab = 0;
    this.requestUpdate();
  }
  #generateTabs(data) {
    const tabs = [];
    let parsed = null;
    if (data.result_json) {
      try {
        parsed = JSON.parse(data.result_json);
      } catch {
      }
    }
    if (parsed != null) {
      if (data.result_type === "table" && Array.isArray(parsed) && parsed.length > 0) {
        tabs.push({ label: "Table", content: this.#renderTable(parsed), type: "html" });
      } else if (data.result_type === "scalar") {
        tabs.push({ label: "Value", content: String(parsed), type: "text" });
      } else {
        tabs.push({ label: "Result", content: JSON.stringify(parsed, null, 2), type: "code" });
      }
    }
    if (data.error) {
      tabs.push({ label: "Error", content: data.error, type: "text" });
    }
    if (data.code) {
      tabs.push({ label: "Code", content: data.code, type: "code" });
    }
    if (data.result_json) {
      tabs.push({ label: "Raw JSON", content: data.result_json, type: "code" });
    }
    return tabs;
  }
  #renderTable(rows) {
    if (rows.length === 0) return "<p>No data</p>";
    const keys = Object.keys(rows[0]);
    const header = keys.map((k) => `<th>${this.#escape(k)}</th>`).join("");
    const body = rows.slice(0, 100).map(
      (row) => `<tr>${keys.map((k) => `<td>${this.#escape(String(row[k] ?? ""))}</td>`).join("")}</tr>`
    ).join("");
    let html2 = `<table class="data-table"><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
    if (rows.length > 100) {
      html2 += `<p style="color:var(--ck-text-muted);font-size:0.8em;margin-top:0.5em;">Showing 100 of ${rows.length} rows</p>`;
    }
    return html2;
  }
  #escape(text2) {
    const div = document.createElement("div");
    div.textContent = text2;
    return div.innerHTML;
  }
  update() {
    const shadow = this.shadowRoot;
    shadow.innerHTML = "";
    if (this.#tabs.length === 0) return;
    const card = document.createElement("div");
    card.className = "card";
    const tabBar = document.createElement("div");
    tabBar.className = "tab-bar";
    this.#tabs.forEach((tab, i) => {
      const btn = document.createElement("button");
      btn.className = `tab-btn${i === this.#activeTab ? " active" : ""}`;
      btn.textContent = tab.label;
      btn.addEventListener("click", () => {
        this.#activeTab = i;
        this.requestUpdate();
      });
      tabBar.appendChild(btn);
    });
    card.appendChild(tabBar);
    const activeTab = this.#tabs[this.#activeTab];
    if (activeTab) {
      const content = document.createElement("div");
      content.className = "tab-content";
      if (activeTab.type === "code") {
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = activeTab.content;
        pre.appendChild(code);
        content.appendChild(pre);
      } else if (activeTab.type === "html") {
        content.innerHTML = purify.sanitize(activeTab.content, {
          ALLOWED_TAGS: ["table", "thead", "tbody", "tr", "th", "td", "p"],
          ALLOWED_ATTR: ["class", "style"]
        });
      } else if (activeTab.type === "text") {
        const isError = activeTab.label === "Error";
        const p = document.createElement("pre");
        if (isError) p.className = "error-text";
        p.textContent = activeTab.content;
        content.appendChild(p);
      } else {
        content.textContent = activeTab.content;
      }
      card.appendChild(content);
    }
    shadow.appendChild(card);
  }
}
export {
  CkApp,
  CkArtifact,
  CkBase,
  CkInput,
  CkMessage,
  CkMessages,
  CkSidebar,
  CkToolCard,
  EventType,
  StreamState,
  StreamStateMachine,
  animationsSheet,
  connectSSE,
  markdownSheet,
  resetSheet
};
//# sourceMappingURL=index.js.map
