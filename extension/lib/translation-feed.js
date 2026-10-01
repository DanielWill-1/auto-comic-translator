/*
 * Phase 3.6 — translation feed.
 *
 * A compact, collapsible, page-overlaying panel that lists the translated
 * regions of every translated comic image in DOM reading order.
 *
 * It is a *view* over results that already exist: the per-image validated API v1
 * payloads stored by the Phase 3.4 queue. It never OCRs, translates, or fetches
 * anything, and it never modifies the comic reader's layout.
 *
 * Ordering is DOM order (live `document.images` index), not completion order, so
 * lazily translated images that finish out of order still read in page order.
 *
 * All OCR/translated strings are inserted with `textContent`; nothing from the
 * backend is ever interpreted as markup.
 */
(() => {
  const LANGUAGE_LABELS = Object.freeze({
    auto: "Auto",
    ja: "Japanese",
    ko: "Korean",
    zh: "Chinese",
    "zh-Hans": "Chinese (Simplified)",
    "zh-Hant": "Chinese (Traditional)",
    en: "English",
  });
  // Only an image crossing the middle band of the viewport counts as "current".
  const ACTIVITY_ROOT_MARGIN = "-45% 0px -45% 0px";
  const FALLBACK_NOTE = "Translation unavailable — showing original text";
  const ACTIVE_CLASS = "act-feed-entry-active";

  function defaultLabelFor(code) {
    if (typeof code !== "string" || code === "") {
      return "Unknown";
    }
    return LANGUAGE_LABELS[code] || code;
  }

  function createTranslationFeed({
    document: doc = globalThis.document,
    intersectionObserverFactory = globalThis.IntersectionObserver,
    labelFor = defaultLabelFor,
    onEvent = () => {},
  } = {}) {
    if (!doc) {
      throw new TypeError("A document is required to build the translation feed.");
    }

    const records = new Map();
    let shell = null;
    let toggleButton = null;
    let listElement = null;
    let emptyMessage = null;
    let open = false;
    let currentImage = null;
    let activityObserver = null;
    let sequenceCounter = 0;

    function orderIndexOf(image) {
      const images = doc.images;
      for (let index = 0; index < images.length; index += 1) {
        if (images[index] === image) {
          return index;
        }
      }
      return Number.MAX_SAFE_INTEGER;
    }

    function sortedRecords() {
      return [...records.values()].sort((left, right) => {
        const difference = orderIndexOf(left.image) - orderIndexOf(right.image);
        return difference !== 0 ? difference : left.sequence - right.sequence;
      });
    }

    function createShell() {
      shell = doc.createElement("aside");
      shell.className = "act-feed";
      shell.dataset.actFeed = "true";
      shell.setAttribute("role", "complementary");
      shell.setAttribute("aria-label", "Translation feed");

      const header = doc.createElement("div");
      header.className = "act-feed-header";
      const title = doc.createElement("strong");
      title.className = "act-feed-title";
      title.textContent = "Translation Feed";
      const closeButton = doc.createElement("button");
      closeButton.className = "act-feed-close";
      closeButton.type = "button";
      closeButton.textContent = "×";
      closeButton.setAttribute("aria-label", "Close translation feed");
      closeButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        setOpen(false);
      });
      header.append(title, closeButton);

      emptyMessage = doc.createElement("p");
      emptyMessage.className = "act-feed-empty";
      emptyMessage.textContent =
        "No translations yet. Scroll through the comic to translate pages.";

      listElement = doc.createElement("div");
      listElement.className = "act-feed-body";
      listElement.setAttribute("role", "list");
      listElement.setAttribute("aria-label", "Translated regions in reading order");

      shell.append(header, emptyMessage, listElement);

      toggleButton = doc.createElement("button");
      toggleButton.className = "act-feed-toggle";
      toggleButton.dataset.actFeedToggle = "true";
      toggleButton.type = "button";
      toggleButton.textContent = "Feed";
      toggleButton.setAttribute("aria-label", "Open translation feed");
      toggleButton.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        setOpen(!open);
      });

      (doc.body || doc.documentElement).append(shell, toggleButton);
      applyOpenState();
      onEvent("shell-created", {});
    }

    function applyOpenState() {
      if (!shell) {
        return;
      }
      shell.dataset.actFeedOpen = open ? "true" : "false";
      shell.hidden = !open;
      toggleButton.setAttribute("aria-expanded", open ? "true" : "false");
      toggleButton.setAttribute(
        "aria-label",
        open ? "Hide translation feed" : "Open translation feed",
      );
    }

    function ensureShell() {
      if (!shell) {
        createShell();
      }
      return shell;
    }

    function setOpen(value) {
      ensureShell();
      open = value !== false;
      applyOpenState();
      onEvent(open ? "opened" : "closed", {});
    }

    function createRegion(region) {
      const wrapper = doc.createElement("div");
      wrapper.className = "act-feed-region";
      const isFallback = region?.translation_status === "fallback";
      wrapper.dataset.actFeedRegion = isFallback ? "fallback" : "ok";

      const originalLabel = doc.createElement("span");
      originalLabel.className = "act-feed-label";
      originalLabel.textContent = "Original";
      const original = doc.createElement("p");
      original.className = "act-feed-original";
      original.textContent =
        typeof region?.original_text === "string" ? region.original_text : "";

      const translatedLabel = doc.createElement("span");
      translatedLabel.className = "act-feed-label";
      translatedLabel.textContent = "English";
      const translated = doc.createElement("p");
      translated.className = "act-feed-translated";
      if (isFallback) {
        // A fallback region carries the untranslated original text; presenting
        // it as English would be wrong, so say what actually happened.
        translated.textContent = FALLBACK_NOTE;
        translated.dataset.actFeedFallback = "true";
      } else {
        translated.textContent =
          typeof region?.translated_text === "string"
            ? region.translated_text
            : "";
      }

      wrapper.append(originalLabel, original, translatedLabel, translated);
      return wrapper;
    }

    function renderEntryBody(record, payload) {
      const regions = Array.isArray(payload?.regions) ? payload.regions : [];
      const elements = regions.map(createRegion);
      record.body.replaceChildren(...elements);
      record.regionCount = elements.length;
      record.fallbackCount = elements.filter(
        (element) => element.dataset.actFeedRegion === "fallback",
      ).length;
      const parts = [
        `${record.regionCount} region${record.regionCount === 1 ? "" : "s"}`,
      ];
      if (record.fallbackCount > 0) {
        parts.push(`${record.fallbackCount} fallback`);
      }
      record.status.textContent = parts.join(" · ");
      record.element.dataset.actFeedState = "translated";
    }

    function createRecord(image) {
      const element = doc.createElement("section");
      element.className = "act-feed-entry";
      element.dataset.actFeedEntry = "true";
      element.setAttribute("role", "listitem");

      const header = doc.createElement("button");
      header.className = "act-feed-entry-header";
      header.type = "button";
      const title = doc.createElement("span");
      title.className = "act-feed-entry-title";
      const languages = doc.createElement("span");
      languages.className = "act-feed-entry-langs";
      const status = doc.createElement("span");
      status.className = "act-feed-entry-status";
      header.append(title, languages, status);
      header.addEventListener("click", (event) => {
        event.preventDefault();
        scrollToImage(image);
      });

      const body = doc.createElement("div");
      body.className = "act-feed-entry-body";
      element.append(header, body);

      return {
        image,
        element,
        header,
        title,
        languages,
        status,
        body,
        regionCount: 0,
        fallbackCount: 0,
        position: 0,
        sequence: sequenceCounter,
      };
    }

    function scrollToImage(image) {
      if (!image?.isConnected) {
        return false;
      }
      if (typeof image.scrollIntoView === "function") {
        image.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      onEvent("navigated", { image });
      return true;
    }

    /*
     * Re-order entry elements to match reading order. Existing entry content is
     * never rebuilt; only node positions and the "Image N" numbering change.
     */
    function reorder() {
      const ordered = sortedRecords();
      let reference = null;
      for (let index = ordered.length - 1; index >= 0; index -= 1) {
        const record = ordered[index];
        if (
          record.element.parentNode !== listElement ||
          record.element.nextSibling !== reference
        ) {
          listElement.insertBefore(record.element, reference);
        }
        reference = record.element;
        const position = index + 1;
        if (record.position !== position) {
          record.position = position;
          record.title.textContent = `Image ${position}`;
        }
      }
      if (emptyMessage) {
        emptyMessage.hidden = ordered.length > 0;
      }
    }

    function ensureRecord(image) {
      let record = records.get(image);
      if (record) {
        return record;
      }
      record = createRecord(image);
      sequenceCounter += 1;
      records.set(image, record);
      listElement.append(record.element);
      observeImage(image);
      return record;
    }

    function update(image, payload) {
      if (!image?.isConnected || !payload) {
        return null;
      }
      ensureShell();
      const record = ensureRecord(image);
      record.languages.textContent =
        `${labelFor(payload.source_language)} → ${labelFor(payload.target_language)}`;
      renderEntryBody(record, payload);
      reorder();
      onEvent("entry-updated", { image, regionCount: record.regionCount });
      return record;
    }

    function updateFailed(image, error) {
      if (!image?.isConnected) {
        return null;
      }
      ensureShell();
      const record = ensureRecord(image);
      record.languages.textContent = "";
      record.status.textContent = "Translation unavailable";
      record.body.replaceChildren();
      record.regionCount = 0;
      record.fallbackCount = 0;
      record.element.dataset.actFeedState = "error";
      reorder();
      onEvent("entry-failed", { image, kind: error?.kind || "unknown" });
      return record;
    }

    function remove(image) {
      const record = records.get(image);
      if (!record) {
        return false;
      }
      record.element.remove();
      records.delete(image);
      if (currentImage === image) {
        currentImage = null;
      }
      activityObserver?.unobserve?.(image);
      reorder();
      onEvent("entry-removed", { image });
      return true;
    }

    function clear() {
      for (const record of records.values()) {
        record.element.remove();
        activityObserver?.unobserve?.(record.image);
      }
      records.clear();
      currentImage = null;
      if (emptyMessage) {
        emptyMessage.hidden = false;
      }
      onEvent("cleared", {});
    }

    function setCurrent(image) {
      if (image === currentImage) {
        return false;
      }
      records.get(currentImage)?.element.classList.remove(ACTIVE_CLASS);
      currentImage = image;
      records.get(currentImage)?.element.classList.add(ACTIVE_CLASS);
      onEvent("current-changed", { image });
      return true;
    }

    function handleActivity(entries) {
      for (const entry of entries) {
        if (entry?.isIntersecting && records.has(entry.target)) {
          setCurrent(entry.target);
          return;
        }
      }
      // Nothing crosses the middle band right now: keep the last highlight so
      // the feed does not flicker between images.
    }

    function observeImage(image) {
      if (typeof intersectionObserverFactory !== "function") {
        return false;
      }
      if (!activityObserver) {
        activityObserver = new intersectionObserverFactory(handleActivity, {
          root: null,
          rootMargin: ACTIVITY_ROOT_MARGIN,
        });
      }
      activityObserver.observe(image);
      return true;
    }

    function setEnabled(value) {
      if (value === false) {
        clear();
        if (shell) {
          setOpen(false);
        }
        return;
      }
      applyOpenState();
    }

    function destroy() {
      clear();
      activityObserver?.disconnect?.();
      activityObserver = null;
      shell?.remove();
      toggleButton?.remove();
      shell = null;
      toggleButton = null;
      listElement = null;
      emptyMessage = null;
      open = false;
    }

    return Object.freeze({
      setOpen,
      isOpen: () => open,
      toggle: () => setOpen(!open),
      update,
      updateFailed,
      remove,
      clear,
      setCurrent,
      setEnabled,
      destroy,
      currentImage: () => currentImage,
      entryCount: () => records.size,
      regionCountFor: (image) => records.get(image)?.regionCount ?? 0,
      entryFor: (image) => records.get(image)?.element ?? null,
      titleFor: (image) => records.get(image)?.title.textContent ?? null,
      elements: () => sortedRecords().map((record) => record.element),
    });
  }

  globalThis.ACTTranslationFeed = Object.freeze({
    LANGUAGE_LABELS,
    FALLBACK_NOTE,
    ACTIVITY_ROOT_MARGIN,
    ACTIVE_CLASS,
    createTranslationFeed,
  });
})();
