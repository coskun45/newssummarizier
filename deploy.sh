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

    # Tek seferlik göç: eski git-tracked db dosyalarını çalışma ağacından
    # çıkar, yoksa 'git pull' onları canlı veriyle birlikte silip üzerine yazar.
    mkdir -p data
    if [ -f backend/news_summary.db ] && [ ! -f data/news_summary.db ]; then
        mv backend/news_summary.db data/news_summary.db
        info "news_summary.db → data/ dizinine taşındı"
    fi
    if [ -f backend/checkpoints.db ] && [ ! -f data/checkpoints.db ]; then
        mv backend/checkpoints.db data/checkpoints.db
    fi

    # Eski deploy.sh sürümleri docker-compose.yml'i sunucuda sed ile değiştiriyordu
    # (JWT secret, IP); artık tüm ayarlar .env'de — yerel değişikliği at ki pull çakışmasın.
    git checkout -- docker-compose.yml
    git pull
else
    warn "Repo klonlanıyor..."
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi
info "Kod hazır: $APP_DIR"

# ── 3. Sunucu IP'si (CORS için) ───────────────────────────────────────────────
SERVER_IP=$(curl -s --max-time 5 ifconfig.me || curl -s --max-time 5 api.ipify.org)
if [ -z "$SERVER_IP" ]; then
    error "Sunucu IP'si alınamadı. İnternet bağlantısını kontrol et."
fi

# ── 4. Tek yapılandırma dosyası: repo kökündeki .env ─────────────────────────
# Modeller, token/maliyet limitleri, CORS, JWT, POSTGRES_* ve secret'lar hep bu
# dosyada. Şablon: .env.example. Dosya yoksa üretilir; eski düzenden kalan
# backend/.env varsa içeriği taşınır (scripts/ensure_env.py). Git-ignore'lu
# olduğu için sonraki deploy'larda kalıcıdır.
ENV_FILE="$APP_DIR/.env"

if [ ! -f "$ENV_FILE" ] && [ ! -f "$APP_DIR/backend/.env" ]; then
    warn ".env bulunamadı, oluşturuluyor..."
    echo ""
    read -p "  OpenAI API Key girin (sk-proj-...): " OPENAI_API_KEY
    echo ""
    read -p "  İlk admin e-posta adresi girin: " ADMIN_EMAIL
    ADMIN_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(18))")
    echo ""
    info "İlk admin şifresi üretildi: $ADMIN_PASSWORD"
    warn "Bu şifreyi şimdi bir yere kaydet — tekrar gösterilmeyecek."
    echo ""
    export OPENAI_API_KEY ADMIN_EMAIL ADMIN_PASSWORD
fi

python3 scripts/ensure_env.py --server-ip "$SERVER_IP"
info "CORS_ORIGINS → http://$SERVER_IP (varsayılandaysa)"

# ── 7. Build & Start ──────────────────────────────────────────────────────────
echo ""
warn "Docker imajları build ediliyor (ilk seferde birkaç dakika sürebilir)..."
docker compose build --no-cache

# Postgres'i backend'den ÖNCE, tek başına ayağa kaldır — backend her
# başlangıçta seed_database() çalıştırır (topics/feeds/system_prompts'a
# idempotent seed verisi ekler); eski SQLite verisi varsa migrasyon bundan
# ÖNCE çalışmalı, yoksa aynı satırları ikinci kez eklemeye çalışıp unique
# constraint hatası alır (bkz. README "Veritabanı Kalıcılığı").
echo ""
warn "PostgreSQL başlatılıyor..."
docker compose up -d db

LEGACY_DB_FILE="$APP_DIR/data/news_summary.db"
if [ -f "$LEGACY_DB_FILE" ]; then
    warn "Eski SQLite verisi bulundu ($LEGACY_DB_FILE), Postgres'e taşınıyor..."
    docker compose run --rm backend python migrate_sqlite_to_postgres.py \
        --sqlite-path /app/data/news_summary.db
    info "SQLite → Postgres migrasyonu tamamlandı"
fi

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
