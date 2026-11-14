# 🤖 TeleCraft - Professional Telegram Bot Constructor

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](Dockerfile)

TeleCraft is a professional-grade Telegram bot constructor platform that allows you to create, manage, and deploy multiple Telegram bots with an intuitive interface.

## ✨ Features

### 🏗️ Bot Builder
- **Bot Creation**: Create multiple Telegram bots from BotFather tokens
- **Menu System**: Build hierarchical menu structures
- **Button Management**: Add, edit, and delete buttons with custom actions
- **Action Types**: 
  - 📝 Send text messages
  - 🔗 Open links
  - 📂 Navigate to other menus
  - 👨‍💼 Send to admins
  - 📁 Send files and videos

### 🎨 User Experience
- **Intuitive Interface**: Easy-to-use Telegram UI for bot construction
- **Confirmation Dialogs**: Safe deletion with confirmation prompts
- **Real-time Feedback**: Instant confirmation for all actions
- **Error Handling**: Comprehensive error handling and user-friendly messages

### 📊 Analytics & Monitoring
- **Event Tracking**: Track every user interaction
- **Bot Statistics**: Monitor total users, events, and engagement
- **User Statistics**: Track individual user behavior
- **Metrics**: Record performance metrics for monitoring

### 🔒 Security & Performance
- **Rate Limiting**: Protect against abuse
- **Connection Pooling**: Efficient database connections
- **Input Validation**: Validate all user inputs
- **Error Logging**: Structured logging for debugging

### 🚀 Deployment
- **Docker Support**: Containerized deployment
- **Production Ready**: Optimized for scaling
- **Health Checks**: Built-in monitoring endpoints
- **Prometheus Metrics**: Export metrics for monitoring

## 📋 Requirements

- Python 3.11+
- SQLite (default) or PostgreSQL for production
- Telegram Bot Token from BotFather

## 🛠️ Installation

### Option 1: Using Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/yourusername/telecraft.git
cd telecraft

# Copy environment template
cp .env.example .env

# Edit .env with your settings
nano .env

# Start using Docker Compose
docker-compose up -d
```

### Option 2: Using Python

```bash
# Clone the repository
git clone https://github.com/yourusername/telecraft.git
cd telecraft

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env

# Edit .env with your settings
nano .env

# Initialize database
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"

# Run the constructor bot
python run_constructor.py

