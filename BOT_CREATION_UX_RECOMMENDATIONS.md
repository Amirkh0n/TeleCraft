# Bot yaratish UI/UX tavsiyalari

## Hozirgi oqim

Foydalanuvchi “Yangi bot”ni bosadi, bot tokenini yuboradi, tizim tokenni tekshiradi, Telegram webhook’ini o‘rnatadi va botni bazaga saqlaydi. Muvaffaqiyatli yakunda boshqarish tugmasi ko‘rsatiladi.

Bu oqim qisqa, lekin foydalanuvchi qaysi qadamda ekanini, tokenni qayerdan olishini, xatoda nima qilishini va webhook o‘rnatilmasa bot ishlaydimi-yo‘qmi aniq bilmay qolishi mumkin.

## Tavsiya etiladigan foydalanuvchi oqimi

1. **Yaratishni boshlash**
   - Bo‘sh botlar ro‘yxatida bitta asosiy CTA: **“➕ Birinchi botimni yaratish”**.
   - Botlari bor foydalanuvchida **“➕ Bot qo‘shish”** tugmasi ro‘yxat ostida tursin.
   - Boshlash ekranida jarayonni qisqacha tushuntiring: “BotFather’dan token oling, shu yerga yuboring. Token tekshiriladi va webhook avtomatik ulanadi.”

2. **Tokenni olish bo‘yicha yordam**
   - Token kiritish xabari BotFather yo‘riqnomasiga ega bo‘lsin: BotFather’da `/newbot` yuborish, bot nomi va username tanlash, berilgan tokenni nusxalash.
   - **“📖 Tokenni qayerdan olaman?”**, **“❌ Bekor qilish”** tugmalari bo‘lsin.
   - Tokenni faqat shaxsiy chatda yuborishni eslating. Tokenni xabarda qayta ko‘rsatib, tasdiqlatish shart emas.

3. **Kiritilgan qiymatni tekshirish**
   - Bo‘sh matn, noto‘g‘ri format yoki Telegram tomonidan rad etilgan token uchun alohida, tushunarli xabar chiqaring.
   - Xatolik xabarida foydalanuvchi qaysi ishni bajarishi kerakligi aytilsin: “Token noto‘g‘ri ko‘rinadi. BotFather’dan tokenni qayta nusxalab yuboring.”
   - Xato chiqqanda yaratish holatini saqlang; foydalanuvchi boshidan boshlamasdan tokenni qayta yubora olsin.
   - Tiklanishi mumkin bo‘lgan tarmoq xatosini noto‘g‘ri token xabaridan alohida ko‘rsating: “Telegram bilan vaqtincha bog‘lanib bo‘lmadi. Bir ozdan keyin qayta urinib ko‘ring.”

4. **Tekshirish va ulash jarayoni**
   - API tekshiruvi yoki webhook o‘rnatilishi davomida qisqa holat xabari ko‘rsating: **“⏳ Token tekshirilmoqda…”**, keyin **“🔔 Webhook ulanmoqda…”**.
   - So‘rov uzoq cho‘zilsa foydalanuvchi kutayotganini tushunsin; qayta-qayta token yuborishga undamang.

5. **Natijani aniq ko‘rsatish**
   - Webhook muvaffaqiyatli ulangan bo‘lsa: **“✅ @username botingiz tayyor. Endi botga o‘tib /start yuboring.”**
   - Asosiy CTA: **“⚙️ Botni sozlash”**; ikkilamchi CTA: **“🤖 Botni ochish”** va **“📂 Botlarim”**.
   - Webhook ulanmagan bo‘lsa, botni “tayyor” deb ko‘rsatmang. Muammoni sodda tushuntirib, **“🔄 Qayta ulash”** va **“📋 Bot holatini ko‘rish”** amallarini taklif qiling.
   - Bot allaqachon qo‘shilgan bo‘lsa, takroriy bot yaratmasdan: **“Bu bot hisobingizga avval qo‘shilgan”** deb, mavjud botni ochish tugmasini ko‘rsating.

## Matn va boshqaruv bo‘yicha tavsiyalar

