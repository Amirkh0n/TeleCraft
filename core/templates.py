"""Ready-made bot templates: a start message plus menus and buttons the owner then edits.

A button is ``(text, answer)`` where ``answer`` is a text reply, or ``Sub(...)`` for a button that opens a sub-menu.
Texts are examples (no real phone numbers or addresses): the owner replaces them with their own details.
"""
from dataclasses import dataclass, field

PHONE = "📞 Telefon: +998 XX XXX XX XX\n💬 Telegram: @username"
PLACE = "📍 Manzil: shahar, ko‘cha, uy raqami\n🧭 Mo‘ljal: ..."
HOURS = "🕒 Ish vaqti\n\nDushanba–Shanba: 09:00–21:00\nYakshanba: 10:00–18:00"


@dataclass
class Sub:
    title: str
    text: str
    items: list = field(default_factory=list)  # [(button text, answer)]


@dataclass
class Template:
    key: str
    icon: str
    title: str
    about: str
    start: str
    buttons: list = field(default_factory=list)


TEMPLATES = [
    Template("cafe", "☕", "Kafe / restoran", "Menyu, ish vaqti, manzil, aksiyalar", "Assalomu alaykum! 👋\n<b>Kafemiz</b> botiga xush kelibsiz. Quyidan kerakli bo‘limni tanlang.", [
        ("🍽 Menyu", Sub("🍽 Menyu", "Menyu bo‘limini tanlang:", [
            ("🍲 Ovqatlar", "🍲 <b>Ovqatlar</b>\n\nPlov — 00 000 so‘m\nLag‘mon — 00 000 so‘m\nShashlik — 00 000 so‘m"),
            ("🥤 Ichimliklar", "🥤 <b>Ichimliklar</b>\n\nChoy — 00 000 so‘m\nKofe — 00 000 so‘m\nSharbat — 00 000 so‘m"),
            ("🍰 Shirinliklar", "🍰 <b>Shirinliklar</b>\n\nTort — 00 000 so‘m\nMedovik — 00 000 so‘m")])),
        ("🎉 Aksiyalar", "🎉 <b>Aksiyalar</b>\n\nHozirgi chegirma va takliflar shu yerda e’lon qilinadi."),
        ("🕒 Ish vaqti", HOURS), ("📍 Manzil", PLACE), ("📞 Aloqa", PHONE)]),
    Template("salon", "💇", "Go‘zallik saloni", "Xizmatlar va narxlar, bron, ustalar", "Assalomu alaykum! ✨\n<b>Salonimiz</b> botiga xush kelibsiz. Xizmat va narxlarni ko‘ring, qabulga yoziling.", [
        ("💅 Xizmatlar va narxlar", Sub("💅 Xizmatlar va narxlar", "Yo‘nalishni tanlang:", [
            ("✂️ Soch", "✂️ <b>Soch</b>\n\nKesish — 00 000 so‘m\nBo‘yash — 000 000 so‘m\nUkladka — 00 000 so‘m"),
            ("💅 Manikyur / pedikyur", "💅 <b>Manikyur / pedikyur</b>\n\nManikyur — 00 000 so‘m\nPedikyur — 00 000 so‘m"),
            ("🧖 Yuz parvarishi", "🧖 <b>Yuz parvarishi</b>\n\nTozalash — 000 000 so‘m\nMaska — 00 000 so‘m")])),
        ("📅 Qabulga yozilish", "📅 <b>Qabulga yozilish</b>\n\nIsmingiz, xizmat turi va qulay vaqtni shu bot orqali yoki telefon bilan yuboring.\n\n" + PHONE),
        ("👩‍🎨 Ustalarimiz", "👩‍🎨 <b>Ustalarimiz</b>\n\nUstalar haqida qisqacha ma’lumot, tajriba va ish namunalari."),
        ("🕒 Ish vaqti", HOURS), ("📍 Manzil", PLACE), ("📞 Aloqa", PHONE)]),
    Template("edu", "🎓", "O‘quv markazi", "Kurslar, jadval, narxlar, sinov darsi", "Assalomu alaykum! 📚\n<b>O‘quv markazimiz</b> botiga xush kelibsiz. Kurslar bilan tanishing va sinov darsiga yoziling.", [
        ("📚 Kurslar", Sub("📚 Kurslar", "Kursni tanlang:", [
            ("🇬🇧 Ingliz tili", "🇬🇧 <b>Ingliz tili</b>\n\nDarajalar: Beginner – Advanced\nDavomiyligi: 6 oy\nNarxi: 000 000 so‘m/oy"),
            ("💻 Dasturlash", "💻 <b>Dasturlash</b>\n\nPython, web, mobil\nDavomiyligi: 8 oy\nNarxi: 000 000 so‘m/oy"),
            ("➗ Matematika", "➗ <b>Matematika</b>\n\nMaktab va abituriyentlar uchun\nNarxi: 000 000 so‘m/oy")])),
        ("🗓 Dars jadvali", "🗓 <b>Dars jadvali</b>\n\nDushanba, Chorshanba, Juma — 15:00\nSeshanba, Payshanba, Shanba — 17:00"),
        ("🎁 Sinov darsi", "🎁 <b>Bepul sinov darsi</b>\n\nYozilish uchun ism va telefon raqamingizni yuboring:\n" + PHONE),
        ("📍 Manzil", PLACE), ("📞 Aloqa", PHONE)]),
    Template("clinic", "🏥", "Klinika / shifokor", "Xizmatlar, shifokorlar, qabulga yozilish", "Assalomu alaykum! 🩺\n<b>Klinikamiz</b> botiga xush kelibsiz. Xizmatlar bilan tanishing va qabulga yoziling.", [
        ("🩺 Xizmatlar", Sub("🩺 Xizmatlar", "Yo‘nalishni tanlang:", [
            ("🔬 Tahlillar", "🔬 <b>Tahlillar</b>\n\nQon, siydik, gormonlar. Natija — 1 kun ichida."),
            ("🦷 Stomatologiya", "🦷 <b>Stomatologiya</b>\n\nTekshiruv, davolash, tozalash."),
            ("🩻 Diagnostika", "🩻 <b>Diagnostika</b>\n\nUZI, rentgen, EKG.")])),
        ("👨‍⚕️ Shifokorlarimiz", "👨‍⚕️ <b>Shifokorlarimiz</b>\n\nShifokor ismi — mutaxassisligi, tajribasi."),
        ("📅 Qabulga yozilish", "📅 <b>Qabulga yozilish</b>\n\nIsm, yosh va qulay vaqtni yuboring.\n\n" + PHONE),
        ("🕒 Ish vaqti", HOURS), ("📍 Manzil", PLACE), ("📞 Aloqa", PHONE)]),
    Template("shop", "🛍", "Do‘kon katalogi", "Katalog, yetkazib berish, to‘lov", "Assalomu alaykum! 🛍\n<b>Do‘konimiz</b> botiga xush kelibsiz. Katalogni ko‘ring va buyurtma bering.", [
        ("🗂 Katalog", Sub("🗂 Katalog", "Bo‘limni tanlang:", [
            ("👕 Kiyim", "👕 <b>Kiyim</b>\n\nMahsulot nomi — 000 000 so‘m\nMahsulot nomi — 000 000 so‘m"),
            ("👟 Poyabzal", "👟 <b>Poyabzal</b>\n\nMahsulot nomi — 000 000 so‘m"),
            ("🎒 Aksessuarlar", "🎒 <b>Aksessuarlar</b>\n\nMahsulot nomi — 00 000 so‘m")])),
        ("🛒 Buyurtma berish", "🛒 <b>Buyurtma berish</b>\n\nMahsulot nomi va manzilingizni yuboring:\n" + PHONE),
        ("🚚 Yetkazib berish", "🚚 <b>Yetkazib berish</b>\n\nShahar bo‘yicha — 1 kun, narxi 00 000 so‘m.\nViloyatlarga — 2–3 kun."),
        ("💳 To‘lov usullari", "💳 <b>To‘lov usullari</b>\n\nNaqd, karta orqali, o‘tkazma."),
        ("📞 Aloqa", PHONE)]),
    Template("gym", "🏋️", "Fitnes zal", "Abonementlar, jadval, trenerlar", "Assalomu alaykum! 💪\n<b>Zalimiz</b> botiga xush kelibsiz. Abonement va mashg‘ulotlar bilan tanishing.", [
        ("🎫 Abonementlar", Sub("🎫 Abonementlar", "Abonementni tanlang:", [
            ("1 oy", "🎫 <b>1 oylik abonement</b>\n\n000 000 so‘m"),
            ("3 oy", "🎫 <b>3 oylik abonement</b>\n\n000 000 so‘m"),
            ("12 oy", "🎫 <b>12 oylik abonement</b>\n\n0 000 000 so‘m")])),
        ("🗓 Mashg‘ulot jadvali", "🗓 <b>Jadval</b>\n\nTonggi guruh — 07:00\nKunduzgi — 13:00\nKechki — 19:00"),
        ("🏅 Trenerlar", "🏅 <b>Trenerlar</b>\n\nTrener ismi — yo‘nalishi, tajribasi."),
        ("🕒 Ish vaqti", HOURS), ("📍 Manzil", PLACE), ("📞 Aloqa", PHONE)]),
    Template("card", "💼", "Vizitka / xizmatlar", "Kompaniya yoki mutaxassis uchun", "Assalomu alaykum! 👋\nMen — <b>Ismingiz</b>. Bu yerda xizmatlarim va ish namunalarim bilan tanishishingiz mumkin.", [
        ("ℹ️ Men haqimda", "ℹ️ <b>Men haqimda</b>\n\nQisqacha tajriba, yo‘nalish va yutuqlar."),
        ("🛠 Xizmatlar", Sub("🛠 Xizmatlar", "Xizmatni tanlang:", [
            ("Xizmat 1", "<b>Xizmat 1</b>\n\nTavsif va narxi."),
            ("Xizmat 2", "<b>Xizmat 2</b>\n\nTavsif va narxi.")])),
        ("🖼 Ish namunalari", "🖼 <b>Ish namunalari</b>\n\nHavola yoki rasm/video shu yerda bo‘ladi."),
        ("💰 Narxlar", "💰 <b>Narxlar</b>\n\nXizmat 1 — 000 000 so‘m\nXizmat 2 — 000 000 so‘m"),
        ("📞 Bog‘lanish", PHONE)]),
    Template("channel", "📣", "Kanal / blogger", "Kanal, reklama, aloqa", "Assalomu alaykum! 👋\n<b>Kanalimiz</b> rasmiy botiga xush kelibsiz.", [
        ("📣 Kanalimiz", "📣 <b>Kanalimiz</b>\n\nKanal havolasi: https://t.me/kanal_nomi"),
        ("📢 Reklama", "📢 <b>Reklama</b>\n\nReklama joylash narxlari va shartlari."),
        ("🤝 Hamkorlik", "🤝 <b>Hamkorlik</b>\n\nTaklifingizni yuboring."),
        ("📞 Aloqa", PHONE)]),
]
BY_KEY = {t.key: t for t in TEMPLATES}
BACK = "⬅️ Orqaga"
