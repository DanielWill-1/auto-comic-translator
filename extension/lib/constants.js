export const API_VERSION = "1";
export const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
export const HEALTH_TIMEOUT_MS = 3500;

export const SOURCE_LANGUAGES = Object.freeze([
  { value: "auto", label: "Auto detect" },
  { value: "ja", label: "Japanese" },
  { value: "ko", label: "Korean" },
  { value: "zh-Hans", label: "Chinese (Simplified)" },
  { value: "zh-Hant", label: "Chinese (Traditional)" },
]);

export const DISPLAY_MODES = Object.freeze([
  { value: "overlay", label: "Overlay" },
  { value: "feed", label: "Translation feed" },
]);