- Bir xabarda bitta asosiy vazifa va bitta aniq keyingi qadam bo‘lsin.
- Texnik atamalarni izohsiz ishlatmang. “Webhook” so‘zini foydalanuvchiga ko‘rsatish zarur bo‘lsa, “Telegram botingiz bilan server orasidagi ulanish” deb tushuntiring.
- Har bir bosqichda **“❌ Bekor qilish”** yoki **“⬅️ Orqaga”** bo‘lsin. Bekor qilish so‘rovdan oldingi holatga qaytarsin va kiritilgan token matnini qayta yubormasin.
- Botlar ro‘yxatida nom bilan birga holat belgisi ko‘rsating: **Ishlayapti**, **Ulanmoqda**, **Ulanish kerak**. Holat faqat webhook o‘rnatilganidan kelib chiqib belgilanmasin; real holat tekshiruvi bo‘lsin.
- Telegram’dan olingan `first_name` bilan birga `@username`ni ham ko‘rsatish foydalanuvchiga aynan qaysi bot qo‘shilganini aniqlashga yordam beradi.

## Xatolik va chekka holatlar

- **Noto‘g‘ri token:** qayta yuborish va bekor qilish.
- **Telegram API vaqtincha ishlamayapti:** botni saqlab qo‘yish yoki saqlamaslik siyosati oldindan aniq bo‘lsin; holat “tekshiruv tugamadi” deb ko‘rsatilsin va qayta urinish berilsin.
- **Webhook o‘rnatilmadi:** sabab va keyingi qadamni ko‘rsatish; webhook’ni qayta o‘rnatish mumkin bo‘lsin.
- **Token boshqa hisobda ishlatilgan:** mavjud botni egasiga bog‘lash qoidasi aniq bo‘lsin; foydalanuvchiga umumiy server xatosini ko‘rsatmang.
- **Foydalanuvchi jarayonni tark etdi:** keyin qaytganda kutayotgan bosqichni tiklash yoki bekor qilish imkoniyati bo‘lsin.
- **Noto‘g‘ri update turi:** token kutilayotgan paytda matn bo‘lmagan xabar kelsa, nima yuborish kerakligini eslating.

## Tavsiya etiladigan qisqa matn namunasi

> 🤖 Yangi bot qo‘shamiz
>
> Avval [@BotFather](https://t.me/BotFather) orqali bot yarating va u bergan tokenni shu chatga yuboring. Tokenni hech kimga ulashmang.
>
> [📖 Tokenni olish] [❌ Bekor qilish]

Muvaffaqiyat xabari:

> ✅ **@username** qo‘shildi va ulanish tekshirildi.
>
> Telegram’da botni ochib `/start` yuboring.
>
> [⚙️ Botni sozlash] [🤖 Botni ochish]

Webhook muvaffaqiyatsiz bo‘lsa:

> ⚠️ **@username** saqlandi, lekin Telegram bilan ulanish o‘rnatilmadi. Hozircha botga kelgan xabarlar qayta ishlanmasligi mumkin.
>
> [🔄 Qayta ulash] [📋 Holatni ko‘rish]

## Amalga oshirish ustuvorligi

1. Noto‘g‘ri token, Telegram API xatosi va webhook xatosi uchun alohida xabarlar.
2. Bosqichma-bosqich progress xabari va barcha bosqichlarda bekor qilish.
3. Muvaffaqiyat va xatolik natijalarida aniq keyingi amal.
4. Token olish bo‘yicha qisqa yo‘riqnoma.
5. Botlar ro‘yxatida username va real ulanish holatini ko‘rsatish.
6. Jarayonni tashlab ketish va keyin davom ettirish holatlarini yaxshilash.

## UX muvaffaqiyat mezonlari

- Yangi foydalanuvchi tokenni qayerdan olishni botdan chiqmasdan tushunadi.
- Token xatosi yoki vaqtinchalik aloqa xatosidan keyin jarayonni qayta boshlamasdan davom ettira oladi.
- Har bir vaqtda foydalanuvchi qaysi bosqichdaligini va keyin nima qilishini biladi.
- “Tayyor” holati faqat webhook muvaffaqiyatli o‘rnatilib, botga xabar yuborish mumkin bo‘lganda ko‘rsatiladi.
- Muvaffaqiyatli qo‘shilgandan so‘ng botni sozlashga bitta bosishda o‘tiladi.
