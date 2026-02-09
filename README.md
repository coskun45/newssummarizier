# News Summarizer - DW Deutsche Welle

Ein intelligentes News-Aggregations- und Zusammenfassungssystem, das automatisch Nachrichten von Deutsche Welle (DW) RSS-Feeds verarbeitet, kategorisiert und mit KI zusammenfasst.

## 🎯 Features

- **Automatische RSS-Verarbeitung**: Fetcht und verarbeitet DW-Nachrichten automatisch
- **KI-basierte Kategorisierung**: Ordnet Artikel automatisch Themen zu (Politik, Wirtschaft, Technologie, etc.)
- **Multi-Format Zusammenfassungen**: Generiert kurze, standard und detaillierte Zusammenfassungen
- **Web-Scraping**: Extrahiert vollständigen Artikelinhalt von Webseiten (mit robots.txt Compliance)
- **Interaktives Dashboard**: React-basierte Benutzeroberfläche mit Suche und Filterung
- **Cost Tracking**: Überwacht OpenAI API-Kosten mit konfigurierbaren Limits
- **LangGraph Workflow**: Robuste Agent-Orchestrierung für komplexe Verarbeitungspipelines

## 🏗️ Architektur

### Backend

- **FastAPI**: Moderne, schnelle API mit automatischer OpenAPI-Dokumentation
- **LangGraph**: Multi-Agent Workflow-Orchestrierung
- **SQLite**: Leichtgewichtige Datenbank für Artikel, Zusammenfassungen und Metadaten
- **OpenAI**: GPT-3.5-turbo und GPT-4 für Kategorisierung und Zusammenfassung

### Frontend

- **React 18**: Moderne UI mit TypeScript
- **Vite**: Schneller Build-Tool und Dev-Server
- **TanStack Query**: Effizientes Data Fetching und Caching
- **Responsive Design**: Funktioniert auf Desktop, Tablet und Mobile

## 📋 Voraussetzungen

