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
- Broadcast va majburiy obuna hozircha konstruktor bot ichida; muharrirga keyingi bosqichda ko‘chiriladi.

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
