import {
  DEFAULT_BACKEND_URL,
  DISPLAY_MODES,
  SOURCE_LANGUAGES,
} from "./constants.js";

export const DEFAULT_SETTINGS = Object.freeze({
  enabled: true,
  showOverlays: true,
  backendUrl: DEFAULT_BACKEND_URL,
  sourceLanguage: "auto",
  targetLanguage: "en",
  displayMode: "overlay",
});

const SETTING_KEYS = new Set(Object.keys(DEFAULT_SETTINGS));
const SOURCE_VALUES = new Set(SOURCE_LANGUAGES.map(({ value }) => value));
const DISPLAY_VALUES = new Set(DISPLAY_MODES.map(({ value }) => value));

export function normalizeBackendUrl(value) {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error("Enter a backend URL.");
  }

  const trimmed = value.trim();
  if (!/^https?:\/\//i.test(trimmed)) {
    throw new Error("Use an HTTP or HTTPS URL.");
  }

  const normalized = trimmed.replace(/\/+$/, "");
  let parsed;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error("Enter a valid backend URL.");
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Use an HTTP or HTTPS URL.");
  }
  if (!parsed.hostname) {
    throw new Error("Enter a valid backend host.");
  }
  if (parsed.username || parsed.password) {
    throw new Error("Backend URLs cannot contain login credentials.");
  }
  if (parsed.search || parsed.hash) {
    throw new Error("Backend URLs cannot contain a query or fragment.");
  }

  return normalized;
}

export async function loadSettings() {
  const stored = await chrome.storage.local.get(DEFAULT_SETTINGS);
  let backendUrl =
    typeof stored.backendUrl === "string"
      ? stored.backendUrl
      : DEFAULT_SETTINGS.backendUrl;
  try {
    backendUrl = normalizeBackendUrl(backendUrl);
  } catch {
    // Keep a previously saved invalid value visible so the popup can explain it.
  }

  return {
    enabled:
      typeof stored.enabled === "boolean"
        ? stored.enabled
        : DEFAULT_SETTINGS.enabled,
    showOverlays:
      typeof stored.showOverlays === "boolean"
        ? stored.showOverlays
        : DEFAULT_SETTINGS.showOverlays,
    backendUrl,
    sourceLanguage: SOURCE_VALUES.has(stored.sourceLanguage)
      ? stored.sourceLanguage
      : DEFAULT_SETTINGS.sourceLanguage,
    targetLanguage: "en",
    displayMode: DISPLAY_VALUES.has(stored.displayMode)
      ? stored.displayMode
      : DEFAULT_SETTINGS.displayMode,
  };
}

export async function saveSetting(key, value) {
  if (!SETTING_KEYS.has(key)) {
    throw new Error("Unknown setting.");
  }

  let validatedValue = value;
  if (key === "enabled" && typeof value !== "boolean") {
    throw new Error("Invalid translator setting.");
  }
  if (key === "showOverlays" && typeof value !== "boolean") {
    throw new Error("Invalid overlay setting.");
  }
  if (key === "backendUrl") {
    validatedValue = normalizeBackendUrl(value);
  }
  if (key === "sourceLanguage" && !SOURCE_VALUES.has(value)) {
    throw new Error("Choose a supported source language.");
  }
  if (key === "displayMode" && !DISPLAY_VALUES.has(value)) {
    throw new Error("Choose a supported display mode.");
  }
  if (key === "targetLanguage" && value !== "en") {
    throw new Error("English is the only supported target language.");
  }

  await chrome.storage.local.set({ [key]: validatedValue });
  return validatedValue;
}
