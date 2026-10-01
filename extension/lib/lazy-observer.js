/*
 * Phase 3.4 — IntersectionObserver wrapper for lazy translation.
 *
 * Registers candidate comic images and reports them when they come within
 * `rootMargin` of the viewport, so translation can start shortly before the
 * user reaches them. The observer factory is injectable so the registration
 * behaviour can be tested without a browser.
 */
(() => {
  const DEFAULT_ROOT_MARGIN = "800px 0px";

  function createLazyObserver({
    onEnter,
    rootMargin = DEFAULT_ROOT_MARGIN,
    observerFactory = globalThis.IntersectionObserver,
  } = {}) {
    if (typeof onEnter !== "function") {
      throw new TypeError("An onEnter callback is required.");
    }

    let observer = null;
    let observed = new WeakSet();

    function handleEntries(entries) {
      for (const entry of entries) {
        if (entry?.isIntersecting) {
          onEnter(entry.target, entry);
        }
      }
    }

    function observe(image) {
      if (typeof observerFactory !== "function" || !image) {
        return false;
      }
      if (observed.has(image)) {
        return false;
      }
      if (!observer) {
        observer = new observerFactory(handleEntries, {
          root: null,
          rootMargin,
        });
      }
      observed.add(image);
      observer.observe(image);
      return true;
    }

    function unobserve(image) {
      if (!observer || !observed.has(image)) {
        return false;
      }
      observed.delete(image);
      observer.unobserve(image);
      return true;
    }

    function disconnect() {
      observer?.disconnect();
      observer = null;
      observed = new WeakSet();
    }

    return Object.freeze({
      rootMargin,
      observe,
      unobserve,
      disconnect,
      isObserved: (image) => observed.has(image),
    });
  }

  globalThis.ACTLazyObserver = Object.freeze({
    DEFAULT_ROOT_MARGIN,
    createLazyObserver,
  });
})();
