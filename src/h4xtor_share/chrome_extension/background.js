import { ALL, chosenDevice, devices, payloadFor, send, sendAll, summarize } from "./api.js";

const ROOT = "h4xtor-root";
const CONTEXTS = ["page", "link", "selection", "image", "video", "audio"];

async function rebuildMenus() {
  await chrome.contextMenus.removeAll();
  let list = [];
  try {
    list = await devices();
  } catch (error) {
    list = [];
  }
  chrome.contextMenus.create({ id: ROOT, title: "Send med h4xtor share", contexts: CONTEXTS });
  if (!list.length) {
    chrome.contextMenus.create({
      id: "h4xtor-setup",
      parentId: ROOT,
      title: "Forbind udvidelsen (klik på h4xtor-ikonet)",
      contexts: CONTEXTS,
      enabled: false,
    });
    return;
  }
  // Right-click on a picture: "Send billede til <enhed>" first, like Join's "Download Image on …".
  for (const device of list.length >= 2 ? [...list, ALL] : list) {
    chrome.contextMenus.create({
      id: `image:${device.id}`,
      parentId: ROOT,
      title: `Send billede til ${device.all ? "alle enheder" : device.name}${device.online ? "" : "  (offline)"}`,
      contexts: ["image"],
    });
  }
  chrome.contextMenus.create({
    id: "h4xtor-image-separator",
    parentId: ROOT,
    type: "separator",
    contexts: ["image"],
  });
  if (list.length >= 2) {
    chrome.contextMenus.create({
      id: `device:${ALL.id}`,
      parentId: ROOT,
      title: ALL.name,
      contexts: CONTEXTS,
    });
    chrome.contextMenus.create({
      id: "h4xtor-separator",
      parentId: ROOT,
      type: "separator",
      contexts: CONTEXTS,
    });
  }
  for (const device of list) {
    chrome.contextMenus.create({
      id: `device:${device.id}`,
      parentId: ROOT,
      title: `${device.name}${device.online ? "" : "  (offline)"}`,
      contexts: CONTEXTS,
    });
  }
}

function describe(kind) {
  return { link: "Link", text: "Tekst", "file-url": "Billede" }[kind] || "Indhold";
}

async function notify(title, message) {
  try {
    await chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon128.png",
      title,
      message,
      priority: 0,
    });
  } catch (error) {
    // Notifications may be disabled; ignore.
  }
}

async function deliver(deviceId, deviceName, kind, value) {
  if (!value || (kind !== "text" && !/^https?:\/\//i.test(value))) {
    await notify(
      "Kan ikke sendes",
      kind === "file-url"
        ? "Billedet kan ikke hentes herfra. Åbn det på en ny fane, og prøv igen."
        : "Kun almindelige web-links kan sendes.",
    );
    return;
  }
  try {
    await chrome.action.setBadgeBackgroundColor({ color: "#C6613F" });
    await chrome.action.setBadgeText({ text: "…" });
    if (deviceId === ALL.id) {
      let list = [];
      try {
        list = await devices();
      } catch (error) {
        // Only used to say "offline" instead of the raw error.
      }
      const summary = summarize(await sendAll(kind, value), list);
      await chrome.action.setBadgeText({ text: summary.failed ? "!" : "✓" });
      await notify(`${describe(kind)}: ${summary.text}`, value.slice(0, 120));
    } else {
      await send(deviceId, kind, value);
      await chrome.action.setBadgeText({ text: "✓" });
      await notify(`${describe(kind)} sendt til ${deviceName}`, value.slice(0, 120));
    }
  } catch (error) {
    await chrome.action.setBadgeText({ text: "!" });
    await notify("Kunne ikke sende", error.message);
  } finally {
    setTimeout(() => chrome.action.setBadgeText({ text: "" }), 2500);
  }
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const [prefix, ...rest] = String(info.menuItemId).split(":");
  if (prefix !== "device" && prefix !== "image") return;
  const deviceId = rest.join(":");
  const [kind, value] = payloadFor(info, tab, prefix === "image");
  let name = deviceId === ALL.id ? ALL.name : "enheden";
  try {
    const list = await devices();
    name = (list.find((d) => d.id === deviceId) || {}).name || name;
  } catch (error) {
    // Name is cosmetic.
  }
  await chrome.storage.local.set({ deviceId });
  await deliver(deviceId, name, kind, value);
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "send-tab") return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  try {
    const device = await chosenDevice(await devices());
    if (!device) throw new Error("Ingen forbundne enheder.");
    await deliver(device.id, device.name, "link", tab.url);
  } catch (error) {
    await notify("Kunne ikke sende", error.message);
  }
});

chrome.runtime.onInstalled.addListener(() => {
  rebuildMenus();
  chrome.alarms.create("refresh-menus", { periodInMinutes: 1 });
});
chrome.runtime.onStartup.addListener(rebuildMenus);
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "refresh-menus") rebuildMenus();
});
chrome.runtime.onMessage.addListener((message, _sender, reply) => {
  if (message && message.type === "rebuild-menus") {
    rebuildMenus().then(() => reply({ ok: true }));
    return true;
  }
  return false;
});