# For webhook server
uvicorn app.main:app --reload
```

## ⚙️ Configuration

Create a `.env` file with the following variables:

```env
TELEGRAM_TOKEN=your_constructor_bot_token_here
BOT_TOKENS=bot_token1,bot_token2
# Local: SQLite file. Production: PostgreSQL URL, e.g. postgresql://user:pass@host/db?sslmode=require
DATABASE_URL=sqlite+aiosqlite:///./constructor.db
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000
LOG_LEVEL=INFO
LOG_FORMAT=json
MAX_CONNECTIONS=20
CONNECTION_POOL_SIZE=10
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60
ADMIN_IDS=123456789,987654321
DEBUG=False
TESTING=False
```

## 📖 Usage

### Creating a Bot

1. Send `/start` command to the constructor bot
2. Click "➕ Bot qo'shish"
3. Paste your BotFather token
4. Your bot will be created automatically

### Creating Menus

1. Select your bot from the bot list
2. Click "📁 Menular"
3. Click "➕ Menu qo'shish"
4. Enter the menu name
5. Your menu will be created

### Adding Buttons

1. Click on your menu
2. Click "➕ Tugma qo'shish"
3. Enter the button text
4. Choose the action type:
   - 📝 Text: Send a text message
   - 🔗 Link: Open a URL
   - 📂 Menu: Navigate to another menu
   - 👨‍💼 Admin: Send to admin

### Testing Your Bot

Send `/start` command to your created bot to test:
- Start menu will appear
- Buttons will work with configured actions
- Navigation between menus

## 🏗️ Architecture

```
TeleCraft/
├── constructor/      # Bot constructor logic
│   ├── handlers.py   # Command handlers
│   ├── flows/        # User flows
│   ├── states.py     # State management
│   └── bot.py        # Bot initialization
├── engine/           # Bot runtime engine
│   ├── router.py     # Request routing
│   ├── resolver.py   # Logic resolution
│   └── actions.py    # Action execution
├── app/              # FastAPI webhook server
│   └── main.py       # Main application
├── core/             # Core utilities
│   ├── database.py   # Database configuration
│   ├── config.py     # Settings management
│   ├── logger.py     # Logging
│   ├── errors.py     # Error handling
│   ├── validators.py # Input validation
│   └── analytics.py  # Analytics tracking
├── models/           # Database models
│   ├── base.py       # Base model
│   ├── users.py      # User model
│   ├── bots.py       # Bot model
│   ├── menus.py      # Menu model
│   └── analytics.py  # Analytics models
└── tests/            # Test suite
```

## 🚀 Deployment

### Docker Deployment

```bash
docker build -t telecraft .
docker run -d -p 8000:8000 --env-file .env telecraft
```

### Database migrations (Alembic)

The schema is versioned in `migrations/versions/`. The app runs `alembic upgrade head` on every
start, so a deploy brings the database up to date by itself. An existing database that predates
Alembic is adopted automatically (data is kept).

When you change a model in `models/`:

```bash
alembic revision --autogenerate -m "what changed"   # then READ the generated file
alembic upgrade head                                 # try it locally
```

Commit the migration together with the model change. A test (`test_models_and_migrations_do_not_drift`)
and CI fail if a model changed without a migration. Never edit the database schema by hand or add
`ALTER TABLE` to the application code.

### Render Deployment

Render's filesystem is wiped on every deploy and restart, so **never run on SQLite there** —
all bots and menus would disappear. Use an external PostgreSQL database.

1. Create a free PostgreSQL database (e.g. [Neon](https://neon.com)) and copy its connection string
   (use the *pooled* one).
2. In Render → Environment set:
   - `DATABASE_URL` = the connection string (as given, `postgresql://...?sslmode=require` is fine)
   - `ENCRYPTION_KEY` = a long random string (`python -c "import secrets; print(secrets.token_urlsafe(48))"`)
   - `PUBLIC_BASE_URL` = your Render service URL
   - `TELEGRAM_TOKEN` = the constructor bot token
3. Push to GitHub — Render deploys automatically. Tables are created on startup.

Never commit the connection string or `ENCRYPTION_KEY`; keep them in the Render dashboard only.

### VPS Deployment

```bash
# SSH into your VPS
ssh user@your-vps

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Pull and run
docker run -d \
  --name telecraft \
  -p 8000:8000 \
  --env-file .env \
  telecraft:latest
```

## 📊 Monitoring

### Health Check

```bash
curl http://localhost:8000/health
```

### Prometheus Metrics

```bash
curl http://localhost:8000/metrics
```

### Database Stats

Access bot statistics through the constructor bot:
- Total users
- Total events
- Active menus
- Total buttons

## 🔧 Development

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=constructor --cov=engine --cov=core --cov=app
```

### Code Style

```bash
# Check code style
black --check .
isort --check-only .
flake8 .

