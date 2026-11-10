// TeleCraft muharriri: a Telegram Mini App for building a bot by tapping what its users will see.
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) { tg.ready(); tg.expand(); try { tg.setHeaderColor && tg.setHeaderColor("bg_color"); } catch (_) { /* older clients */ } }
const initData = (tg && tg.initData) || "";

/* ------------------------------------------------------------------ small helpers */
const SVG_NS = "http://www.w3.org/2000/svg";
function icon(name, cls = "") {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", `i ${cls}`.trim());
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "value" || k === "disabled" || k === "checked") el[k] = v;
    else if (k.startsWith("aria-") || k.startsWith("data-")) el.setAttribute(k, String(v));
    else if (v !== false) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const haptic = (kind = "light") => { try { tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred(kind); } catch (_) { /* optional */ } };
const notify = (kind) => { try { tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred(kind); } catch (_) { /* optional */ } };

let toastTimer;
function toast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = `show${isError ? " err" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = ""; }, isError ? 4200 : 1900);
  if (isError) notify("error");
}

function applyScheme() {
  const scheme = (tg && tg.colorScheme) || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.scheme = scheme;
}
applyScheme();
if (tg) tg.onEvent("themeChanged", applyScheme);
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyScheme);

/* ------------------------------------------------------------------ API */
class ApiError extends Error { constructor(message, status) { super(message); this.status = status; } }

async function api(method, path, body, form) {
  const headers = { Authorization: `tma ${initData}` };
  let payload;
  if (form) payload = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
  let res;
  try { res = await fetch(`/api/v1${path}`, { method, headers, body: payload }); }
  catch (_) { throw new ApiError("Internet aloqasi yo‘q. Qayta urinib ko‘ring.", 0); }
  if (res.status === 204) return null;
  const type = res.headers.get("content-type") || "";
  const data = type.includes("json") ? await res.json() : await res.blob();
  if (!res.ok) {
    let msg = "Saqlab bo‘lmadi. Qayta urinib ko‘ring.";
    if (data && typeof data.detail === "string") msg = data.detail;
    else if (data && Array.isArray(data.detail)) msg = "Kiritilgan ma‘lumot noto‘g‘ri. Maydonlarni tekshiring.";
    if (res.status === 401) S.expired = true;
    throw new ApiError(msg, res.status);
  }
  return data;
}

/* ------------------------------------------------------------------ state */
const S = { bots: [], bot: null, menus: [], forms: [], menuId: null, tab: "screens", stats: null, expired: false, loading: true };
const ACTIONS = {
  text:  { title: "Xabar yuborish", hint: "Bot shu matn bilan javob beradi", icon: "text" },
  menu:  { title: "Boshqa ekranni ochish", hint: "Mijoz yangi menyuga o‘tadi", icon: "screen" },
  link:  { title: "Havolani ochish", hint: "Sayt, kanal yoki profil", icon: "link" },
  form:  { title: "Forma to‘ldirtirish", hint: "Ariza, buyurtma, so‘rovnoma", icon: "form" },
  media: { title: "Fayl yuborish", hint: "Rasm, video, PDF yoki audio", icon: "image" },
  admin: { title: "Adminga yozdirish", hint: "Mijoz xabari sizga yetib boradi", icon: "user" },
};
const BADGE = { link: "out", menu: "screen", form: "form", media: "image", admin: "user" };
const FIELD_TYPES = {
  text: { title: "Matn", icon: "text" }, number: { title: "Raqam", icon: "hash" }, phone: { title: "Telefon", icon: "phone" },
  email: { title: "Email", icon: "mail" }, choice: { title: "Tanlov", icon: "list" }, photo: { title: "Rasm", icon: "image" },
  location: { title: "Lokatsiya", icon: "pin" },
};
const MEDIA_NAMES = { photo: "Rasm", video: "Video", document: "Fayl", audio: "Audio", voice: "Ovozli xabar", animation: "GIF" };

const currentMenu = () => S.menus.find((m) => m.id === S.menuId) || S.menus[0] || null;
function replaceMenu(menu) {
  const i = S.menus.findIndex((m) => m.id === menu.id);
  if (i >= 0) S.menus[i] = menu; else S.menus.push(menu);
}

async function loadBots() {
  S.bots = await api("GET", "/bots");
  if (!S.bots.length) { S.bot = null; return; }
  let saved = null;
  try { saved = Number(localStorage.getItem("tc.bot")); } catch (_) { /* storage may be blocked */ }
  await selectBot(S.bots.find((b) => b.id === saved) || S.bots[0]);
}
async function selectBot(bot) {
  const data = await api("GET", `/bots/${bot.id}`);
  S.bot = data.bot; S.menus = data.menus; S.forms = data.forms; S.stats = null;
  S.menuId = (S.menus.find((m) => m.is_start) || S.menus[0] || {}).id || null;
  try { localStorage.setItem("tc.bot", String(bot.id)); } catch (_) { /* optional */ }
}
async function reloadBot() {
  const data = await api("GET", `/bots/${S.bot.id}`);
  S.bot = data.bot; S.menus = data.menus; S.forms = data.forms;
  if (!S.menus.some((m) => m.id === S.menuId)) S.menuId = (S.menus[0] || {}).id || null;
}

/* ------------------------------------------------------------------ Telegram-flavoured HTML in the preview */
const TAG_MAP = { b: "strong", strong: "strong", i: "em", em: "em", u: "u", ins: "u", s: "s", strike: "s", del: "s", code: "code", pre: "pre", blockquote: "blockquote" };
function renderTelegramHtml(target, source) {
  const doc = new DOMParser().parseFromString(`<body>${source}</body>`, "text/html");
  const walk = (node, parent) => {
    for (const child of node.childNodes) {
      if (child.nodeType === 3) { parent.append(document.createTextNode(child.nodeValue)); continue; }
      if (child.nodeType !== 1) continue;
      const tag = child.tagName.toLowerCase();
      let el = null;
      if (TAG_MAP[tag]) el = document.createElement(TAG_MAP[tag]);
      else if (tag === "tg-spoiler") { el = document.createElement("span"); el.className = "spoiler"; }
      else if (tag === "a") {
        const href = child.getAttribute("href") || "";
        el = document.createElement("a");
        if (/^(https?:|tg:)/i.test(href)) el.setAttribute("href", href);
        el.setAttribute("tabindex", "-1");
      }
      walk(child, el || parent);
      if (el) parent.append(el);
    }
  };
  walk(doc.body, target);
}

/* ------------------------------------------------------------------ sheets (bottom panels) */
const sheets = [];
function syncBackButton() {
  if (!tg || !tg.BackButton) return;
  if (sheets.length) tg.BackButton.show(); else tg.BackButton.hide();
}
if (tg && tg.BackButton) tg.BackButton.onClick(() => { const top = sheets[sheets.length - 1]; if (top) top.close(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && sheets.length) sheets[sheets.length - 1].close(); });

function openSheet({ title, body, foot, tall = false }) {
  const scrim = h("div", { class: "scrim" });
  const sheet = h("div", { class: `sheet${tall ? " tall" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": title },
    h("div", { class: "sheet-head" },
      h("h3", { text: title }),
      h("button", { class: "ghost", "aria-label": "Yopish", onClick: () => handle.close() }, icon("close"))),
    h("div", { class: "sheet-body" }, body),
    foot ? h("div", { class: "sheet-foot" }, foot) : null);
  const handle = {
    el: sheet,
    close() {
      const i = sheets.indexOf(handle);
      if (i >= 0) sheets.splice(i, 1);
      scrim.remove(); sheet.remove(); syncBackButton();
    },
  };
  scrim.addEventListener("click", () => handle.close());
  scrim.style.zIndex = String(20 + sheets.length * 2);
  sheet.style.zIndex = String(21 + sheets.length * 2);
  document.body.append(scrim, sheet);
  sheets.push(handle);
  syncBackButton();
  return handle;
}

