// Platform admin pages of the Mini App (only for ADMIN_IDS); mounted by app.js with its shared helpers.
export function mountAdmin(ctx) {
  const { h, api, toast, openSheet, field, segmented, guarded, money, icon, S, haptic, starMark, KIND_LABEL, renderApp } = ctx;
  const A = { tab: "home", home: null, pays: { status: "pending", items: [], more: false, loaded: false }, cust: { q: "", items: [], more: false, loaded: false },
    bots: { q: "", items: [], more: false, loaded: false }, sys: null };
  const PLAN_NAMES = { free: "Free", start: "Start", pro: "Pro", business: "Business" };
  const PAY_STATUS = { pending: "⏳ Kutilmoqda", approved: "✅ Tasdiqlangan", rejected: "❌ Rad etilgan", cancelled: "Bekor", draft: "Qoralama" };
  const LOG_NAMES = { pay_ok: "To‘lov tasdiqlandi", pay_no: "To‘lov rad etildi", grant: "Tarif berildi", reset_trial: "Sinov tiklandi", message: "Xabar",
    bot_on: "Bot yoqildi", bot_off: "Bot to‘xtatildi", broadcast: "Platforma xabari", backup: "Zaxira" };

  const dt = (iso) => (iso ? new Date(iso).toLocaleString("ru-RU", { timeZone: "Asia/Tashkent", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
  const dd = (iso) => (iso ? new Date(iso).toLocaleDateString("ru-RU", { timeZone: "Asia/Tashkent" }) : "—");
  const debounce = (fn, ms = 350) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };
  const rerender = () => renderApp();

  function adminPage() {
    const tab = (id, label, ic) => h("button", { class: "tab", "aria-current": A.tab === id, onClick: () => { A.tab = id; haptic(); adminLoad(); rerender(); } }, icon(ic), label);
    const body = { home: homePage, pays: paysPage, cust: custPage, bots: botsPage, sys: sysPage }[A.tab]();
    return [h("div", { class: "top" }, h("button", { class: "ghost", "aria-label": "Bosh sahifaga qaytish", onClick: () => { S.admin = false; S.view = "home"; rerender(); } }, icon("chev", "back")),
      h("div", { style: "min-width:0;flex:1" }, h("div", { class: "name", text: "Admin" }), h("div", { class: "sub", text: "Platforma boshqaruvi" })),
      null),
    body, h("nav", { class: "tabbar five", "aria-label": "Admin bo‘limlari" }, tab("home", "Bosh", "chart"), tab("pays", "To‘lovlar", "form"), tab("cust", "Mijozlar", "user"), tab("bots", "Botlar", "screen"), tab("sys", "Tizim", "list"))];
  }

  function adminLoad(force = false) {
    const run = (p) => guarded(null, async () => { await p; rerender(); });
    if (A.tab === "home" && (force || !A.home)) run(api("GET", "/admin/dashboard").then((d) => { A.home = d; }));
    if (A.tab === "pays" && (force || !A.pays.loaded)) run(loadPays(true));
    if (A.tab === "cust" && (force || !A.cust.loaded)) run(loadList("cust", "/admin/customers", true));
    if (A.tab === "bots" && (force || !A.bots.loaded)) run(loadList("bots", "/admin/bots", true));
    if (A.tab === "sys" && (force || !A.sys)) run(api("GET", "/admin/system").then((d) => { A.sys = d; }));
  }
  const loading = () => h("div", { class: "splash", style: "min-height:40dvh" }, h("div", { class: "spin" }));
  const empty = (text) => h("p", { class: "hint", style: "text-align:center;padding:24px 0", text });

  /* ---------------------------------------------------------------- home */
  const bar = (label, n, max, isMoney) => h("div", { class: "bar", style: "grid-template-columns:70px 1fr auto" }, h("span", { text: label }), h("div", { class: "track" }, h("div", { class: "fill", style: `width:${n ? Math.max(3, (n / max) * 100) : 0}%` })), h("b", { text: isMoney ? money(n) : n }));
  function homePage() {
    const d = A.home;
    if (!d) return h("div", { class: "page" }, h("h2", { text: "Bosh sahifa" }), loading());
    const fact = (n, l, wide) => h("div", { class: "fact", style: wide ? "grid-column:1/-1" : null }, h("b", { text: n }), h("small", { text: l }));
    const max = Math.max(1, ...d.revenue.map((x) => x.total));
    const spreadMax = Math.max(1, ...Object.values(d.plans));
    return h("div", { class: "page" }, h("h2", { text: "Bosh sahifa" }),
      h("div", { class: "facts" }, fact(money(d.month_revenue), "Shu oy tushum", true), fact(d.customers, "Mijozlar"), fact(d.bots, `Botlar (${d.active_bots} faol)`),
        fact(d.bot_users, "Bot foydalanuvchilari"), fact(d.licenses, "Alohida to‘langan botlar"),
        h("button", { class: "fact", style: "text-align:left;border:0", onClick: () => { A.tab = "pays"; adminLoad(); rerender(); } }, h("b", { text: d.pending }), h("small", { text: "Kutilayotgan to‘lov" })),
        fact(d.expiring, "7 kunda tugaydi")),
      h("div", { class: "section" }, h("h3", { text: "Tariflar" }),
      h("div", { class: "bars" }, Object.entries(d.plans).map(([code, n]) => bar(PLAN_NAMES[code], n, spreadMax)))),
    h("div", { class: "section" }, h("h3", { text: "Tushum (6 oy)" }),
      h("div", { class: "bars" }, d.revenue.map((x) => bar(x.month, x.total, max, true))),
      h("button", { class: "btn ghost", style: "margin-top:10px", onClick: (e) => guarded(e.currentTarget, () => downloadCsv(d.revenue[d.revenue.length - 1].month)) }, "Shu oy hisoboti (CSV)")));
  }
  async function downloadCsv(month) {
    const blob = await api("GET", `/admin/payments.csv?month=${month}`);
    const a = h("a", { href: URL.createObjectURL(blob), download: `tushum_${month}.csv` });
    document.body.append(a); a.click(); a.remove();
  }

  /* ---------------------------------------------------------------- payments */
  async function loadPays(reset) {
    const p = A.pays, offset = reset ? 0 : p.items.length;
    const data = await api("GET", `/admin/payments?status=${p.status}&offset=${offset}`);
    p.items = reset ? data.items : p.items.concat(data.items); p.more = data.more; p.loaded = true;
  }
  function payRow(p) {
    return h("button", { class: "row", onClick: () => openPayment(p) }, h("div", { class: "ico", text: p.status === "approved" ? "✅" : p.status === "rejected" ? "❌" : "💳" }),
      h("div", { class: "grow" }, h("b", { text: `${money(p.amount)} · ${p.name}` }), h("small", { text: `${p.what} · ${dt(p.created_at)}` })));
  }
  function paysPage() {
    const p = A.pays;
    const chip = (id, label) => h("button", { class: "chip", "aria-current": p.status === id, onClick: () => { p.status = id; p.loaded = false; p.items = []; adminLoad(); rerender(); } }, h("span", { text: label }));
    return h("div", { class: "page" }, h("h2", { text: "To‘lovlar" }),
      h("div", { class: "chips", style: "padding:0 0 10px" }, chip("pending", "Kutilayotgan"), chip("approved", "Tasdiqlangan"), chip("rejected", "Rad etilgan"), chip("all", "Hammasi")),
      !p.loaded ? loading() : !p.items.length ? empty("To‘lov yo‘q.") : h("div", { class: "list" }, p.items.map(payRow)),
      p.more ? h("button", { class: "btn ghost", style: "margin-top:10px", onClick: (e) => guarded(e.currentTarget, async () => { await loadPays(false); rerender(); }) }, "Yana") : null);
  }
  function openPayment(p) {
    const img = h("div", { class: "splash", style: "min-height:160px" }, h("div", { class: "spin" }));
    const reason = h("input", { class: "input", placeholder: "Rad etish sababi (ixtiyoriy)", maxlength: "200" });
    let sheet;
    const decide = (approve) => (e) => guarded(e.currentTarget, async () => {
      await api("POST", `/admin/payments/${p.id}/decide`, { approve, reason: reason.value.trim() || null });
      sheet.close(); toast(approve ? "Tasdiqlandi" : "Rad etildi"); A.home = null; await loadPays(true); rerender();
    });
    const foot = p.status === "pending" ? h("div", { style: "display:grid;gap:8px;width:100%" }, reason, h("div", { class: "facts" },
      h("button", { class: "btn", onClick: decide(true) }, "✅ Tasdiqlash"), h("button", { class: "btn ghost", onClick: decide(false) }, "❌ Rad"))) : null;
    sheet = openSheet({ title: `To‘lov #${p.id}`, tall: true, foot, body: [
      h("div", { class: "row static" }, h("div", { class: "grow" }, h("b", { text: `${money(p.amount)} · ${p.what}` }), h("small", { text: `${p.name} · ${p.tg_user_id}` }))),
      h("p", { class: "hint", text: `${PAY_STATUS[p.status] || p.status} · yuborilgan ${dt(p.created_at)}${p.decided_at ? ` · hal qilingan ${dt(p.decided_at)}` : ""}` }), img] });
    if (p.receipt) api("GET", `/admin/payments/${p.id}/receipt`).then((blob) => {
      img.replaceWith(blob.type.startsWith("image/") ? h("img", { src: URL.createObjectURL(blob), alt: "Chek", style: "width:100%;border-radius:12px" })
        : h("a", { class: "btn ghost", href: URL.createObjectURL(blob), download: `chek_${p.id}` }, "Chekni yuklab olish"));
    }).catch((err) => img.replaceWith(h("p", { class: "hint", text: err.message })));
  }

  /* ---------------------------------------------------------------- customers & bots (searchable lists) */
  async function loadList(key, path, reset) {
    const s = A[key], offset = reset ? 0 : s.items.length;
    const data = await api("GET", `${path}?q=${encodeURIComponent(s.q)}&offset=${offset}`);
    s.items = reset ? data.items : s.items.concat(data.items); s.more = data.more; s.loaded = true;
  }
  function searchBox(key, path, placeholder) {
    const s = A[key];
    const input = h("input", { class: "input", type: "search", placeholder, value: s.q, autocomplete: "off" });
    input.addEventListener("input", debounce(() => guarded(null, async () => { s.q = input.value.trim(); await loadList(key, path, true); const at = input.selectionStart; rerender(); const again = document.querySelector(`[data-search="${key}"]`); if (again) { again.focus(); again.setSelectionRange(at, at); } })));
    input.setAttribute("data-search", key);
    return input;
  }
  function custPage() {
    const s = A.cust;
    return h("div", { class: "page" }, h("h2", { text: "Mijozlar" }), searchBox("cust", "/admin/customers", "Ism, Telegram ID yoki @bot"),
      !s.loaded ? loading() : !s.items.length ? empty("Hech kim topilmadi.") : h("div", { class: "list", style: "margin-top:10px" }, s.items.map((c) =>
        h("button", { class: "row", onClick: () => openCustomer(c.id) }, h("div", { class: "ico" }, icon("user")),
          h("div", { class: "grow" }, h("b", { text: c.name + (c.admin ? " 🛡" : "") }),
            h("small", { text: `${c.plan}${c.expires_at ? ` · ${dd(c.expires_at)} gacha` : ""} · ${c.bots} bot` }))))),
      s.more ? h("button", { class: "btn ghost", style: "margin-top:10px", onClick: (e) => guarded(e.currentTarget, async () => { await loadList("cust", "/admin/customers", false); rerender(); }) }, "Yana") : null);
  }
  async function openCustomer(id) {
    const c = await guarded(null, () => api("GET", `/admin/customers/${id}`));
    if (!c) return;
    const refresh = async () => { sheet.close(); A.home = null; await loadList("cust", "/admin/customers", true); rerender(); openCustomer(id); };
    const planBtn = h("button", { class: "btn", onClick: () => grantSheet(c, refresh) }, "Tarif berish / uzaytirish");
    const sheet = openSheet({ title: c.name, tall: true, body: [
      h("div", { class: "facts" }, h("div", { class: "fact" }, h("b", { text: c.plan }), h("small", { text: c.expires_at ? `${dd(c.expires_at)} gacha${c.status === "grace" ? " (imtiyoz)" : ""}` : "Muddatsiz" })),
        h("div", { class: "fact" }, h("b", { text: String(c.bots) }), h("small", { text: `Telegram ID ${c.tg_id}` }))),
      h("div", { style: "display:grid;gap:8px;margin:12px 0" }, planBtn,
        h("button", { class: "btn ghost", onClick: () => messageSheet(c) }, "Xabar yuborish"),
        c.trial_used ? h("button", { class: "btn ghost", onClick: (e) => guarded(e.currentTarget, async () => { await api("POST", `/admin/customers/${id}/reset-trial`); toast("Sinov qayta ochildi"); refresh(); }) }, "Bepul sinovni qayta ochish") : null),
      h("div", { class: "section" }, h("h3", { text: "Botlari" }), c.bot_list.length ? h("div", { class: "list" }, c.bot_list.map((b) => h("div", { class: "row static" }, h("div", { class: "grow" },
        h("b", { text: `${b.name}${b.active ? "" : " · to‘xtatilgan"}` }), h("small", { text: `${b.username ? `@${b.username} · ` : ""}${KIND_LABEL[b.kind] || "Oddiy"} · ${b.users} foydalanuvchi${b.license_until ? ` · alohida: ${dd(b.license_until)} gacha` : ""}` }))))) : empty("Bot yo‘q.")),
      h("div", { class: "section" }, h("h3", { text: "To‘lovlar" }), c.payments.length ? h("div", { class: "list" }, c.payments.map(payRow)) : empty("To‘lov yo‘q.")),
      c.log.length ? h("div", { class: "section" }, h("h3", { text: "Admin amallari" }), c.log.map((x) => h("p", { class: "hint", text: `${dt(x.at)} · ${LOG_NAMES[x.action] || x.action}${x.detail ? ` · ${x.detail}` : ""}` }))) : null] });
  }
  function grantSheet(c, done) {
    let plan = c.plan === "Free" ? "pro" : c.plan.toLowerCase();
    const days = h("input", { class: "input", type: "number", inputmode: "numeric", min: "1", max: "3650", value: "30" });
    const reason = h("input", { class: "input", placeholder: "Sabab (ixtiyoriy)", maxlength: "200" });
    const sheet = openSheet({ title: "Tarif berish", body: [
      field("Tarif", segmented([["start", "Start"], ["pro", "Pro"], ["business", "Business"], ["free", "Free"]], plan, (v) => { plan = v; })),
      field("Necha kun", days, "Bir xil tarif bo‘lsa, muddat oxiridan uzaytiriladi. Free tanlansa, tarif darhol olinadi."), field("Sabab", reason)],
      foot: h("button", { class: "btn", onClick: (e) => guarded(e.currentTarget, async () => {
        await api("POST", `/admin/customers/${c.id}/plan`, { plan, days: Math.max(1, Number(days.value) || 30), reason: reason.value.trim() });
        sheet.close(); toast("Saqlandi"); done();
      }) }, "Saqlash") });
  }
  function messageSheet(c) {
    const area = h("textarea", { class: "area", rows: 5, maxlength: "3500", placeholder: "Xabar matni" });
    const sheet = openSheet({ title: `Xabar: ${c.name}`, body: [area], foot: h("button", { class: "btn", onClick: (e) => guarded(e.currentTarget, async () => {
      if (!area.value.trim()) return;
      await api("POST", `/admin/customers/${c.id}/message`, { text: area.value.trim() }); sheet.close(); toast("Yuborildi");
    }) }, "Yuborish") });
  }

  function botsPage() {
    const s = A.bots;
    return h("div", { class: "page" }, h("h2", { text: "Botlar" }), searchBox("bots", "/admin/bots", "Bot, @username yoki egasi"),
      !s.loaded ? loading() : !s.items.length ? empty("Bot topilmadi.") : h("div", { class: "list", style: "margin-top:10px" }, s.items.map((b) =>
        h("button", { class: "row", onClick: () => openBotAdmin(b) }, h("div", { class: "ico", text: b.active ? "🟢" : "⏸" }),
          h("div", { class: "grow" }, h("b", { text: b.name }), h("small", { text: `${b.username ? `@${b.username} · ` : ""}${KIND_LABEL[b.kind] || "Oddiy"} · ${b.users} foyd. · ${b.owner}` }))))),
      s.more ? h("button", { class: "btn ghost", style: "margin-top:10px", onClick: (e) => guarded(e.currentTarget, async () => { await loadList("bots", "/admin/bots", false); rerender(); }) }, "Yana") : null);
  }
  function openBotAdmin(b) {
    const sheet = openSheet({ title: b.name, body: [
      h("div", { class: "row static" }, h("div", { class: "grow" }, h("b", { text: `${b.username ? `@${b.username}` : "Username yo‘q"}` }), h("small", { text: `${KIND_LABEL[b.kind] || "Oddiy bot"} · ${b.users} foydalanuvchi · ${b.connected ? "ulangan" : "ulanmagan"}` }))),
      h("p", { class: "hint", text: "To‘xtatilgan bot foydalanuvchilarga javob bermaydi. Ma’lumotlar saqlanadi, istalgan vaqtda qayta yoqish mumkin." }),
      h("button", { class: "btn ghost", onClick: () => { sheet.close(); openCustomer(b.owner_id); } }, `Egasi: ${b.owner}`)],
      foot: h("button", { class: "btn", onClick: (e) => guarded(e.currentTarget, async () => {
        await api("POST", `/admin/bots/${b.id}/active`, { active: !b.active }); sheet.close(); toast(b.active ? "To‘xtatildi" : "Yoqildi"); await loadList("bots", "/admin/bots", true); rerender();
      }) }, b.active ? "⏸ Botni to‘xtatish" : "▶️ Botni yoqish") });
  }

  /* ---------------------------------------------------------------- system */
  function sysPage() {
    const d = A.sys;
    if (!d) return h("div", { class: "page" }, h("h2", { text: "Tizim" }), loading());
    return h("div", { class: "page" }, h("h2", { text: "Tizim" }),
      h("div", { class: "facts" }, h("div", { class: "fact" }, h("b", { text: d.version }), h("small", { text: `Baza: ${d.dialect}` })),
        h("div", { class: "fact" }, h("b", { text: d.enforced ? "Yoqilgan" : "O‘chiq" }), h("small", { text: "Tarif cheklovlari" })),
        h("div", { class: "fact" }, h("b", { text: d.card ? "Bor" : "Yo‘q" }), h("small", { text: "To‘lov kartasi sozlangan" })),
        h("div", { class: "fact" }, h("b", { text: String(d.admins) }), h("small", { text: "Adminlar" }))),
      h("div", { style: "display:grid;gap:8px;margin:14px 0" },
        h("button", { class: "btn", onClick: (e) => guarded(e.currentTarget, async () => { await api("POST", "/admin/backup"); toast("Zaxira botga yuborildi"); A.sys = null; adminLoad(); }) }, "🗄 Zaxira nusxani hozir olish"),
        h("button", { class: "btn ghost", onClick: broadcastSheet }, "📣 Hamma mijozga xabar")),
      h("div", { class: "section" }, h("h3", { text: "Admin jurnali" }), d.log.length ? d.log.map((x) => h("p", { class: "hint", text: `${dt(x.at)} · ${x.admin} · ${LOG_NAMES[x.action] || x.action}${x.detail ? ` · ${x.detail}` : ""}` })) : empty("Hozircha bo‘sh.")));
  }
  function broadcastSheet() {
    let plan = "all";
    const area = h("textarea", { class: "area", rows: 6, maxlength: "3500", placeholder: "Yangilik, texnik ish yoki aksiya haqida xabar" });
    const sheet = openSheet({ title: "Platforma xabari", body: [
      field("Kimga", segmented([["all", "Hamma"], ["free", "Free"], ["start", "Start"], ["pro", "Pro"], ["business", "Business"]], plan, (v) => { plan = v; })), field("Matn", area)],
      foot: h("button", { class: "btn", onClick: (e) => guarded(e.currentTarget, async () => {
        if (!area.value.trim() || !confirm("Xabar tanlangan mijozlarga yuboriladi. Davom etasizmi?")) return;
        const r = await api("POST", "/admin/broadcast", { text: area.value.trim(), plan }); sheet.close(); toast(`${r.queued} kishiga yuborilmoqda`); A.sys = null; adminLoad();
      }) }, "Yuborish") });
  }
  return { adminPage, adminLoad };
}
