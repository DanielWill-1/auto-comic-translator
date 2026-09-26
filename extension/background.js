import "./lib/translation-api.js";

const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
const MAX_BASE64_LENGTH = Math.ceil(MAX_IMAGE_BYTES / 3) * 4;
const SOURCE_LANGUAGES = new Set([
  "auto",
  "ja",
  "ko",
  "zh-Hans",
  "zh-Hant",
]);
const activeRequests = new Map();

class WorkerRequestError extends Error {
  constructor(kind, message, requestId = null) {
    super(message);
    this.kind = kind;
    this.requestId = requestId;
  }
}

function isAllowedSender(sender) {
  if (sender.id !== chrome.runtime.id || typeof sender.url !== "string") {
    return false;
  }
  try {
    return new URL(sender.url).origin === "http://127.0.0.1:8080";
  } catch {
    return false;
  }
}

function imageFromMessage(message) {
  if (
    typeof message.imageBase64 !== "string" ||
    message.imageBase64.length === 0 ||
    message.imageBase64.length > MAX_BASE64_LENGTH
  ) {
    throw new WorkerRequestError("image", "The selected image data is invalid.");
  }

  let binary;
  try {
    binary = atob(message.imageBase64);
  } catch {
    throw new WorkerRequestError("image", "The selected image data is invalid.");
  }
  if (binary.length === 0 || binary.length > MAX_IMAGE_BYTES) {
    throw new WorkerRequestError(
      "image",
      "The selected image exceeds the backend's 20 MiB limit.",
    );
  }

  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const imageType =
    typeof message.imageType === "string" && message.imageType.length <= 100
      ? message.imageType
      : "application/octet-stream";
  return new Blob([bytes], { type: imageType });
}

function errorResponse(error) {
  return {
    ok: false,
    error: {
      kind: typeof error?.kind === "string" ? error.kind : "backend-network",
      message:
        typeof error?.message === "string"
          ? error.message.slice(0, 300)
          : "The local translation request failed.",
      requestId:
        typeof error?.requestId === "string"
          ? error.requestId
          : null,
    },
  };
}

async function handleTranslation(message, sender) {
  const requestId = message.requestId;
  if (!isAllowedSender(sender)) {
    return errorResponse(
      new WorkerRequestError(
        "configuration",
        "Translation requests are accepted only from the local test page.",
      ),
    );
  }
  if (
    typeof requestId !== "string" ||
    !/^[0-9a-f-]{36}$/i.test(requestId) ||
    typeof message.backendUrl !== "string" ||
    (message.backendUrl !== DEFAULT_BACKEND_URL &&
      message.backendUrl !== `${DEFAULT_BACKEND_URL}/`) ||
    !SOURCE_LANGUAGES.has(message.sourceLanguage) ||
    message.targetLanguage !== "en"
  ) {
    return errorResponse(
      new WorkerRequestError(
        "configuration",
        "The translation request settings are not supported.",
      ),
    );
  }

  const controller = new AbortController();
  activeRequests.set(requestId, controller);
  try {
    const imageBlob = imageFromMessage(message);
    const result = await globalThis.ACTTranslationApi.submitImageFromWorker({
      imageBlob,
      sourceLanguage: message.sourceLanguage,
      targetLanguage: message.targetLanguage,
      backendUrl: message.backendUrl,
      signal: controller.signal,
    });
    return { ok: true, ...result };
  } catch (error) {
    return errorResponse(error);
  } finally {
    activeRequests.delete(requestId);
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "ACT_TRANSLATE_IMAGE") {
    void handleTranslation(message, sender).then(sendResponse, (error) =>
      sendResponse(errorResponse(error)),
    );
    return true;
  }

  if (
    message?.type === "ACT_CANCEL_TRANSLATION" &&
    sender.id === chrome.runtime.id &&
    typeof message.requestId === "string"
  ) {
    activeRequests.get(message.requestId)?.abort();
    sendResponse({ ok: true });
  }
  return false;
});