async function guarded(button, task) {
  if (button) button.disabled = true;
  try { return await task(); }
  catch (err) {
    toast(err.message || "Xatolik yuz berdi.", true);
    if (S.expired) renderApp();
    return undefined;
  } finally { if (button) button.disabled = false; }
}

/* ------------------------------------------------------------------ form controls */
function field(label, control, hint) {
  return h("div", { class: "field" }, h("div", { class: "lab" }, label), control, hint ? h("p", { class: "hint", text: hint }) : null);
}
function segmented(options, value, onPick) {
  const wrap = h("div", { class: "seg", role: "group" });
  const paint = (current) => {
    wrap.replaceChildren(...options.map(([val, label]) =>
      h("button", { type: "button", "aria-pressed": val === current, onClick: () => { haptic(); onPick(val); paint(val); } }, label)));
  };
  paint(value);
  return wrap;
}
function switchRow(label, value, onToggle) {
  let on = value;
  const row = h("button", { type: "button", class: "switch", role: "switch", "aria-checked": on, onClick: () => { on = !on; row.setAttribute("aria-checked", String(on)); haptic(); onToggle(on); } },
    h("span", { text: label }), h("span", { class: "track" }));
  return row;
}
function richArea(initial, { rows = 6, placeholder = "" } = {}) {
  const area = h("textarea", { class: "area", rows, placeholder, value: initial || "", spellcheck: "true" });
  const linkInput = h("input", { class: "input", type: "url", placeholder: "https://…", inputmode: "url" });
  const linkRow = h("div", { class: "fmt", hidden: true }, linkInput,
    h("button", { type: "button", onClick: () => { const url = linkInput.value.trim(); if (url) wrap2("<a href=\"" + url.replace(/"/g, "&quot;") + "\">", "</a>"); linkRow.hidden = true; linkInput.value = ""; } }, icon("check")));
  const wrap2 = (open, close) => {
    const { selectionStart: a, selectionEnd: b, value } = area;
    area.value = value.slice(0, a) + open + (value.slice(a, b) || "matn") + close + value.slice(b);
    area.focus();
    area.setSelectionRange(a + open.length, a + open.length + (b - a || 4));
  };
  const toolbar = h("div", { class: "fmt" },
    h("button", { type: "button", "aria-label": "Qalin", onClick: () => wrap2("<b>", "</b>") }, h("b", { text: "B" })),
    h("button", { type: "button", "aria-label": "Qiyshiq", onClick: () => wrap2("<i>", "</i>") }, h("i", { text: "I" })),
    h("button", { type: "button", "aria-label": "Tagiga chizilgan", onClick: () => wrap2("<u>", "</u>") }, h("u", { text: "U" })),
    h("button", { type: "button", "aria-label": "Ustiga chizilgan", onClick: () => wrap2("<s>", "</s>") }, h("s", { text: "S" })),
    h("button", { type: "button", "aria-label": "Kod", onClick: () => wrap2("<code>", "</code>") }, "</>"),
    h("button", { type: "button", "aria-label": "Havola", onClick: () => { linkRow.hidden = !linkRow.hidden; if (!linkRow.hidden) linkInput.focus(); } }, icon("link")));
  return { area, node: h("div", { class: "field" }, toolbar, linkRow, area) };
}
function pickList(items, selected, onPick) {
  const wrap = h("div", { class: "picker", role: "group" });
  const paint = (current) => wrap.replaceChildren(...items.map(([val, label]) =>
    h("button", { type: "button", "aria-pressed": String(val) === String(current), onClick: () => { haptic(); onPick(val); paint(val); } }, label)));
  paint(selected);
  return wrap;
}
function mediaPicker({ current, accept, onFile, onRemove, label = "Rasm, video yoki fayl" }) {
  const input = h("input", { type: "file", accept: accept || "*/*", class: "sr", tabindex: "-1" });
  const status = h("div", { class: "grow" });
  const actions = h("div", { class: "acts" });
  const paint = (media) => {
    status.replaceChildren(h("b", { text: media ? MEDIA_NAMES[media] || "Fayl" : "Biriktirilmagan" }),
      h("small", { text: media ? "Telegram’da saqlangan" : label }));
    actions.replaceChildren(...[
      h("button", { type: "button", class: "btn soft", onClick: () => input.click() }, media ? "Almashtirish" : "Tanlash"),
      media && onRemove ? h("button", { type: "button", class: "ghost", "aria-label": "Olib tashlash", onClick: async () => { await onRemove(); paint(null); } }, icon("trash")) : null,
    ].filter(Boolean));
  };
  paint(current);
  input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    status.replaceChildren(h("b", { text: "Yuklanmoqda…" }), h("small", { text: file.name }));
    try { const media = await onFile(file); paint(media); }
    catch (err) { toast(err.message || "Yuklab bo‘lmadi.", true); paint(current); }
    input.value = "";
  });
  return h("div", { class: "mediabox" }, h("div", { class: "ico" }, icon("image")), status, actions, input);
}