# Fix issues
black .
isort .
```

## 📈 Performance

### Database Optimization

- Connection pooling configured
- Async operations throughout
- Indexes on frequently queried fields

### Scaling

- Horizontal scaling supported
- Stateless webhook handlers
- Efficient database queries

## 🔒 Security

- Rate limiting implemented
- Input validation for all inputs
- Environment variable configuration
- No hardcoded secrets

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- python-telegram-bot library
- FastAPI framework
- SQLAlchemy ORM

## 📧 Support

For support, email support@telecraft.app or create an issue on GitHub.

## 🌟 Star History

If you find TeleCraft useful, please star ⭐ the repository!

## Imkoniyatlar (engine v2 + audience)

**Child bot:** media bilan menyular (rasm, video, GIF, fayl, audio), xabar ostidagi yoki pastki klaviatura
tugmalari, kontakt/lokatsiya so‘rash, formalar (matn, raqam, telefon, email, tanlov, rasm, lokatsiya),
adminlarga bildirishnoma.

**Auditoriya:** har bir child bot o‘z foydalanuvchilarini (`bot_users`) kuzatadi: kim, qachon, qaysi
`/start nom` havolasidan kelgani, botni bloklaganmi. Statistika konstruktorda: 👥 Auditoriya.

**Broadcast:** matn/media + havola tugmasi, avval o‘zingizga ko‘rib chiqish, tasdiqdan so‘ng yuborish.
Telegram limitiga mos (~25 xabar/s), bloklaganlar avtomatik belgilanadi, server qayta ishga tushsa
yuborish qolgan joyidan davom etadi (eng ko‘pi 10 kishiga ikki marta borishi mumkin).

**Majburiy obuna:** foydalanuvchi ko‘rsatilgan kanallarga a‘zo bo‘lmaguncha botdan foydalana olmaydi.
Child bot kanalda **administrator** bo‘lishi kerak. Tekshiruv amalga oshmasa (bot admin emas, kanal
o‘chirilgan) foydalanuvchi bloklanmaydi.

`my_chat_member` yangilanishlari uchun webhooklar `WEBHOOK_REFRESH_ON_START=True` bilan qayta
o‘rnatiladi; shundan keyin botni bloklash/blokdan chiqarish darhol ko‘rinadi.

## Vizual muharrir (Telegram Mini App)

Konstruktor botda **Bot boshqaruvi → 🎨 Vizual muharrir** (yoki chatdagi «Muharrir» tugmasi) muharrirni
ochadi: mijoz ko‘radigan chat aynan shu ko‘rinishda chiqadi, xabar yoki tugmani bosib tahrirlaysiz.
Ekranlar, tugmalar va ularning amallari, media, tugmalar joylashuvi (xabar ostida / pastki klaviatura),
formalar va auditoriya statistikasi shu yerda.

- Mini App faqat **HTTPS** manzilda ochiladi: Render'da `PUBLIC_BASE_URL=https://<servis>.onrender.com` bo‘lishi kerak.
- Kirish Telegram imzosi bilan (`initData`, konstruktor bot tokeni orqali tekshiriladi): parol yoki sessiya yo‘q,
  har bir so‘rov faqat foydalanuvchining o‘z botlari bilan ishlaydi.
- Manzil: `/app/`, API: `/api/v1/…`. Qurish bosqichi yo‘q: `webapp/static/` dagi oddiy HTML/CSS/JS.
- Muharrirda to‘rt bo‘lim: Ekranlar, Formalar, Tarqatish (broadcast: ko‘rinishini ko‘rish, o‘zingizga sinov yuborish, jarayonni kuzatish) va Auditoriya (statistika + majburiy obuna kanallari).
- Tugmalarni bosib turib sudrab tartiblash mumkin; saqlanmagan o‘zgarishlar yopishdan oldin ogohlantiriladi.

## Kino bot rejimi

Bot panelidagi **🎬 Kino bot** tugmasi botni kino katalogiga aylantiradi.

- **Tomoshabin**: kino *kodini* (masalan `105`) yoki *nomining bir qismini* yozadi — bot videoni yuboradi. Nom bo‘yicha qidirishda natijalar tugma ko‘rinishida chiqadi. Majburiy obuna kino botda ham ishlaydi.
- **Saqlash**: kino videosi Telegram `file_id` sifatida saqlanadi va shu `file_id` orqali yuboriladi (fayl serverda saqlanmaydi). `file_id` har bir bot uchun alohida, shuning uchun kino **child botning o‘ziga** yuboriladi.
- **Adminlar child botning o‘zida kinolarni boshqaradi** (CRUD): `/admin` → ➕ qo‘shish (video → kod → nom → tavsif), 📋 ro‘yxat (sahifalash), tahrirlash (nom, kod, tavsif, faylni almashtirish), o‘chirish (tasdiq bilan), 📊 statistika (eng ko‘p ko‘rilganlar). `/cancel` joriy amalni bekor qiladi, `/auto` keyingi bo‘sh kodni beradi.
- **Admin qo‘shish asosiy (constructor) bot orqali**: bot paneli → **👮 Adminlar** → Telegram ID yuborish. Bot egasi har doim adminlik huquqiga ega.
- Rejimni o‘chirsangiz oddiy menyu/tugmalar qaytadi, kinolar bazada saqlanib qoladi.

Texnik: migratsiya `0004_cinema` (faqat qo‘shimcha: `movies`, `bots.kind`, `user_sessions.state/state_data`), mantiq `engine/cinema.py`, constructor tomoni `constructor/flows/cinema.py`.

### Kino bot: deep link, kanal e’loni, himoya

