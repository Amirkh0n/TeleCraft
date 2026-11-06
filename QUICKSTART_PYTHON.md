# 🚀 TeleCraft Quick Start - Python Only (No Docker)

## 📋 Prerequisites
- Python 3.11 or higher
- Telegram Bot Token (get it from @BotFather)

## ⚡ Quick Start (3 Steps)

### Step 1: Install Requirements

**Option A: Using requirements.txt**
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

**Option B: Install packages individually**
```bash
pip install python-telegram-bot==22.* fastapi uvicorn[standard] sqlalchemy aiosqlite pydantic pydantic-settings python-dotenv prometheus-client
```

### Step 2: Configure Environment

```bash
# Copy environment template
copy .env.example .env

# Edit .env file and add your Telegram token
notepad .env  # Windows
nano .env     # Linux/Mac
```

Add your token:
```env
TELEGRAM_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
DATABASE_URL=sqlite+aiosqlite:///./constructor.db
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000
LOG_LEVEL=INFO
DEBUG=False
```

### Step 3: Initialize Database

```bash
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"
```

## 🎯 Run TeleCraft

**Terminal 1 - Constructor Bot:**
```bash
python start.py
```

**Terminal 2 - Webhook Server:**
```bash
python webhook_start.py
```

## 📝 What to Expect

1. **Constructor Bot** - This will be the interface you use to create bots
2. **Webhook Server** - This handles your created bots

## 🧪 Test Your Setup

1. Open Telegram and send `/start` to your constructor bot
2. Click "➕ Bot qo'shish" and paste your BotFather token
3. Your bot will be created!

## 🛑 Stop TeleCraft

Press `Ctrl+C` in each terminal to stop the services.

## 🔄 Restart TeleCraft

1. Press `Ctrl+C` in both terminals
2. Run the startup commands again:
   ```bash
   python start.py        # Terminal 1
   python webhook_start.py # Terminal 2
   ```

## ✅ Verification

Run the setup checker:
```bash
python verify_setup.py
```

This will verify:
- Python version
- Virtual environment
- Required packages
- Environment configuration
- Database initialization

## 📚 Full Documentation

See `RUNNING_GUIDE.md` for detailed instructions and troubleshooting.

## 🆘 Common Issues

**Issue: "Module not found"**
```bash
pip install -r requirements.txt
```

**Issue: ".env file not found"**
```bash
copy .env.example .env
```

**Issue: Database errors**
```bash
rm constructor.db
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"
```

**Issue: Port in use**
```bash
# Change WEBHOOK_PORT in .env to 8001
WEBHOOK_PORT=8001
```

## 🎉 You're Ready!

Start TeleCraft:
```bash
python start.py    # Terminal 1
python webhook_start.py # Terminal 2
```

See your first bot created in seconds! 🚀
