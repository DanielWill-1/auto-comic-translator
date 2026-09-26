(() => {
  const CANDIDATE_ATTRIBUTE = "data-act-comic-candidate";
  const detector = globalThis.ACTImageDetector;
  if (!detector) {
    return;
  }

  const translationApi = globalThis.ACTTranslationApi;
  let enabled = false;
  let sourceLanguage = "auto";
  let backendUrl = "http://127.0.0.1:8000";
  let observer = null;
  let processedImages = new WeakSet();
  const pendingLoadHandlers = new WeakMap();
  const imageStates = new WeakMap();
  const debugCards = new WeakMap();
  const activeRequests = new Map();

  function removeCandidateMark(image) {
    image.removeAttribute(CANDIDATE_ATTRIBUTE);
  }

  function setImageState(image, state) {
    imageStates.set(image, state);
    if (state === "idle") {
      image.removeAttribute("data-act-state");
    } else {
      image.setAttribute("data-act-state", state);
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
    removeDebugCard(image);
    setImageState(image, "idle");
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

  function updateDebugCard(image, state, lines) {
    const card = createDebugCard(image);
    card.dataset.state = state;
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

  function showTranslationResult(image, result) {
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
      lines.push(list);
    }

    updateDebugCard(image, "translated", lines);
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

  async function translateCandidate(image) {
    if (!enabled || !translationApi) {
      return;
    }
    if (imageStates.get(image) === "translating") {
      return;
    }

    const request = {
      controller: new AbortController(),
    };
    activeRequests.set(image, request);
    setImageState(image, "translating");
    updateDebugCard(image, "translating", [
      createCardLine(
        "act-dev-result-status",
        "Fetching image and translating…",
      ),
    ]);

    try {
      const imageBlob = await fetchImageBlob(image, request.controller.signal);
      if (!enabled || activeRequests.get(image) !== request) {
        return;
      }
      const result = await translationApi.translateImage({
        imageBlob,
        sourceLanguage,
        targetLanguage: "en",
        backendUrl,
        signal: request.controller.signal,
      });
      if (!enabled || activeRequests.get(image) !== request) {
        return;
      }

      activeRequests.delete(image);
      setImageState(image, "translated");
      showTranslationResult(image, result);
      console.info("[ACT] translation completed", {
        requestId: result.requestId,
        regionCount: result.payload.regions.length,
      });
    } catch (error) {
      if (activeRequests.get(image) !== request || !enabled) {
        return;
      }
      activeRequests.delete(image);
      if (error?.kind === "cancelled") {
        setImageState(image, "idle");
        removeDebugCard(image);
        return;
      }

      setImageState(image, "error");
      showTranslationError(image, error);
      console.warn("[ACT] translation failed", {
        kind: error?.kind || "unknown",
        requestId: error?.requestId || null,
      });
    }
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
    void translateCandidate(image);
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
      removeCandidateMark(image);
      return;
    }

    if (!imageStates.has(image)) {
      imageStates.set(image, "idle");
    }
    image.setAttribute(CANDIDATE_ATTRIBUTE, "true");
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
    for (const record of records) {
      if (record.type === "childList") {
        for (const node of record.addedNodes) {
          collectImages(node, imagesToCheck);
        }
      } else if (
        record.type === "attributes" &&
        record.target.tagName === "IMG"
      ) {
        imagesToCheck.add(record.target);
        imagesToRefresh.add(record.target);
      }
    }

    for (const image of imagesToCheck) {
      if (imagesToRefresh.has(image)) {
        cancelImage(image);
        processedImages.delete(image);
        removeCandidateMark(image);
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
    if (observer) {
      return;
    }

    enabled = true;
    observer = new MutationObserver(handleMutations);
    observer.observe(document.documentElement || document, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["src", "srcset"],
    });
    discoverExistingImages();
  }

  function stopDiscovery() {
    enabled = false;
    observer?.disconnect();
    observer = null;
    for (const image of activeRequests.keys()) {
      cancelImage(image);
    }
    processedImages = new WeakSet();
    document
      .querySelectorAll(`[${CANDIDATE_ATTRIBUTE}="true"]`)
      .forEach(removeCandidateMark);
    document
      .querySelectorAll("img[data-act-state]")
      .forEach((image) => {
        image.removeAttribute("data-act-state");
        imageStates.delete(image);
      });
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

  let settingsRevision = 0;
  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "local") {
      return;
    }
    if (
      !["enabled", "sourceLanguage", "backendUrl"].some((key) =>
        Object.hasOwn(changes, key),
      )
    ) {
      return;
    }
    settingsRevision += 1;
    if (Object.hasOwn(changes, "enabled")) {
      setEnabled(changes.enabled.newValue);
    }
    if (Object.hasOwn(changes, "sourceLanguage")) {
      const value = changes.sourceLanguage.newValue;
      sourceLanguage =
        ["auto", "ja", "ko", "zh-Hans", "zh-Hant"].includes(value)
          ? value
          : "auto";
    }
    if (Object.hasOwn(changes, "backendUrl")) {
      backendUrl = changes.backendUrl.newValue;
    }
  });

  const initialRevision = settingsRevision;
  chrome.storage.local
    .get({
      enabled: true,
      sourceLanguage: "auto",
      backendUrl: "http://127.0.0.1:8000",
    })
    .then((settings) => {
      if (initialRevision === settingsRevision) {
        sourceLanguage = settings.sourceLanguage || "auto";
        backendUrl = settings.backendUrl || "http://127.0.0.1:8000";
        setEnabled(settings.enabled);
      }
    })
    .catch(() => {
      if (initialRevision === settingsRevision) {
        sourceLanguage = "auto";
        backendUrl = "http://127.0.0.1:8000";
        setEnabled(true);
      }
    });

  document.addEventListener("click", handleDocumentClick, true);
})();