- **Python 3.9+**
- **Node.js 18+** und npm
- **OpenAI API Key** ([hier erhalten](https://platform.openai.com/api-keys))

## 🚀 Installation

### 1. Repository klonen

```bash
cd c:\Users\ecoskun\Desktop\newsSummary
```

### 2. Backend einrichten

```bash
cd backend

# Virtuelle Umgebung erstellen
python -m venv venv

# Virtuelle Umgebung aktivieren
# Windows:
venv\Scripts\activate
# Linux/Mac:
# source venv/bin/activate

# Dependencies installieren
pip install -r requirements.txt

# .env Datei erstellen
copy .env.example .env
# Oder auf Linux/Mac:
# cp .env.example .env
```

**Wichtig**: Öffnen Sie `.env` und fügen Sie Ihren OpenAI API Key ein:

```env
OPENAI_API_KEY=sk-your-actual-api-key-here
```

### 3. Frontend einrichten

```bash
cd ../frontend

# Dependencies installieren
npm install
```

## 🎮 Anwendung starten

### Backend starten (Terminal 1)

```bash
cd backend
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

uvicorn app.main:app --reload
```

Backend läuft auf: **http://localhost:8000**

- API Dokumentation: **http://localhost:8000/docs**
- Health Check: **http://localhost:8000/health**

### Frontend starten (Terminal 2)

```bash
cd frontend
npm run dev
```

Frontend läuft auf: **http://localhost:5173**

## 📖 Verwendung

### Erste Schritte

1. **Backend starten**: Das System initialisiert automatisch:
   - Erstellt SQLite-Datenbank
   - Seed Topics (Politik, Wirtschaft, Technologie, etc.)
   - Fügt DW RSS Feed hinzu
   - Startet initiales Fetching im Hintergrund

2. **Frontend öffnen**: Navigieren Sie zu http://localhost:5173

3. **Artikel erscheinen**: Nach 1-2 Minuten beginnen Artikel zu erscheinen

### Dashboard Features

- **Themenfilter**: Klicken Sie auf Themen in der Sidebar zum Filtern
- **Suche**: Suchen Sie in Titel und Inhalt der Artikel
- **Zusammenfassungen anzeigen**:
  - Klicken Sie auf "Zusammenfassung anzeigen"
  - Wählen Sie zwischen Kurz, Standard, Detailliert
- **Original öffnen**: Klicken Sie auf "Original öffnen" für den vollständigen Artikel

### API Endpoints

#### Feeds

- `GET /api/feeds` - Liste aller RSS-Feeds
- `POST /api/feeds` - Neuen Feed hinzufügen
- `POST /api/feeds/{id}/refresh` - Feed manuell aktualisieren

#### Artikel

- `GET /api/articles` - Artikel auflisten (mit Filtern)
  - Query params: `skip`, `limit`, `topic_ids`, `search`, `status`
- `GET /api/articles/{id}` - Einzelner Artikel
- `GET /api/articles/topic/{topic_name}` - Artikel nach Thema

#### Zusammenfassungen

- `GET /api/articles/{id}/summaries` - Alle Zusammenfassungen eines Artikels
- `GET /api/articles/{id}/summary/{type}` - Spezifische Zusammenfassung (brief/standard/detailed)

#### Topics & Stats

- `GET /api/topics` - Alle Themen mit Artikelanzahl
- `GET /api/stats/costs` - API-Kostenstatistiken

#### Settings

- `GET /api/settings` - Benutzereinstellungen abrufen
- `PUT /api/settings` - Benutzereinstellungen aktualisieren

## ⚙️ Konfiguration

### Backend (.env)

```env
# OpenAI
OPENAI_API_KEY=your-key-here
DEFAULT_MODEL=gpt-3.5-turbo
DETAILED_MODEL=gpt-4-turbo-preview

# Database
DATABASE_URL=sqlite:///./news_summary.db

# RSS Feed
DEFAULT_FEED_URL=https://rss.dw.com/atom/rss-de-all
FEED_REFRESH_INTERVAL=1800  # 30 Minuten

# Scraping
SCRAPING_ENABLED=True
SCRAPING_DELAY=1.0  # Sekunden zwischen Anfragen

# Cost Limits
DAILY_COST_LIMIT=5.0  # USD
MONTHLY_COST_LIMIT=100.0  # USD

# CORS
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

### Kosten-Management

Das System tracked automatisch OpenAI API-Kosten:

- **Brief Summary** (GPT-3.5): ~$0.0007 pro Artikel
- **Standard Summary** (GPT-3.5): ~$0.0007 pro Artikel
- **Detailed Summary** (GPT-4): ~$0.015 pro Artikel

**Geschätzte Kosten für 1000 Artikel/Tag**:

- Nur Standard-Zusammenfassungen: ~$21/Monat
- Mit allen drei Typen: ~$50-70/Monat

Limits können in `.env` konfiguriert werden.

## 🧪 Entwicklung

### Datenbank zurücksetzen

```bash
cd backend
rm news_summary.db checkpoints.db
# Beim nächsten Start wird die DB neu erstellt
```

### Manuelle Feed-Verarbeitung

```python
from app.tasks.background import process_feed_task

# In Python REPL oder Script
process_feed_task(feed_id=1)
```

### API testen mit curl

```bash
# Feeds auflisten
curl http://localhost:8000/api/feeds

# Artikel abrufen
curl http://localhost:8000/api/articles?limit=10

# Zusammenfassung abrufen
curl http://localhost:8000/api/articles/1/summary/standard
```

## 📁 Projektstruktur

```
newsSummary/
├── backend/
│   ├── app/
│   │   ├── agents/          # LangGraph Workflow
│   │   │   ├── graph.py     # Workflow-Definition
│   │   │   ├── nodes.py     # Agent-Nodes
│   │   │   ├── state.py     # State-Schema
│   │   │   └── tools.py     # Agent-Tools
│   │   ├── api/
│   │   │   └── routes/      # API Endpoints
│   │   ├── core/            # Config & Exceptions
│   │   ├── db/              # Database Models & CRUD
│   │   ├── services/        # Business Logic
│   │   ├── tasks/           # Background Tasks
│   │   └── main.py          # FastAPI App
│   ├── requirements.txt
│   └── .env
├── frontend/
│   ├── src/
│   │   ├── components/      # React Components
│   │   ├── hooks/           # Custom Hooks
│   │   ├── services/        # API Client
│   │   ├── types/           # TypeScript Types
│   │   └── main.tsx         # Entry Point
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

## 🛠️ Technologie-Stack

**Backend:**

- FastAPI (Web Framework)
- LangGraph (Agent Orchestration)
- LangChain (LLM Integration)
- OpenAI (GPT Models)
- SQLAlchemy (ORM)
- Feedparser (RSS Parsing)
- Trafilatura (Content Extraction)
- Aiohttp (Async HTTP)

**Frontend:**

- React 18 (UI Framework)
- TypeScript (Type Safety)
- Vite (Build Tool)
- TanStack Query (Data Fetching)
- Axios (HTTP Client)
- date-fns (Date Formatting)

## 🐛 Troubleshooting

### Backend startet nicht

**Problem**: `ModuleNotFoundError`

```bash
# Stelle sicher, dass venv aktiviert ist
cd backend
venv\Scripts\activate
pip install -r requirements.txt
```

**Problem**: `OpenAI API Key fehlt`

```bash
# Überprüfe .env Datei
cat .env  # Linux/Mac
type .env  # Windows
```

### Frontend startet nicht

**Problem**: `Cannot find module`

```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

### Keine Artikel erscheinen

1. Überprüfe Backend-Logs auf Fehler
2. Prüfe ob Feed existiert: `curl http://localhost:8000/api/feeds`
3. Manuell Feed refreshen: `curl -X POST http://localhost:8000/api/feeds/1/refresh`
4. Warte 2-3 Minuten (Verarbeitung braucht Zeit)

### Hohe OpenAI-Kosten

1. Reduziere `DAILY_COST_LIMIT` in `.env`
2. Nutze nur `gpt-3.5-turbo` statt GPT-4
3. Erhöhe `FEED_REFRESH_INTERVAL`

## 📄 Lizenz

Dieses Projekt ist für Bildungszwecke erstellt.

## 🙏 Credits

- DW Deutsche Welle für RSS-Feeds
- OpenAI für GPT-Modelle
- LangGraph Team für Agent-Framework

## 📞 Support

Bei Fragen oder Problemen öffnen Sie ein Issue auf GitHub oder kontaktieren Sie den Entwickler.

---

**Viel Erfolg mit Ihrem News Summarizer!** 🎉
