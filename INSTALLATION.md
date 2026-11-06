# 📚 Installation Guide - TeleCraft

## 🎯 Quick Start (3 Steps)

### 1️⃣ Install Python Requirements
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2️⃣ Setup Configuration
```bash
cp .env.example .env
# Edit .env and add your TELEGRAM_TOKEN
```

### 3️⃣ Initialize Database
```bash
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"
```

## 🚀 Run TeleCraft

**Terminal 1:**
```bash
python start.py
```

**Terminal 2:**
```bash
python webhook_start.py
```

## ✅ Complete Installation Checklist

- [ ] Python 3.11+ installed
- [ ] Virtual environment created
- [ ] Dependencies installed
- [ ] `.env` file created and configured
- [ ] Database initialized
- [ ] Constructor bot running
- [ ] Webhook server running

## 📋 Windows Installation

### Option 1: Using start.bat
```bash
# Double-click start.bat OR
start.bat
```

### Option 2: Manual
```bash
# Create virtual environment
python -m venv venv
call venv\Scripts\activate.bat

# Install dependencies
pip install -r requirements.txt

# Setup environment
copy .env.example .env
notepad .env  # Add your token

# Initialize database
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"

# Start TeleCraft
# Terminal 1: python start.py
# Terminal 2: python webhook_start.py
```

## 🐧 Linux/Mac Installation

### Option 1: Using start.sh
```bash
# Make executable
chmod +x start.sh

# Run script
./start.sh
```

### Option 2: Manual
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
nano .env  # Add your token

# Initialize database
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"

# Start TeleCraft
# Terminal 1: python start.py
# Terminal 2: python webhook_start.py
```

## 🔧 Configuration Guide

### .env File Options

```env
# Required
TELEGRAM_TOKEN=your_constructor_bot_token_here

# Optional - Database
DATABASE_URL=sqlite+aiosqlite:///./constructor.db
# For production with PostgreSQL:
# DATABASE_URL=postgresql://user:password@localhost/telecraft

# Webhook Server
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000

# Logging
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT=json  # json or text

# Performance
MAX_CONNECTIONS=20
CONNECTION_POOL_SIZE=10

# Rate Limiting
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW=60

# User Management
ADMIN_IDS=123456789,987654321

# Environment
DEBUG=False  # Set to True for development
TESTING=False
```

## 📊 Directory Structure

After installation, you should have:

```
TeleCraft/
├── venv/                 # Virtual environment (created)
├── constructor.db        # Database (created)
├── .env                  # Environment config
├── start.py              # Constructor bot startup
├── webhook_start.py      # Webhook server startup
├── requirements.txt      # Python dependencies
├── app/                  # Webhook server
├── constructor/          # Constructor bot
├── core/                 # Core utilities
├── engine/               # Bot engine
├── models/               # Database models
├── tests/                # Test suite
├── data/                 # Data directory
├── logs/                 # Logs directory
└── *.md                  # Documentation
```

## ✨ What Each Component Does

### 1. Constructor Bot (start.py)
- Creates and manages Telegram bots
- Builds menus and buttons
- Configures bot actions
- User interface for bot construction

### 2. Webhook Server (webhook_start.py)
- Handles incoming updates for user bots
- Processes user interactions
- Executes bot actions
- Serves API endpoints

## 🧪 Testing Installation

### Test 1: Constructor Bot
1. Send `/start` to your constructor bot
2. Should see "Sizning botlaringiz:" message

### Test 2: Webhook Server
```bash
# Check if server is running
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy"}
```

### Test 3: Health Check
```bash
# Constructor bot
# Should start without errors

# Webhook server
# Should show "Application startup complete"
```

## 🔄 Update After Code Changes

```bash
# Stop both services (Ctrl+C)

# Reinstall dependencies if changed
pip install -r requirements.txt

# Restart services
python start.py        # Terminal 1
python webhook_start.py # Terminal 2
```

## 🛑 Maintenance

### Database Backup
```bash
# Backup database
cp constructor.db constructor.db.backup

# Restore from backup
cp constructor.db.backup constructor.db
```

### Logs
Logs are printed to console. For persistent logs:
```bash
# Run with logging to file
python start.py > logs/startup.log 2>&1
```

### Update Requirements
```bash
# Check for updates
pip list --outdated

# Update requirements
pip install --upgrade -r requirements.txt
```

## 🆘 Common Issues

### Issue: Module not found
```bash
pip install -r requirements.txt
```

### Issue: Database locked
```bash
# Close all processes accessing database
rm constructor.db
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"
```

### Issue: Port in use
```bash
# Change WEBHOOK_PORT in .env
WEBHOOK_PORT=8001
```

### Issue: Can't import modules
```bash
# Activate virtual environment
source venv/bin/activate  # Windows: venv\Scripts\activate
```

## 📞 Support

If you encounter issues:
1. Check the error messages
2. Verify Python version (3.11+)
3. Ensure .env file is configured
4. Check virtual environment is active
5. Review logs in console

## ✅ Quick Verify Command

Run this command to verify installation:

```bash
# Should print: Database initialized successfully!
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"
```

---

**Installation Complete! Ready to run: `python start.py` 🚀**
