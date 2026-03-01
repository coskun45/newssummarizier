#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# News Summarizer — Deploy Script
# Kullanım: bash deploy.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

REPO_URL="https://github.com/coskun45/newssummarizier.git"
APP_DIR="$HOME/newssummarizier"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[✓]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }
error()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}   News Summarizer — Deploy${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# ── 1. Bağımlılık kontrolü ────────────────────────────────────────────────────
command -v docker >/dev/null 2>&1 || error "Docker kurulu değil. Önce Docker kur."
docker compose version >/dev/null 2>&1 || error "Docker Compose kurulu değil."
command -v git >/dev/null 2>&1    || error "Git kurulu değil."

# ── 2. Repo: clone veya pull ──────────────────────────────────────────────────
if [ -d "$APP_DIR/.git" ]; then
    warn "Repo mevcut, güncelleniyor..."
    cd "$APP_DIR"
    git pull
else
    warn "Repo klonlanıyor..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi
info "Kod hazır: $APP_DIR"

# ── 3. backend/.env oluştur (ilk kurulumda) ───────────────────────────────────
ENV_FILE="$APP_DIR/backend/.env"

if [ ! -f "$ENV_FILE" ]; then
    warn "backend/.env bulunamadı, oluşturuluyor..."
    echo ""
    read -p "  OpenAI API Key girin (sk-proj-...): " OPENAI_KEY
    echo ""

    cat > "$ENV_FILE" <<EOF
# OpenAI
OPENAI_API_KEY=$OPENAI_KEY

# Database
DATABASE_URL=sqlite:///./news_summary.db
CHECKPOINTS_DB=checkpoints.db

# App
APP_NAME=News Summarizer
APP_VERSION=1.0.0
DEBUG=False

# RSS
DEFAULT_FEED_URL=https://rss.dw.com/atom/rss-de-all
FEED_REFRESH_INTERVAL=1800

# Scraping
SCRAPING_ENABLED=True
SCRAPING_DELAY=1.0
MAX_RETRIES=3

# OpenAI modeller
DEFAULT_MODEL=gpt-4o-mini
DETAILED_MODEL=gpt-4o
MAX_TOKENS_INPUT=40000
MAX_TOKENS_OUTPUT_BRIEF=1500
MAX_TOKENS_OUTPUT_STANDARD=3000
MAX_TOKENS_OUTPUT_DETAILED=10000

# Maliyet limiti
DAILY_COST_LIMIT=10.0
MONTHLY_COST_LIMIT=100.0

# CORS (docker-compose.yml override eder)
CORS_ORIGINS=http://localhost:5173
EOF
    info "backend/.env oluşturuldu"
else
    info "backend/.env mevcut, atlanıyor"
fi

# ── 4. JWT_SECRET_KEY üret / kontrol et ──────────────────────────────────────
SECRETS_FILE="$APP_DIR/.jwt_secret"

if [ ! -f "$SECRETS_FILE" ]; then
    JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "$JWT_SECRET" > "$SECRETS_FILE"
    chmod 600 "$SECRETS_FILE"
    info "JWT_SECRET_KEY üretildi → $SECRETS_FILE"
else
    JWT_SECRET=$(cat "$SECRETS_FILE")
    info "JWT_SECRET_KEY mevcut, kullanılıyor"
fi

export JWT_SECRET_KEY="$JWT_SECRET"

# docker-compose.yml içindeki fallback değeri gerçek secret ile değiştir
sed -i "s|JWT_SECRET_KEY: \${JWT_SECRET_KEY:-.*}|JWT_SECRET_KEY: \"$JWT_SECRET\"|" docker-compose.yml
info "JWT_SECRET_KEY docker-compose.yml'e yazıldı"

# ── 5. CORS — sunucu IP'sini ayarla ──────────────────────────────────────────
SERVER_IP=$(curl -s --max-time 5 ifconfig.me || curl -s --max-time 5 api.ipify.org)
if [ -z "$SERVER_IP" ]; then
    error "Sunucu IP'si alınamadı. İnternet bağlantısını kontrol et."
fi

sed -i "s|CORS_ORIGINS: \"http://.*\"|CORS_ORIGINS: \"http://$SERVER_IP\"|" docker-compose.yml
info "CORS_ORIGINS → http://$SERVER_IP"

# TODO satırını da temizle
sed -i '/# TODO: Replace YOUR_SERVER_IP/d' docker-compose.yml

# ── 6. SQLite DB dosyası ve izinleri ─────────────────────────────────────────
DB_FILE="$APP_DIR/backend/news_summary.db"
if [ ! -f "$DB_FILE" ]; then
    touch "$DB_FILE"
    info "news_summary.db oluşturuldu"
fi
chown 1001:1001 "$DB_FILE"
info "DB dosyası izinleri ayarlandı (UID 1001)"

# ── 7. Build & Start ──────────────────────────────────────────────────────────
echo ""
warn "Docker imajları build ediliyor (ilk seferde birkaç dakika sürebilir)..."
docker compose build --no-cache

echo ""
warn "Servisler başlatılıyor..."
docker compose up -d

# ── 8. Durum kontrolü ────────────────────────────────────────────────────────
echo ""
warn "Servisler hazır olana kadar bekleniyor (30s)..."
sleep 30

docker compose ps

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}   Deploy tamamlandı!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  Uygulama:  ${GREEN}http://$SERVER_IP${NC}"
echo -e "  Loglar:    docker compose logs -f"
echo ""
