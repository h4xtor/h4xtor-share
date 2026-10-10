// Tiny client for the h4xtor share desktop app's loopback API.
export const BASE = "http://127.0.0.1:47476";

export async function getToken() {
  const { token } = await chrome.storage.local.get("token");
  return token || null;
}

export async function call(path, { method = "GET", body, auth = true, timeoutMs = 8000 } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = await getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(BASE + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (error) {
    const offline = new Error("h4xtor share kører ikke på denne PC. Start programmet og prøv igen.");
    offline.code = "offline";
    throw offline;
  } finally {
    clearTimeout(timer);
  }
  if (response.status === 401) {
    await chrome.storage.local.remove("token");
    const unauth = new Error("Forbind udvidelsen til h4xtor share først.");
    unauth.code = "unauthorised";
    throw unauth;
  }
  if (!response.ok) {
    const text = (await response.text()).trim();
    throw new Error(text || `Fejl ${response.status}`);
  }
  return response.json();
}

export async function connect() {
  const result = await call("/v1/connect", {
    method: "POST",
    body: { name: "Chrome" },
    auth: false,
    timeoutMs: 130000,
  });
  await chrome.storage.local.set({ token: result.token, pcName: result.name });
  return result;
}

export async function devices() {
  const result = await call("/v1/devices");
  return result.devices || [];
}

export async function send(deviceId, kind, value) {
  return call("/v1/send", {
    method: "POST",
    body: { device_id: deviceId, kind, value },
    timeoutMs: 180000,
  });
}

// Pseudo-device for "send to every paired device" (stored as deviceId "all").
export const ALL = { id: "all", name: "Alle enheder", platform: "all", online: true, all: true };

export async function sendAll(kind, value) {
  const result = await call("/v1/send-all", {
    method: "POST",
    body: { kind, value },
    timeoutMs: 180000,
  });
  return result.results || [];
}

// "Sendt til 2 af 3 – Bærbar: offline" from the per-device results of sendAll().
export function summarize(results, list = []) {
  const failed = results.filter((r) => !r.ok);
  const sent = results.length - failed.length;
  let text = `Sendt til ${sent} af ${results.length}`;
  if (sent === results.length) text = `Sendt til alle ${results.length} enheder`;
  if (failed.length) {
    const why = failed.map((r) => {
      const device = list.find((d) => d.id === r.id);
      const reason = device && !device.online ? "offline" : (r.error || "fejl").split(/(?<=\.)\s/)[0];
      return `${r.name}: ${reason}`;
    });
    text += ` – ${why.join(", ")}`;
  }
  return { sent, total: results.length, failed: failed.length, text };
}

export async function chosenDevice(list) {
  const { deviceId } = await chrome.storage.local.get("deviceId");
  if (deviceId === ALL.id && list.length >= 2) return ALL;
  return (
    list.find((d) => d.id === deviceId) ||
    list.find((d) => d.selected) ||
    list.find((d) => d.online) ||
    list[0] ||
    null
  );
}
