# Bülten

Deutsche Welle (DW) RSS beslemelerinden haber toplayan, kategorize eden ve yapay zeka ile özetleyen akıllı haber toplama ve özet sistemi.

## 🎯 Özellikler

- **Otomatik RSS İşleme**: DW haberlerini otomatik olarak çeker ve işler
- **Yapay Zeka Tabanlı Kategorizasyon**: Makaleleri otomatik olarak konulara ayırır (Politika, Ekonomi, Teknoloji vb.)
- **Çoklu Format Özetler**: Kısa, standart ve detaylı özetler oluşturur
- **Web Scraping**: Web sitelerinden tam makale içeriğini çıkarır (robots.txt uyumlu)
- **İnteraktif Dashboard**: Arama ve filtreleme ile React tabanlı kullanıcı arayüzü
- **Maliyet Takibi**: Yapılandırılabilir limitlerle OpenAI API maliyetlerini izler
- **LangGraph Workflow**: Karmaşık işleme hatları için sağlam agent orkestrasyon

## 🏗️ Mimari

### Backend

- **FastAPI**: Otomatik OpenAPI dokümantasyonu ile modern, hızlı API
- **LangGraph**: Çok-ajanlı iş akışı orkestrasyon
- **SQLite**: Makaleler, özetler ve meta veriler için hafif veritabanı
- **OpenAI**: Kategorizasyon ve özetleme için GPT-3.5-turbo ve GPT-4

### Frontend

- **React 18**: TypeScript ile modern kullanıcı arayüzü
- **Vite**: Hızlı build aracı ve geliştirme sunucusu
- **TanStack Query**: Verimli veri çekme ve önbellekleme
- **Responsive Tasarım**: Masaüstü, tablet ve mobilde çalışır

## 📋 Gereksinimler

