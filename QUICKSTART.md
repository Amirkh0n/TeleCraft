# 🚀 Quick Start Guide

## 📦 Prerequisites

- Python 3.11+
- Docker (optional, but recommended)
- Telegram Bot Token (from @BotFather)

## 🏃 Quick Start (Docker)

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/telecraft.git
cd telecraft

# 2. Copy environment template
cp .env.example .env

# 3. Edit .env with your token
nano .env  # Add your TELEGRAM_TOKEN

# 4. Start with Docker Compose
docker-compose up -d

# 5. Check logs
docker-compose logs -f

# 6. Initialize database
docker exec -it telecraft_constructor python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"
```

## ⚡ Quick Start (Python)

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/telecraft.git
cd telecraft

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment template
cp .env.example .env

# 5. Edit .env with your token
nano .env

# 6. Initialize database
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"

# 7. Start the constructor bot
python run_constructor.py

# 8. Start the webhook server (new terminal)
uvicorn app.main:app --reload
```

## 📝 First Steps

1. **Add your bot**:
   - Send `/start` to the constructor bot
   - Click "➕ Bot qo'shish"
   - Paste your BotFather token
   - Done! Your bot is created

2. **Create menus**:
   - Click on your bot
   - Click "📁 Menular"
   - Click "➕ Menu qo'shish"
   - Enter menu name

3. **Add buttons**:
   - Click on your menu
   - Click "➕ Tugma qo'shish"
   - Enter button text
   - Choose action type

4. **Test your bot**:
   - Send `/start` command to your created bot
   - Try buttons and menus

## 🔧 Common Commands

### Docker
```bash
# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Restart services
docker-compose restart

# Update code
git pull
docker-compose up -d --build

# View database
docker exec -it telecraft_constructor sqlite3 constructor.db "SELECT * FROM users;"
```

### Python
```bash
# Run tests
pytest tests/ -v

# Check code style
black --check .
isort --check-only .
flake8 .

# Create database
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"

# Seed database (for testing)
python seed.py
```

## 📊 Monitoring

### Health Check
```bash
curl http://localhost:8000/health
```

### Metrics
```bash
curl http://localhost:8000/metrics
```

### Database Stats
Send `/start` to your bot and check the bot statistics.

## 🐛 Troubleshooting

### Bot not starting
```bash
# Check if port is already in use
netstat -ano | findstr :8000
```

### Database errors
```bash
# Reset database
docker-compose down -v
docker-compose up -d
```

### Import errors
```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

## 📱 Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/help` | Show help |

## 🔗 Useful Links

- [Python Telegram Bot Docs](https://docs.python-telegram-bot.org/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Docker Docs](https://docs.docker.com/)

## 💡 Tips

1. Use environment variables for sensitive data
2. Enable DEBUG mode for development
3. Use PostgreSQL for production with 50+ bots
4. Monitor logs regularly
5. Set up backups for your database

## 🆘 Support

- Email: support@telecraft.app
- GitHub Issues: [Create Issue](https://github.com/yourusername/telecraft/issues)

## 🎯 Next Steps

- Add bot testing mode
- Implement export/import
- Add bulk operations
- Set up monitoring dashboard
- Configure automated backups

## 📚 Full Documentation

See the main [README.md](README.md) for complete documentation.

---

**Ready to build your first Telegram bot? Let's go! 🚀**
