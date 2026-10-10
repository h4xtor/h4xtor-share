import { ALL, chosenDevice, connect, devices, getToken, send, sendAll, summarize } from "./api.js";

const $ = (id) => document.getElementById(id);
const COLORS = { android: "#3DDC84", windows: "#2F7BEA", linux: "#E8A33D", darwin: "#8E8E93", macos: "#8E8E93", all: "#D97757" };
let list = [];
let current = null;

function show(state) {
  for (const id of ["loading", "offline", "connect", "ready"]) {
    $(`state-${id}`).classList.toggle("hidden", id !== state);
  }
}

let toastTimer;
function toast(message, error = false) {
  const element = $("toast");
  element.textContent = message;
  element.classList.toggle("error", error);
  element.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.add("hidden"), error ? 4500 : 2200);
}

function renderDevices() {
  const container = $("devices");
  container.textContent = "";
  if (!list.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Ingen forbundne enheder. Forbind din telefon i h4xtor share på PC'en.";
    container.append(empty);
  }
  for (const device of list.length >= 2 ? [ALL, ...list] : list) {
    const row = document.createElement("button");
    row.className = "device" + (current && current.id === device.id ? " active" : "");
    const avatar = document.createElement("span");
    avatar.className = "avatar";
    avatar.style.background = COLORS[(device.platform || "").toLowerCase()] || "#A3A19A";
    avatar.textContent = device.all ? "★" : (device.platform || "?").slice(0, 1).toUpperCase();
    const texts = document.createElement("span");
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = device.name;
    const meta = document.createElement("div");
    meta.className = "meta";
    const dot = document.createElement("span");
    dot.className = "dot" + (device.online ? " on" : "");
    if (device.all) meta.append(`${list.length} enheder`);
    else meta.append(dot, device.online ? "Online" : "Offline");
    texts.append(name, meta);
    row.append(avatar, texts);
    row.addEventListener("click", async () => {
      current = device;
      await chrome.storage.local.set({ deviceId: device.id });
      renderDevices();
    });
    container.append(row);
  }
  $("send-tab").disabled = !current;
  $("send-tab").textContent = current
    ? `Send denne fane til ${current.all ? "alle enheder" : current.name}`
    : "Send denne fane";
}

async function refresh() {
  show("loading");
  if (!(await getToken())) {
    try {
      await fetch("http://127.0.0.1:47476/v1/status");
      show("connect");
    } catch (error) {
      show("offline");
    }
    return;
  }
  try {
    list = await devices();
    current = await chosenDevice(list);
    const { pcName } = await chrome.storage.local.get("pcName");
    $("pc").textContent = pcName ? `via ${pcName}` : "";
    renderDevices();
    show("ready");
    chrome.runtime.sendMessage({ type: "rebuild-menus" });
  } catch (error) {
    if (error.code === "unauthorised") show("connect");
    else show("offline");
  }
}

async function sendValue(kind, value, label) {
  if (!current) return toast("Vælg en enhed først", true);
  try {
    if (current.all) {
      const summary = summarize(await sendAll(kind, value), list);
      toast(summary.failed ? summary.text : `${label} sendt til alle ${summary.total} enheder ✓`, summary.sent === 0);
      return;
    }
    await send(current.id, kind, value);
    toast(`${label} sendt til ${current.name} ✓`);
  } catch (error) {
    toast(error.message, true);
  }
}

$("retry").addEventListener("click", refresh);
$("connect").addEventListener("click", async () => {
  $("connect").disabled = true;
  $("connect-wait").classList.remove("hidden");
  try {
    await connect();
    toast("Forbundet ✓");
    await refresh();
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("connect").disabled = false;
    $("connect-wait").classList.add("hidden");
  }
});
$("send-tab").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !/^https?:/i.test(tab.url || "")) return toast("Denne side kan ikke sendes", true);
  await sendValue("link", tab.url, "Fanen");
});
async function sendText() {
  const value = $("text").value.trim();
  if (!value) return;
  const isLink = /^https?:\/\/\S+$/i.test(value);
  await sendValue(isLink ? "link" : "text", value, isLink ? "Linket" : "Teksten");
  // Only clear what was sent; the user may already have typed the next thing.
  if ($("text").value.trim() === value) $("text").value = "";
}
$("send-text").addEventListener("click", sendText);
$("text").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendText();
  }
});

refresh();
