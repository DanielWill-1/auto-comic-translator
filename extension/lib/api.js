import { API_VERSION, HEALTH_TIMEOUT_MS } from "./constants.js";
import { normalizeBackendUrl } from "./settings.js";
import "./translation-api.js";

export async function translateImage(options) {
  return globalThis.ACTTranslationApi.translateImage(options);
}

function isPermittedDefaultBackend(baseUrl) {
  try {
    const parsed = new URL(baseUrl);
    return (
      parsed.origin === "http://127.0.0.1:8000" &&
      parsed.pathname === "/"
    );
  } catch {
    return false;
  }
}

export async function checkHealth(
  baseUrl,
  timeoutMs = HEALTH_TIMEOUT_MS,
) {
  let normalizedUrl;
  try {
    normalizedUrl = normalizeBackendUrl(baseUrl);
  } catch {
    return {
      state: "disconnected",
      message: "Enter a valid HTTP or HTTPS backend URL.",
    };
  }

  if (!isPermittedDefaultBackend(normalizedUrl)) {
    return {
      state: "permission-needed",
      message: "Custom host saved; browser permission support is needed to check it.",
    };
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${normalizedUrl}/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: controller.signal,
      cache: "no-store",
      redirect: "error",
    });

    if (!response.ok) {
      return {
        state: "disconnected",
        message: `Backend returned HTTP ${response.status}.`,
      };
    }

    let payload;
    try {
      payload = await response.json();
    } catch {
      return {
        state: "disconnected",
        message: "Backend returned invalid JSON.",
      };
    }

    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      return {
        state: "disconnected",
        message: "Backend returned an invalid health response.",
      };
    }
    if (payload.api_version !== API_VERSION) {
      return {
        state: "incompatible",
        message: "Unsupported backend API version.",
      };
    }
    if (payload.status !== "ok") {
      return {
        state: "disconnected",
        message: "Backend health check did not pass.",
      };
    }

    return { state: "connected", message: "Backend connected." };
  } catch (error) {
    if (error?.name === "AbortError") {
      return { state: "disconnected", message: "Backend check timed out." };
    }
    return { state: "disconnected", message: "Backend offline." };
  } finally {
    clearTimeout(timeoutId);
  }
}
