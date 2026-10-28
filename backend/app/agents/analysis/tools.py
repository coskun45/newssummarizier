"""
The Asistan's tools: the catalog shown in Ayarlar › Asistan (with availability and on/off state) and
the executors the agent calls.

A tool reaches the model only if it is *available* (its infrastructure exists — semantic search,
the Python sandbox and web search come in later stages) AND *enabled* in Ayarlar
(`chat_enabled_tools`, read only through `get_enabled_chat_tools`).
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.exceptions import CostLimitExceededError
from app.db import crud
from app.db.database import SessionLocal, vector_support
from app.services import summary_service
from app.agents.analysis.sql_guard import SqlRejected, validate_sql
from app.agents.analysis.time_range import resolve_time_range

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatTool:
    name: str
    label: str
    description: str
    data_tool: bool  # reads the news data; at least one must stay enabled
    not_built_reason: Optional[str] = None  # set while the tool belongs to a later stage


CHAT_TOOLS: Dict[str, ChatTool] = {
    tool.name: tool for tool in (
        ChatTool("time", "Zaman tespiti",
                 "“Geçen hafta”, “son 3 gün”, “1-15 Ekim” gibi ifadeleri kesin tarih aralığına çevirir.", False),
        ChatTool("sql", "Veritabanı (SQL)",
                 "Haber verisi üzerinde salt-okunur SQL ile sayım, dağılım, trend ve listeler çıkarır.", True),
        ChatTool("semantic_search", "Vektör arama",
                 "Haberlerin tam metninde anlam benzerliği ve kelime eşleşmesiyle arar; konu, olay ve "
                 "ayrıntı soruları için.", True),
        ChatTool("python", "Code interpreter",
                 "Python (pandas) ile istatistik, korelasyon ve görsel analiz yapar.", False,
                 "Henüz kurulmadı — Python sandbox'ı sonraki aşamada gelecek."),
        ChatTool("web_search", "Web arama",
                 "Haber verisi dışındaki güncel bağlam ve doğrulama için internette arar.", False,
                 "Henüz kurulmadı — sonraki aşamada gelecek."),
        ChatTool("chart", "Grafik",
                 "Sonuçları çubuk veya çizgi grafik olarak çizer.", False),
    )
}
DATA_TOOLS = tuple(name for name, tool in CHAT_TOOLS.items() if tool.data_tool)


def unavailable_reason(name: str) -> Optional[str]:
    """Why a tool can't be used right now (Turkish, shown in Ayarlar), or None if it can."""
    tool = CHAT_TOOLS[name]
    if tool.not_built_reason:
        return tool.not_built_reason
    if name == "semantic_search" and not vector_support["available"]:
        return vector_support["reason"] or "Vektör veritabanı kullanılamıyor."
    return None


def available_tool_names() -> List[str]:
    return [name for name in CHAT_TOOLS if unavailable_reason(name) is None]


def normalize_enabled_tools(value: str) -> str:
    """Validate a `chat_enabled_tools` setting value (comma-separated names) and return it in
    canonical order. Raises ValueError (Turkish message) for unknown names or when no available
    data tool would remain."""
    requested = {part.strip() for part in value.split(",") if part.strip()}
    unknown = requested - set(CHAT_TOOLS)
    if unknown:
        raise ValueError(f"Bilinmeyen araç: {', '.join(sorted(unknown))}")
    if not requested & set(DATA_TOOLS) & set(available_tool_names()):
        raise ValueError("En az bir veri aracı (Veritabanı veya Vektör arama) açık kalmalı")
    return ",".join(name for name in CHAT_TOOLS if name in requested)


def get_enabled_chat_tools(db) -> List[str]:
    """Tools the agent may use now: enabled in Ayarlar and available, in catalog order. Unset (or
    a value naming nothing usable) means every available tool."""
    raw = crud.get_setting(db, "chat_enabled_tools")
    available = available_tool_names()
    if raw is None:
        return available
    enabled = {part.strip() for part in raw.split(",") if part.strip()}
    chosen = [name for name in available if name in enabled]
    return chosen if set(chosen) & set(DATA_TOOLS) else available


