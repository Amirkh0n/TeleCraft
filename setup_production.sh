#!/bin/bash

# Production Setup Script
# This script will prepare TeleCraft for production deployment

set -e

echo "======================================"
echo "TeleCraft Production Setup"
echo "======================================"
echo ""

# Function to print colored messages
print_success() {
    echo -e "\033[0;32m✅ $1\033[0m"
}

print_info() {
    echo -e "\033[1;33mℹ️  $1\033[0m"
}

print_error() {
    echo -e "\033[0;31m❌ $1\033[0m"
}

# Step 1: Check Python version
print_info "Checking Python version..."
python_version=$(python --version 2>&1 | awk '{print $2}')
python_major=$(echo $python_version | cut -d. -f1)
python_minor=$(echo $python_version | cut -d. -f2)

if [ "$python_major" -lt 3 ] || ([ "$python_major" -eq 3 ] && [ "$python_minor" -lt 11 ]); then
    print_error "Python 3.11+ required. Found: $python_version"
    exit 1
fi

print_success "Python $python_version found"

# Step 2: Create virtual environment
print_info "Creating production virtual environment..."
python -m venv venv
source venv/bin/activate

# Step 3: Install production dependencies
print_info "Installing production dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

print_success "Dependencies installed"

# Step 4: Check PostgreSQL installation
print_info "Checking PostgreSQL installation..."
if command -v psql &> /dev/null; then
    print_success "PostgreSQL found"
else
    print_error "PostgreSQL not found!"
    print_info "Please install PostgreSQL: sudo apt-get install postgresql"
    exit 1
fi

# Step 5: Create PostgreSQL database and user
print_info "Setting up PostgreSQL database..."
sudo -u postgres psql << EOF
-- Create user if not exists
DO
\$\$BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'telecraft_user') THEN
        CREATE ROLE telecraft_user WITH LOGIN PASSWORD 'telecraft_password';
    END IF;
END
\$\$;

-- Create database if not exists
DO
\$\$BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'telecraft_db') THEN
        CREATE DATABASE telecraft_db OWNER telecraft_user;
    END IF;
END
\$\$;

-- Grant permissions
GRANT ALL PRIVILEGES ON DATABASE telecraft_db TO telecraft_user;
EOF

print_success "Database and user created"

# Step 6: Copy environment file
print_info "Copying environment file..."
if [ ! -f ".env.production" ]; then
    print_error ".env.production file not found!"
    exit 1
fi

cp .env.production .env
print_success "Environment file created"

# Step 7: Edit .env file with your details
print_info "Please edit .env file with your configuration:"
print_info "nano .env"
print_info "1. Update TELEGRAM_TOKEN"
print_info "2. Update WEBHOOK_HOST to your server IP"
print_info "3. Update DATABASE_URL with your PostgreSQL credentials"

read -p "Press Enter when you're done editing .env..."

# Step 8: Initialize database
print_info "Initializing database..."
python -c "from core.database import init_models; import asyncio; asyncio.run(init_models())"
print_success "Database initialized"

# Step 9: Create systemd service
print_info "Creating systemd service..."
sudo tee /etc/systemd/system/telecraft.service > /dev/null << EOF
[Unit]
Description=TeleCraft Constructor Bot
After=network.target postgresql.service

[Service]
Type=simple
User=telecraft
Group=telecraft
WorkingDirectory=$(pwd)
Environment="PATH=$(pwd)/venv/bin"
ExecStart=$(pwd)/venv/bin/gunicorn app.main:app -k uvicorn.workers.UvicornWorker --workers 4 --bind 0.0.0.0:8000 --timeout 120
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Step 10: Create telecraft user
print_info "Creating telecraft system user..."
sudo useradd -r -s /bin/false telecraft 2>/dev/null || true
sudo chown -R telecraft:telecraft $(pwd)
print_success "System user created"

# Step 11: Reload systemd and enable service
print_info "Enabling and starting TeleCraft service..."
sudo systemctl daemon-reload
sudo systemctl enable telecraft
sudo systemctl start telecraft

print_success "TeleCraft service started"

# Step 12: Check service status
print_info "Checking service status..."
sudo systemctl status telecraft

# Step 13: Setup firewall
print_info "Setting up firewall..."
if command -v ufw &> /dev/null; then
    sudo ufw allow 8000/tcp
    print_success "Firewall configured"
fi

# Step 14: Setup SSL (optional)
print_info "SSL Certificate setup (Optional)..."
print_info "For production, you should set up SSL with Nginx or Apache"
print_info "See PRODUCTION_DEPLOYMENT.md for detailed SSL configuration"

echo ""
echo "======================================"
print_success "Production Setup Complete!"
echo "======================================"
echo ""
echo "Service Status: $(sudo systemctl is-active telecraft)"
echo "Webhook URL: http://YOUR_SERVER_IP:8000/webhook/{token}"
echo ""
echo "Useful commands:"
echo "  Start: sudo systemctl start telecraft"
echo "  Stop:  sudo systemctl stop telecraft"
echo "  Restart: sudo systemctl restart telecraft"
echo "  Logs: sudo journalctl -u telecraft -f"
echo ""
