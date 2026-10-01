"use strict";

/*
 * Minimal, dependency-free browser harness for the Phase 3.4 content script.
 *
 * It provides just enough DOM, MutationObserver, IntersectionObserver, and
 * `chrome` surface for `extension/content.js`, and loads the real extension
 * modules (`image-detector`, `translation-queue`, `lazy-observer`) inside a
 * `vm` context. The translation client is a stub so tests never touch the
 * backend or load OCR/MT models.
 */

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const EXTENSION_DIR = path.join(__dirname, "..", "..", "extension");

function attributeNameFor(datasetKey) {
  return `data-${String(datasetKey).replace(
    /[A-Z]/g,
    (letter) => `-${letter.toLowerCase()}`,
  )}`;
}

function matchesSelector(element, selector) {
  if (!element || element.nodeType !== 1) {
    return false;
  }
  let rest = String(selector).trim();

  const attributeMatch = rest.match(/\[([a-zA-Z0-9-]+)(?:="([^"]*)")?\]/);
  if (attributeMatch) {
    rest = rest.replace(attributeMatch[0], "");
    if (!element.hasAttribute(attributeMatch[1])) {
      return false;
    }
    if (
      attributeMatch[2] !== undefined &&
      element.getAttribute(attributeMatch[1]) !== attributeMatch[2]
    ) {
      return false;
    }
  }

  const classMatches = rest.match(/\.[a-zA-Z0-9_-]+/g) || [];
  for (const token of classMatches) {
    if (!String(element.className).split(/\s+/).includes(token.slice(1))) {
      return false;
    }
  }
  rest = rest.replace(/\.[a-zA-Z0-9_-]+/g, "").trim();

  return !rest || element.tagName === rest.toUpperCase();
}

function descendants(root) {
  const found = [];
  const walk = (node) => {
    for (const child of node.childNodes) {
      if (child.nodeType === 1) {
        found.push(child);
        walk(child);
      }
    }
  };
  walk(root);
  return found;
}

class FakeElement {
  constructor(tagName, ownerDocument) {
    this.tagName = String(tagName).toUpperCase();
    this.ownerDocument = ownerDocument;
    this.nodeType = 1;
    this.childNodes = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.className = "";
    this.textContent = "";
    this.style = {};
    this.isConnected = true;
    this.rect = { width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0 };
    this.clientWidth = 0;
    this.clientHeight = 0;
    this.clientLeft = 0;
    this.clientTop = 0;
    this.listeners = new Map();

    const attributes = this.attributes;
    this.dataset = new Proxy(
      {},
      {
        get: (_target, key) => attributes.get(attributeNameFor(key)),
        set: (_target, key, value) => {
          attributes.set(attributeNameFor(key), String(value));
          return true;
        },
        has: (_target, key) => attributes.has(attributeNameFor(key)),
        deleteProperty: (_target, key) => {
          attributes.delete(attributeNameFor(key));
          return true;
        },
      },
    );
  }

  get firstElementChild() {
    return this.childNodes[0] || null;
  }

  get nextSibling() {
    if (!this.parentNode) {
      return null;
    }
    const index = this.parentNode.childNodes.indexOf(this);
    return index >= 0 ? this.parentNode.childNodes[index + 1] || null : null;
  }

  get classList() {
    const element = this;
    const names = () => String(element.className).split(/\s+/).filter(Boolean);
    const write = (list) => {
      element.className = list.join(" ");
    };
    return {
      add: (...tokens) => {
        const list = names();
        for (const token of tokens) {
          if (!list.includes(token)) {
            list.push(token);
          }
        }
        write(list);
      },
      remove: (...tokens) => {
        write(names().filter((name) => !tokens.includes(name)));
      },
      contains: (token) => names().includes(token),
      toggle: (token, force) => {
        const has = names().includes(token);
        const shouldAdd = force === undefined ? !has : Boolean(force);
        if (shouldAdd && !has) {
          element.classList.add(token);
        } else if (!shouldAdd && has) {
          element.classList.remove(token);
        }
        return shouldAdd;
      },
      toString: () => names().join(" "),
    };
  }

  get offsetParent() {
    let node = this.parentNode;
    while (node) {
      const position = node.style?.position;
      if (
        position === "relative" ||
        position === "absolute" ||
        position === "fixed"
      ) {
        return node;
      }
      node = node.parentNode;
    }
    return this === this.ownerDocument.body ? null : this.ownerDocument.body;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  hasAttribute(name) {
    return this.attributes.has(name);
  }

  detach() {
    if (this.parentNode) {
      const index = this.parentNode.childNodes.indexOf(this);
      if (index >= 0) {
        this.parentNode.childNodes.splice(index, 1);
      }
      this.parentNode = null;
    }
  }

  adopt(node) {
    // Real DOM insertion moves an already-attached node instead of duplicating
    // it, so a node can never appear twice in childNodes.
    node.detach();
    node.parentNode = this;
    node.isConnected = true;
    this.childNodes.push(node);
  }

  append(...nodes) {
    for (const node of nodes) {
      this.adopt(node);
    }
  }

  insertBefore(node, reference) {
    node.detach();
    let index = -1;
    if (reference !== null && reference !== undefined) {
      index = this.childNodes.indexOf(reference);
    }
    if (index < 0) {
      this.childNodes.push(node);
    } else {
      this.childNodes.splice(index, 0, node);
    }
    node.parentNode = this;
    node.isConnected = true;
    return node;
  }

  replaceChildren(...nodes) {
    this.childNodes = [];
    for (const node of nodes) {
      this.adopt(node);
    }
  }

  insertAdjacentElement(position, element) {
    const parent = this.parentNode;
    if (!parent || position !== "afterend") {
      return null;
    }
    const index = parent.childNodes.indexOf(this);
    parent.childNodes.splice(index + 1, 0, element);
    element.parentNode = parent;
    element.isConnected = true;
    return element;
  }

  remove() {
    if (this.parentNode) {
      const index = this.parentNode.childNodes.indexOf(this);
      if (index >= 0) {
        this.parentNode.childNodes.splice(index, 1);
      }
    }
    this.parentNode = null;
    this.isConnected = false;
  }

  addEventListener(type, handler) {
    const handlers = this.listeners.get(type) || [];
    handlers.push(handler);
    this.listeners.set(type, handlers);
  }

  removeEventListener(type, handler) {
    const handlers = this.listeners.get(type) || [];
    this.listeners.set(
      type,
      handlers.filter((entry) => entry !== handler),
    );
  }

  dispatch(type, event) {
    for (const handler of this.listeners.get(type) || []) {
      handler(event);
    }
    return event;
  }

  querySelectorAll(selector) {
    return descendants(this).filter((element) =>
      matchesSelector(element, selector),
    );
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }

  closest(selector) {
    let node = this;
    while (node) {
      if (matchesSelector(node, selector)) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  getBoundingClientRect() {
    return this.rect;
  }

  getClientRects() {
    return this.rect.width > 0 ? [this.rect] : [];
  }

  getComputedStyle() {
    return {
      display: "block",
      visibility: "visible",
      opacity: "1",
      contentVisibility: "visible",
      objectFit: this.style?.objectFit || "fill",
    };
  }
}

class FakeDocument {
  constructor() {
    this.documentElement = new FakeElement("html", this);
    this.body = new FakeElement("body", this);
    this.documentElement.append(this.body);
    this.listeners = new Map();
  }

  get images() {
    return this.querySelectorAll("img");
  }

  createElement(tagName) {
    return new FakeElement(tagName, this);
  }

  addEventListener(type, handler) {
    const handlers = this.listeners.get(type) || [];
    handlers.push(handler);
    this.listeners.set(type, handlers);
  }

  dispatch(type, event) {
    for (const handler of this.listeners.get(type) || []) {
      handler(event);
    }
    return event;
  }

  querySelectorAll(selector) {
    return descendants(this.documentElement).filter((element) =>
      matchesSelector(element, selector),
    );
  }

  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
}

class FakeIntersectionObserver {
  constructor(callback, options) {
    this.callback = callback;
    this.options = options;
    this.targets = [];
    FakeIntersectionObserver.instances.push(this);
  }

  observe(target) {
    if (!this.targets.includes(target)) {
      this.targets.push(target);
    }
  }

  unobserve(target) {
    this.targets = this.targets.filter((entry) => entry !== target);
  }

  disconnect() {
    this.targets = [];
  }

  enter(target) {
    this.callback([{ target, isIntersecting: true }], this);
  }

  leave(target) {
    this.callback([{ target, isIntersecting: false }], this);
  }
}
FakeIntersectionObserver.instances = [];

class FakeMutationObserver {
  constructor(callback) {
    this.callback = callback;
    this.observing = false;
    FakeMutationObserver.instances.push(this);
  }

  observe(target, options) {
    this.target = target;
    this.options = options;
    this.observing = true;
  }

  disconnect() {
    this.observing = false;
  }

  trigger(records) {
    if (!this.observing) {
      return;
    }
    // Real MutationRecords always expose both node lists.
    const normalized = records.map((record) => ({
      addedNodes: [],
      removedNodes: [],
      ...record,
    }));
    this.callback(normalized, this);
  }
}
FakeMutationObserver.instances = [];

class FakeResizeObserver {
  constructor(callback) {
    this.callback = callback;
    this.targets = [];
    this.disconnected = false;
    FakeResizeObserver.instances.push(this);
  }

  observe(target) {
    if (!this.targets.includes(target)) {
      this.targets.push(target);
    }
  }

  unobserve(target) {
    this.targets = this.targets.filter((entry) => entry !== target);
  }

  disconnect() {
    this.disconnected = true;
    this.targets = [];
  }

  trigger() {
    this.callback(
      this.targets.map((target) => ({ target, contentRect: target.rect })),
      this,
    );
  }
}
FakeResizeObserver.instances = [];

function successResult() {
  return {
    payload: {
      api_version: "1",
      source_language: "ja",
      target_language: "en",
      image: { width: 436, height: 654 },
      regions: [
        {
          original_text: "こんにちは",
          translated_text: "Hello",
          translation_status: "ok",
          source_language: "ja",
          bbox: { x1: 4, y1: 8, x2: 40, y2: 60 },
        },
      ],
    },
    requestId: "11111111-1111-1111-1111-111111111111",
  };
}

function createEnvironment(options = {}) {
  FakeIntersectionObserver.instances = [];
  FakeMutationObserver.instances = [];
  FakeResizeObserver.instances = [];

  const document = new FakeDocument();
  const logs = [];
  const translateCalls = [];
  const fetchCalls = [];
  const scrollCalls = [];

  class TranslationError extends Error {
    constructor(kind, message, requestId = null) {
      super(message);
      this.name = "TranslationError";
      this.kind = kind;
      this.requestId = requestId;
    }
  }

  const makeError = (kind, message, requestId = null) =>
    new TranslationError(kind, message, requestId);

  const translationApi = {
    TRANSLATION_TIMEOUT_MS: 60_000,
    TranslationError,
    async translateImage(call) {
      translateCalls.push(call);
      if (typeof options.translate === "function") {
        return options.translate(call, makeError);
      }
      return successResult();
    },
  };

  const fetchImpl =
    options.fetch ||
    (async () => ({
      ok: true,
      status: 200,
      blob: async () => new Blob([new Uint8Array([1, 2, 3])], { type: "image/png" }),
    }));

  const storage = {
    enabled: true,
    sourceLanguage: "ja",
    backendUrl: "http://127.0.0.1:8000",
    ...(options.storage || {}),
  };
  const changeListeners = [];

  const chromeStub = {
    storage: {
      local: { get: async (defaults) => ({ ...defaults, ...storage }) },
      onChanged: {
        addListener: (listener) => changeListeners.push(listener),
      },
    },
    runtime: { id: "test-extension" },
  };

  const sandbox = {
    console: {
      info: (...args) => logs.push(["info", ...args]),
      warn: (...args) => logs.push(["warn", ...args]),
      error: (...args) => logs.push(["error", ...args]),
      log: (...args) => logs.push(["log", ...args]),
    },
    setTimeout,
    clearTimeout,
    AbortController,
    Blob,
    URL,
    crypto: globalThis.crypto,
    document,
    chrome: chromeStub,
    Element: FakeElement,
    Node: { ELEMENT_NODE: 1, TEXT_NODE: 3 },
    MutationObserver: FakeMutationObserver,
    IntersectionObserver: FakeIntersectionObserver,
    ResizeObserver: FakeResizeObserver,
    getComputedStyle: (element) => element.getComputedStyle(),
    fetch: async (url, init) => {
      fetchCalls.push({ url, init });
      return fetchImpl(url, init);
    },
  };

  const context = vm.createContext(sandbox);
  const load = (relativePath) => {
    const filename = path.join(EXTENSION_DIR, relativePath);
    vm.runInContext(fs.readFileSync(filename, "utf8"), context, { filename });
  };

  load("lib/image-detector.js");
  load("lib/translation-queue.js");
  load("lib/lazy-observer.js");
  load("lib/overlay-renderer.js");
  load("lib/translation-feed.js");
  sandbox.ACTTranslationApi = translationApi;
  load("content.js");

  const flush = async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  };

  return {
    document,
    sandbox,
    logs,
    translateCalls,
    fetchCalls,
    scrollCalls,
    makeError,
    flush,
    async ready() {
      await flush();
    },
    addImage({
      naturalWidth = 436,
      naturalHeight = 654,
      complete = true,
      renderedWidth = 400,
      renderedHeight = 600,
      src = "http://127.0.0.1:8080/comic-page.png",
      connected = true,
      parent = document.body,
    } = {}) {
      const image = new FakeElement("img", document);
      image.naturalWidth = naturalWidth;
      image.naturalHeight = naturalHeight;
      image.complete = complete;
      image.src = src;
      image.currentSrc = src;
      image.rect = {
        width: renderedWidth,
        height: renderedHeight,
        top: 0,
        left: 0,
        right: renderedWidth,
        bottom: renderedHeight,
      };
      image.clientWidth = renderedWidth;
      image.clientHeight = renderedHeight;
      image.clientLeft = 0;
      image.clientTop = 0;
      image.scrollIntoView = (options) => scrollCalls.push({ image, options });
      if (connected) {
        parent.append(image);
      } else {
        image.isConnected = false;
      }
      return image;
    },
    altClick(image) {
      return document.dispatch("click", {
        altKey: true,
        button: 0,
        target: image,
        preventDefault() {},
        stopPropagation() {},
      });
    },
    click(image) {
      return document.dispatch("click", {
        altKey: false,
        button: 0,
        target: image,
        preventDefault() {},
        stopPropagation() {},
      });
    },
    lastIntersectionObserver() {
      // The lazy prefetch observer (rootMargin "800px 0px"), not the feed's
      // own activity observer.
      return (
        FakeIntersectionObserver.instances.find(
          (observer) => observer.options?.rootMargin === "800px 0px",
        ) || null
      );
    },
    feedActivityObserver() {
      return (
        FakeIntersectionObserver.instances.find(
          (observer) => observer.options?.rootMargin?.includes("-45%"),
        ) || null
      );
    },
    lastMutationObserver() {
      return FakeMutationObserver.instances.at(-1) || null;
    },
    changeSetting(key, value) {
      storage[key] = value;
      for (const listener of changeListeners) {
        listener({ [key]: { newValue: value } }, "local");
      }
    },
    cards() {
      return document.querySelectorAll('[data-act-debug-ui="true"]');
    },
    overlays() {
      return document.querySelectorAll('[data-act-overlay-layer="true"]');
    },
    overlayRegions() {
      return document.querySelectorAll('[data-act-translation-region="true"]');
    },
    feedShell() {
      return document.querySelectorAll('[data-act-feed="true"]')[0] || null;
    },
    feedEntries() {
      return document.querySelectorAll('[data-act-feed-entry="true"]');
    },
    feedToggle() {
      return document.querySelectorAll('[data-act-feed-toggle="true"]')[0] || null;
    },
    clickFeedToggle() {
      const toggle = document.querySelectorAll(".act-feed-toggle")[0];
      if (toggle) {
        toggle.dispatch("click", {
          preventDefault() {},
          stopPropagation() {},
        });
      }
      return toggle || null;
    },
    clickFeedEntry(index) {
      const entry = document.querySelectorAll(".act-feed-entry-header")[index];
      if (entry) {
        entry.dispatch("click", {
          preventDefault() {},
          stopPropagation() {},
        });
      }
      return entry || null;
    },
    resizeObservers() {
      return FakeResizeObserver.instances;
    },
  };
}

/*
 * Minimal environment for the overlay renderer on its own (no content script).
 * Exposes the renderer module's pure helpers plus a configured renderer.
 */
function createOverlayEnvironment() {
  FakeResizeObserver.instances = [];
  const document = new FakeDocument();
  const sandbox = {
    console: { info() {}, warn() {}, error() {}, log() {} },
    setTimeout,
    clearTimeout,
    document,
    Element: FakeElement,
    Node: { ELEMENT_NODE: 1, TEXT_NODE: 3 },
    ResizeObserver: FakeResizeObserver,
    getComputedStyle: (element) => element.getComputedStyle(),
  };
  const context = vm.createContext(sandbox);
  vm.runInContext(
    fs.readFileSync(path.join(EXTENSION_DIR, "lib/overlay-renderer.js"), "utf8"),
    context,
    { filename: "lib/overlay-renderer.js" },
  );

  const api = sandbox.ACTOverlayRenderer;
  const events = [];
  const renderer = api.createOverlayRenderer({
    onEvent: (event, detail) => events.push({ event, ...detail }),
  });

  return {
    document,
    api,
    renderer,
    events,
    resizeObservers: () => FakeResizeObserver.instances,
    addImage({
      naturalWidth = 1000,
      naturalHeight = 2000,
      renderedWidth = 500,
      renderedHeight = 1000,
      left = 0,
      top = 0,
      objectFit = "fill",
      parent = document.body,
      connected = true,
    } = {}) {
      const image = new FakeElement("img", document);
      image.naturalWidth = naturalWidth;
      image.naturalHeight = naturalHeight;
      image.complete = true;
      image.src = "http://127.0.0.1:8080/comic.png";
      image.currentSrc = image.src;
      image.rect = {
        width: renderedWidth,
        height: renderedHeight,
        top,
        left,
        right: left + renderedWidth,
        bottom: top + renderedHeight,
      };
      image.clientWidth = renderedWidth;
      image.clientHeight = renderedHeight;
      image.style.objectFit = objectFit;
      if (connected) {
        parent.append(image);
      } else {
        image.isConnected = false;
      }
      return image;
    },
    layers() {
      return document.querySelectorAll('[data-act-overlay-layer="true"]');
    },
    regions() {
      return document.querySelectorAll('[data-act-translation-region="true"]');
    },
  };
}

/*
 * Minimal environment for the translation feed on its own (no content script).
 */
function createFeedEnvironment() {
  FakeIntersectionObserver.instances = [];
  const document = new FakeDocument();
  const scrollCalls = [];
  const sandbox = {
    console: { info() {}, warn() {}, error() {}, log() {} },
    setTimeout,
    clearTimeout,
    document,
    Element: FakeElement,
    Node: { ELEMENT_NODE: 1, TEXT_NODE: 3 },
    IntersectionObserver: FakeIntersectionObserver,
    getComputedStyle: (element) => element.getComputedStyle(),
  };
  const context = vm.createContext(sandbox);
  vm.runInContext(
    fs.readFileSync(path.join(EXTENSION_DIR, "lib/translation-feed.js"), "utf8"),
    context,
    { filename: "lib/translation-feed.js" },
  );

  const api = sandbox.ACTTranslationFeed;
  const events = [];
  const feed = api.createTranslationFeed({
    onEvent: (event, detail) => events.push({ event, ...detail }),
  });

  return {
    document,
    api,
    feed,
    events,
    scrollCalls,
    addImage({
      naturalWidth = 436,
      naturalHeight = 654,
      renderedWidth = 400,
      renderedHeight = 600,
      src = "http://127.0.0.1:8080/comic.png",
      parent = document.body,
      connected = true,
    } = {}) {
      const image = new FakeElement("img", document);
      image.naturalWidth = naturalWidth;
      image.naturalHeight = naturalHeight;
      image.complete = true;
      image.src = src;
      image.currentSrc = src;
      image.rect = {
        width: renderedWidth,
        height: renderedHeight,
        top: 0,
        left: 0,
        right: renderedWidth,
        bottom: renderedHeight,
      };
      image.clientWidth = renderedWidth;
      image.clientHeight = renderedHeight;
      image.scrollIntoView = (options) => scrollCalls.push({ image, options });
      if (connected) {
        parent.append(image);
      } else {
        image.isConnected = false;
      }
      return image;
    },
    shell() {
      return document.querySelectorAll('[data-act-feed="true"]')[0] || null;
    },
    toggleButton() {
      return document.querySelectorAll(".act-feed-toggle")[0] || null;
    },
    closeButton() {
      return document.querySelectorAll(".act-feed-close")[0] || null;
    },
    entries() {
      return document.querySelectorAll('[data-act-feed-entry="true"]');
    },
    activityObserver() {
      return FakeIntersectionObserver.instances.at(-1) || null;
    },
  };
}

module.exports = {
  createEnvironment,
  createOverlayEnvironment,
  createFeedEnvironment,
  successResult,
  FakeElement,
};
