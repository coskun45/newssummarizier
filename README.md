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
- **Word Bülten Raporu**: Seçilen zaman aralığı ve önem seviyesindeki haberlerden, şablondaki örnek bülten
  yapısında bir Word (.docx) raporu üretir (en fazla `BULLETIN_MAX_ARTICLES` = 50 haber): en başta yapay
  zekanın önceliği en yüksek ve en yeni 10 haber arasından seçtiği en fazla 5 haberlik **Öne Çıkan
  Başlıklar**, ardından kullanıcı tanımlı üst düzey kategoriler (Avrupa, Amerika vb.; Heading1) ve her birinin
  altında haberlerin konularına göre oluşturulan anlamlı alt başlıklar (Heading3). Her haber, uygulamanın kısa
  özetiyle (`📌 Kaynak / Yazar - Başlık` + `🔹` maddeler) yazılır; kısa özeti olmayan habere aynı özetleyiciyle
  özet üretilip kaydedilir; üretilemezse kayıtlı standart, o da yoksa detaylı özet kullanılır. İçindekiler hazır doldurulur (Word açılışta güncelleme sormaz); "BAZI KAYNAKLAR"
  listesine takip edilen RSS beslemeleri eklenir. Şablon: `backend/app/resources/bulletin_template.docx`
- **Playground**: Header'daki sekmeden mevcut RSS'lerdeki haberlerden biri seçilip pipeline'ın (sınıflandırma +
  öncelik, kısa/standart/detaylı özet) sonucu görülebilir. Geçerli model ve prompt ayarları gösterilir; prompt'lar
  ve özet talimatları o çalıştırma için geçici olarak değiştirilebilir. Her aşama ayrıntılı incelenir (modele giden
  prompt, ham cevap, token, maliyet, süre). Hiçbir şey veritabanına yazılmaz.
- **Kaynak ve Yazar**: Haber kartında RSS beslemesinin adı "Kaynak" olarak, yazarın üstünde gösterilir (besleme
  adı bu yüzden zorunludur). Özetin 📌 başlığında da aynı kaynak kullanılır; yazarı ise özetle birlikte yapay zeka
  belirler — yalnızca gerçek bir kişi adıysa yazılır ("Sputnik Türkiye" gibi kurum adları yazar sayılmaz), yoksa boş kalır

## 🏗️ Mimari

### Backend

