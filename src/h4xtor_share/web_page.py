"""The page a phone sees when it opens the h4xtor share link (see web_share.py)."""

PAGE = r"""<!doctype html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="h4xtor share">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#262624">
<link rel="apple-touch-icon" href="/icon.png">
<link rel="icon" href="/icon.png">
<title>h4xtor share</title>
<style>
:root {
  --bg: #FAF9F5; --card: #FFFFFF; --border: #E8E6DC; --text: #141413; --muted: #73726C;
  --accent: #C6613F; --accent-soft: #F5E6DF; --success: #2E8B57; --success-soft: #E3F1E8;
  --danger: #C2412D; --track: #ECEAE2;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #262624; --card: #30302E; --border: #3E3E3A; --text: #F5F4EE; --muted: #A6A39A;
    --accent: #D97757; --accent-soft: #45322A; --success: #5BC38E; --success-soft: #24392D;
    --danger: #EF6B55; --track: #3E3E3A;
  }
}
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
html, body { margin: 0; background: var(--bg); color: var(--text); }
body {
  font: 16px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  padding: max(16px, env(safe-area-inset-top)) 16px max(24px, env(safe-area-inset-bottom));
  max-width: 560px; margin: 0 auto;
}
header { display: flex; align-items: center; gap: 10px; margin: 6px 0 18px; }
header h1 { font: 600 26px Georgia, "Iowan Old Style", serif; margin: 0; flex: 1; }
.status { font-size: 13px; color: var(--muted); display: flex; align-items: center; gap: 6px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--muted); }
.dot.on { background: var(--success); } .dot.off { background: var(--danger); }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 18px;
  padding: 16px; margin-bottom: 14px; }
h2 { font-size: 13px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted);
  margin: 22px 4px 8px; font-weight: 600; }
.big { display: flex; align-items: center; justify-content: center; gap: 10px; width: 100%;
  min-height: 64px; border: 0; border-radius: 16px; background: var(--accent); color: #fff;
  font-weight: 600; font-size: 18px; font-family: inherit; cursor: pointer; }
.big span { font-size: 24px; }
button.soft, button.ghost { border: 0; border-radius: 12px; min-height: 44px; padding: 0 16px;
  font-weight: 600; font-size: 15px; font-family: inherit; cursor: pointer; }
button.soft { background: var(--accent-soft); color: var(--accent); }
button.ghost { background: transparent; color: var(--text); border: 1px solid var(--border); }
textarea { width: 100%; min-height: 96px; border-radius: 12px; border: 1px solid var(--border);
  background: var(--bg); color: var(--text); padding: 12px; font-size: 16px;
  font-family: inherit; resize: vertical; }
.row { display: flex; gap: 8px; align-items: center; margin-top: 10px; }
.row .grow { flex: 1; }
.hint { color: var(--muted); font-size: 13px; margin: 8px 2px 0; }
.item { display: flex; gap: 12px; align-items: center; padding: 10px 0;
  border-top: 1px solid var(--border); }
.item:first-child { border-top: 0; padding-top: 0; }
.thumb { width: 48px; height: 48px; border-radius: 10px; flex: none; display: grid;
  place-items: center; font-size: 22px; background: var(--success-soft); color: var(--success);
  overflow: hidden; }
.thumb.up { background: var(--accent-soft); color: var(--accent); }
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.meta { flex: 1; min-width: 0; }
.name { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { color: var(--muted); font-size: 13px; }
.bar { height: 6px; border-radius: 3px; background: var(--track); margin-top: 6px;
  overflow: hidden; }
.bar i { display: block; height: 100%; width: 0; background: var(--accent);
  transition: width .2s; }
.bar.done i { background: var(--success); } .bar.fail i { background: var(--danger); }
.actions { display: flex; gap: 6px; flex: none; }
.actions a, .actions button { text-decoration: none; display: inline-flex; align-items: center;
  min-height: 40px; padding: 0 12px; border-radius: 10px; font-size: 14px; font-weight: 600;
  background: var(--accent-soft); color: var(--accent); border: 0; font-family: inherit; }
.empty { color: var(--muted); font-size: 14px; }
.clip { white-space: pre-wrap; word-break: break-word; background: var(--bg);
  border-radius: 12px; padding: 12px; margin-top: 10px; max-height: 240px; overflow: auto; }
.toast { position: fixed; left: 16px; right: 16px; bottom: max(16px, env(safe-area-inset-bottom));
  max-width: 528px; margin: 0 auto; background: var(--text); color: var(--bg);
  border-radius: 14px; padding: 14px 16px; font-weight: 600; opacity: 0;
  transform: translateY(10px); transition: .2s; pointer-events: none; }
.toast.show { opacity: 1; transform: none; }
.lock { text-align: center; padding: 48px 12px; }
.lock div { font-size: 48px; }
.new { animation: glow 1.6s ease-out; }
@keyframes glow { from { background: var(--accent-soft); } }
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
[hidden] { display: none !important; }
</style>
</head>
<body>
<header>
  <h1>h4xtor share</h1>
  <div class="status"><i class="dot" id="dot"></i><span id="pc">Forbinder…</span></div>
</header>

<section id="lock" class="card lock" hidden>
  <div>🔒</div>
  <p><b>Linket virker ikke</b></p>
  <p class="hint">Åbn h4xtor share på PC'en → <b>iPhone</b>, slå adgangen til og scan
  QR-koden med kameraet.</p>
</section>

<main id="main" hidden>
  <input type="file" id="files" multiple hidden>
  <button class="big" id="pick"><span>↑</span> Send billeder og filer</button>
  <p class="hint">Vælg fra Fotos, Kamera eller Filer – de lander i PC'ens modtagemappe.</p>
  <div id="uploads"></div>

  <h2>Fra PC'en</h2>
  <div class="card" id="outbox"><p class="empty">Intet endnu. Send filer eller tekst til
  iPhone fra PC'en – de dukker op her med det samme.</p></div>

  <h2>Send tekst eller link</h2>
  <div class="card">
    <textarea id="text" placeholder="Skriv eller indsæt her…"></textarea>
    <div class="row">
      <button class="soft grow" id="send">Send til PC</button>
    </div>
    <p class="hint">Et link åbner i PC'ens browser. Tekst lander i PC'ens udklipsholder.</p>
  </div>

  <h2>PC'ens udklipsholder</h2>
  <div class="card">
    <button class="ghost" id="getclip" style="width:100%">Hent og kopiér</button>
    <div class="clip" id="clip" hidden></div>
  </div>

  <p class="hint" id="tip">Tip: Tryk på <b>Del</b> → <b>Føj til hjemmeskærm</b>, så har du
  h4xtor share som en app.</p>
</main>
<div class="toast" id="toast"></div>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
let key = new URLSearchParams(location.search).get("k") || "";
try {
  if (key) localStorage.setItem("k", key); else key = localStorage.getItem("k") || "";
} catch (e) { /* private mode: the URL key still works */ }

const IMAGE = /\.(jpe?g|png|gif|webp|heic|heif|bmp)$/i;
let known = null;
let toastTimer = 0;

function toast(text) {
  const el = $("toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}
function bytes(n) {
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(1) : n) + " " + units[i];
}
function fileUrl(id, extra) {
  return "/api/files/" + id + "?k=" + encodeURIComponent(key) + (extra || "");
}
async function api(path, options) {
  const opts = options || {};
  opts.headers = Object.assign({ "X-H4xtor-Key": key }, opts.headers || {});
  const response = await fetch(path, opts);
  if (response.status === 401) { locked(); throw new Error("locked"); }
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}
function locked() {
  $("main").hidden = true;
  $("lock").hidden = false;
  $("dot").className = "dot off";
  $("pc").textContent = "Ikke forbundet";
}
function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  area.setSelectionRange(0, text.length);
  const ok = document.execCommand("copy");
  area.remove();
  return ok ? Promise.resolve() : Promise.reject(new Error("copy"));
}

function renderOutbox(items) {
  const box = $("outbox");
  const ids = items.map((item) => item.id).join(",");
  if (known !== null && ids === known.ids) return;
  const before = known === null ? null : known.set;
  const ids2 = items.map((i) => i.id);
  const fresh = new Set(before === null ? [] : ids2.filter((id) => !before.has(id)));
  known = { ids, set: new Set(items.map((i) => i.id)) };
  if (fresh.size) toast(fresh.size === 1 ? "Nyt fra PC'en" : fresh.size + " nye fra PC'en");
  if (!items.length) {
    box.innerHTML = '<p class="empty">Intet endnu. Send filer eller tekst til iPhone fra ' +
      "PC'en – de dukker op her med det samme.</p>";
    return;
  }
  box.textContent = "";
  for (const item of items) {
    const row = document.createElement("div");
    row.className = "item" + (fresh.has(item.id) ? " new" : "");
    const thumb = document.createElement("div");
    thumb.className = "thumb";
    const meta = document.createElement("div");
    meta.className = "meta";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = item.name;
    const sub = document.createElement("div");
    sub.className = "sub";
    const actions = document.createElement("div");
    actions.className = "actions";
    if (item.kind === "text") {
      thumb.textContent = "✎";
      const more = item.text.length > item.name.length;
      const cut = item.text.length > 120 ? "…" : "";
      sub.textContent = more ? item.text.slice(0, 120) + cut : "Tekst";
      const copy = document.createElement("button");
      copy.textContent = "Kopiér";
      copy.onclick = () => copyText(item.text)
        .then(() => toast("Kopieret ✓"), () => toast("Kunne ikke kopiere"));
      actions.appendChild(copy);
    } else {
      sub.textContent = bytes(item.size);
      if (IMAGE.test(item.name)) {
        const img = document.createElement("img");
        img.loading = "lazy";
        img.alt = "";
        img.src = fileUrl(item.id, "&inline=1&preview=1");
        img.onerror = () => { img.remove(); thumb.textContent = "▣"; };
        thumb.appendChild(img);
        const view = document.createElement("a");
        view.href = fileUrl(item.id, "&inline=1");
        view.target = "_blank";
        view.textContent = "Vis";
        actions.appendChild(view);
      } else {
        thumb.textContent = "↓";
      }
      const get = document.createElement("a");
      get.href = fileUrl(item.id);
      get.setAttribute("download", item.name);
      get.textContent = "Hent";
      actions.appendChild(get);
    }
    meta.append(name, sub);
    row.append(thumb, meta, actions);
    box.appendChild(row);
  }
}

async function refresh() {
  if (!key) { locked(); return; }
  try {
    const state = await api("/api/state");
    $("lock").hidden = true;
    $("main").hidden = false;
    $("dot").className = "dot on";
    $("pc").textContent = state.pc;
    renderOutbox(state.outbox);
  } catch (error) {
    if (error.message !== "locked") {
      $("dot").className = "dot off";
      $("pc").textContent = "PC'en svarer ikke";
    }
  }
}

function uploadRow(file) {
  const row = document.createElement("div");
  row.className = "card item";
  row.innerHTML = '<div class="thumb up">↑</div><div class="meta"><div class="name"></div>' +
    '<div class="sub"></div><div class="bar"><i></i></div></div>';
  row.querySelector(".name").textContent = file.name;
  row.querySelector(".sub").textContent = "Venter · " + bytes(file.size);
  $("uploads").prepend(row);
  return row;
}

function upload(file, row) {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    const sub = row.querySelector(".sub");
    const bar = row.querySelector(".bar");
    const started = Date.now();
    xhr.open("POST", "/api/upload?name=" + encodeURIComponent(file.name) + "&size=" + file.size);
    xhr.setRequestHeader("X-H4xtor-Key", key);
    xhr.upload.onprogress = (event) => {
      const done = event.loaded / Math.max(1, file.size);
      bar.firstChild.style.width = Math.round(done * 100) + "%";
      const seconds = (Date.now() - started) / 1000;
      const speed = seconds > 0.3 ? " · " + bytes(event.loaded / seconds) + "/s" : "";
      sub.textContent = Math.round(done * 100) + "% af " + bytes(file.size) + speed;
    };
    xhr.onload = () => {
      if (xhr.status === 401) locked();
      const ok = xhr.status === 200;
      bar.className = "bar " + (ok ? "done" : "fail");
      bar.firstChild.style.width = "100%";
      sub.textContent = ok ? "På PC'en ✓ · " + bytes(file.size) : "Mislykkedes – prøv igen";
      resolve(ok);
    };
    xhr.onerror = () => {
      bar.className = "bar fail";
      sub.textContent = "Mistede forbindelsen til PC'en";
      resolve(false);
    };
    xhr.send(file);
  });
}

$("pick").onclick = () => $("files").click();
$("files").onchange = async () => {
  const files = Array.from($("files").files);
  $("files").value = "";
  const rows = files.map(uploadRow);
  let sent = 0;
  for (let i = 0; i < files.length; i++) {
    if (await upload(files[i], rows[i])) sent++;
  }
  if (!files.length) return;
  toast(sent === files.length ? "Sendt til PC'en ✓" : sent + " af " + files.length + " sendt");
};

$("send").onclick = async () => {
  const text = $("text").value.trim();
  if (!text) { toast("Skriv noget først"); return; }
  try {
    const result = await api("/api/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    $("text").value = "";
    toast(result.kind === "link" ? "Linket åbner på PC'en ✓" : "I PC'ens udklipsholder ✓");
  } catch (error) {
    if (error.message !== "locked") toast("Kunne ikke sende");
  }
};

$("getclip").onclick = async () => {
  try {
    const result = await api("/api/clipboard");
    const box = $("clip");
    box.hidden = false;
    if (!result.text) { box.textContent = "PC'ens udklipsholder er tom."; return; }
    box.textContent = result.text;
    copyText(result.text)
      .then(() => toast("Kopieret ✓"), () => toast("Markér teksten for at kopiere"));
  } catch (error) {
    if (error.message !== "locked") toast("PC'en svarer ikke");
  }
};

if (navigator.standalone) $("tip").hidden = true;
refresh();
setInterval(() => { if (document.visibilityState === "visible") refresh(); }, 2500);
document.addEventListener("visibilitychange", refresh);
</script>
</body>
</html>
"""