- **Deep link**: `t.me/<bot>?start=<kino kodi>` kinoni darrov yuboradi (obuna tekshiruvidan keyin). Kirish manbai auditoriya statistikasida (`source`) ko‘rinadi.
- **Kino kanal** (asosiy bot → 🎬 Kino bot → 📢 Kino kanal): ulash, almashtirish, uzish. Child bot kanalda administrator bo‘lishi shart. Kino rejimi yoqilganda kanal darhol so‘raladi.
- **E’lon**: yangi kino qo‘shilganda kanalga *poster + matn (nom, tavsif, kod) + «🎬 Tomosha qilish» tugmasi* yuboriladi (video emas). Poster kino qo‘shishda so‘raladi (`/skip` — rasmsiz matn e’loni). Kino kartasidagi «📢 Kanalga yuborish» e’lonni qayta yuboradi.
- **Himoya**: video `protect_content=True` bilan yuboriladi (forward va saqlash cheklanadi).
- **Majburiy obuna va broadcast** kino botda ham ishlaydi: foydalanuvchilar auditoriyaga yoziladi, adminlar obunadan ozod.
- Migratsiya: `0005_cinema_channel` (faqat qo‘shimcha).

## Bron bot rejimi

Bot panelidagi **📅 Bron bot** tugmasi botni onlayn bron (navbat) tizimiga aylantiradi: sartaroshxona, klinika, o‘quv markaz, avto servis va h.k.

- **Mijoz**: xizmat → mutaxassis (yoki «farqi yo‘q») → kun → vaqt → telefon → tasdiq. Band vaqtlar ko‘rinmaydi, ikki kishi bir vaqtni ola olmaydi. «📋 Mening bronlarim»da ko‘rish va bekor qilish (muddati admin belgilaydi). Telefon raqami keyingi bronlarda eslab qolinadi.
- **Admin (child botning o‘zida, `/admin`)**: bugungi/kelgusi/tasdiq kutayotgan bronlar (tasdiqlash, rad etish, bekor qilish, «bajarildi», «kelmadi»), 🧾 xizmatlar (nom, davomiylik, narx, tavsif), 👤 mutaxassislar (qaysi xizmatlarni bajarishi, shaxsiy jadval), 🕒 ish vaqti (tanaffus bilan: `09:00-13:00, 14:00-18:00`), 🏖 dam kunlari (oraliq bilan), ⚙️ sozlamalar, 📊 statistika.
- **Sozlamalar**: tasdiqlash (avtomatik yoki admin qo‘lda), vaqt qadami, eng kam oldindan band qilish, necha kun oldin, bekor qilish muddati, vaqt mintaqasi (standart Asia/Tashkent), aloqa ma’lumoti.
- **Eslatmalar**: admin vaqtni o‘zi yozadi (`1 kun, 2 soat`). Har bir eslatma bir marta yuboriladi; server to‘xtab qolgan bo‘lsa, eski eslatmalar ketma-ket yog‘ilmaydi, faqat eng yaqini yuboriladi. Fon sikli ilova bilan birga ishlaydi (ilovaning **bitta nusxasi** kerak).
- **Adminlar** asosiy bot → 👮 Adminlar orqali qo‘shiladi; yangi bron, bekor qilish haqida shu adminlarga xabar boradi.
- Majburiy obuna va broadcast bron botda ham ishlaydi.
- Migratsiya `0006_booking` (faqat yangi jadvallar). Vaqtlar UTC da saqlanadi, ko‘rsatishda bot mintaqasi ishlatiladi.

## Test bot rejimi

Bot panelidagi **🧠 Test bot** tugmasi botni test platformasiga aylantiradi (o‘quv markaz, maktab, bilim bellashuvi).

