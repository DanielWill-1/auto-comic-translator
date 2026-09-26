(() => {
  const API_VERSION = "1";
  const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
  const TRANSLATION_TIMEOUT_MS = 60_000;
  const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
  const MAX_BASE64_LENGTH = Math.ceil(MAX_IMAGE_BYTES / 3) * 4;
  const SOURCE_LANGUAGES = new Set([
    "auto",
    "ja",
    "ko",
    "zh-Hans",
    "zh-Hant",
  ]);

  class TranslationError extends Error {
    constructor(kind, message, requestId = null) {
      super(message);
      this.name = "TranslationError";
      this.kind = kind;
      this.requestId = requestId;
    }
  }

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function requireRecord(value, message, requestId = null) {
    if (!isRecord(value)) {
      throw new TranslationError("malformed", message, requestId);
    }
  }

  function getPermittedEndpoint(backendUrl) {
    let parsed;
    try {
      parsed = new URL(backendUrl);
    } catch {
      throw new TranslationError(
        "configuration",
        "The configured backend URL is invalid.",
      );
    }

    if (
      parsed.origin !== DEFAULT_BACKEND_URL ||
      parsed.pathname !== "/" ||
      parsed.search ||
      parsed.hash
    ) {
      throw new TranslationError(
        "configuration",
        `Translation is limited to ${DEFAULT_BACKEND_URL} in this milestone.`,
      );
    }
    return `${parsed.origin}/translate`;
  }

  function filenameForBlob(blob) {
    const extensionByType = {
      "image/bmp": "bmp",
      "image/gif": "gif",
      "image/jpeg": "jpg",
      "image/png": "png",
      "image/tiff": "tiff",
      "image/webp": "webp",
    };
    const extension = extensionByType[blob.type.toLowerCase()] || "img";
    return `comic-image.${extension}`;
  }

  function getRequestId(response, payload) {
    const headerId = response.headers.get("X-Request-ID");
    if (headerId) {
      return headerId;
    }
    const bodyId = payload?.error?.request_id;
    return typeof bodyId === "string" && bodyId ? bodyId : null;
  }

  function validateResponse(payload, requestId) {
    requireRecord(
      payload,
      "Backend returned a malformed response.",
      requestId,
    );

    if (payload.api_version !== API_VERSION) {
      throw new TranslationError(
        "incompatible-api",
        `Unsupported backend API version: ${String(payload.api_version)}.`,
        requestId,
      );
    }

    requireRecord(
      payload.image,
      "Response is missing image dimensions.",
      requestId,
    );
    const { width, height } = payload.image;
    if (
      !Number.isFinite(width) ||
      width <= 0 ||
      !Number.isFinite(height) ||
      height <= 0
    ) {
      throw new TranslationError(
        "malformed",
        "Backend returned invalid image dimensions.",
        requestId,
      );
    }

    if (!Array.isArray(payload.regions)) {
      throw new TranslationError(
        "malformed",
        "Backend response is missing its regions array.",
        requestId,
      );
    }

    for (const [index, region] of payload.regions.entries()) {
      requireRecord(
        region,
        `Backend region ${index + 1} is malformed.`,
        requestId,
      );
      if (
        typeof region.original_text !== "string" ||
        typeof region.translated_text !== "string" ||
        (region.source_language !== null &&
          typeof region.source_language !== "string") ||
        !["ok", "fallback"].includes(region.translation_status)
      ) {
        throw new TranslationError(
          "malformed",
          `Backend region ${index + 1} is missing required fields.`,
          requestId,
        );
      }

      const bbox = region.bbox;
      if (!isRecord(bbox)) {
        throw new TranslationError(
          "malformed",
          `Backend region ${index + 1} is missing its bounding box.`,
          requestId,
        );
      }
      const coordinates = [bbox.x1, bbox.y1, bbox.x2, bbox.y2];
      if (
        coordinates.some((coordinate) => !Number.isFinite(coordinate)) ||
        bbox.x1 < 0 ||
        bbox.y1 < 0 ||
        bbox.x2 < bbox.x1 ||
        bbox.y2 < bbox.y1 ||
        bbox.x2 > width ||
        bbox.y2 > height
      ) {
        throw new TranslationError(
          "malformed",
          `Backend region ${index + 1} has an invalid bounding box.`,
          requestId,
        );
      }
    }

    return payload;
  }

  async function submitImageFromWorker({
    imageBlob,
    sourceLanguage = "auto",
    targetLanguage = "en",
    backendUrl = DEFAULT_BACKEND_URL,
    timeoutMs = TRANSLATION_TIMEOUT_MS,
    signal,
  }) {
    const endpoint = getPermittedEndpoint(backendUrl);
    if (!(imageBlob instanceof Blob) || imageBlob.size === 0) {
      throw new TranslationError(
        "image",
        "The selected image has no usable image data.",
      );
    }
    if (imageBlob.size > MAX_IMAGE_BYTES) {
      throw new TranslationError(
        "image",
        "The selected image exceeds the backend's 20 MiB limit.",
      );
    }
    if (!SOURCE_LANGUAGES.has(sourceLanguage) || targetLanguage !== "en") {
      throw new TranslationError(
        "configuration",
        "The saved translation language settings are not supported.",
      );
    }
    if (signal?.aborted) {
      throw new TranslationError("cancelled", "Translation was cancelled.");
    }

    const formData = new FormData();
    formData.append("image", imageBlob, filenameForBlob(imageBlob));
    formData.append("source_language", sourceLanguage);
    formData.append("target_language", targetLanguage);

    const controller = new AbortController();
    let timedOut = false;
    const timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs);
    const relayAbort = () => controller.abort();
    signal?.addEventListener("abort", relayAbort, { once: true });

    try {
      let response;
      try {
        response = await fetch(endpoint, {
          method: "POST",
          headers: { Accept: "application/json" },
          body: formData,
          signal: controller.signal,
          cache: "no-store",
          credentials: "omit",
          redirect: "error",
        });
      } catch (error) {
        if (timedOut) {
          const timeoutSeconds = Math.round(timeoutMs / 1000);
          throw new TranslationError(
            "timeout",
            `Translation request timed out after ${timeoutSeconds} seconds.`,
          );
        }
        if (controller.signal.aborted) {
          throw new TranslationError("cancelled", "Translation was cancelled.");
        }
        throw new TranslationError(
          "backend-network",
          "Could not reach the backend. It may be offline or the browser may " +
            "have blocked this cross-origin request; check the extension " +
            "Console for details.",
        );
      }

      let payload;
      try {
        payload = await response.json();
      } catch {
        throw new TranslationError(
          response.ok ? "malformed" : "backend-api",
          response.ok
            ? "Backend returned invalid JSON."
            : `Backend returned HTTP ${response.status} with an invalid ` +
              "error response.",
          response.headers.get("X-Request-ID"),
        );
      }

      const requestId = getRequestId(response, payload);
      requireRecord(
        payload,
        "Backend returned a malformed response.",
        response.headers.get("X-Request-ID"),
      );
      if (payload.api_version !== API_VERSION) {
        throw new TranslationError(
          "incompatible-api",
          `Unsupported backend API version: ${String(payload.api_version)}.`,
          requestId,
        );
      }
      if (!response.ok) {
        const apiError = payload.error;
        const code =
          isRecord(apiError) && typeof apiError.code === "string"
            ? apiError.code.slice(0, 80)
            : "API_ERROR";
        const message =
          isRecord(apiError) && typeof apiError.message === "string"
            ? apiError.message.slice(0, 220)
            : "The backend rejected the translation request.";
        throw new TranslationError(
          "backend-api",
          `Backend returned HTTP ${response.status} (${code}): ${message}`,
          requestId,
        );
      }

      return {
        payload: validateResponse(payload, requestId),
        requestId,
      };
    } finally {
      clearTimeout(timeoutId);
      signal?.removeEventListener("abort", relayAbort);
    }
  }

  async function blobToBase64(blob) {
    const bytes = new Uint8Array(await blob.arrayBuffer());
    const chunks = [];
    const chunkSize = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      chunks.push(
        String.fromCharCode(...bytes.subarray(offset, offset + chunkSize)),
      );
    }
    return btoa(chunks.join(""));
  }

  function cancelWorkerRequest(requestId) {
    void chrome.runtime
      .sendMessage({ type: "ACT_CANCEL_TRANSLATION", requestId })
      .catch(() => {});
  }

  async function translateImage({
    imageBlob,
    sourceLanguage = "auto",
    targetLanguage = "en",
    backendUrl = DEFAULT_BACKEND_URL,
    timeoutMs = TRANSLATION_TIMEOUT_MS,
    signal,
  }) {
    getPermittedEndpoint(backendUrl);
    if (!(imageBlob instanceof Blob) || imageBlob.size === 0) {
      throw new TranslationError(
        "image",
        "The selected image has no usable image data.",
      );
    }
    if (imageBlob.size > MAX_IMAGE_BYTES) {
      throw new TranslationError(
        "image",
        "The selected image exceeds the backend's 20 MiB limit.",
      );
    }
    if (!SOURCE_LANGUAGES.has(sourceLanguage) || targetLanguage !== "en") {
      throw new TranslationError(
        "configuration",
        "The saved translation language settings are not supported.",
      );
    }
    if (signal?.aborted) {
      throw new TranslationError("cancelled", "Translation was cancelled.");
    }

    const imageBase64 = await blobToBase64(imageBlob);
    if (signal?.aborted) {
      throw new TranslationError("cancelled", "Translation was cancelled.");
    }
    if (imageBase64.length > MAX_BASE64_LENGTH) {
      throw new TranslationError("image", "The selected image is too large.");
    }

    const requestId = crypto.randomUUID();
    const message = {
      type: "ACT_TRANSLATE_IMAGE",
      requestId,
      backendUrl,
      sourceLanguage,
      targetLanguage,
      imageType: imageBlob.type,
      imageBase64,
    };

    return new Promise((resolve, reject) => {
      let settled = false;
      const cleanup = () => {
        clearTimeout(timeoutId);
        signal?.removeEventListener("abort", handleAbort);
      };
      const finish = (callback, value) => {
        if (settled) return;
        settled = true;
        cleanup();
        callback(value);
      };
      const handleAbort = () => {
        cancelWorkerRequest(requestId);
        finish(
          reject,
          new TranslationError("cancelled", "Translation was cancelled."),
        );
      };
      const timeoutId = setTimeout(() => {
        const timeoutSeconds = Math.round(timeoutMs / 1000);
        cancelWorkerRequest(requestId);
        finish(
          reject,
          new TranslationError(
            "timeout",
            `Translation request timed out after ${timeoutSeconds} seconds.`,
          ),
        );
      }, timeoutMs);

      signal?.addEventListener("abort", handleAbort, { once: true });
      if (signal?.aborted) {
        handleAbort();
        return;
      }

      chrome.runtime
        .sendMessage(message)
        .then((workerResponse) => {
          if (!isRecord(workerResponse)) {
            throw new TranslationError(
              "malformed",
              "The extension translation worker returned an invalid response.",
              requestId,
            );
          }
          if (workerResponse.ok !== true) {
            const error = workerResponse.error;
            throw new TranslationError(
              typeof error?.kind === "string" ? error.kind : "backend-network",
              typeof error?.message === "string"
                ? error.message
                : "The extension translation worker could not complete the request.",
              typeof error?.requestId === "string"
                ? error.requestId
                : null,
            );
          }

          const backendRequestId =
            typeof workerResponse.requestId === "string"
              ? workerResponse.requestId
              : null;
          const payload = validateResponse(
            workerResponse.payload,
            backendRequestId,
          );
          finish(resolve, { payload, requestId: backendRequestId });
        })
        .catch((error) => {
          if (error instanceof TranslationError) {
            finish(reject, error);
          } else {
            finish(
              reject,
              new TranslationError(
                "backend-network",
                "Could not contact the extension translation worker.",
                requestId,
              ),
            );
          }
        });
    });
  }

  globalThis.ACTTranslationApi = Object.freeze({
    TRANSLATION_TIMEOUT_MS,
    TranslationError,
    submitImageFromWorker,
    translateImage,
  });
})();