def get_chat_require_plan_approval(db) -> bool:
    return crud.get_setting(db, "chat_require_plan_approval") == "true"


def tool_catalog(db) -> List[Dict[str, Any]]:
    """The catalog for Ayarlar › Asistan and the Asistan screen."""
    raw = crud.get_setting(db, "chat_enabled_tools")
    stored = None if raw is None else {part.strip() for part in raw.split(",") if part.strip()}
    effective = set(get_enabled_chat_tools(db))
    catalog = []
    for tool in CHAT_TOOLS.values():
        reason = unavailable_reason(tool.name)
        catalog.append({
            "name": tool.name,
            "label": tool.label,
            "description": tool.description,
            "data_tool": tool.data_tool,
            "available": reason is None,
            "unavailable_reason": reason,
            # What Ayarlar shows switched on: the stored choice (an unavailable tool can be
            # pre-enabled), or by default everything available.
            "enabled": (tool.name in stored) if stored is not None else reason is None,
            "active": tool.name in effective,
        })
    return catalog


# ---------------------------------------------------------------------------
# OpenAI function schemas
# ---------------------------------------------------------------------------

_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "time": {
        "name": "resolve_time_range",
        "description": "Türkçe bir zaman ifadesini kesin tarih aralığına çevirir. Örnekler: 'bugün', 'dün', "
                       "'geçen hafta', 'bu ay', 'son 3 gün', 'son 2 ay', '1-15 Ekim', '5 Kasım 2025', 'Ekim sonu', "
                       "'1 Eylül'den beri', 'Ağustos sonundan bu yana', "
                       "'2026-10-01 - 2026-10-07'. SQL'de dönen from_utc/to_utc kullanılır.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "Zaman ifadesi"}},
            "required": ["expression"],
        },
    },
    "sql": {
        "name": "run_sql",
        "description": "Haber verisinde salt-okunur tek bir PostgreSQL SELECT sorgusu çalıştırır. Yalnızca "
                       "chat_articles, chat_article_topics, chat_summaries view'ları okunabilir. Sonuç en fazla "
                       f"{settings.chat_sql_max_rows} satırdır.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "PostgreSQL SELECT sorgusu"},
                "purpose": {"type": "string", "description": "Sorgunun ne bulduğu, kısa Türkçe"},
            },
            "required": ["query"],
        },
    },
    "semantic_search": {
        "name": "semantic_search",
        "description": "Haberlerin tam metninde anlamca arar (metin parçalarının benzerliği ve kelime eşleşmesi birlikte). "
                       "Konu/olay/kişi hakkındaki haberleri bulmak ve içerik sorularını cevaplamak için. Her sonuç "
                       "kimlik, başlık, tarih, önem, kaynak, özet ve sorguyla en çok eşleşen metin parçasını içerir. "
                       "Sorguyu açıklayıcı yaz (ör. 'Almanya'da erken seçim tartışması'); haberler Almanca/İngilizce olabilir.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Ne aranıyor"},
                "priorities": {"type": "array", "items": {"type": "string", "enum": ["high", "med", "low"]}},
                "date_from_utc": {"type": "string", "description": "'YYYY-MM-DD HH:MM:SS' (UTC), zaman aracından"},
                "date_to_utc": {"type": "string", "description": "'YYYY-MM-DD HH:MM:SS' (UTC)"},
                "topics": {"type": "array", "items": {"type": "string"}, "description": "Konu adları"},
                "analyzable_only": {"type": "boolean", "description": "Yalnızca önem seviyeli, Önemsiz olmayan"},
                "k": {"type": "integer", "minimum": 1, "maximum": 15},
            },
            "required": ["query"],
        },
    },
    "chart": {
        "name": "render_chart",
        "description": "Kullanıcıya grafik gösterir. x ekseni etiketleri ve her seri için x ile aynı uzunlukta "
                       "sayısal değerler verilir.",
        "parameters": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["bar", "line", "stacked_bar"]},
                "title": {"type": "string"},
                "x": {"type": "array", "items": {"type": "string"}},
                "series": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "values": {"type": "array", "items": {"type": "number"}},
                        },
                        "required": ["name", "values"],
                    },
                },
                "x_label": {"type": "string"},
                "y_label": {"type": "string"},
            },
            "required": ["type", "title", "x", "series"],
        },
    },
}
_FUNCTION_TO_TOOL = {schema["name"]: name for name, schema in _SCHEMAS.items()}