/* ------------------------------------------------------------------ main views */
const app = document.getElementById("app");

function splash(title, text, action) {
  return h("div", { class: "splash" }, h("div", { class: "mark", style: "margin:0 auto;width:52px;height:52px;border-radius:16px" }, starMark()),
    h("h1", { text: title }), h("p", { text }), action || null);
}
function starMark() {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 72 72");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", "M36 6l6 14 14-6-6 14 14 6-14 6 6 14-14-6-6 14-6-14-14 6 6-14-14-6 14-6-6-14 14 6z");
  svg.append(path);
  return svg;
}

function renderApp() {
  if (S.expired) {
    app.replaceChildren(splash("Sessiya tugadi", "Muharrirni yopib, konstruktor botdan qayta oching.", h("button", { class: "btn", onClick: () => (tg ? tg.close() : location.reload()) }, "Yopish")));
    return;
  }
  if (S.loading) { app.replaceChildren(h("div", { class: "splash" }, h("div", { class: "spin" }))); return; }
  if (!S.bot) {
    app.replaceChildren(splash("Hali botingiz yo‘q", "Konstruktor botda tokenni yuboring — bot shu yerda paydo bo‘ladi va uni tahrirlay olasiz.",
      h("button", { class: "btn", onClick: () => (tg ? tg.close() : null) }, "Botga qaytish")));
    return;
  }
  const page = S.tab === "forms" ? formsPage() : S.tab === "stats" ? statsPage() : screensPage();
  app.replaceChildren(header(), page, tabbar());
}

function header() {
  const multi = S.bots.length > 1;
  return h("div", { class: "top" },
    h("div", { class: "mark" }, starMark()),
    h("button", { class: "botpick", disabled: !multi, "aria-label": "Botni almashtirish", onClick: openBotPicker },
      h("div", { style: "min-width:0" },
        h("div", { class: "name", text: S.bot.name }),
        h("div", { class: "sub" }, h("span", { class: `dot${S.bot.connected ? "" : " off"}` }),
          S.bot.connected ? (S.bot.username ? `@${S.bot.username}` : "Ulangan") : "Ulanish kutilmoqda")),
      multi ? icon("chev") : null),
    S.bot.link ? h("button", { class: "ghost", "aria-label": "Botni Telegram’da ochish", onClick: () => (tg ? tg.openTelegramLink(S.bot.link) : window.open(S.bot.link, "_blank")) }, icon("out")) : null);
}

function tabbar() {
  const tab = (id, label, ic) => h("button", { class: "tab", "aria-current": S.tab === id, onClick: () => { S.tab = id; haptic(); renderApp(); if (id === "stats") loadStats(); } }, icon(ic), label);
  return h("nav", { class: "tabbar", "aria-label": "Bo‘limlar" }, tab("screens", "Ekranlar", "screen"), tab("forms", "Formalar", "form"), tab("stats", "Auditoriya", "chart"));
}

function openBotPicker() {
  const sheet = openSheet({
    title: "Botni tanlang",
    body: h("div", { class: "list" }, S.bots.map((b) => h("button", { class: "row", onClick: () => guarded(null, async () => { sheet.close(); S.loading = true; renderApp(); await selectBot(b); S.loading = false; renderApp(); }) },
      h("div", { class: "ico" }, icon("star")), h("div", { class: "grow" }, h("b", { text: b.name }), h("small", { text: b.username ? `@${b.username}` : "Ulanish kutilmoqda" }))))),
  });
}

