#!/bin/bash
# Sensei VPS Deployment Script
# Run this on your VPS as root (or with sudo)
#
# This script:
# 1. Installs Docker, Docker Compose, Nginx, Certbot
# 2. Clones the Sensei repo
# 3. Builds frontend and backend
# 4. Sets up Nginx reverse proxy
# 5. Sets up SSL with Let's Encrypt
# 6. Starts everything
#
# Usage:
#   chmod +x deploy/vps-deploy.sh
#   ./deploy/vps-deploy.sh

set -e

DOMAIN="senseiissei.dev"
APP_DIR="/opt/sensei"

echo "=========================================="
echo "  Sensei VPS Deployment"
echo "  Domain: $DOMAIN"
echo "  Directory: $APP_DIR"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root or with sudo"
  exit 1
fi

# Step 1: Install dependencies
echo "[1/7] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx git curl ufw

# Install Docker if not present
if ! command -v docker &> /dev/null; then
  echo "  Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi

# Step 2: Clone or update repo
echo "[2/7] Cloning Sensei repository..."
if [ -d "$APP_DIR" ]; then
  echo "  Updating existing repo..."
  cd "$APP_DIR"
  git pull origin main
else
  git clone https://github.com/SenseiIssei/Sensei.git "$APP_DIR"
  cd "$APP_DIR"
fi

# Step 3: Configure environment
echo "[3/7] Setting up environment..."
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  Created .env from .env.example"
  echo "  IMPORTANT: Edit .env and add your API keys!"
  echo "  Press Enter to continue..."
  read
fi

# Set JWT secret for user auth
if ! grep -q "SENSEI_JWT_SECRET" .env; then
  JWT_SECRET=$(openssl rand -hex 32)
  echo "SENSEI_JWT_SECRET=$JWT_SECRET" >> .env
  echo "  Generated JWT secret"
fi

# Step 4: Build frontend
echo "[4/7] Building frontend..."
cd frontend
npm install --silent
npm run build
cd ..

# Step 5: Start backend with Docker
echo "[5/7] Starting backend..."
docker compose up -d --build
echo "  Waiting for backend to start..."
sleep 5

# Step 6: Configure Nginx
echo "[6/7] Configuring Nginx..."
cp deploy/nginx.conf /etc/nginx/sites-available/sensei
ln -sf /etc/nginx/sites-available/sensei /etc/nginx/sites-enabled/sensei
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# Step 7: SSL
echo "[7/7] Setting up SSL with Let's Encrypt..."
echo "  Make sure $DOMAIN points to this server's IP"
echo "  Press Enter to continue with SSL setup..."
read
certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email || true

# Firewall
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 22/tcp
ufw --force enable

echo ""
echo "=========================================="
echo "  Deployment Complete! 🎉"
echo "=========================================="
echo ""
echo "  Public chat:  https://$DOMAIN"
echo "  Dev panel:    https://$DOMAIN/#/devpanel"
echo "  API docs:     https://$DOMAIN/docs"
echo "  Health:       https://$DOMAIN/health"
echo ""
echo "  Next steps:"
echo "  1. Edit .env: nano $APP_DIR/.env"
echo "  2. Add API keys for your preferred model provider"
echo "  3. Restart: cd $APP_DIR && docker compose restart"
echo ""
echo "  To update later:"
echo "  cd $APP_DIR && git pull && cd frontend && npm run build && cd .. && docker compose restart"
echo ""
echo "  💚 Stay awesome! 🚀"
