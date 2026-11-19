/* Languages of a child bot: turn languages on, translate every screen text, button label and text answer. */
export function mountLangs({ h, api, toast, openSheet, field, switchRow, guarded, S }) {
  const path = () => `/bots/${S.bot.id}/translations`;

  async function open() {
    let data;
    try { data = await api("GET", path()); } catch (err) { toast(err.message, true); return; }
    const sheet = openSheet({ title: "🌐 Tillar", tall: true, body: [], foot: null });
    const body = sheet.el.querySelector(".sheet-body");
    const paint = () => {
      body.replaceChildren(
        h("p", { class: "hint", text: "Asosiy til — o‘zbekcha. Qo‘shimcha til yoqsangiz, mijoz /start bosganda tilni tanlaydi. Tarjima yozilmagan matn o‘zbekcha ko‘rinadi." }),
        h("div", { class: "section" }, data.available.map((code) => switchRow(data.labels[code], data.languages.includes(code), async (on) => {
          const next = on ? [...data.languages, code] : data.languages.filter((c) => c !== code);
          try { data = await api("PUT", `/bots/${S.bot.id}/languages`, { languages: next }); paint(); } catch (err) { toast(err.message, true); paint(); }
        }))),
        data.languages.length ? h("div", { class: "list" }, data.menus.map((m) => h("button", { class: "row", onClick: () => translateMenu(m, () => data, (d) => { data = d; paint(); }) },
          h("div", { class: "ico", text: "🌐" }),
          h("div", { class: "grow" }, h("b", { text: m.title }), h("small", { text: summary(m, data.languages) }))))) : null,
      );
    };
    paint();
  }

  function summary(menu, langs) {
    const items = [["menu", menu.tr, !!(menu.message_text || "").trim()], ...menu.buttons.flatMap((b) => [["b", b.tr, true], ...(b.action_text ? [["a", b.action_tr, true]] : [])])];
    const total = items.filter((i) => i[2]).length * langs.length;
    const done = items.reduce((n, [, tr, need]) => n + (need ? langs.filter((l) => tr[l]).length : 0), 0);
    return `${done} / ${total} tarjima qilingan`;
  }

  function translateMenu(menu, getData, setData) {
    const langs = getData().languages;
    const inputs = [];
    const block = (label, base, entity, id, tr, rows = 1) => {
      const wrap = h("div", { class: "field" }, h("div", { class: "lab", text: label }),
        h("div", { class: "note", text: (base || "").slice(0, 200) || "—" }),
        langs.map((lang) => {
          const area = h(rows > 1 ? "textarea" : "input", { class: rows > 1 ? "area" : "input", rows, placeholder: getData().labels[lang], value: tr[lang] || "", ...(rows === 1 ? { maxlength: "64" } : {}) });
          inputs.push({ entity, entity_id: id, lang, area, old: tr[lang] || "" });
          return area;
        }));
      return wrap;
    };
    const parts = [block("Xabar matni", menu.message_text, "menu_text", menu.id, menu.tr, 5)];
    menu.buttons.forEach((b) => {
      parts.push(block(`Tugma: ${b.text}`, b.text, "button_text", b.id, b.tr));
      if (b.action_text) parts.push(block(`Javob: ${b.text}`, b.action_text, "action_text", b.id, b.action_tr, 4));
    });
    const save = h("button", { class: "btn", onClick: () => guarded(save, async () => {
      const items = inputs.filter((i) => i.area.value.trim() !== i.old.trim()).map((i) => ({ entity: i.entity, entity_id: i.entity_id, lang: i.lang, text: i.area.value }));
      if (items.length) setData(await api("PUT", path(), { items }));
      sheet.dirty = false; sheet.close(); toast("Saqlandi");
    }) }, "Saqlash");
    const sheet = openSheet({ title: menu.title, tall: true, body: parts, foot: [save] });
  }

  return { open };
}