/* ---- screens tab */
function screensPage() {
  const menu = currentMenu();
  const chips = h("div", { class: "chips", role: "tablist", "aria-label": "Ekranlar" },
    S.menus.map((m) => h("button", { class: "chip", role: "tab", "aria-current": m.id === (menu && menu.id), onClick: () => { S.menuId = m.id; haptic(); renderApp(); } },
      m.is_start ? icon("star") : null, h("span", { text: m.title }))),
    h("button", { class: "chip add", onClick: openNewMenu }, icon("plus"), "Ekran"));
  if (!menu) {
    return h("div", { class: "page" }, chips, h("div", { class: "empty" }, emptyArt(), h("h3", { text: "Birinchi ekranni yarating" }),
      h("p", { text: "Ekran — bot /start bosilganda ko‘rsatadigan xabar va tugmalar." }), h("button", { class: "btn", onClick: openNewMenu }, icon("plus"), "Ekran qo‘shish")));
  }
  const reply = menu.keyboard_mode === "reply";
  const todo = menu.buttons.some((b) => !b.action);
  const keyNodes = menu.buttons.map((b) => keyEl(b, menu));
  const addKey = h("button", { class: "key add", onClick: () => openNewButton(menu) }, icon("plus"), h("span", { text: "Tugma" }));
  const stage = h("div", { class: "stage" },
    h("div", { class: "stage-bar" }, h("div", { class: "avatar", text: (S.bot.name || "B").slice(0, 1).toUpperCase() }), h("div", {}, h("b", { text: S.bot.name }), h("small", { text: "bot" }))),
    h("div", { class: "chat" },
      h("div", { class: "bubble-wrap" },
        bubbleEl(menu),
        h("div", { class: "edit-hint", text: "Xabarni tahrirlash uchun bosing" }),
        reply ? null : h("div", { class: `keys c${menu.columns}` }, keyNodes, addKey))),
    reply ? h("div", { class: "replykb", style: `grid-template-columns:repeat(${menu.columns},1fr)` }, keyNodes.map((n) => n.cloneNode(true)).length ? keyNodes : null, addKey.cloneNode(true)) : null);
  if (reply) {
    // cloneNode drops listeners: rebuild the keyboard keys properly.
    const kb = stage.querySelector(".replykb");
    kb.replaceChildren(...menu.buttons.map((b) => keyEl(b, menu)), h("button", { class: "key add", onClick: () => openNewButton(menu) }, icon("plus"), h("span", { text: "Tugma" })));
  }
  return h("div", { class: "page", style: "padding-left:0;padding-right:0" }, chips,
    h("div", { class: "stage-wrap" }, stage),
    h("div", { class: "legend" },
      h("span", { text: reply ? "Pastki klaviatura rejimi" : "Tugmalar xabar ostida" }),
      todo ? h("span", {}, h("i"), "Punktir — tugma bosilganda nima bo‘lishi tanlanmagan") : null));
}

function bubbleEl(menu) {
  const text = h("div", { class: "text" });
  if (menu.message_text && menu.message_text.trim()) renderTelegramHtml(text, menu.message_text);
  else text.append(h("span", { class: "placeholder", text: "Xabar matnini yozing" }));
  return h("button", { class: `bubble${menu.media_type ? " has-media" : ""}`, "aria-label": "Xabarni tahrirlash", onClick: () => openMenuSheet(menu) },
    menu.media_type ? h("div", { class: "media" }, icon("image"), MEDIA_NAMES[menu.media_type] || "Fayl") : null, text);
}

function keyEl(button, menu) {
  const lead = button.kind === "contact" ? icon("phone") : button.kind === "location" ? icon("pin") : null;
  const badge = button.action && BADGE[button.action.type] && menu.keyboard_mode === "inline" ? h("span", { class: "badge" }, icon(BADGE[button.action.type])) : null;
  return h("button", { class: `key${button.action ? "" : " todo"}`, onClick: () => openButtonSheet(button, menu) }, lead, h("span", { text: button.text }), badge);
}
function emptyArt() {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "big"); svg.setAttribute("viewBox", "0 0 72 72");
  const p = document.createElementNS(SVG_NS, "path");
  p.setAttribute("d", "M36 6l6 14 14-6-6 14 14 6-14 6 6 14-14-6-6 14-6-14-14 6 6-14-14-6 14-6-6-14 14 6z");
  svg.append(p);
  return svg;
}

/* ---- sheet: new screen */
function openNewMenu() {
  const input = h("input", { class: "input", placeholder: "Masalan: Narxlar", maxlength: "60", autofocus: true });
  const create = h("button", { class: "btn", onClick: () => guarded(create, async () => {
    const title = input.value.trim();
    if (!title) { toast("Ekran nomini yozing.", true); return; }
    const menu = await api("POST", `/bots/${S.bot.id}/menus`, { title });
    replaceMenu(menu); S.menuId = menu.id; sheet.close(); renderApp(); notify("success");
    openMenuSheet(menu);
  }) }, "Yaratish");
  const sheet = openSheet({ title: "Yangi ekran", body: [field("Ekran nomi", input, "Bu nomni faqat siz ko‘rasiz.")], foot: [create] });
  setTimeout(() => input.focus(), 120);
}