MAX_CHART_POINTS = 60
MAX_CHART_SERIES = 6
LLM_TABLE_ROWS = 50  # rows of a SQL result shown to the model; the full result stays an artifact


def openai_tools(tool_names: List[str]) -> List[Dict[str, Any]]:
    """Function schemas for the given tools (those that have an executor)."""
    return [{"type": "function", "function": _SCHEMAS[name]} for name in tool_names if name in _SCHEMAS]


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------

def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _utc_text(iso: str) -> str:
    """'2026-10-19T00:00:00+02:00' → '2026-10-18 22:00:00': timestamps are stored as naive UTC."""
    return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def run_time_tool(args: Dict[str, Any]) -> Dict[str, Any]:
    expression = str(args.get("expression") or "")
    resolved = resolve_time_range(expression)
    if resolved is None:
        return {"ok": False, "summary": f"“{expression}” anlaşılamadı",
                "content": json.dumps({"error": "İfade anlaşılamadı; kullanıcıya dönemi sorun."}, ensure_ascii=False)}
    payload = {**resolved, "from_utc": _utc_text(resolved["from"]), "to_utc": _utc_text(resolved["to"])}
    return {"ok": True, "summary": f"{resolved['label']}: {payload['from'][:10]} → {payload['to'][:10]}",
            "content": json.dumps(payload, ensure_ascii=False), "data": payload}


def run_sql_tool(args: Dict[str, Any], artifact_id: str) -> Dict[str, Any]:
    query = str(args.get("query") or "")
    db = SessionLocal()
    try:
        dialect = "postgres" if db.get_bind().dialect.name == "postgresql" else "sqlite"
        try:
            sql = validate_sql(query, settings.chat_sql_max_rows, dialect=dialect)
        except SqlRejected as e:
            return {"ok": False, "summary": f"Sorgu reddedildi: {e}", "sql": query,
                    "content": json.dumps({"error": f"Sorgu reddedildi: {e}"}, ensure_ascii=False)}
        try:
            result = crud.run_readonly_query(db, sql, settings.chat_sql_timeout_ms, settings.chat_sql_max_rows)
        except Exception as e:  # syntax/runtime error from the DB: let the model fix its query
            message = str(getattr(e, "orig", e)).strip().splitlines()[0][:300]
            return {"ok": False, "summary": f"Sorgu hatası: {message}", "sql": sql,
                    "content": json.dumps({"error": f"Sorgu hatası: {message}"}, ensure_ascii=False)}
    finally:
        db.close()

    rows = [[_json_value(v) for v in row] for row in result["rows"]]
    artifact = {"id": artifact_id, "kind": "table", "sql": sql, "purpose": args.get("purpose"),
                "columns": result["columns"], "rows": rows, "truncated": result["truncated"]}
    shown = rows[:LLM_TABLE_ROWS]
    content = {
        "artifact_id": artifact_id,
        "columns": result["columns"],
        "rows": shown,
        "row_count": len(rows),
        "truncated": result["truncated"],
    }
    if len(rows) > len(shown):
        content["note"] = f"Modele ilk {len(shown)} satır gösterildi; tamamı {artifact_id} olarak saklandı."
    summary = f"{len(rows)} satır" + (" (sınırda kesildi)" if result["truncated"] else "")
    return {"ok": True, "summary": summary, "sql": sql, "artifact": artifact,
            "content": json.dumps(content, ensure_ascii=False)}


RRF_K = 60  # reciprocal rank fusion constant (the usual 60)
SEARCH_CANDIDATES = 30
SEARCH_DEFAULT_K = 8
SEARCH_MAX_K = 15


