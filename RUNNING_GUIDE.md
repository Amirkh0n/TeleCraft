# 🚀 Running TeleCraft without Docker

## 📦 Prerequisites

1. **Python 3.11+** installed
2. **Telegram Bot Token** (from BotFather)
3. **Git** (optional, for cloning)

## 🔧 Installation Steps

### Step 1: Install Dependencies

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### Step 2: Setup Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env file
nano .env
```

Add your Telegram bot token:
```env
TELEGRAM_TOKEN=your_bot_token_here
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

## 🎯 Running TeleCraft

TeleCraft has **two main components** that need to run:

### 1. Constructor Bot (Tunboshlanish Bot)

The constructor bot manages your Telegram bot creations.

**Start in Terminal 1:**
```bash
python start.py
```

This will:
- Initialize the database
- Start the constructor bot
- Show logs in the console

### 2. Webhook Server (Webhook Server)

The webhook server handles incoming updates for your created bots.

**Start in Terminal 2:**
```bash
python webhook_start.py
```

This will:
- Initialize the database
- Start FastAPI webhook server
- Make bots accessible to users

## 📝 Using Windows Batch Script (Easiest)

Windows users can use the batch script:

```bash
# Double-click start.bat OR run from terminal
start.bat
```

This will:
1. Create virtual environment if needed
2. Install dependencies if needed
3. Create .env file if needed
4. Start constructor bot in a new window
5. Start webhook server in current window

## 🐧 Using Linux/Mac Script

Linux/Mac users can use the shell script:

```bash
# Make script executable
chmod +x start.sh

# Run script
./start.sh
```

## 🧪 Testing the Setup

### 1. Test Constructor Bot

1. Send `/start` to your constructor bot
2. Click "➕ Bot qo'shish"
3. Paste your BotFather token
4. Check that bot is created

### 2. Test Webhook Server

Check if webhook server is running:

```bash
# Health check
curl http://localhost:8000/health

# Expected response:
# {"status":"healthy"}
```

## 🔍 Managing Multiple Terminals

### Option 1: Two Separate Terminals
- Terminal 1: `python start.py`
- Terminal 2: `python webhook_start.py`

### Option 2: Use tmux (Linux/Mac)
```bash
# Create new tmux session
tmux new -s telecraft

# Split window
Ctrl+B, %

# Run constructor in first pane
python start.py

# Switch to second pane
Ctrl+B, arrow key

# Run webhook in second pane
python webhook_start.py
```

### Option 3: Use tmuxp (Save sessions)
```bash
pip install tmuxp
# Configure tmuxp.json for your setup
```

## 🛑 Stopping TeleCraft

### Stop Constructor Bot
In Terminal 1, press: `Ctrl+C`

### Stop Webhook Server
In Terminal 2, press: `Ctrl+C`

## 🔄 Restarting TeleCraft

```bash
# 1. Stop both services (Ctrl+C in each terminal)

# 2. Start constructor bot again
python start.py

# 3. Start webhook server again
python webhook_start.py
```

## 📊 Monitoring

### Constructor Bot Logs
Look at the console output for constructor bot:
```
2024-11-03 10:00:00 - INFO - telecraft.bot - Bot starting...
```

### Webhook Server Logs
Look at the console output for webhook server:
```
2024-11-03 10:00:01 - INFO - uvicorn - Application startup complete.
```

### Health Check
```bash
curl http://localhost:8000/health
```

### Metrics
```bash
curl http://localhost:8000/metrics
```

## ⚙️ Configuration Options

Edit `.env` file to change:

```env
TELEGRAM_TOKEN=your_token          # Your constructor bot token
DATABASE_URL=sqlite+aiosqlite:///./constructor.db
WEBHOOK_HOST=0.0.0.0               # Host for webhook server
WEBHOOK_PORT=8000                  # Port for webhook server
LOG_LEVEL=INFO                     # DEBUG, INFO, WARNING, ERROR
DEBUG=False                        # Enable for development
```

## 🔧 Troubleshooting

### Issue: "Module not found" error

**Solution:**
```bash
pip install -r requirements.txt
```

### Issue: ".env file not found"

**Solution:**
```bash
cp .env.example .env
# Edit .env and add your token
```

### Issue: Database errors

**Solution:**
```bash
# Reset database
rm constructor.db
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"
```

### Issue: Port already in use

**Solution:**
```bash
# Change WEBHOOK_PORT in .env to another port
WEBHOOK_PORT=8001
# Or stop the process using port 8000
# Windows: netstat -ano | findstr :8000
# Linux/Mac: lsof -i :8000
```

### Issue: Can't connect to Telegram

**Solution:**
- Check your internet connection
- Verify TELEGRAM_TOKEN is correct
- Check Telegram service status

## 📱 Testing Your Bots

1. **Create a bot** via constructor bot
2. **Test your bot** by sending `/start` to it
3. **Check bot works** with your configured menus and buttons

## 🎯 Next Steps

1. **Edit `.env`** with your settings
2. **Initialize database** with the command above
3. **Start both services** in two terminals
4. **Create your first bot**
5. **Test your bot**

## 💡 Pro Tips

1. **Use tmux** to manage multiple sessions easily
2. **Set DEBUG=True** during development
3. **Use LOG_LEVEL=DEBUG** for detailed logs
4. **Keep logs in a file** for debugging
5. **Backup your database** regularly

## 🆘 Getting Help

- Check logs in console output
- Review error messages
- Check `.env` file settings
- Verify Python version (3.11+)

---

**Ready to start? Run: `python start.py` in Terminal 1**
**Webhook: `python webhook_start.py` in Terminal 2** 🚀
