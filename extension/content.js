(() => {
  const CANDIDATE_ATTRIBUTE = "data-act-comic-candidate";
  // Phase 3.4: keep a single in-flight request. The local backend already
  // bounds its own OCR/translation inference, so the extension must not open
  // many simultaneous requests.
  const MAX_CONCURRENT_TRANSLATIONS = 1;
  // Queue images shortly before they become visible so translation can start
  // ahead of the user's scroll position without translating the whole page.
  const LAZY_ROOT_MARGIN = "800px 0px";
  // Queue state -> existing development outline attribute used by content.css.
  const IMAGE_STATE_ATTRIBUTES = Object.freeze({
    queued: "queued",
    processing: "translating",
    success: "translated",
    error: "error",
  });

  const detector = globalThis.ACTImageDetector;
  const queueApi = globalThis.ACTTranslationQueue;
  const lazyObserverApi = globalThis.ACTLazyObserver;
  const overlayRendererApi = globalThis.ACTOverlayRenderer;
  const feedApi = globalThis.ACTTranslationFeed;
  if (
    !detector ||
    !queueApi ||
    !lazyObserverApi ||
    !overlayRendererApi ||
    !feedApi
  ) {
    return;
  }

  const translationApi = globalThis.ACTTranslationApi;
  let enabled = false;
  let showOverlays = true;
  let sourceLanguage = "auto";
  let backendUrl = "http://127.0.0.1:8000";
  let mutationObserver = null;
  let lazyObserver = null;
  let translationQueue = null;
  let overlayRenderer = null;
  let translationFeed = null;
  let processedImages = new WeakSet();
  const pendingLoadHandlers = new WeakMap();
  const debugCards = new WeakMap();
  const activeRequests = new Map();

  function removeCandidateMark(image) {
    image.removeAttribute(CANDIDATE_ATTRIBUTE);
  }

  function applyImageState(image, state) {
    const attribute = IMAGE_STATE_ATTRIBUTES[state];
    if (attribute) {
      image.setAttribute("data-act-state", attribute);
    } else {
      image.removeAttribute("data-act-state");
    }
  }

  function removeDebugCard(image) {
    debugCards.get(image)?.remove();
    debugCards.delete(image);
  }

  function cancelImage(image) {
    const activeRequest = activeRequests.get(image);
    if (activeRequest) {
      activeRequests.delete(image);
      activeRequest.controller.abort();
    }
    translationQueue?.forget(image);
    removeDebugCard(image);
    applyImageState(image, null);
  }

  function ensureOverlayRenderer() {
    if (!overlayRenderer) {
      overlayRenderer = overlayRendererApi.createOverlayRenderer({
        onEvent: (event, detail) => {
          console.info(`[ACT] overlay ${event}`, {
            regionCount: detail.regionCount ?? null,
          });
        },
      });
    }
    return overlayRenderer;
  }

  function showOverlayFor(image, result) {
    if (!showOverlays || !result?.payload) {
      return;
    }
    ensureOverlayRenderer().render(image, result.payload);
  }

  function ensureFeed() {
    if (!translationFeed) {
      translationFeed = feedApi.createTranslationFeed({
        onEvent: (event, detail) => {
          console.info(`[ACT] feed ${event}`, {
            regionCount: detail.regionCount ?? null,
            kind: detail.kind ?? null,
          });
        },
      });
    }
    return translationFeed;
  }

  // The feed is a view over the same stored result the overlay uses; it never
  // triggers its own request.
  function publishToFeed(image, result) {
    if (!result?.payload) {
      return;
    }
    ensureFeed().update(image, result.payload);
  }

  // Re-render the stored result of an image that already succeeded (for
  // example after the translator was disabled and enabled again).
  function restoreTranslatedImage(image) {
    if (!translationQueue) {
      return;
    }
    const stored = translationQueue.resultOf(image);
    if (stored?.status === "success") {
      showOverlayFor(image, stored.result);
      publishToFeed(image, stored.result);
    }
  }

  // Drop every stored translation because its identity changed (source
  // language or backend URL). Overlays, feed entries, and cached per-image
  // results are removed together so the two views cannot diverge.
  function invalidateTranslations(reason) {
    for (const image of [...document.images]) {
      releaseImage(image);
    }
    translationFeed?.clear();
    console.info("[ACT] translation results invalidated", { reason });
    discoverExistingImages();
  }

  // Release everything attached to an image that changed source or left the
  // page: queued work, overlay layer, feed entry, resize observation, mark.
  function releaseImage(image) {
    cancelImage(image);
    overlayRenderer?.remove(image);
    translationFeed?.remove(image);
    lazyObserver?.unobserve(image);
    processedImages.delete(image);
    removeCandidateMark(image);
  }

  function createDebugCard(image) {
    let card = debugCards.get(image);
    if (card?.isConnected) {
      return card;
    }

    card = document.createElement("section");
    card.className = "act-dev-result";
    card.dataset.actDebugUi = "true";
    card.setAttribute("aria-label", "ACT translation development result");
    const header = document.createElement("div");
    header.className = "act-dev-result-header";
    const title = document.createElement("strong");
    title.className = "act-dev-result-title";
    title.textContent = "ACT Translation Debug";
    const closeButton = document.createElement("button");
    closeButton.className = "act-dev-result-close";
    closeButton.type = "button";
    closeButton.textContent = "×";
    closeButton.setAttribute("aria-label", "Remove translation debug result");
    closeButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      removeDebugCard(image);
    });
    header.append(title, closeButton);
    card.append(header);

    image.insertAdjacentElement("afterend", card);
    debugCards.set(image, card);
    return card;
  }

  function updateDebugCard(image, state, lines, mode = "manual") {
    const card = createDebugCard(image);
    card.dataset.state = state;
    card.dataset.mode = mode;
    const header = card.firstElementChild;
    card.replaceChildren(header, ...lines);
  }

  function createCardLine(className, text) {
    const line = document.createElement("p");
    line.className = className;
    line.textContent = text;
    return line;
  }

  function shorten(text, limit = 120) {
    return text.length > limit ? `${text.slice(0, limit)}…` : text;
  }

  function buildRegionList(regions) {
    const list = document.createElement("ol");
    list.className = "act-dev-result-list";
    for (const region of regions.slice(0, 3)) {
      const item = document.createElement("li");
      item.textContent =
        `${shorten(region.original_text)}\n→ ${shorten(region.translated_text)}\n` +
        `Status: ${region.translation_status} · ` +
        `Language: ${region.source_language || "unknown"}`;
      list.append(item);
    }
    if (regions.length > 3) {
      const remaining = document.createElement("li");
      remaining.textContent = `${regions.length - 3} more regions omitted.`;
      list.append(remaining);
    }
    return list;
  }

  // The Phase 3.3 development card is kept for debugging, but the overlay now
  // shows the translation on the image, so the card is always collapsed.
  function showTranslationResult(image, result, { mode = "auto" } = {}) {
    const { payload, requestId } = result;
    const regions = payload.regions;
    const source =
      typeof payload.source_language === "string"
        ? payload.source_language
        : sourceLanguage;
    const cacheLabel = payload.cache?.hit ? " · cache hit" : "";
    const lines = [
      createCardLine(
        "act-dev-result-status",
        `${regions.length} region${regions.length === 1 ? "" : "s"} returned.`,
      ),
      createCardLine(
        "act-dev-result-meta",
        `${payload.image.width} × ${payload.image.height} · ${source} ` +
          `→ en${cacheLabel}`,
      ),
      createCardLine(
        "act-dev-result-request",
        `Request ID: ${requestId || "unavailable"}`,
      ),
    ];

    if (regions.length === 0) {
      lines.push(
        createCardLine(
          "act-dev-result-meta",
          "No text regions were detected in this image.",
        ),
      );
    } else {
      const details = document.createElement("details");
      details.className = "act-dev-result-details";
      // Automatic translations stay collapsed (the overlay and feed are the
      // reading UI); an explicit Alt+Click opens the development detail.
      details.open = mode === "manual";
      const summary = document.createElement("summary");
      summary.textContent = `Show ${regions.length} region${
        regions.length === 1 ? "" : "s"
      }`;
      details.append(summary, buildRegionList(regions));
      lines.push(details);
    }

    updateDebugCard(image, "translated", lines, mode);
  }

  function showTranslationError(image, error) {
    const kindLabels = {
      "image-fetch": "Image could not be fetched",
      image: "Image could not be uploaded",
      configuration: "Translation settings need attention",
      "backend-network": "Backend offline or browser blocked the request",
      timeout: "Translation request timed out",
      "backend-api": "Backend API error",
      "incompatible-api": "Incompatible backend API version",
      malformed: "Malformed backend response",
    };
    const lines = [
      createCardLine(
        "act-dev-result-status",
        kindLabels[error.kind] || "Translation failed",
      ),
      createCardLine("act-dev-result-meta", error.message),
    ];
    if (error.requestId) {
      lines.push(
        createCardLine(
          "act-dev-result-request",
          `Request ID: ${error.requestId}`,
        ),
      );
    }
    updateDebugCard(image, "error", lines);
    const status = debugCards.get(image)?.querySelector(
      ".act-dev-result-status",
    );
    status?.setAttribute("data-state", "error");
  }

  async function fetchImageBlob(image, signal) {
    const imageSource = image.currentSrc || image.src;
    if (!imageSource) {
      throw new translationApi.TranslationError(
        "image-fetch",
        "The selected image has no source URL.",
      );
    }

    let blob;
    try {
      const response = await fetch(imageSource, {
        method: "GET",
        credentials: "same-origin",
        signal,
      });
      if (!response.ok) {
        throw new translationApi.TranslationError(
          "image-fetch",
          `Image fetch returned HTTP ${response.status}.`,
        );
      }
      blob = await response.blob();
    } catch (error) {
      if (error?.kind === "image-fetch") {
        throw error;
      }
      if (signal.aborted) {
        throw new translationApi.TranslationError(
          "cancelled",
          "Image fetch was cancelled.",
        );
      }
      throw new translationApi.TranslationError(
        "image-fetch",
        "Could not fetch the selected image bytes. Same-origin images work " +
          "on the local test page; other sites may block this request.",
      );
    }

    if (blob.size === 0) {
      throw new translationApi.TranslationError(
        "image-fetch",
        "The selected image returned no data.",
      );
    }
    return blob;
  }

  // Shared Phase 3.3 translation path. Both the Alt+Click development trigger
  // and the Phase 3.4 lazy queue worker call this single implementation.
  async function translateCandidate(image, { manual = false } = {}) {
    if (!enabled || !translationApi) {
      return queueApi.SKIP;
    }

    const request = {
      controller: new AbortController(),
    };
    activeRequests.set(image, request);
    updateDebugCard(
      image,
      "processing",
      [
        createCardLine(
          "act-dev-result-status",
          "Fetching image and translating…",
        ),
      ],
      manual ? "manual" : "auto",
    );

    try {
      const imageBlob = await fetchImageBlob(image, request.controller.signal);
      if (!enabled || activeRequests.get(image) !== request) {
        return queueApi.SKIP;
      }
      const result = await translationApi.translateImage({
        imageBlob,
        sourceLanguage,
        targetLanguage: "en",
        backendUrl,
        signal: request.controller.signal,
      });
      if (!enabled || activeRequests.get(image) !== request) {
        return queueApi.SKIP;
      }

      activeRequests.delete(image);
      showTranslationResult(image, result, {
        mode: manual ? "manual" : "auto",
      });
      console.info("[ACT] translation completed", {
        requestId: result.requestId,
        regionCount: result.payload.regions.length,
      });
      return result;
    } catch (error) {
      if (activeRequests.get(image) === request) {
        activeRequests.delete(image);
      }
      if (error?.kind === "cancelled") {
        removeDebugCard(image);
        return queueApi.SKIP;
      }
      throw error;
    }
  }

  // Phase 3.4 queue/observer logging. Never logs image bytes, OCR text, or
  // translated dialogue; request IDs are logged where already available.
  function handleQueueEvent(event, detail) {
    const image = detail.image;
    if (!image) {
      return;
    }
    applyImageState(image, detail.state);

    if (event === "failed") {
      showTranslationError(image, detail.error);
      console.warn("[ACT] lazy translation failed", {
        kind: detail.error?.kind || "unknown",
        requestId: detail.error?.requestId || null,
      });
      return;
    }

    if (event === "reused") {
      // Re-intersecting an already translated image must not churn the UI; an
      // explicit Alt+Click re-shows the stored result instead.
      if (detail.manual === true) {
        const stored = translationQueue?.resultOf(image);
        if (stored?.result) {
          showTranslationResult(image, stored.result, { mode: "manual" });
        }
      }
      console.info("[ACT] lazy translation reused", { state: detail.state });
      return;
    }

    if (event === "completed") {
      showOverlayFor(image, detail.result);
      publishToFeed(image, detail.result);
    }

    if (event === "failed") {
      // The feed keeps a compact placeholder so reading order stays intact; it
      // never shows backend error text.
      translationFeed?.updateFailed(image, detail.error);
    }

    console.info(`[ACT] lazy translation ${event}`, {
      state: detail.state,
      manual: detail.manual === true,
      reason: detail.reason || null,
    });
  }

  function isEligibleForTranslation(image) {
    return Boolean(
      enabled &&
        image?.isConnected &&
        processedImages.has(image) &&
        image.getAttribute(CANDIDATE_ATTRIBUTE) === "true" &&
        image.naturalWidth > 0 &&
        image.naturalHeight > 0,
    );
  }

  function handleNearViewport(image) {
    if (!enabled || !translationQueue) {
      return;
    }
    translationQueue.enqueue(image);
  }

  function registerCandidateForTranslation(image) {
    if (!lazyObserver?.observe(image)) {
      return;
    }
    console.info("[ACT] lazy translation observed", {
      rootMargin: LAZY_ROOT_MARGIN,
    });
  }

  function handleDocumentClick(event) {
    if (!enabled || !translationApi || !event.altKey || event.button !== 0) {
      return;
    }
    const target = event.target;
    if (!(target instanceof Element)) {
      return;
    }
    const image = target.closest(`img[${CANDIDATE_ATTRIBUTE}="true"]`);
    if (!image) {
      return;
    }

    event.preventDefault();
    // Alt+Click reuses the Phase 3.4 queue so an already translated image is
    // re-shown, an in-flight image is not duplicated, and an errored image can
    // be retried explicitly.
    translationQueue?.enqueue(image, { manual: true });
  }

  function imageIsVisible(image) {
    const style = getComputedStyle(image);
    if (
      style.display === "none" ||
      style.visibility === "hidden" ||
      style.visibility === "collapse" ||
      style.contentVisibility === "hidden" ||
      Number(style.opacity) === 0
    ) {
      return false;
    }

    const rect = image.getBoundingClientRect();
    return (
      image.getClientRects().length > 0 &&
      rect.width > 1 &&
      rect.height > 1
    );
  }

  function evaluateImage(image) {
    if (!enabled || !image.isConnected || processedImages.has(image)) {
      return;
    }

    if (!image.complete) {
      waitForImage(image);
      return;
    }

    const rect = image.getBoundingClientRect();
    const result = detector.classifyImage({
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
      renderedWidth: rect.width,
      renderedHeight: rect.height,
      visible: imageIsVisible(image),
    });
    processedImages.add(image);

    if (!result.candidate) {
      lazyObserver?.unobserve(image);
      removeCandidateMark(image);
      return;
    }

    image.setAttribute(CANDIDATE_ATTRIBUTE, "true");
    registerCandidateForTranslation(image);
    // A previously translated image keeps its stored result across a
    // disable/enable cycle; re-render its overlay instead of retranslating.
    restoreTranslatedImage(image);
    console.info("[ACT] candidate image", {
      width: image.naturalWidth,
      height: image.naturalHeight,
      orientation: result.orientation,
      aspectRatio: result.aspectRatio,
      reason: result.reason,
    });
  }

  function waitForImage(image) {
    if (pendingLoadHandlers.has(image)) {
      return;
    }

    const cleanup = () => {
      image.removeEventListener("load", handleLoad);
      image.removeEventListener("error", handleError);
      pendingLoadHandlers.delete(image);
    };
    const handleLoad = () => {
      cleanup();
      processedImages.delete(image);
      evaluateImage(image);
    };
    const handleError = () => {
      cleanup();
      processedImages.add(image);
      cancelImage(image);
      lazyObserver?.unobserve(image);
      removeCandidateMark(image);
    };

    pendingLoadHandlers.set(image, { handleLoad, handleError });
    image.addEventListener("load", handleLoad, { once: true });
    image.addEventListener("error", handleError, { once: true });
  }

  function collectImages(node, images) {
    if (node.nodeType !== Node.ELEMENT_NODE) {
      return;
    }
    if (node.tagName === "IMG") {
      images.add(node);
    }
    node.querySelectorAll("img").forEach((image) => images.add(image));
  }

  function handleMutations(records) {
    if (!enabled) {
      return;
    }

    const imagesToCheck = new Set();
    const imagesToRefresh = new Set();
    const imagesToRelease = new Set();
    for (const record of records) {
      if (record.type === "childList") {
        for (const node of record.addedNodes) {
          collectImages(node, imagesToCheck);
        }
        for (const node of record.removedNodes) {
          collectImages(node, imagesToRelease);
        }
      } else if (
        record.type === "attributes" &&
        record.target.tagName === "IMG"
      ) {
        imagesToCheck.add(record.target);
        imagesToRefresh.add(record.target);
      }
    }

    // A removed comic image must not leave its overlay layer, resize
    // observation, or queued work behind.
    for (const image of imagesToRelease) {
      if (image.isConnected) {
        continue;
      }
      releaseImage(image);
    }

    for (const image of imagesToCheck) {
      if (imagesToRefresh.has(image)) {
        // Lazy-loaded images swap a placeholder for the real asset. Drop the
        // stale queue/observer/overlay state so the new source is discovered
        // and observed again when it comes near the viewport.
        releaseImage(image);
      }
      evaluateImage(image);
    }
  }

  function discoverExistingImages() {
    for (const image of document.images) {
      evaluateImage(image);
    }
  }

  function startDiscovery() {
    if (mutationObserver) {
      return;
    }

    enabled = true;
    translationQueue ??= queueApi.createTranslationQueue({
      maxConcurrent: MAX_CONCURRENT_TRANSLATIONS,
      runTask: translateCandidate,
      isEligible: isEligibleForTranslation,
      onEvent: handleQueueEvent,
    });
    lazyObserver = lazyObserverApi.createLazyObserver({
      onEnter: handleNearViewport,
      rootMargin: LAZY_ROOT_MARGIN,
    });
    mutationObserver = new MutationObserver(handleMutations);
    mutationObserver.observe(document.documentElement || document, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["src", "srcset"],
    });
    discoverExistingImages();
  }

  function stopDiscovery() {
    enabled = false;
    mutationObserver?.disconnect();
    mutationObserver = null;
    lazyObserver?.disconnect();
    lazyObserver = null;
    for (const image of activeRequests.keys()) {
      cancelImage(image);
    }
    // Completed results are kept so re-enabling does not retranslate images
    // that already succeeded; overlays are removed immediately and restored
    // from those results when the translator is enabled again.
    translationQueue?.reset({ keepResults: true });
    overlayRenderer?.removeAll();
    // Nothing of the reading UI stays on the page while the translator is off.
    translationFeed?.destroy();
    translationFeed = null;
    processedImages = new WeakSet();
    document
      .querySelectorAll(`[${CANDIDATE_ATTRIBUTE}="true"]`)
      .forEach(removeCandidateMark);
    document
      .querySelectorAll("img[data-act-state]")
      .forEach((image) => image.removeAttribute("data-act-state"));
    document
      .querySelectorAll('[data-act-debug-ui="true"]')
      .forEach((card) => card.remove());
  }

  function setEnabled(value) {
    if (value === false) {
      stopDiscovery();
    } else {
      startDiscovery();
    }
  }

  function setShowOverlays(value) {
    showOverlays = value !== false;
    if (!showOverlays) {
      overlayRenderer?.removeAll();
      return;
    }
    // Re-render stored results instead of translating again.
    for (const image of document.images) {
      restoreTranslatedImage(image);
    }
  }

  let settingsRevision = 0;
  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "local") {
      return;
    }
    if (
      !["enabled", "sourceLanguage", "backendUrl", "showOverlays"].some((key) =>
        Object.hasOwn(changes, key),
      )
    ) {
      return;
    }
    settingsRevision += 1;
    if (Object.hasOwn(changes, "enabled")) {
      setEnabled(changes.enabled.newValue);
    }
    if (Object.hasOwn(changes, "showOverlays")) {
      setShowOverlays(changes.showOverlays.newValue);
    }
    if (Object.hasOwn(changes, "sourceLanguage")) {
      const value = changes.sourceLanguage.newValue;
      const next = ["auto", "ja", "ko", "zh-Hans", "zh-Hant"].includes(value)
        ? value
        : "auto";
      if (next !== sourceLanguage) {
        sourceLanguage = next;
        // Stored results belong to the previous language identity.
        invalidateTranslations("source-language");
      }
    }
    if (Object.hasOwn(changes, "backendUrl")) {
      const next = changes.backendUrl.newValue;
      if (next !== backendUrl) {
        backendUrl = next;
        invalidateTranslations("backend-url");
      }
    }
  });

  const initialRevision = settingsRevision;
  chrome.storage.local
    .get({
      enabled: true,
      showOverlays: true,
      sourceLanguage: "auto",
      backendUrl: "http://127.0.0.1:8000",
    })
    .then((settings) => {
      if (initialRevision === settingsRevision) {
        sourceLanguage = settings.sourceLanguage || "auto";
        backendUrl = settings.backendUrl || "http://127.0.0.1:8000";
        setShowOverlays(settings.showOverlays);
        setEnabled(settings.enabled);
      }
    })
    .catch(() => {
      if (initialRevision === settingsRevision) {
        sourceLanguage = "auto";
        backendUrl = "http://127.0.0.1:8000";
        setShowOverlays(true);
        setEnabled(true);
      }
    });

  document.addEventListener("click", handleDocumentClick, true);
})();