/* ---- sheet: edit screen (message, media, layout) */
function openMenuSheet(menu) {
  const draft = { title: menu.title, keyboard_mode: menu.keyboard_mode, columns: menu.columns };
  const title = h("input", { class: "input", value: menu.title, maxlength: "60" });
  const rich = richArea(menu.message_text || "", { rows: 7, placeholder: "Mijoz ko‘radigan xabar. Savol bering yoki nima qila olishingizni yozing." });
  const media = mediaPicker({
    current: menu.media_type, accept: "image/*,video/*,audio/*,application/pdf,.gif",
    onFile: async (file) => { const form = new FormData(); form.append("file", file); const updated = await api("POST", `/menus/${menu.id}/media`, undefined, form); replaceMenu(updated); renderApp(); return updated.media_type; },
    onRemove: async () => { const updated = await api("PATCH", `/menus/${menu.id}`, { remove_media: true }); replaceMenu(updated); renderApp(); },
  });
  const save = h("button", { class: "btn", onClick: () => guarded(save, async () => {
    const updated = await api("PATCH", `/menus/${menu.id}`, { title: title.value.trim() || menu.title, message_text: rich.area.value, keyboard_mode: draft.keyboard_mode, columns: draft.columns });
    replaceMenu(updated); sheet.close(); renderApp(); toast("Saqlandi"); notify("success");
  }) }, "Saqlash");
  const foot = [save];
  if (!menu.is_start) {
    foot.unshift(h("button", { class: "btn danger icon", "aria-label": "Ekranni o‘chirish", onClick: () => confirmDelete(`“${menu.title}” ekrani`, async () => {
      await api("DELETE", `/menus/${menu.id}`); await reloadBot(); sheet.close(); renderApp(); toast("O‘chirildi");
    }) }, icon("trash")));
  }
  const sheet = openSheet({
    title: menu.is_start ? "Bosh ekran" : "Ekran", foot, tall: true,
    body: [
      field("Mijozga ko‘rinadigan xabar", rich.node, menu.is_start ? "Bot /start bosilganda shu xabarni yuboradi." : null),
      field("Media", media, "Rasm yoki video xabarning tepasida chiqadi. Faylni bot orqali sizga yuborib, so‘ng o‘chiramiz: avval botga /start yozgan bo‘lishingiz kerak."),
      field("Tugmalar qayerda ko‘rinsin", segmented([["inline", "Xabar ostida"], ["reply", "Pastki klaviatura"]], draft.keyboard_mode, (v) => { draft.keyboard_mode = v; })),
      field("Qatorda nechta tugma", segmented([[1, "1 ta"], [2, "2 ta"]], draft.columns, (v) => { draft.columns = v; })),
      field("Ekran nomi", title, "Muharrirda ekranni topish uchun. Mijoz ko‘rmaydi."),
    ],
  });
}

function confirmDelete(what, task) {
  const go = h("button", { class: "btn danger", onClick: () => guarded(go, async () => { await task(); sheet.close(); }) }, "Ha, o‘chirish");
  const sheet = openSheet({ title: "O‘chirishni tasdiqlang", body: [h("p", { text: `${what} o‘chiriladi. Buni qaytarib bo‘lmaydi.` })], foot: [h("button", { class: "btn line", onClick: () => sheet.close() }, "Bekor qilish"), go] });
}

/* ---- sheet: new button */
function openNewButton(menu) {
  const input = h("input", { class: "input", placeholder: "Masalan: Narxlar", maxlength: "64" });
  let kind = "normal";
  const kinds = menu.keyboard_mode === "reply"
    ? field("Turi", segmented([["normal", "Oddiy"], ["contact", "Kontakt so‘rash"], ["location", "Lokatsiya so‘rash"]], kind, (v) => { kind = v; if (v !== "normal" && !input.value) input.value = v === "contact" ? "Raqamimni yuborish" : "Lokatsiyamni yuborish"; }))
    : null;
  const create = h("button", { class: "btn", onClick: () => guarded(create, async () => {
    const text = input.value.trim();
    if (!text) { toast("Tugma yozuvini kiriting.", true); return; }
    const button = await api("POST", `/menus/${menu.id}/buttons`, { text, kind });
    menu.buttons.push(button); sheet.close(); renderApp(); notify("success");
    openButtonSheet(button, menu);
  }) }, "Qo‘shish");
  const sheet = openSheet({ title: "Yangi tugma", body: [field("Tugma yozuvi", input), kinds], foot: [create] });
  setTimeout(() => input.focus(), 120);
}

