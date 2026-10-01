import { DISPLAY_MODES, SOURCE_LANGUAGES } from "../lib/constants.js";
import { checkHealth } from "../lib/api.js";
import {
  loadSettings,
  normalizeBackendUrl,
  saveSetting,
} from "../lib/settings.js";

const connectionCard = document.querySelector(".connection-card");
const connectionMessage = document.querySelector("#connection-message");
const checkButton = document.querySelector("#check-connection");
const enabledInput = document.querySelector("#enabled");
const showOverlaysInput = document.querySelector("#show-overlays");
const sourceSelect = document.querySelector("#source-language");
const displaySelect = document.querySelector("#display-mode");
const backendForm = document.querySelector("#backend-form");
const backendInput = document.querySelector("#backend-url");
const backendError = document.querySelector("#backend-error");
const saveFeedback = document.querySelector("#save-feedback");

function addOptions(select, options) {
  for (const { value, label } of options) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.append(option);
  }
}

function showConnection(state, message) {
  connectionCard.dataset.state = state;
  connectionMessage.textContent = message;
}

function showBackendError(message) {
  backendError.textContent = message;
  backendInput.setAttribute("aria-invalid", message ? "true" : "false");
}

function showSaveFeedback(message) {
  saveFeedback.textContent = message;
}

async function persistPreference(key, value) {
  try {
    await saveSetting(key, value);
    showSaveFeedback("Saved");
  } catch {
    showSaveFeedback("Could not save");
  }
}

async function saveBackendUrl() {
  let normalizedUrl;
  try {
    normalizedUrl = normalizeBackendUrl(backendInput.value);
    await saveSetting("backendUrl", normalizedUrl);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Could not save this URL.";
    showBackendError(message);
    showConnection("not-checked", "Backend URL is invalid.");
    showSaveFeedback("");
    backendInput.focus();
    return null;
  }

  backendInput.value = normalizedUrl;
  showBackendError("");
  showConnection("not-checked", "Backend URL saved. Check connection to verify.");
  showSaveFeedback("Backend URL saved");
  return normalizedUrl;
}

async function runHealthCheck(baseUrl = backendInput.value) {
  let normalizedUrl;
  try {
    normalizedUrl = normalizeBackendUrl(baseUrl);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Enter a valid backend URL.";
    showBackendError(message);
    showConnection("disconnected", "Backend URL needs attention.");
    return;
  }

  backendInput.value = normalizedUrl;
  showBackendError("");
  showConnection("checking", "Checking backend…");
  checkButton.disabled = true;
  checkButton.textContent = "Checking…";
  const result = await checkHealth(normalizedUrl);
  showConnection(result.state, result.message);
  checkButton.disabled = false;
  checkButton.textContent = "Check";
}

async function handleConnectionCheck() {
  const normalizedUrl = await saveBackendUrl();
  if (normalizedUrl) {
    await runHealthCheck(normalizedUrl);
  }
}

async function initialize() {
  addOptions(sourceSelect, SOURCE_LANGUAGES);
  addOptions(
    displaySelect,
    DISPLAY_MODES.map(({ value, label }) => ({ value, label })),
  );

  try {
    const settings = await loadSettings();
    enabledInput.checked = settings.enabled;
    showOverlaysInput.checked = settings.showOverlays;
    sourceSelect.value = settings.sourceLanguage;
    displaySelect.value = settings.displayMode;
    backendInput.value = settings.backendUrl;
    await runHealthCheck(settings.backendUrl);
  } catch {
    showConnection("disconnected", "Could not load extension settings.");
    showSaveFeedback("Settings unavailable");
  }
}

enabledInput.addEventListener("change", () => {
  persistPreference("enabled", enabledInput.checked);
});

showOverlaysInput.addEventListener("change", () => {
  persistPreference("showOverlays", showOverlaysInput.checked);
});

sourceSelect.addEventListener("change", () => {
  persistPreference("sourceLanguage", sourceSelect.value);
});

displaySelect.addEventListener("change", () => {
  persistPreference("displayMode", displaySelect.value);
});

backendForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await saveBackendUrl();
});

checkButton.addEventListener("click", handleConnectionCheck);

backendInput.addEventListener("input", () => {
  if (backendError.textContent) {
    showBackendError("");
  }
});

initialize();