- **FastAPI**: Otomatik OpenAPI dokümantasyonu ile modern, hızlı API
- **LangGraph**: Çok-ajanlı iş akışı orkestrasyon
- **PostgreSQL** (Docker `db` servisi; yerel `uvicorn` geliştirmede de aynı DB kullanılır): Makaleler,
  özetler ve meta veriler için veritabanı — bkz. [Docker ile Çalıştırma](#-docker)
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

# Tek yapılandırma dosyası: REPO KÖKÜNDEKİ .env
cd ..
copy .env.example .env
# veya Linux/Mac'te:
# cp .env.example .env
```

**Önemli**: Tüm ayarlar (OpenAI, modeller, token/maliyet limitleri, Postgres, JWT, CORS) **repo
kökündeki tek `.env` dosyasında** tutulur. Dosyayı açın ve OpenAI API Key'inizi ekleyin:

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

**1. Repo kökünde `.env` dosyası oluşturun (tek yapılandırma dosyası):**

```bash
cp .env.example .env
```

`.env` dosyasını açın ve OpenAI API Key'inizi girin:

```env
OPENAI_API_KEY=sk-your-actual-api-key-here
```

**2. JWT Secret ayarlayın (Docker'da ZORUNLU)** — container `DEBUG=false` ile çalıştığı için `.env.example`'daki
varsayılan değerle backend başlamayı reddeder. Aynı `.env` dosyasında değiştirin:

```env
JWT_SECRET_KEY=your-very-strong-random-secret
```

Rastgele değer üretmek için: `python -c "import secrets; print(secrets.token_hex(32))"`

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

### Sunucuya Bağlanma ve Canlı Loglar

Uygulama `deploy.sh` ile bir sunucuya deploy edildiğinde (bkz. `.github/workflows/deploy.yml`), kod `~/newssummarizier` dizinine klonlanır ve Docker Compose ile ayağa kaldırılır. Canlı loglara bakmak için:

```bash
# 1. Sunucuya SSH ile bağlan
 ssh root@77.42.89.136  

# 2. Proje dizinine geç
cd ~/newssummarizier

# 3. Tüm servislerin canlı loglarını izle
docker compose logs -f

# Sadece belirli bir servis
docker compose logs -f backend     # FastAPI / agent pipeline
docker compose logs -f frontend    # Nginx
docker compose logs -f db          # PostgreSQL

# Son N satırı görüp sonra takibe devam et
docker compose logs --tail=200 -f backend

# Servislerin ayakta olup olmadığını kontrol et
docker compose ps
```

> `<sunucu-ip>` ve SSH kullanıcı adı deploy'un yapıldığı ortama özeldir (bkz. `.github/workflows/deploy.yml` secrets). Loglar Docker'ın container log sürücüsünden okunur; ayrı bir log dosyasına yazılmaz.

### Günlük Sağlık Raporu (Claude)

`.github/workflows/daily-health.yml` her sabah **08:00 (Europe/Berlin)** sunucuyu kontrol eder. GitHub Actions
üzerinde, yani sunucunun **dışında** çalışır; bu sayede sunucu tamamen çökse bile bildirim gelir.

1. `http://<sunucu>/api/health` dışarıdan çağrılır.
2. SSH ile salt-okunur olarak toplanır: `docker compose ps`, restart/health durumu, son 24 saatin hata logları
   (`error|exception|traceback|fatal|oom…`), disk, bellek ve uptime.
3. `scripts/daily_health_report.py` secret'ları, e-postaları ve IP'leri maskeler, veriyi Claude'a (Anthropic API)
   analiz ettirir ve `OK` / `UYARI` / `KRİTİK` derecesini belirler. Health kontrolü ya da SSH başarısızsa derece her zaman `KRİTİK` olur.
4. Sonuç:
   - **UYARI/KRİTİK:** `daily-health` etiketli bir issue açılır (GitHub e-posta gönderir). Açık bir issue varsa yenisi açılmaz, mevcut issue'ya yorum eklenir.
   - **OK:** açık issue varsa otomatik kapatılır.
   - Claude'a ulaşılamazsa issue yine açılır, bu durumda ham bulgular kullanılır.

**Kurulum:** repo → *Settings → Secrets and variables → Actions* altına `ANTHROPIC_API_KEY` ekleyin.
`SERVER_HOST`, `SERVER_USER` ve `SSH_PRIVATE_KEY` deploy için tanımlı olanlardır. İsteğe bağlı olarak *Variables* sekmesindeki `CLAUDE_MODEL`
ile model değiştirilebilir (varsayılan `claude-opus-5`). Elle denemek için: *Actions → Daily Health → Run workflow*.

> Zamanlanmış workflow'lar yalnızca varsayılan dalda (`master`) çalışır. GitHub, 60 gün commit almayan public repolarda
> zamanlanmış workflow'ları devre dışı bırakır; bu durumda Actions sekmesinden yeniden etkinleştirin.

### Ortam Değişkenleri

Tüm değişkenler repo kökündeki **tek `.env`** dosyasından gelir (şablon: `.env.example`);
`docker-compose.yml` bu dosyayı hem `${VAR}` substitution'ı için hem de backend container'ının
`env_file`'ı olarak yükler. Sunucuda dosya `scripts/ensure_env.py` ile ilk deploy'da otomatik üretilir
(rastgele `POSTGRES_PASSWORD` ve `JWT_SECRET_KEY` dahil), sonraki deploy'larda mevcut değerlere dokunulmaz.
Aşağıdaki tablo öne çıkanlardır; tam liste `.env.example`'dadır. Container içinde yalnızca `DATABASE_URL`
(`db` host'una çevrilir), `BULLETIN_STORAGE_DIR` ve `DEBUG=false` compose tarafından ezilir; ayrıca `APP_VERSION` (aşağıya bakın) deploy'da CI'dan gelirse `.env`'yi ezer.

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `OPENAI_API_KEY` | – | **(Zorunlu)** OpenAI API Key |
| `JWT_SECRET_KEY` | – (şablondaki placeholder yalnızca `DEBUG=true`'da kabul edilir) | JWT imza anahtarı — **`DEBUG=false` iken varsayılan değerde bırakılırsa uygulama başlamayı reddeder** |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | – | İlk admin kullanıcısını oluşturmak için (ikisi de set edilmelidir). Boş bırakılırsa hiç admin oluşturulmaz — bkz. `db/seed.py` |
| `DEV_AUTO_LOGIN` | `false` | Yalnızca lokal geliştirme: `DEBUG=true` ile birlikte `true` yapılırsa giriş sayfası atlanır, uygulama admin kullanıcısıyla açılır (`POST /api/auth/dev-login`). Container'da `DEBUG=false` olduğu için etkisizdir |
| `POSTGRES_USER` | `bulten` | PostgreSQL kullanıcı adı (`db` servisine ve backend'in `DATABASE_URL`'ine enjekte edilir) |
| `POSTGRES_PASSWORD` | `changeme` | PostgreSQL şifresi — **production'da güçlü bir değer olmalı** (deploy rastgele üretir) |
| `POSTGRES_DB` | `bulten` | PostgreSQL veritabanı adı |
| `DATABASE_URL` | `postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}` | Backend'in bağlandığı veritabanı — `db` servisine işaret eder, doğrudan override edilmez |
| `APP_VERSION` | `2.0.0` | Uygulama sürümü (`/api/info`, arayüzde profil menüsü) — deploy'da CI otomatik ayarlar, bkz. [Sürümleme](#sürümleme) |
| `DEBUG` | `false` | Debug modu (container'da her zaman `false`) |
| `CORS_ORIGINS` | `http://localhost:5173,...` | İzin verilen CORS origin'leri (deploy sunucu IP'sine ayarlar) |
| `DEFAULT_MODEL` / `DETAILED_MODEL` | `gpt-4o-mini` / `gpt-4o` | Kategorizasyon/kısa özet ve detaylı özet modelleri |
| `MAX_TOKENS_OUTPUT_BRIEF` / `_STANDARD` / `_DETAILED` | `1500` / `3000` / `10000` | Özet tipine göre çıktı token limiti |
| `DAILY_COST_LIMIT` / `MONTHLY_COST_LIMIT` | `10.0` / `100.0` | Maliyet limitleri (USD) — sınıflandırma, özet, bülten ve Playground dahil tüm OpenAI çağrılarının toplamı |
| `FEED_REFRESH_INTERVAL` | `3600` | Otomatik feed yenileme aralığının varsayılanı (saniye); admin Ayarlar › RSS Beslemeleri'nden değiştirir |

### Sürümleme

Her deploy (`master`'a push → testler → `ci-cd.yml`) uygulamaya otomatik bir sürüm verir; `scripts/next_version.py` hesaplar:

- **Minor her deploy'da artar** (`2.0.0` → `2.1.0` → `2.2.0`); patch hep `0`.
- **Major, `frontend/src/data/features.json`'daki en yüksek `vN`'dir.** Yeni ana sürüm başlatmak için oraya yeni bir
  `vN` bloğu ekleyin; sonraki deploy `N.0.0` olur, sonra yine minor artar.
- Mevcut sürüm git tag'lerinden (`vX.Y.Z`) okunur; deploy başarılı olunca yeni tag push'lanır.
- Sürüm container'a `APP_VERSION` olarak iletilir, `/api/info` döndürür ve arayüzde profil simgesine tıklayınca
  açılan menüde ve Ayarlar › Features'ta görünür.

### Veritabanı Kalıcılığı

Veritabanı, Docker Compose ile çalıştırıldığında **PostgreSQL** (`db` servisi, `postgres:16-alpine`)
üzerinde tutulur; verisi adlandırılmış bir Docker volume'ünde (`postgres_data`) kalıcı olur:

```yaml
volumes:
  - postgres_data:/var/lib/postgresql/data
```

Üretilen Word bültenleri ise ayrıca host'taki `./data/` dizinine
mount edilir (repo'nun git ağacının dışında, asla commit'lenmez):

```yaml
volumes:
  - ./data:/app/data
```

Bu şu anlama gelir: Veriler `docker compose down` ve `git pull`/`reset --hard` sonrasında bile
korunur. Sadece `docker compose down -v` (Postgres volume'ünü de siler) veya `./data` dizinini
silmek veriyi kaldırır.

Yerel geliştirmede (`uvicorn` ile) de aynı Docker Postgres'i kullanılır: `db` servisi
`127.0.0.1:5432` üzerinden yalnızca localhost'a açılır. Önce `docker compose up -d db` ile DB'yi
başlat, kök `.env` içinde
`DATABASE_URL=postgresql+psycopg2://bulten:changeme@localhost:5432/bulten` olsun (kullanıcı/şifre/DB
adı `POSTGRES_*` değerleriyle aynı olmalı). Böylece yerel `uvicorn` ve Docker'daki backend aynı
veriyi görür.

**Var olan bir SQLite veritabanını Postgres'e taşımak için** (ör. önceki bir sürümden yükseltme),
backend'i normal başlatmadan ÖNCE (aksi halde `seed_database()` topics/feeds/system_prompts'a
seed verisi ekler ve migrasyon aynı satırları tekrar eklemeye çalışıp unique constraint hatası alır):

```bash
docker compose up -d db                                  # sadece Postgres
docker compose run --rm backend python migrate_sqlite_to_postgres.py \
    --sqlite-path /app/data/news_summary.db
docker compose up -d                                      # migrasyondan sonra her şeyi başlat
```

Script kaynak/hedef satır sayılarını karşılaştırıp özet basar; hedef tablolar zaten doluysa
(yanlışlıkla ikinci kez çalıştırmayı önlemek için) durur.

### Proje Yapısı (Docker ile)

```
Bulten/
├── backend/
│   ├── Dockerfile          # Python 3.12-slim Image
│   ├── migrate_sqlite_to_postgres.py  # Bir kerelik SQLite → Postgres veri göçü
│   └── ...
├── frontend/
│   ├── Dockerfile          # Multi-Stage: Node build → Nginx serve
│   ├── nginx.conf          # Nginx Konfigürasyonu (API-Proxy + SPA-Fallback)
│   └── ...
├── docker-compose.yml      # Servis orkestrasyon (db: Postgres, backend, frontend)
├── scripts/ensure_env.py   # Sunucuda .env üretir/günceller (deploy tarafından çağrılır)
├── scripts/next_version.py # Deploy sürümünü hesaplar (major: features.json, minor: git tag'leri)
├── .env.example            # Tek yapılandırma şablonu
├── .env                    # TÜM ayarlar + secret'lar — tek dosya (Git'e eklemeyin!)
└── README.md
```

---

## 📖 Kullanım

### İlk Adımlar

1. **Backend'i başlat**: Sistem otomatik olarak:
   - PostgreSQL tablolarını oluşturur
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
- **Playground**: Header'daki "Playground" sekmesinde bir RSS kaynağı/haber seçin, isterseniz sınıflandırma ve
  özetleme prompt'larını (ve özet türü talimatlarını) düzenleyip "Sınıflandır", "Özetle" veya "Tümünü
  çalıştır" ile sonucu aşama aşama inceleyin. Düzenlenen prompt'lar kaydedilmez; kalıcı değişiklik için
  Ayarlar › Sistem Promptları kullanılır. Çalıştırmalar OpenAI'ye gerçek istek atar (maliyet oluşur, ancak
  günlük/aylık limit hesabına dahil edilmez). Başlıktaki "Sistem ayarlarına döndür" butonu, düzenlenen
  prompt'ları, özet türü talimatlarını ve özet türü seçimini Ayarlar'daki güncel değerlere geri alır.
- **Sınıflandırma promptu**: Ayarlar › Sistem Promptları ve Playground'da yalnızca kriterler (önem filtresi,
  keyword listesi, öncelik seviyeleri) düzenlenir. Uygulama mantığının dayandığı kısım — güncel konu listesi
  (mevcut konular ve açıklamaları), JSON çıktı formatı ve `confidence >= 0.5` kuralı — her çağrıda sistem
  tarafından otomatik eklenir; editörün altında "kilitli" olarak, modele giden haliyle görünür ama değiştirilemez.
  Böylece prompt ne kadar değiştirilirse değiştirilsin sonuç ayrıştırılabilir kalır.
- **Özetleme promptu**: Ayarlar › Sistem Promptları'nda düzenlenen metin system mesajıdır. Özet türlerinin
  (kısa/standart/detaylı) talimatı, haberin kaynağı (besleme adı) ile RSS'teki yazar ipucu, JSON çıktı formatı
  (`{"summary": ..., "author": ...}`) ve sabit dil satırı ("Write the summary in Turkish.") haber metniyle
  birlikte kullanıcı mesajına sistem tarafından eklenir; editörün altında "kilitli" olarak görünür, değiştirilemez.
  Ayarlar'da yalnızca **etkin** özet türleri listelenir (Özet Türleri'ni değiştirip kaydedince güncellenir);
  Playground'da ise o çalıştırma için **işaretli** türler ve (düzenlenmişse) talimatları gösterilir.

### API Endpoints

#### Beslemeler (Feeds)

- `GET /api/feeds` - Tüm RSS beslemelerini listele
- `POST /api/feeds` - Yeni besleme ekle (`title` zorunlu: haberlerde "Kaynak" olarak görünür; boşsa 422)
- `POST /api/feeds/{id}/refresh` - Beslemeyi manuel olarak yenile

#### Makaleler

- `GET /api/articles` - Makaleleri listele (filtrelerle; `is_error=true` sadece önem etiketi olmayan "Error" haberleri döner)
  - Query params: `skip`, `limit`, `topic_ids`, `search`, `status`
  - Her makalede `source` (besleme adı; adı olmayan eski beslemelerde alan adı) ve `author` (özetin belirlediği kişi, yoksa `null`) döner
- `GET /api/articles/{id}` - Tek bir makale
- `GET /api/articles/topic/{topic_name}` - Konuya göre makaleler
- `POST /api/articles/topic/{topic_id}/delete-all` - Konudaki tüm okunmamış makaleleri sil
- `POST /api/articles/topic/{topic_id}/archive-all` - Konudaki tüm okunmamış makaleleri arşive gönder
- `POST /api/articles/unimportant/delete-all` - Tüm okunmamış önemsiz makaleleri sil
- `POST /api/articles/unimportant/archive-all` - Tüm okunmamış önemsiz makaleleri arşive gönder
- `POST /api/articles/reprocess` - Error haberleri (tek/toplu: `article_ids` veya `all_errors`) arka planda yeniden sınıflandır + özetle
- `GET /api/articles/reprocess-status` - Yeniden işleme ilerlemesi (`idle`/`running`/`done`, `total`, `done`, `failed`)

#### Özetler

- `GET /api/articles/{id}/summaries` - Bir makalenin tüm özetleri
- `GET /api/articles/{id}/summary/{type}` - Belirli bir özet türü (brief/standard/detailed)

#### Konular & İstatistikler

- `GET /api/topics` - Makale sayısıyla birlikte tüm konular
- `GET /api/stats/costs` - API maliyet istatistikleri

#### Ayarlar

- `GET /api/settings` - Kullanıcı ayarlarını getir
- `PUT /api/settings` - Kullanıcı ayarlarını güncelle

#### Bülten (Word Raporu)

- `GET /api/bulletin/categories` - Üst düzey bülten kategorilerini listele
- `POST /api/bulletin/categories` - Yeni üst düzey kategori ekle (admin)
- `PUT /api/bulletin/categories/reorder` - Kategori görüntüleme sırasını güncelle (admin)
- `POST /api/bulletin/generate` - Filtrelere (tarih aralığı, önem seviyesi) göre Word (.docx) bülten
  raporu oluşturur ve dosya olarak döner

#### Sistem Promptları

- `GET /api/prompts/{prompt_type}/locked` - Promptun düzenlenemeyen, pipeline'ın kendisinin eklediği kısmı.
  `classification` için güncel konu listesi + JSON çıktı formatı, `summarization` için etkin özet türlerinin
  talimatları + kaynak/yazar ve JSON çıktı kuralı + dil satırı döner; diğer tiplerde boş metin

#### Playground (kayıt yapmayan deneme çalıştırması)

- `GET /api/playground/settings` - Pipeline'ın şu an kullandığı model, prompt (kayıtlı/varsayılan), sınıflandırma
  promptunun kilitli kısmı (`classification_locked_text`), özet türleri ve konu listesi
- `POST /api/playground/run` - Seçilen tek bir haber için sınıflandırma ve/veya özetlemeyi (isteğe bağlı prompt
  değişiklikleriyle) çalıştırıp her aşamanın ayrıntısını döner; veritabanına hiçbir şey yazmaz

## ⚙️ Yapılandırma

### Backend (.env)

```env
# OpenAI
OPENAI_API_KEY=your-key-here
DEFAULT_MODEL=gpt-4o-mini
DETAILED_MODEL=gpt-4o
OPENAI_TIMEOUT_SECONDS=60.0  # tek bir OpenAI isteği için üst sınır (saniye)

# Veritabanı (Docker'daki Postgres: `docker compose up -d db`)
DATABASE_URL=postgresql+psycopg2://bulten:changeme@localhost:5432/bulten

# RSS Feed
DEFAULT_FEED_URL=https://rss.dw.com/atom/rss-de-all
FEED_REFRESH_INTERVAL=3600  # 1 saat (Ayarlar'dan değiştirilebilir)

# Scraping
SCRAPING_ENABLED=True
SCRAPING_DELAY=1.0  # İstekler arası saniye

# Maliyet Limitleri
DAILY_COST_LIMIT=10.0  # USD
MONTHLY_COST_LIMIT=100.0  # USD

# Bülten Raporu
BULLETIN_CLASSIFICATION_BATCH_SIZE=15  # LLM sınıflandırma çağrısı başına haber sayısı
BULLETIN_MAX_ARTICLES=50  # Tek bir raporda izin verilen maksimum haber sayısı

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
docker compose down -v    # Postgres volume'ünü siler — TÜM veri gider
docker compose up -d db   # boş DB; backend bir sonraki başlatmada tabloları yeniden oluşturur
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
│   │   ├── resources/       # Statik dosyalar (Bülten Word şablonu)
│   │   ├── services/        # İş Mantığı
│   │   ├── tasks/           # Arka Plan Görevleri
│   │   └── main.py          # FastAPI Uygulaması
│   ├── Dockerfile           # Python 3.12-slim Image
│   ├── requirements.txt
│   └── migrate_sqlite_to_postgres.py  # Bir kerelik SQLite → Postgres veri göçü
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
- python-docx (Word Bülten Raporu Üretimi)

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

### Kartta kaynak yanlış veya yazar boş

- **Kaynak yanlış/alan adı görünüyor**: Kaynak, beslemenin adıdır. Ayarlar › RSS Beslemeleri'nde adı düzeltin
  (ör. "DW Türkçe"); o beslemenin tüm kartları hemen güncellenir. Özet başlığı ise bir sonraki işlemede değişir.
- **Yazar boş**: Yazar yalnızca metinde veya RSS'te gerçek bir kişi adı varsa yazılır; kurum adları (ör.
  "Sputnik Türkiye") bilinçli olarak gösterilmez. Eski haberler "Tekrar dene" ile yeniden işlenene kadar eski
  yazarı gösterir.

### Yüksek OpenAI maliyetleri

1. `.env` dosyasında `DAILY_COST_LIMIT` değerini düşürün
2. GPT-4 yerine sadece `gpt-3.5-turbo` kullanın
3. Ayarlar › RSS Beslemeleri'nde otomatik yenileme aralığını artırın

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

# Yaygın sebep: kök .env'de OPENAI_API_KEY eksik
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
docker compose down -v   # -v Postgres volume'ünü de siler
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