/* ---- sheet: edit button + what it does */
function openButtonSheet(button, menu) {
  const state = { type: button.action ? button.action.type : null, value: button.action ? button.action.value : "" };
  const text = h("input", { class: "input", value: button.text, maxlength: "64" });
  const detail = h("div", { class: "field" });
  const choiceWrap = h("div", { class: "choices", role: "group" });
  let textRich = null; let caption = null; let pendingFile = null;

  const paintChoices = () => choiceWrap.replaceChildren(...Object.entries(ACTIONS).map(([type, meta]) =>
    h("button", { type: "button", class: "choice", "aria-pressed": state.type === type, onClick: () => { state.type = type; if (button.action && button.action.type !== type) state.value = ""; haptic(); paintChoices(); paintDetail(); } },
      h("span", { class: "ico" }, icon(meta.icon)), h("span", {}, h("b", { text: meta.title }), h("small", { text: meta.hint })))));

  const paintDetail = () => {
    detail.replaceChildren();
    textRich = null; caption = null;
    if (state.type === "text") {
      textRich = richArea(state.type === (button.action && button.action.type) ? button.action.value : state.value, { rows: 5, placeholder: "Bot shu matn bilan javob beradi" });
      detail.append(field("Javob matni", textRich.node));
    } else if (state.type === "menu") {
      const others = S.menus.filter((m) => m.id !== menu.id);
      detail.append(field("Qaysi ekran ochilsin", others.length ? pickList(others.map((m) => [m.id, m.title]), state.value, (v) => { state.value = String(v); }) : h("div", { class: "note", text: "Boshqa ekran yo‘q. Avval yangi ekran qo‘shing." })));
    } else if (state.type === "link") {
      const input = h("input", { class: "input", type: "url", inputmode: "url", placeholder: "https://…", value: state.value, onInput: () => { state.value = input.value; } });
      detail.append(field("Havola manzili", input, "Sayt, kanal (t.me/…) yoki profil havolasi."));
    } else if (state.type === "form") {
      detail.append(field("Qaysi forma", S.forms.length ? pickList(S.forms.map((f) => [f.id, f.title]), state.value, (v) => { state.value = String(v); }) : h("div", { class: "note", text: "Forma yo‘q. Formalar bo‘limida yarating, keyin bu yerga qaytib tanlang." })));
    } else if (state.type === "media") {
      const has = button.action && button.action.type === "media";
      caption = h("input", { class: "input", placeholder: "Fayl ostidagi izoh (ixtiyoriy)", value: has ? button.action.media.caption : "", maxlength: "1000" });
      const picker = mediaPicker({ current: has ? button.action.media.type : null, onFile: async (file) => { pendingFile = file; return guessKind(file); } });
      detail.append(field("Yuboriladigan fayl", picker, "Saqlash tugmasini bosganda yuklanadi. Avval botga /start yozgan bo‘lishingiz kerak."), field("Izoh", caption));
    } else if (state.type === "admin") {
      const input = h("input", { class: "input", inputmode: "numeric", placeholder: "Masalan: 123456789", value: state.value, onInput: () => { state.value = input.value; } });
      detail.append(field("Adminning Telegram ID raqami", input, "Admin avval botga /start yozishi kerak. ID ni @userinfobot orqali bilib olish mumkin."));
    }
  };
  paintChoices(); paintDetail();

  const move = (delta) => guarded(null, async () => {
    const ids = menu.buttons.map((b) => b.id);
    const i = ids.indexOf(button.id); const j = i + delta;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    replaceMenu(await api("PUT", `/menus/${menu.id}/buttons/order`, { ids }));
    const fresh = S.menus.find((m) => m.id === menu.id); menu.buttons = fresh.buttons; renderApp(); haptic();
  });

  const save = h("button", { class: "btn", onClick: () => guarded(save, async () => {
    const label = text.value.trim();
    if (!label) { toast("Tugma yozuvi bo‘sh bo‘lmasin.", true); return; }
    let updated = button;
    if (label !== button.text) updated = await api("PATCH", `/buttons/${button.id}`, { text: label });
    if (state.type === "media") {
      if (pendingFile) {
        const form = new FormData(); form.append("file", pendingFile); form.append("caption", caption.value);
        updated = await api("POST", `/buttons/${button.id}/media`, undefined, form);
      } else if (!(button.action && button.action.type === "media")) { toast("Yuboriladigan faylni tanlang.", true); return; }
    } else if (state.type) {
      const value = state.type === "text" ? textRich.area.value : String(state.value || "").trim();
      if (!value) { toast("Amal uchun ma‘lumot kiriting.", true); return; }
      updated = await api("PATCH", `/buttons/${button.id}`, { action: { type: state.type, value } });
    }
    const i = menu.buttons.findIndex((b) => b.id === button.id); if (i >= 0) menu.buttons[i] = updated;
    sheet.close(); renderApp(); toast("Saqlandi"); notify("success");
  }) }, "Saqlash");

  const del = h("button", { class: "btn danger icon", "aria-label": "Tugmani o‘chirish", onClick: () => confirmDelete(`“${button.text}” tugmasi`, async () => {
    await api("DELETE", `/buttons/${button.id}`); menu.buttons = menu.buttons.filter((b) => b.id !== button.id); sheet.close(); renderApp(); toast("O‘chirildi");
  }) }, icon("trash"));

  const shareNote = button.kind !== "normal" ? h("div", { class: "note", text: button.kind === "contact" ? "Mijoz bu tugmani bosganda telefon raqamini yuboradi. Raqam sizga keladi; pastda esa unga nima javob berilishini tanlang." : "Mijoz bu tugmani bosganda joylashuvini yuboradi. Joylashuv sizga keladi; pastda esa unga nima javob berilishini tanlang." }) : null;
  const sheet = openSheet({
    title: "Tugma", tall: true, foot: [del, save],
    body: [field("Tugma yozuvi", text), shareNote, field("Bosilganda nima bo‘lsin?", choiceWrap), detail,
      h("div", { class: "field" }, h("div", { class: "lab", text: "Tartib" }), h("div", { class: "fmt" },
        h("button", { type: "button", "aria-label": "Oldinga", onClick: () => move(-1) }, icon("up")), h("button", { type: "button", "aria-label": "Keyinga", onClick: () => move(1) }, icon("down"))))],
  });
}
function guessKind(file) {
  const t = file.type || "";
  if (t === "image/gif") return "animation";
  if (/^image\/(jpeg|png|webp)$/.test(t)) return "photo";
  if (t.startsWith("video/")) return "video";
  if (t.startsWith("audio/")) return "audio";
  return "document";
}

/* ---- forms tab */
function formsPage() {
  const list = S.forms.map((f) => h("button", { class: "row", onClick: () => openFormSheet(f) },
    h("div", { class: "ico" }, icon("form")), h("div", { class: "grow" }, h("b", { text: f.title }), h("small", { text: `${f.fields.length} savol · ${f.submissions} javob` })), icon("chev")));
  return h("div", { class: "page" }, h("h2", { text: "Formalar" }),
    h("p", { class: "lead", text: "Bot mijozdan savollar so‘rab, javoblarni sizga yetkazadi: ariza, buyurtma, so‘rovnoma." }),
    list.length ? h("div", { class: "list" }, list) : h("div", { class: "empty" }, emptyArt(), h("h3", { text: "Hali forma yo‘q" }), h("p", { text: "Birinchi formani yarating, so‘ng tugmaga ulang." })),
    h("div", { style: "margin-top:16px" }, h("button", { class: "btn block", onClick: openNewForm }, icon("plus"), "Yangi forma")));
}
function openNewForm() {
  const input = h("input", { class: "input", placeholder: "Masalan: Ariza", maxlength: "100" });
  const create = h("button", { class: "btn", onClick: () => guarded(create, async () => {
    const title = input.value.trim(); if (!title) { toast("Forma nomini yozing.", true); return; }
    const form = await api("POST", `/bots/${S.bot.id}/forms`, { title }); S.forms.push(form); sheet.close(); renderApp(); openFormSheet(form);
  }) }, "Yaratish");
  const sheet = openSheet({ title: "Yangi forma", body: [field("Forma nomi", input)], foot: [create] });
  setTimeout(() => input.focus(), 120);
}