- **Test yaratish — hamma foydalanuvchi** (adminlar «faqat adminlar» qilib cheklashi va har bir foydalanuvchi limitini qo‘yishi mumkin): nom → tavsif → **har bir savol uchun vaqt** (5–600 s) → savollar.
- **Savollarni yuborish usullari**: (1) **.txt fayl**, (2) matn sifatida yozish/joylash, (3) Telegram **Quiz so‘rovi** (📎 → So‘rov → Quiz) — bir necha marta yuborib qo‘shib borish mumkin. Bot «📄 Namuna fayl» va «🤖 AI uchun so‘rov» (ChatGPT/Claude orqali savol tuzish) ni ham beradi.
- **TXT format**: `#Savol`, `+to‘g‘ri`, `-noto‘g‘ri`, `!izoh`. Bir nechta `+` — ko‘p javobli savol. BOM, CRLF, cp1251, qatorga sig‘magan matn, bo‘sh qatorsiz yozuv qabul qilinadi; xatolar qator raqami bilan ko‘rsatiladi, to‘g‘ri savollar baribir qo‘shiladi. 300 belgidan uzun savol / 100 belgidan uzun variant avtomatik xabar + A, B, C harflariga o‘tkaziladi.
- **Ishlash**: savollar vaqt cheklangan so‘rovnoma (`open_period`) bo‘lib keladi, ishtirokchilar anonim emas. Savollar va variantlar aralashtiriladi (test sozlamasi), «har urinishda N ta tasodifiy savol» ham bor. Vaqt tugasa savol o‘tkaziladi; ketma-ket 2 ta o‘tkazib yuborilsa test to‘xtaydi va «▶️ Davom ettirish» tugmasi chiqadi. `/stop` — to‘xtatish.
- **Natija**: to‘g‘ri/xato/o‘tkazib yuborilgan, vaqt, reytingdagi o‘rin, «🔍 Xatolarni ko‘rish» (to‘g‘ri javoblar va izohlar bilan), qayta ishlash, do‘stlarga ulashish. Har test uchun reyting (eng yaxshi urinish: avval ball, keyin tezlik).
- **Katalog va qidiruv**: ommabop/yangi testlar; nom yozsangiz qidiradi; havola `t.me/bot?start=t<id>`; test «faqat havola orqali» bo‘lishi ham mumkin.
- **Muallif**: nom/tavsif/vaqt, aralashtirish, ommaviylik, savol qo‘shish/o‘chirish, **TXT yuklab olish**, statistika va reytingni ko‘rish.
- **Admin paneli (`/admin`)**: barcha testlarni ko‘rish/yashirish, yaratish siyosati, limit, statistika. Adminlar har qanday testni boshqara oladi.
- Poll holati bazada saqlanadi: server qayta ishga tushsa ham javoblar to‘g‘ri hisoblanadi va taymerlar qayta yoqiladi. Rejim yoqilganda webhook `poll_answer` yangilanishlariga ruxsat bilan qayta ro‘yxatdan o‘tkaziladi.
- Migratsiya `0007_quiz` (faqat yangi jadvallar).

## Kurs bot rejimi

Bot panelidagi **🎓 Kurs bot** tugmasi botni onlayn kurs platformasiga aylantiradi (o‘quv markaz, ustoz, bloger).

- **Tuzilma**: kurs → modul → dars. Dars = matn + istalgancha fayl (video, audio, PDF/hujjat, rasm). Fayllar `file_id` bilan saqlanadi, shuning uchun adminlar ularni **child botning o‘ziga** yuklaydi (`/admin` → kurs → modul → dars → «📎 Fayl qo‘shish», bir nechta faylni ketma-ket yuborib `/done`). O‘quvchilarga hammasi `protect_content` bilan (nusxalash/uzatish cheklangan) yuboriladi; adminning «👁 Ko‘rish» tugmasi himoyasiz.
- **Kirish turi** (har kurs uchun alohida): 🆓 bepul · 🔑 kirish kodi (5 ta urinish, bosh sahifadagi «Kod kiritish» ham ishlaydi) · 💰 pullik: o‘quvchi kartaga o‘tkazib, **chek rasmini** yuboradi → adminlarga rasm va «✅ Tasdiqlash / ❌ Rad etish» tugmalari boradi (rad etishda sabab yoziladi) → tasdiqlansa kurs ochiladi. Bir vaqtda bitta kutilayotgan chek; takroriy bosish xavfsiz. Karta, egasi va izoh — ⚙️ Sozlamalar. (Click/Payme keyingi bosqichda.)
- **Darslar ochilishi** (har kurs uchun): 🔓 hammasi ochiq · ➡️ ketma-ket (avvalgisini «✅ Tugatdim» qilsa keyingisi ochiladi) · 📅 jadval bo‘yicha (har N kunda bitta, ochilish soati va vaqt mintaqasi sozlanadi). Jadvalli kursda dars ochilganda o‘quvchiga avtomatik **eslatma** keladi (fon sikli; uzoq uzilishdan keyin faqat eng yangi dars haqida bitta xabar).
- **O‘quvchi**: katalog, kurs sahifasi (muqova, tavsif, dastur), «🎓 Mening kurslarim», «▶️ Davom etish», progress chizig‘i, **tanishuv darslari** (kursga yozilmasdan ko‘rish mumkin), dars bo‘yicha «❓ Savol», tugatganda 🎓 **sertifikat**. Kurs havolasi: `t.me/bot?start=c<id>`.
- **Admin paneli (`/admin`)**: kurs/modul/dars CRUD (kurs, modul va darslar yaratilgan tartibda ko‘rinadi: birinchi yaratilgani birinchi; o‘chirishda tasdiq), e’lon qilish/qoralama (pullik kursni karta va narxsiz e’lon qilib bo‘lmaydi), o‘quvchilar (qo‘lda qo‘shish/chiqarish, progress), to‘lovlar, javobsiz savollar, statistika (tushum, tugatganlar).
- Boshqa botlar kabi majburiy obuna va broadcast ishlaydi.
- Migratsiya `0008_course` (faqat yangi jadvallar). Fon sikli bitta nusxadagi ilova uchun mo‘ljallangan.

