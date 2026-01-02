const DEFAULT_OUTPUT = "Waiting for a request...";
const POLL_INTERVAL_MS = 4000;

const baseUrlInput = document.querySelector("#baseUrl");
const activeIdInput = document.querySelector("#activeId");
const detailIdInput = document.querySelector("#detailId");
const parentIdInput = document.querySelector("#parentId");
const startQueryInput = document.querySelector("#startQuery");
const continueQueryInput = document.querySelector("#continueQuery");
const uploadFileInput = document.querySelector("#uploadFile");
const outputEl = document.querySelector("#output");

const startBtn = document.querySelector("#startBtn");
const uploadBtn = document.querySelector("#uploadBtn");
const continueBtn = document.querySelector("#continueBtn");
const detailBtn = document.querySelector("#detailBtn");
const historyBtn = document.querySelector("#historyBtn");
const pollBtn = document.querySelector("#pollBtn");
const useLastIdBtn = document.querySelector("#useLastId");
const copyBtn = document.querySelector("#copyBtn");
const clearBtn = document.querySelector("#clearBtn");

let lastId = "";
let pollTimer = null;
let pollInFlight = false;

const storage = window.localStorage;
const storedBaseUrl = storage.getItem("odr_base_url");
const storedLastId = storage.getItem("odr_last_id");

if (storedBaseUrl) {
  baseUrlInput.value = storedBaseUrl;
}

if (storedLastId && !activeIdInput.value) {
  lastId = storedLastId;
  activeIdInput.value = storedLastId;
  detailIdInput.value = storedLastId;
}

baseUrlInput.addEventListener("input", () => {
  storage.setItem("odr_base_url", baseUrlInput.value.trim());
});

function setOutput(value) {
  if (typeof value === "string") {
    outputEl.textContent = value;
    return;
  }
  outputEl.textContent = JSON.stringify(value, null, 2);
}

function showError(message) {
  setOutput({ ok: false, error: message });
}

function getBaseUrl() {
  return baseUrlInput.value.trim().replace(/\/+$/, "");
}

function setActiveId(id) {
  if (!id) {
    return;
  }
  activeIdInput.value = id;
  detailIdInput.value = id;
  lastId = id;
  storage.setItem("odr_last_id", id);
}

function getActiveId() {
  return activeIdInput.value.trim();
}

function getDetailId() {
  return detailIdInput.value.trim() || getActiveId();
}

async function apiRequest(path, options = {}) {
  const baseUrl = getBaseUrl();
  if (!baseUrl) {
    showError("API Base URL is required.");
    return null;
  }

  const url = `${baseUrl}${path}`;
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");

  const hasBody = Object.prototype.hasOwnProperty.call(options, "body");
  if (hasBody && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const requestOptions = {
    method: options.method || "GET",
    headers,
    body: options.body,
  };

  setOutput("Loading...");

  try {
    const response = await fetch(url, requestOptions);
    const contentType = response.headers.get("content-type") || "";
    let payload = {};

    if (contentType.includes("application/json")) {
      payload = await response.json();
    } else {
      const text = await response.text();
      payload = text ? { raw: text } : {};
    }

    const output = {
      ok: response.ok,
      status: response.status,
      url,
      response: payload,
    };

    setOutput(output);

    if (!response.ok) {
      return null;
    }

    return payload;
  } catch (error) {
    showError(error.message || "Request failed.");
    return null;
  }
}

startBtn.addEventListener("click", async () => {
  const query = startQueryInput.value.trim();
  if (!query) {
    showError("Query is required to start research.");
    return;
  }

  const payload = { query };
  const parentId = parentIdInput.value.trim();
  if (parentId) {
    payload.parent_research_id = parentId;
  }

  const data = await apiRequest("/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });

  if (data && data.research_id) {
    setActiveId(data.research_id);
  }
});

uploadBtn.addEventListener("click", async () => {
  const researchId = getActiveId();
  if (!researchId) {
    showError("Active Research ID is required for uploads.");
    return;
  }

  const file = uploadFileInput.files[0];
  if (!file) {
    showError("Select a TXT or PDF file to upload.");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  await apiRequest(`/${researchId}/upload`, {
    method: "POST",
    body: formData,
  });
});

continueBtn.addEventListener("click", async () => {
  const researchId = getActiveId();
  if (!researchId) {
    showError("Active Research ID is required to continue.");
    return;
  }

  const query = continueQueryInput.value.trim();
  if (!query) {
    showError("Follow-up query is required to continue research.");
    return;
  }

  const data = await apiRequest(`/${researchId}/continue`, {
    method: "POST",
    body: JSON.stringify({ query }),
  });

  if (data && data.research_id) {
    setActiveId(data.research_id);
  }
});

detailBtn.addEventListener("click", async () => {
  const researchId = getDetailId();
  if (!researchId) {
    showError("Research ID is required to fetch details.");
    return;
  }

  await apiRequest(`/${researchId}`);
});

historyBtn.addEventListener("click", async () => {
  await apiRequest("/history");
});

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  pollBtn.textContent = "Poll Status";
}

async function pollOnce() {
  if (pollInFlight) {
    return;
  }
  pollInFlight = true;

  const researchId = getDetailId();
  if (!researchId) {
    showError("Research ID is required to poll status.");
    stopPolling();
    pollInFlight = false;
    return;
  }

  const data = await apiRequest(`/${researchId}`);
  pollInFlight = false;

  if (data && (data.status === "COMPLETED" || data.status === "FAILED")) {
    stopPolling();
  }
}

pollBtn.addEventListener("click", () => {
  if (pollTimer) {
    stopPolling();
    return;
  }

  pollBtn.textContent = "Stop Polling";
  pollOnce();
  pollTimer = setInterval(pollOnce, POLL_INTERVAL_MS);
});

useLastIdBtn.addEventListener("click", () => {
  if (!lastId) {
    showError("No research ID stored yet.");
    return;
  }
  activeIdInput.value = lastId;
  detailIdInput.value = lastId;
});

copyBtn.addEventListener("click", async () => {
  const text = outputEl.textContent.trim();
  if (!text) {
    return;
  }

  if (!navigator.clipboard) {
    showError("Clipboard not available in this browser.");
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    const originalLabel = copyBtn.textContent;
    copyBtn.textContent = "Copied";
    setTimeout(() => {
      copyBtn.textContent = originalLabel;
    }, 1200);
  } catch (error) {
    showError("Copy failed.");
  }
});

clearBtn.addEventListener("click", () => {
  setOutput(DEFAULT_OUTPUT);
});

setOutput(DEFAULT_OUTPUT);