function openFormSheet(original) {
  const form = JSON.parse(JSON.stringify(original));
  const title = h("input", { class: "input", value: form.title, maxlength: "100" });
  const intro = richArea(form.intro_text || "", { rows: 3, placeholder: "Savollardan oldin ko‘rsatiladi (ixtiyoriy)" });
  const final = richArea(form.final_message || "", { rows: 3, placeholder: "Rahmat! Arizangiz qabul qilindi." });
  const questions = h("div", { class: "sub-list" });
  const paint = () => questions.replaceChildren(
    ...form.fields.map((q, i) => h("button", { class: "qrow", onClick: () => openQuestionSheet(q, () => paint(), () => { form.fields.splice(i, 1); paint(); }, (d) => { const j = i + d; if (j >= 0 && j < form.fields.length) { [form.fields[i], form.fields[j]] = [form.fields[j], form.fields[i]]; paint(); } }) },
      h("span", { class: "ico" }, icon(FIELD_TYPES[q.type].icon)), h("span", { class: "grow" }, h("b", { text: q.label }), h("small", { text: `${FIELD_TYPES[q.type].title}${q.required ? "" : " · ixtiyoriy"}` })), icon("chev"))),
    form.fields.length >= 20 ? null : h("button", { class: "btn soft block", onClick: () => { const q = { label: "", prompt: "", type: "text", required: true, options: null }; openQuestionSheet(q, () => { form.fields.push(q); paint(); }, null, null, true); } }, icon("plus"), "Savol qo‘shish"));
  paint();
  const save = h("button", { class: "btn", onClick: () => guarded(save, async () => {
    const updated = await api("PUT", `/forms/${form.id}`, { title: title.value.trim() || form.title, intro_text: intro.area.value, final_message: final.area.value, notify_admins: form.notify_admins, fields: form.fields });
    const i = S.forms.findIndex((f) => f.id === form.id); S.forms[i] = updated; sheet.close(); renderApp(); toast("Saqlandi"); notify("success");
  }) }, "Saqlash");
  const del = h("button", { class: "btn danger icon", "aria-label": "Formani o‘chirish", onClick: () => confirmDelete(`“${form.title}” formasi va barcha javoblari`, async () => {
    await api("DELETE", `/forms/${form.id}`); await reloadBot(); sheet.close(); renderApp(); toast("O‘chirildi");
  }) }, icon("trash"));
  const answers = h("button", { class: "btn line block", onClick: () => openSubmissions(original) }, icon("download"), `Javoblar (${original.submissions})`);
  const sheet = openSheet({ title: "Forma", tall: true, foot: [del, save], body: [
    field("Forma nomi", title), field("Savollar", questions), field("Boshlashdan oldin matn", intro.node), field("Tugagach xabar", final.node),
    switchRow("Yangi javob kelganda menga xabar yuborilsin", form.notify_admins, (v) => { form.notify_admins = v; }), answers] });
}

function openQuestionSheet(q, onDone, onDelete, onMove, isNew = false) {
  const draft = { ...q };
  const label = h("input", { class: "input", value: q.label, maxlength: "100", placeholder: "Masalan: Ism" });
  const prompt = h("input", { class: "input", value: q.prompt, maxlength: "500", placeholder: "Masalan: Ismingiz nima?" });
  const options = h("textarea", { class: "area", rows: 4, placeholder: "Har bir variant yangi qatorda", value: (q.options || []).join("\n") });
  const optionsField = field("Variantlar", options, "2 tadan 12 tagacha.");
  const types = h("div", { class: "choices", role: "group" });
  const paintTypes = () => {
    types.replaceChildren(...Object.entries(FIELD_TYPES).map(([type, meta]) => h("button", { type: "button", class: "choice", "aria-pressed": draft.type === type, onClick: () => { draft.type = type; optionsField.hidden = type !== "choice"; haptic(); paintTypes(); } },
      h("span", { class: "ico" }, icon(meta.icon)), h("span", {}, h("b", { text: meta.title })))));
  };
  paintTypes(); optionsField.hidden = draft.type !== "choice";
  const done = h("button", { class: "btn", onClick: () => {
    const p = prompt.value.trim(); if (!p) { toast("Savol matnini yozing.", true); return; }
    q.prompt = p; q.label = label.value.trim() || p.slice(0, 40); q.type = draft.type; q.required = draft.required;
    q.options = draft.type === "choice" ? options.value.split("\n").map((s) => s.trim()).filter(Boolean) : null;
    if (q.type === "choice" && q.options.length < 2) { toast("Tanlov uchun kamida 2 ta variant kerak.", true); return; }
    sheet.close(); onDone();
  } }, isNew ? "Qo‘shish" : "Tayyor");
  const foot = [done];
  if (onDelete) foot.unshift(h("button", { class: "btn danger icon", "aria-label": "Savolni o‘chirish", onClick: () => { sheet.close(); onDelete(); } }, icon("trash")));
  const sheet = openSheet({ title: "Savol", tall: true, foot, body: [
    field("Savol matni", prompt, "Mijoz aynan shuni ko‘radi."), field("Javobda ko‘rinadigan nom", label, "Sizga kelgan javob va CSV ustunida chiqadi."),
    field("Javob turi", types), optionsField,
    switchRow("Javob majburiy", draft.required, (v) => { draft.required = v; }),
    onMove ? h("div", { class: "field" }, h("div", { class: "lab", text: "Tartib" }), h("div", { class: "fmt" },
      h("button", { type: "button", "aria-label": "Yuqoriga", onClick: () => { sheet.close(); onMove(-1); } }, icon("up")), h("button", { type: "button", "aria-label": "Pastga", onClick: () => { sheet.close(); onMove(1); } }, icon("down")))) : null] });
}