### Manuel Çalıştırma
- **Python 3.9+**
- **Node.js 18+** ve npm
- **OpenAI API Key** ([buradan edinin](https://platform.openai.com/api-keys))

### Docker ile Çalıştırma (önerilen)
- **Docker** 24+
- **Docker Compose** v2+
- **OpenAI API Key**

## 🚀 Kurulum

### 1. Repository'yi klonlayın

```bash
git clone https://github.com/Hid49/Bulten.git
cd Bulten
```

### 2. Backend kurulumu

```bash
cd backend

# Sanal ortam oluştur
python -m venv venv

# Sanal ortamı aktifleştir
# Windows:
venv\Scripts\activate
# Linux/Mac:
# source venv/bin/activate

# Bağımlılıkları yükle
pip install -r requirements.txt

# .env dosyası oluştur
copy .env.example .env
# veya Linux/Mac'te:
# cp .env.example .env
```

**Önemli**: `.env` dosyasını açın ve OpenAI API Key'inizi ekleyin:

```env
OPENAI_API_KEY=sk-your-actual-api-key-here
```

### 3. Frontend kurulumu

```bash
cd ../frontend

# Bağımlılıkları yükle
npm install
```

## 🎮 Uygulamayı Başlatma

### Backend'i başlat (Terminal 1)

```bash
cd backend
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

uvicorn app.main:app --reload
```

Backend şu adreste çalışır: **http://localhost:8000**

- API Dokümantasyon: **http://localhost:8000/docs**
- Health Check: **http://localhost:8000/health**

### Frontend'i başlat (Terminal 2)

```bash
cd frontend
npm run dev
```

Frontend şu adreste çalışır: **http://localhost:5173**

## 🐳 Docker

Uygulamayı başlatmanın en kolay yolu Docker Compose kullanmaktır. Backend ve frontend otomatik olarak build edilir ve başlatılır – Python ortamları veya Node.js kurulumu gerekmez.

### Gereksinimler

- **Docker** 24+
- **Docker Compose** v2+ (Docker Desktop ile birlikte gelir)

### Hızlı Başlangıç

**1. Backend dizininde `.env` dosyası oluşturun:**

```bash
cp backend/.env.example backend/.env
```

`backend/.env` dosyasını açın ve OpenAI API Key'inizi girin:

```env
OPENAI_API_KEY=sk-your-actual-api-key-here
```

**2. İsteğe bağlı: JWT Secret ayarlayın (production için önerilir):**

```bash
# Shell'de ortam değişkeni olarak ayarla
export JWT_SECRET_KEY="your-very-strong-random-secret"
```

Ya da proje kök dizininde `.env` dosyası oluşturun:

```env
JWT_SECRET_KEY=your-very-strong-random-secret
```

**3. Container'ları build edin ve başlatın:**

```bash
docker compose up --build
```

İlk başlatmada image'lar build edilir (yaklaşık 2-3 dakika). Sonrasında:

| Servis   | URL                         |
| -------- | --------------------------- |
| Frontend | http://localhost            |
| Backend API | http://localhost/api     |
| API Docs | http://localhost/api/docs   |

> Frontend **80** portunda çalışır. Nginx reverse proxy `/api` isteklerini otomatik olarak backend'e yönlendirir.

### Yararlı Docker Komutları

```bash
# Container'ları arka planda başlat
docker compose up -d --build

# Logları göster
docker compose logs -f

# Sadece Backend logları
docker compose logs -f backend

# Container'ları durdur
docker compose down

# Container'ları durdur ve Volume'leri sil (Veritabanı sıfırlanır!)
docker compose down -v

# Image'ları yeniden build et (kod değişikliklerinden sonra)
docker compose build --no-cache

# Container durumunu kontrol et
docker compose ps
```

### Ortam Değişkenleri (docker-compose.yml)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `OPENAI_API_KEY` | – | **(Zorunlu)** OpenAI API Key |
| `JWT_SECRET_KEY` | `change-me-use-a-strong-secret-in-production` | JWT imza anahtarı |
| `DATABASE_URL` | `sqlite:////app/data/news_summary.db` | Container içinde veritabanı yolu |
| `DEBUG` | `false` | Debug modu |
| `CORS_ORIGINS` | `http://localhost,http://localhost:80` | İzin verilen CORS origin'leri |

### Veritabanı Kalıcılığı

SQLite veritabanı host'a volume olarak mount edilir:

```yaml
volumes:
  - ./backend/news_summary.db:/app/data/news_summary.db
```

Bu şu anlama gelir: Veriler `docker compose down` sonrasında bile korunur. Sadece `docker compose down -v` veritabanını siler.

### Proje Yapısı (Docker ile)

```
Bulten/
├── backend/
│   ├── Dockerfile          # Python 3.12-slim Image
│   ├── .env                # Ortam değişkenleri (Git'e eklemeyin!)
│   └── ...
├── frontend/
│   ├── Dockerfile          # Multi-Stage: Node build → Nginx serve
│   ├── nginx.conf          # Nginx Konfigürasyonu (API-Proxy + SPA-Fallback)
│   └── ...
├── docker-compose.yml      # Servis orkestrasyon
└── README.md
```

---

## 📖 Kullanım

### İlk Adımlar

1. **Backend'i başlat**: Sistem otomatik olarak:
   - SQLite veritabanını oluşturur
   - Kategorileri ekler (Politika, Ekonomi, Teknoloji vb.)
   - DW RSS Feed'ini ekler
   - Arka planda ilk veri çekmeyi başlatır

2. **Frontend'i aç**: http://localhost:5173 adresine gidin

3. **Makaleler belirir**: 1-2 dakika sonra makaleler görünmeye başlar

### Dashboard Özellikleri

- **Konu Filtresi**: Filtrelemek için sidebar'daki konulara tıklayın
- **Arama**: Makale başlığı ve içeriğinde arama yapın
- **Özetleri Göster**:
  - "Özeti Göster"e tıklayın
  - Kısa, Standart, Detaylı arasından seçin
- **Orijinali Aç**: Tam makale için "Orijinali Aç"a tıklayın

### API Endpoints

#### Beslemeler (Feeds)

- `GET /api/feeds` - Tüm RSS beslemelerini listele
- `POST /api/feeds` - Yeni besleme ekle
- `POST /api/feeds/{id}/refresh` - Beslemeyi manuel olarak yenile

#### Makaleler

- `GET /api/articles` - Makaleleri listele (filtrelerle)
  - Query params: `skip`, `limit`, `topic_ids`, `search`, `status`
- `GET /api/articles/{id}` - Tek bir makale
- `GET /api/articles/topic/{topic_name}` - Konuya göre makaleler

#### Özetler

- `GET /api/articles/{id}/summaries` - Bir makalenin tüm özetleri
- `GET /api/articles/{id}/summary/{type}` - Belirli bir özet türü (brief/standard/detailed)

#### Konular & İstatistikler

- `GET /api/topics` - Makale sayısıyla birlikte tüm konular
- `GET /api/stats/costs` - API maliyet istatistikleri

#### Ayarlar

- `GET /api/settings` - Kullanıcı ayarlarını getir
- `PUT /api/settings` - Kullanıcı ayarlarını güncelle

## ⚙️ Yapılandırma

### Backend (.env)

```env
# OpenAI
OPENAI_API_KEY=your-key-here
DEFAULT_MODEL=gpt-3.5-turbo
DETAILED_MODEL=gpt-4-turbo-preview

# Veritabanı
DATABASE_URL=sqlite:///./news_summary.db

# RSS Feed
DEFAULT_FEED_URL=https://rss.dw.com/atom/rss-de-all
FEED_REFRESH_INTERVAL=1800  # 30 dakika

# Scraping
SCRAPING_ENABLED=True
SCRAPING_DELAY=1.0  # İstekler arası saniye

# Maliyet Limitleri
DAILY_COST_LIMIT=5.0  # USD
MONTHLY_COST_LIMIT=100.0  # USD

# CORS
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

### Maliyet Yönetimi

Sistem otomatik olarak OpenAI API maliyetlerini takip eder:

- **Kısa Özet** (GPT-3.5): Makale başına ~$0.0007
- **Standart Özet** (GPT-3.5): Makale başına ~$0.0007
- **Detaylı Özet** (GPT-4): Makale başına ~$0.015

**Günde 1000 makale için tahmini maliyetler**:

- Sadece standart özetler: Ayda ~$21
- Üç tür özet birlikte: Ayda ~$50-70

Limitler `.env` dosyasında yapılandırılabilir.

## 🧪 Geliştirme

### Veritabanını Sıfırlama

```bash
cd backend
rm news_summary.db checkpoints.db
# Bir sonraki başlatmada DB yeniden oluşturulur
```

### Manuel Feed İşleme

```python
from app.tasks.background import process_feed_task

# Python REPL veya script'te
process_feed_task(feed_id=1)
```

### curl ile API Testi

```bash
# Beslemeleri listele
curl http://localhost:8000/api/feeds

# Makaleleri getir
curl http://localhost:8000/api/articles?limit=10

# Özet getir
curl http://localhost:8000/api/articles/1/summary/standard
```

## 📁 Proje Yapısı

```
Bulten/
├── backend/
│   ├── app/
│   │   ├── agents/          # LangGraph Workflow
│   │   │   ├── graph.py     # Workflow tanımı
│   │   │   ├── nodes.py     # Agent Node'ları
│   │   │   ├── state.py     # State Şeması
│   │   │   └── tools.py     # Agent Araçları
│   │   ├── api/
│   │   │   └── routes/      # API Endpoints
│   │   ├── core/            # Config & Exceptions
│   │   ├── db/              # Veritabanı Modelleri & CRUD
│   │   ├── services/        # İş Mantığı
│   │   ├── tasks/           # Arka Plan Görevleri
│   │   └── main.py          # FastAPI Uygulaması
│   ├── Dockerfile           # Python 3.12-slim Image
│   ├── requirements.txt
│   └── .env                 # Ortam değişkenleri (Git'e eklemeyin!)
├── frontend/
│   ├── src/
│   │   ├── components/      # React Bileşenleri
│   │   ├── hooks/           # Custom Hook'lar
│   │   ├── services/        # API İstemcisi
│   │   ├── types/           # TypeScript Tipleri
│   │   └── main.tsx         # Giriş Noktası
│   ├── Dockerfile           # Multi-Stage: Node build → Nginx serve
│   ├── nginx.conf           # Nginx Konfigürasyonu (API-Proxy + SPA-Fallback)
│   ├── package.json
│   └── vite.config.ts
├── docker-compose.yml       # Servis Orkestrasyon
└── README.md
```

## 🛠️ Teknoloji Yığını

**Backend:**

- FastAPI (Web Framework)
- LangGraph (Agent Orkestrasyon)
- LangChain (LLM Entegrasyon)
- OpenAI (GPT Modelleri)
- SQLAlchemy (ORM)
- Feedparser (RSS Ayrıştırma)
- Trafilatura (İçerik Çıkarma)
- Aiohttp (Async HTTP)

**Frontend:**

- React 18 (UI Framework)
- TypeScript (Tip Güvenliği)
- Vite (Build Aracı)
- TanStack Query (Veri Çekme)
- Axios (HTTP İstemcisi)
- date-fns (Tarih Biçimlendirme)

## 🐛 Sorun Giderme

### Backend başlamıyor

**Sorun**: `ModuleNotFoundError`

```bash
# venv'in aktif olduğundan emin olun
cd backend
venv\Scripts\activate
pip install -r requirements.txt
```

**Sorun**: `OpenAI API Key eksik`

```bash
# .env dosyasını kontrol edin
cat .env  # Linux/Mac
type .env  # Windows
```

### Frontend başlamıyor

**Sorun**: `Cannot find module`

```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

### Makaleler görünmüyor

1. Backend loglarını hatalara karşı kontrol edin
2. Feed'in var olup olmadığını kontrol edin: `curl http://localhost:8000/api/feeds`
3. Feed'i manuel olarak yenileyin: `curl -X POST http://localhost:8000/api/feeds/1/refresh`
4. 2-3 dakika bekleyin (işleme zaman alır)

### Yüksek OpenAI maliyetleri

1. `.env` dosyasında `DAILY_COST_LIMIT` değerini düşürün
2. GPT-4 yerine sadece `gpt-3.5-turbo` kullanın
3. `FEED_REFRESH_INTERVAL` değerini artırın

### Docker sorunları

**Sorun**: Container başlamıyor / Port 80 kullanımda

```bash
# Hangi process'in Port 80 kullandığını kontrol edin
docker compose ps
# Başka bir port kullanın (örn. 8080)
# docker-compose.yml'de: ports: "8080:80"
```

**Sorun**: Backend-Container sağlıksız (`unhealthy`)

```bash
# Backend loglarını kontrol edin
docker compose logs backend

# Yaygın sebep: backend/.env'de OPENAI_API_KEY eksik
```

**Sorun**: Koddaki değişiklikler yansımıyor

```bash
# Image'ları yeniden build edin
docker compose build --no-cache
docker compose up -d
```

**Sorun**: Güncelleme sonrası veritabanı hatası

```bash
# Veritabanını sıfırlayın (Dikkat: tüm veriler silinir!)
docker compose down
rm backend/news_summary.db
docker compose up -d
```

## 📄 Lisans

Bu proje eğitim amaçlı oluşturulmuştur.

## 🙏 Teşekkürler

- RSS beslemeleri için DW Deutsche Welle
- GPT modelleri için OpenAI
- Agent framework için LangGraph Team

## 📞 Destek

Sorular veya sorunlar için GitHub'da bir Issue açın veya geliştirici ile iletişime geçin.

---

**Haber Özetleyicinizle başarılar!** 🎉