## Do‘kon bot rejimi

Bot panelidagi **🛒 Do‘kon bot** tugmasi botni onlayn do‘konga aylantiradi.

- **Katalog**: bo‘lim → mahsulot. Mahsulotda bir nechta rasm (`file_id`, adminlar child botning o‘ziga yuklaydi), narx, **eski narx** (chegirma foizi ko‘rsatiladi), ombor soni (bo‘sh = cheksiz), **variantlar** (o‘lcham/rang: har birining o‘z narxi va qoldig‘i; `nom | narx | qoldiq` qatorlari bilan qo‘shiladi, bir xil nom yangilanadi). Yashirish/ko‘rsatish, tartiblash, qidiruv, mahsulot havolasi `t.me/bot?start=p<id>`.
- **Savat**: ➕/➖/🗑, qoldiqqa moslash, sotuvdan olingan mahsulot avtomatik chiqariladi.
- **Buyurtma**: telefon (kontakt tugmasi yoki yozib; oxirgi raqam taklif qilinadi) → 🚚 yetkazish (manzil yoki lokatsiya) yoki 🏪 olib ketish → 💵 naqd yoki 💳 karta (karta raqamiga o‘tkazib **chek rasmi** yuboriladi) → tasdiqlash. Yetkazish narxi, «X so‘mdan yuqori bepul» va minimal buyurtma sozlanadi; faqat bitta variant yoqilgan bo‘lsa, savol o‘tkazib yuboriladi.
- **Ombor xavfsizligi**: qoldiq buyurtma paytida bitta `UPDATE … WHERE stock >= qty` bilan kamayadi (ikki mijoz oxirgi donani sotib ola olmaydi); biror mahsulot yetmasa butun buyurtma bekor bo‘ladi. Buyurtma bekor qilinsa (mijoz — faqat «yangi» holatda, yoki admin) qoldiq bir marta qaytariladi.
- **Admin paneli (`/admin`)**: yangi buyurtmalar adminlarga xabar bo‘lib keladi; holatlar «✅ Tasdiqlash → 👨‍🍳 Tayyorlanmoqda → 🚚 Yo‘lda / 🏪 Tayyor → ✔️ Yakunlash» (har o‘zgarishda xaridorga xabar, orqaga qaytib bo‘lmaydi), cheklarni tasdiqlash/rad etish (sabab bilan), bekor qilish; bo‘lim/mahsulot/variant CRUD; sozlamalar (karta, yetkazish, aloqa, to‘lov usullarini yoqish/o‘chirish); statistika (holatlar, tushum, ko‘p sotilgan mahsulotlar).
- Buyurtma qatorlari nusxa sifatida saqlanadi: mahsulot keyin o‘zgartirilsa yoki o‘chirilsa, eski buyurtmalar buzilmaydi. Majburiy obuna va broadcast ishlaydi. Migratsiya `0009_shop` (faqat yangi jadvallar).

Shuningdek: barcha bot turlarida tugma bosilganda Telegram’ga javob qaytariladi (tugmadagi aylanuvchi indikator qolib ketmaydi).