function openSubmissions(form) {
  const body = h("div", { class: "sub-list" }, h("div", { class: "spin" }));
  const csv = h("button", { class: "btn", onClick: () => guarded(csv, async () => {
    const blob = await api("GET", `/forms/${form.id}/export.csv`);
    const url = URL.createObjectURL(blob); const a = h("a", { href: url, download: `${form.title.replace(/[^\w-]+/g, "_") || "forma"}.csv` }); document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 4000);
  }) }, icon("download"), "CSV yuklab olish");
  openSheet({ title: form.title, tall: true, body: [body], foot: [csv] });
  guarded(null, async () => {
    const rows = await api("GET", `/forms/${form.id}/submissions?limit=30`);
    if (!rows.length) { body.replaceChildren(h("div", { class: "empty" }, emptyArt(), h("h3", { text: "Hali javob yo‘q" }), h("p", { text: "Mijozlar formani to‘ldirgach, javoblar shu yerda paydo bo‘ladi." }))); return; }
    body.replaceChildren(...rows.map((r) => h("div", { class: "answer" },
      h("h4", { text: `${r.full_name || "Noma‘lum"}${r.username ? ` · @${r.username}` : ""}` }),
      h("dl", {}, r.answers.flatMap((a) => [h("dt", { text: a.label }), h("dd", { text: a.value === null ? "—" : a.type === "photo" ? "rasm" : String(a.value) })])))));
  });
}

/* ---- stats tab */
async function loadStats() {
  if (S.stats || !S.bot) return;
  try { S.stats = await api("GET", `/bots/${S.bot.id}/stats`); } catch (err) { toast(err.message, true); return; }
  if (S.tab === "stats") renderApp();
}
function statsPage() {
  const s = S.stats;
  if (!s) return h("div", { class: "page" }, h("div", { class: "splash", style: "min-height:50dvh" }, h("div", { class: "spin" })));
  if (!s.total) {
    return h("div", { class: "page" }, h("h2", { text: "Auditoriya" }), h("div", { class: "empty" }, emptyArt(), h("h3", { text: "Hali hech kim yozmagan" }),
      h("p", { text: "Botga /start yuboring yoki havolani ulashing — foydalanuvchilar shu yerda hisoblanadi." }),
      S.bot.link ? h("button", { class: "btn", onClick: () => (tg ? tg.openTelegramLink(S.bot.link) : window.open(S.bot.link, "_blank")) }, icon("out"), "Botni ochish") : null));
  }
  const max = Math.max(s.new_30d, s.active_7d, 1);
  const bar = (label, n, cls = "") => h("div", { class: "bar" }, h("span", { text: label }), h("div", { class: "track" }, h("div", { class: `fill ${cls}`, style: `width:${Math.max(3, (n / max) * 100)}%` })), h("b", { text: n }));
  return h("div", { class: "page" }, h("h2", { text: "Auditoriya" }),
    h("p", { class: "sentence" }, h("em", { text: s.total }), ` kishi botdan foydalangan, `, h("em", { text: s.active }), " tasiga hozir ham yozish mumkin."),
    h("div", { class: "bars" }, bar("Yangi, 24 soat", s.new_24h), bar("Yangi, 7 kun", s.new_7d), bar("Yangi, 30 kun", s.new_30d),
      bar("Faol, 24 soat", s.active_24h, "t"), bar("Faol, 7 kun", s.active_7d, "t")),
    h("div", { class: "facts" },
      h("div", { class: "fact" }, h("b", { text: s.submissions }), h("small", { text: "forma javobi" })),
      h("div", { class: "fact" }, h("b", { text: s.blocked }), h("small", { text: "botni bloklagan" })),
      h("div", { class: "fact" }, h("b", { text: s.broadcast_messages }), h("small", { text: "xabar yuborilgan" })),
      h("div", { class: "fact" }, h("b", { text: s.sources.length }), h("small", { text: "havola manbasi" }))),
    s.sources.length ? h("div", { class: "bars", style: "margin-top:14px" }, ...s.sources.map(([name, n]) => h("div", { class: "bar", style: "grid-template-columns:1fr 40px" }, h("span", { text: name }), h("b", { text: n })))) : null,
    h("div", { class: "note", style: "margin-top:14px", text: "Hammaga xabar yuborish va majburiy obuna sozlamalari hozircha konstruktor botda: Bot boshqaruvi → Broadcast / Majburiy obuna." }));
}

/* ------------------------------------------------------------------ boot */
(async function boot() {
  if (!initData) {
    S.loading = false;
    app.replaceChildren(splash("Muharrirni Telegram’da oching", "Bu sahifa konstruktor bot ichida ishlaydi. Botda Bot boshqaruvi → Vizual muharrir tugmasini bosing."));
    return;
  }
  renderApp();
  try { await loadBots(); } catch (err) { if (!S.expired) toast(err.message, true); }
  S.loading = false;
  renderApp();
})();