def _utc_arg(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"Geçersiz tarih: {value} (beklenen 'YYYY-MM-DD HH:MM:SS', UTC)")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def fuse_rankings(candidates: Dict[str, list]) -> List[Dict[str, Any]]:
    """Reciprocal rank fusion of the ranked chunk lists from crud.semantic_candidates into one
    article ranking. Each list counts an article once (its best chunk); the best chunk by meaning
    (else by keyword) becomes the article's evidence."""
    scores: Dict[int, float] = {}
    matched: Dict[int, List[str]] = {}
    evidence: Dict[int, str] = {}

    def add(article_ids: List[int], source: str) -> None:
        for rank, article_id in enumerate(article_ids):
            scores[article_id] = scores.get(article_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            matched.setdefault(article_id, []).append(source)

    for source in ("chunk", "keyword"):
        seen: List[int] = []
        for article_id, _chunk_id, text, _score in candidates[source]:
            if article_id not in seen:
                seen.append(article_id)
                evidence.setdefault(article_id, text)
        add(seen, source)
    ranked = sorted(scores, key=lambda article_id: -scores[article_id])
    return [{"article_id": a, "score": round(scores[a], 5), "matched_by": matched[a], "evidence": evidence.get(a)}
            for a in ranked]


def _short(text: Optional[str], limit: int) -> Optional[str]:
    if not text:
        return text
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def run_semantic_search_tool(args: Dict[str, Any], artifact_id: str) -> Dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        return {"ok": False, "summary": "Boş arama",
                "content": json.dumps({"error": "query boş olamaz"}, ensure_ascii=False)}
    try:
        k = max(1, min(int(args.get("k") or SEARCH_DEFAULT_K), SEARCH_MAX_K))
        filters = {
            "priorities": [p for p in args.get("priorities") or [] if p in ("high", "med", "low")] or None,
            "date_from": _utc_arg(args.get("date_from_utc")),
            "date_to": _utc_arg(args.get("date_to_utc")),
            "topic_names": [str(t) for t in args.get("topics") or []] or None,
            "analyzable_only": bool(args.get("analyzable_only")),
        }
    except (TypeError, ValueError) as e:
        return {"ok": False, "summary": f"Geçersiz argüman: {e}",
                "content": json.dumps({"error": str(e)}, ensure_ascii=False)}

    vectors, cost = await summary_service.embed_texts([query], kind="chat")
    # The DB part runs in a worker thread so the event loop keeps serving other streams.
    results = await asyncio.to_thread(_search_results, vectors[0], query, filters, k)
    return _finish_search(artifact_id, query, results, cost)


def _search_results(vector: List[float], query: str, filters: Dict[str, Any], k: int) -> List[Dict[str, Any]]:
    """The hybrid search's best `k` articles with their evidence (blocking DB work)."""
    db = SessionLocal()
    try:
        candidates = crud.semantic_candidates(db, vector, query, limit=SEARCH_CANDIDATES, **filters)
        fused = fuse_rankings(candidates)[:k]
        articles = crud.get_articles_for_search(db, [hit["article_id"] for hit in fused])
        results = []
        for hit in fused:
            article = articles.get(hit["article_id"])
            if article is None:
                continue
            by_type = {s.summary_type: s.summary_text for s in article.summaries}
            summary = by_type.get("brief") or by_type.get("standard") or by_type.get("detailed")
            results.append({
                "id": article.id,
                "title": article.title,
                "date": _json_value(article.published_at or article.fetched_at),
                "priority": article.priority,
                "importance": article.importance,
                "feed": article.feed.title if article.feed else None,
                "topics": [link.topic.name for link in article.topics if link.topic],
                "summary": _short(summary, 400),
                "evidence": _short(hit["evidence"], 500),
                "matched_by": hit["matched_by"],
                "score": hit["score"],
            })
    finally:
        db.close()
    return results


def _finish_search(artifact_id: str, query: str, results: List[Dict[str, Any]], cost: float) -> Dict[str, Any]:
    artifact = {
        "id": artifact_id, "kind": "table", "purpose": f"Vektör arama: {query}",
        "columns": ["id", "title", "date", "priority", "feed", "score"],
        "rows": [[r["id"], r["title"], r["date"], r["priority"], r["feed"], r["score"]] for r in results],
        "truncated": False,
    }
    content: Dict[str, Any] = {"artifact_id": artifact_id, "results": results}
    if not results:
        content["note"] = "Eşleşen haber yok; filtreleri gevşetmeyi veya sorguyu değiştirmeyi deneyin."
    return {"ok": True, "summary": f"{len(results)} haber bulundu", "artifact": artifact, "cost": cost,
            "content": json.dumps(content, ensure_ascii=False)}


def run_chart_tool(args: Dict[str, Any], artifact_id: str) -> Dict[str, Any]:
    def fail(reason: str) -> Dict[str, Any]:
        return {"ok": False, "summary": f"Grafik çizilemedi: {reason}",
                "content": json.dumps({"error": reason}, ensure_ascii=False)}

    chart_type = args.get("type")
    if chart_type not in ("bar", "line", "stacked_bar"):
        return fail("type bar, line veya stacked_bar olmalı")
    x = [str(v) for v in (args.get("x") or [])]
    series = args.get("series") or []
    if not x or len(x) > MAX_CHART_POINTS:
        return fail(f"x 1–{MAX_CHART_POINTS} etiket içermeli")
    if not series or len(series) > MAX_CHART_SERIES:
        return fail(f"1–{MAX_CHART_SERIES} seri olmalı")
    clean_series = []
    for item in series:
        values = item.get("values") if isinstance(item, dict) else None
        if not isinstance(values, list) or len(values) != len(x):
            return fail("her serinin değer sayısı x ile aynı olmalı")
        try:
            numbers = [float(v) if v is not None else 0.0 for v in values]
        except (TypeError, ValueError):
            return fail("değerler sayı olmalı")
        clean_series.append({"name": str(item.get("name") or ""), "values": numbers})
    chart = {
        "id": artifact_id, "kind": "chart", "type": chart_type, "title": str(args.get("title") or ""),
        "x": x, "series": clean_series,
        "x_label": args.get("x_label"), "y_label": args.get("y_label"),
    }
    return {"ok": True, "summary": f"Grafik: {chart['title']}", "artifact": chart, "chart": chart,
            "content": json.dumps({"ok": True, "artifact_id": artifact_id}, ensure_ascii=False)}


async def execute_tool(function_name: str, raw_arguments: str, allowed: List[str], artifact_id: str) -> Dict[str, Any]:
    """Run one model-requested tool call. Never raises: an unknown/disabled tool or bad arguments
    come back as an error result the model can react to. Returns {tool, input, ok, summary,
    content (for the model), artifact?, chart?, sql?, cost?}. Only a cost-limit stop raises."""
    tool = _FUNCTION_TO_TOOL.get(function_name)
    try:
        args = json.loads(raw_arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError
    except ValueError:
        args = None
    if tool is None or tool not in allowed:
        outcome = {"ok": False, "summary": f"“{function_name}” aracı kullanılamaz",
                   "content": json.dumps({"error": "Bu araç kapalı veya yok."}, ensure_ascii=False)}
    elif args is None:
        outcome = {"ok": False, "summary": "Geçersiz araç argümanları",
                   "content": json.dumps({"error": "Argümanlar geçerli JSON nesnesi olmalı."}, ensure_ascii=False)}
    else:
        try:
            if tool == "time":
                outcome = run_time_tool(args)
            elif tool == "sql":
                # Up to CHAT_SQL_TIMEOUT_MS of blocking DB work: off the event loop.
                outcome = await asyncio.to_thread(run_sql_tool, args, artifact_id)
            elif tool == "semantic_search":
                outcome = await run_semantic_search_tool(args, artifact_id)
            else:
                outcome = run_chart_tool(args, artifact_id)
        except CostLimitExceededError:
            raise
        except Exception as e:
            logger.exception("Asistan tool %s failed", tool)
            outcome = {"ok": False, "summary": f"Araç hatası: {e}",
                       "content": json.dumps({"error": "Araç beklenmedik bir hata verdi."}, ensure_ascii=False)}
    return {"tool": tool or function_name, "input": args or {}, **outcome}
