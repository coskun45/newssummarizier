"""
On-demand Word bulletin report generation.

Steps (see `build_bulletin_sections`; `generate_bulletin_report` renders them to .docx):
1. every selected article gets a summary of the chosen `summary_type` (default "stored": the
   one the pipeline already stored), or a new one generated with the same summarizer and saved
   (`_ensure_bulletin_summaries`); its
   "📌 Kaynak / Yazar - Başlık" + "🔹 ..." lines are the article's block in the report;
2. each article is classified into one of the user's top-level categories + a type (cached per
   category set);
3. an LLM editor picks at most 5 articles for "ÖNE ÇIKAN BAŞLIKLAR", grouped under short topic
   headings — those articles are not repeated in their category;
4. per category, the remaining articles are grouped into meaningful topic subheadings;
5. docx_service renders it into the bundled template.

Deliberately separate from the always-on LangGraph ingestion pipeline: this is a batch workflow
triggered by an API route (api/routes/bulletin.py). All OpenAI calls reuse summary_service's
plumbing (client, cost limits, usage booking) instead of duplicating it.
"""
import asyncio
import hashlib
import io
import json
import logging
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, get_args
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.agents.tools import truncate_content
from app.core.config import settings
from app.core.exceptions import BulletinGenerationError, CostLimitExceededError
from app.db import crud, models
from app.services import docx_service, summary_service
from app.services.summary_service import (
    article_source_name,
    calculate_cost,
    check_cost_limits,
    clean_author,
    completion_params,
    count_tokens,
    empty_answer_error,
    get_classification_model,
    get_openai_client,
    is_empty_answer,
    record_llm_usage,
    resolve_summary_author,
)

logger = logging.getLogger(__name__)

_VALID_ARTICLE_TYPES = {"haber", "haber_detayi", "yorum"}
_DIGER_CATEGORY_NAME = "DİĞER"
ONE_CIKAN_BASLIKLAR_LABEL = "ÖNE ÇIKAN BAŞLIKLAR"
HIGHLIGHT_LIMIT = 5
OTHER_GROUP_SUFFIX = "DİĞER GELİŞMELER"

_HEADER_ICON = "📌"
_YORUM_ICON = "⭕️"
_BULLET_ICON = "🔹"
_SUMMARY_CONCURRENCY = 5
_PRIORITY_RANK = {"high": 0, "med": 1, "low": 2, None: 3}
_HIGHLIGHT_CANDIDATE_CAP = 10

_BULLETIN_CLASSIFICATION_SYSTEM_PROMPT = """Sen bir haber editörüsün. Görevin, verilen haberleri belirtilen üst düzey kategorilere ayırmak ve türlerini belirlemektir.
Her zaman geçerli JSON döndür, başka hiçbir şey yazma.

ÜST DÜZEY KATEGORİLER:
{category_list}

Her haber için:
1. top_category: haberin konusu, ülkesi veya bölgesiyle en ilgili kategori; ismi listede yazıldığı gibi yaz.
   Bir haber birden fazla kategoriye uyuyorsa en ilgili olanı seç (ör. Ukrayna savaşı haberi "Ukrayna" varsa oraya,
   ABD haberi "Amerika" varsa oraya, NATO/AB haberi ilgili kategoriye). "DİĞER"i YALNIZCA hiçbir kategori uymuyorsa kullan.
2. type: "haber" (ana/bağımsız haber), "haber_detayi" (aynı konudaki tamamlayıcı/ikincil haber) veya "yorum" (analiz, köşe yazısı, yorum niteliğinde) değerlerinden biri.

ÇIKTI FORMATI (yalnızca geçerli JSON):
{"classifications": [{"article_id": 123, "top_category": "AVRUPA", "type": "haber"}]}
"""

_HIGHLIGHTS_SYSTEM_PROMPT = """Sen deneyimli bir dış haberler editörüsün. Görevin, verilen haberlerden bültenin en başındaki "ÖNE ÇIKAN BAŞLIKLAR" bölümüne girecek haberleri seçmektir.

Seçim ölçütleri: okurun en çok ilgisini çekecek, güncel, dünyayı ve/veya Türkiye'yi yakından ilgilendiren, sansasyonel ve çarpıcı gelişmeler.

Kurallar:
- En fazla {limit} haber seç (daha azı da olabilir).
- Seçtiğin haberleri konularına göre kısa ve öz alt başlıklar altında grupla; aynı konudaki haberleri aynı alt başlıkta topla.
- Alt başlıklar Türkçe, BÜYÜK HARF ve 2-6 kelime olsun (ör. "BM GENEL KURULU", "TÜRKİYE: BORSA İSTANBUL - FON KRİZİ", "K.KOZİNOĞLU SORUŞTURMASI").
- Alt başlıkları önem sırasına göre sırala.

ÇIKTI FORMATI (yalnızca geçerli JSON):
{"highlights": [{"title": "BM GENEL KURULU", "article_ids": [12, 15]}]}
"""

_GROUPING_SYSTEM_PROMPT = """Sen deneyimli bir haber editörüsün. Verilen haberler bültenin "{category}" bölümüne ait. Görevin bu haberleri konularına göre alt başlıklar altında gruplamaktır.

Kurallar:
- Aynı olay, ülke veya gündem konusundaki haberleri AYNI alt başlıkta topla. Her haber için ayrı alt başlık AÇMA; bir alt başlıkta mümkün olduğunca birden fazla haber olsun.
- Alt başlıklar anlamlı, kısa (2-6 kelime), Türkçe ve BÜYÜK HARF olsun; gerektiğinde "ÜLKE: KONU" biçimini kullan (ör. "ALMANYA: AFD / EYALET SEÇİMLERİ", "AVRUPA GÖÇ GÜNDEMİ", "AVRUPA SAVUNMA GÜNDEMİ / NATO", "UKRAYNA SAVAŞI", "KUZEY IRAK", "ABD: ARA SEÇİMLER").
- Hiçbir konuya uymayan tekil haberleri "{other_label}" alt başlığında topla ve bu başlığı en sona koy.
- Her haberi tam olarak bir alt başlığa koy; hiçbir haberi atlama.
- Alt başlıkları önem sırasına göre sırala.

ÇIKTI FORMATI (yalnızca geçerli JSON):
{"groups": [{"title": "AVRUPA GÖÇ GÜNDEMİ", "article_ids": [3, 8]}]}
"""


# Part of the classification cache key. Bump it when classification results must not be reused
# — "2": answers whose category differed only in case/Turkish-I form were stored as DİĞER.
_CLASSIFICATION_CACHE_VERSION = "2"


def compute_category_set_hash(category_names: List[str]) -> str:
    """Short, order-independent, case-fold-independent fingerprint of the
    current top-level category set, used as the classification cache key."""
    normalized = sorted(c.strip().casefold() for c in category_names)
    key = f"v{_CLASSIFICATION_CACHE_VERSION}|" + "|".join(normalized)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# Fold the Turkish I-variants before lowercasing (like crud's category-name duplicate check) so
# "UKRAYNA", "İRAN" or "AMERIKA" match the stored "Ukrayna", "Iran", "Amerika".
_TR_I_FOLD = str.maketrans({"İ": "i", "I": "i", "ı": "i"})


def _category_key(name: str) -> str:
    return _WHITESPACE_RUN_RE.sub(" ", (name or "").strip().translate(_TR_I_FOLD).lower())


def _resolve_category(name: Any, category_names: List[str]) -> str:
    """The user's category a model answer (or cached row) means, compared case- and
    Turkish-I-insensitively; DİĞER when it names none of them."""
    if isinstance(name, str):
        if name in category_names:  # exact first: legacy DBs may hold "Avrupa" and "AVRUPA" both
            return name
        key = _category_key(name)
        for category in category_names:
            if _category_key(category) == key:
                return category
    return _DIGER_CATEGORY_NAME


def _article_source(article: models.Article) -> str:
    """Same "Kaynak" as the article cards and summary header: the feed's name, else the domain."""
    return article_source_name(article.feed.title if article.feed else None, article.url) or ""


def _article_id(value: Any) -> Optional[int]:
    """The model sometimes sends ids as strings ("123"); anything non-numeric is no id."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _tr_upper(text: str) -> str:
    """Upper-case with Turkish i/ı rules (plain str.upper() turns "i" into "I", not "İ")."""
    return text.replace("i", "İ").replace("ı", "I").upper()


def _feed_titles(feeds: List[models.Feed]) -> List[str]:
    """One name per actively-followed RSS feed, for the "BAZI KAYNAKLAR" section."""
    titles = []
    for feed in feeds:
        try:
            hostname = urlparse(feed.url).hostname or ""
        except Exception:
            hostname = ""
        title = (feed.title or "").strip() or hostname or feed.url
        if title not in titles:
            titles.append(title)
    return titles


_WHITESPACE_RUN_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    """Collapse embedded HTML markup down to plain text.

    raw_content is the RSS <description>, which for several feeds (e.g.
    Aydinlik) is itself an HTML fragment (<a>/<img>/<h4>/<div> tags) rather
    than plain text. cleaned_content falls back to that same raw_content
    verbatim when article scraping fails (see agents/nodes.py), so without
    this the markup — and HTML entities like &#039; — leaked straight into
    the rendered bulletin as visible text.

    Uses a real HTML parser (not a "<[^>]+>" regex) so literal bracketed text
    that isn't actually markup, e.g. "büyüme <10 yaş grubunda> daha hızlı",
    isn't mistaken for a tag and deleted."""
    plain = BeautifulSoup(text, "html.parser").get_text(separator=" ")
    return _WHITESPACE_RUN_RE.sub(" ", unescape(plain)).strip()


def _article_content(article: models.Article) -> str:
    return _strip_html(article.cleaned_content or article.raw_content or article.title or "")


def _existing_summary(article: models.Article, summary_type: str) -> Optional[str]:
    return next(
        (s.summary_text for s in article.summaries
         if s.summary_type == summary_type and (s.summary_text or "").strip()),
        None,
    )


# Which summary a bulletin uses, chosen per bulletin (Bülten › Oluştur) and per subscription:
# "stored" uses whichever summary the article already has, the others ask for that one type.
BulletinSummaryType = Literal["stored", "detailed", "standard", "brief"]
BULLETIN_SUMMARY_TYPES = get_args(BulletinSummaryType)
DEFAULT_BULLETIN_SUMMARY_TYPE = "stored"
# Which stored summary "stored" picks first; also the fallback order when a summary fails.
_STORED_PREFERENCE = ("detailed", "standard", "brief")


def _preferred_stored_summary(article: models.Article, first: Optional[str] = None) -> Optional[str]:
    """The article's stored summary: `first` if it has one, else in `_STORED_PREFERENCE` order."""
    order = ([first] if first else []) + [t for t in _STORED_PREFERENCE if t != first]
    return next((text for text in (_existing_summary(article, t) for t in order) if text), None)


# ---------------------------------------------------------------------------
# Bulletin summaries
# ---------------------------------------------------------------------------

async def _ensure_bulletin_summaries(
    db: Session, articles: List[models.Article], summary_type: str,
) -> Dict[int, str]:
    """{article_id: summary text} for the bulletin, per `summary_type` (see BULLETIN_SUMMARY_TYPES):
    "stored" takes the article's stored summary (detailed > standard > brief), a concrete type
    takes the stored summary of that type. An article without one gets it from the pipeline's own
    summarizer (same system prompt, source and author handling as `summary_service.process_article`)
    — for "stored" in the first summary type enabled in Ayarlar, so the bulletin never adds a type
    the user switched off — and it is saved so the next report doesn't pay again. A failed summary
    falls back to any other stored summary (used for this report only), else to plain content;
    hitting the cost limit stops the report."""
    summaries: Dict[int, str] = {}
    missing: List[models.Article] = []
    for article in articles:
        text = (_preferred_stored_summary(article) if summary_type == "stored"
                else _existing_summary(article, summary_type))
        if text:
            summaries[article.id] = text
        else:
            missing.append(article)
    if not missing:
        return summaries

    if summary_type == "stored":
        enabled = summary_service.get_enabled_summary_types(db)
        generate_type = next(t for t in _STORED_PREFERENCE if t in enabled)
    else:
        generate_type = summary_type

    await check_cost_limits()

    # The pipeline only scrapes important articles; a starred filtered/Error one would
    # otherwise be summarized from its RSS teaser.
    # Use the returned text, not a re-read of cleaned_content: storing it may have failed.
    pages: Dict[int, str] = {}
    for article in missing:
        if not article.cleaned_content:
            page = await summary_service.fetch_article_content(db, article.id)
            if page:
                pages[article.id] = _strip_html(page)

    jobs = []
    for article in missing:
        source = _article_source(article)
        jobs.append({
            "article": article,
            "title": article.title,
            "content": truncate_content(pages.get(article.id) or _article_content(article)),
            "source": source,
            "author_hint": clean_author(article.feed_author or article.author, source),
        })

    semaphore = asyncio.Semaphore(_SUMMARY_CONCURRENCY)

    async def summarize(job):
        async with semaphore:
            try:
                return await summary_service.generate_summary(
                    title=job["title"], content=job["content"], summary_type=generate_type,
                    source=job["source"], author_hint=job["author_hint"],
                )
            except CostLimitExceededError:
                raise
            except Exception as e:
                logger.warning(f"Bulletin: {generate_type} summary failed for article {job['article'].id}: {e}")
                return e

    results = await asyncio.gather(*(summarize(job) for job in jobs))

    for job, result in zip(jobs, results):
        article = job["article"]
        if isinstance(result, Exception) or not result or not result.get("summary_text"):
            crud.create_log(db=db, article_id=article.id, agent_name="summarizer", status="error",
                            message=f"Failed to generate {generate_type} summary for the bulletin",
                            error_details=str(result))
            fallback = _preferred_stored_summary(article)
            if fallback:
                summaries[article.id] = fallback
            continue
        crud.create_summary(
            db=db, article_id=article.id, summary_text=result["summary_text"], summary_type=generate_type,
            model_used=result.get("model_used"), tokens_used=result.get("tokens_used", 0),
            cost=result.get("cost", 0.0),
        )
        if not article.author:
            crud.set_article_author(db, article.id, resolve_summary_author([result], job["author_hint"]))
        summaries[article.id] = result["summary_text"]
    return summaries


_ICON_SPLIT_RE = re.compile(r"\s*(📌|⭕️|⭕|🔹)")


def _article_block(article: models.Article, summary: Optional[str], article_type: str) -> Dict[str, Any]:
    """The article as the bulletin shows it: a "📌 Kaynak / Yazar - Başlık" header line and "🔹"
    bullets, taken from the bulletin summary (the summarizer writes every type in this shape)."""
    header: Optional[str] = None
    bullets: List[str] = []
    if summary:
        text = _ICON_SPLIT_RE.sub(r"\n\1", summary.replace("**", ""))
        for line in (raw.strip() for raw in text.splitlines()):
            if not line:
                continue
            if line.startswith(("📌", "⭕")):
                if header is None:
                    header = line
                continue
            body = line[len(_BULLET_ICON):].strip() if line.startswith(_BULLET_ICON) else line
            if body:
                bullets.append(f"{_BULLET_ICON} {body}")

    if header is None:
        source = _article_source(article)
        author = clean_author(article.author, source)
        credit = f"{source} / {author}" if author else source
        header = f"{_HEADER_ICON} {credit} - {article.title}" if credit else f"{_HEADER_ICON} {article.title}"
    if not bullets:
        snippet = truncate_content(_article_content(article), max_tokens=150)
        if snippet and snippet != article.title:
            bullets.append(f"{_BULLET_ICON} {snippet}")

    if article_type == "yorum":
        header = re.sub(r"^(📌|⭕️|⭕)", _YORUM_ICON, header)
    return {"header": header, "bullets": bullets, "article_type": article_type, "url": article.url}


def _prompt_line(article: models.Article, block: Dict[str, Any]) -> str:
    """One line per article for the editor prompts: id, header and the first bullet."""
    first = block["bullets"][0] if block["bullets"] else ""
    return f"{article.id} | {block['header']} | {truncate_content(first, max_tokens=60)}"


def _rank_key(article: models.Article):
    return (
        _PRIORITY_RANK.get(article.priority, 3),
        -(article.published_at.timestamp() if article.published_at else 0),
    )


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

def _chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _build_category_list(category_names: List[str]) -> str:
    return "\n".join(f"- {name}" for name in category_names)


async def _call_json_completion(
    system_prompt: str, user_prompt: str, max_completion_tokens: int, model: str,
) -> Dict[str, Any]:
    """Shared OpenAI JSON-mode call: JSON-fence stripping + one retry on a bad
    parse, mirroring summary_service.categorize_and_prioritize_article. `model` is the
    classification model, resolved once per bulletin by the caller."""
    result: Optional[Dict[str, Any]] = None
    last_error: Optional[Exception] = None

    for attempt in range(2):
        prompt = user_prompt if attempt == 0 else (
            user_prompt + "\n\nÖNEMLİ: Yanıtın SADECE geçerli bir JSON nesnesi olmalı, "
            "başka hiçbir metin, açıklama veya kod bloğu işareti içermemeli."
        )
        response = await get_openai_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            **completion_params(model, 0.1, max_completion_tokens),
        )
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None)
        if not isinstance(input_tokens, int):
            input_tokens = count_tokens(system_prompt + prompt, model)
        output_tokens = getattr(usage, "completion_tokens", 0) or 0
        record_llm_usage("bulletin", model, input_tokens, output_tokens,
                         calculate_cost(model, input_tokens, output_tokens))
        content = response.choices[0].message.content
        if is_empty_answer(content):
            finish_reason = response.choices[0].finish_reason
            last_error = ValueError(empty_answer_error(finish_reason))
            if finish_reason == "length":
                # A retry runs with the same budget and runs out the same way — don't pay twice.
                logger.warning(f"Bulletin LLM call attempt {attempt + 1}: {last_error}")
                break
            logger.warning(f"Bulletin LLM call attempt {attempt + 1} returned no content, retrying: {last_error}")
            continue

        text = content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        try:
            result = json.loads(text)
            break
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(f"Bulletin LLM call attempt {attempt + 1} produced invalid JSON, retrying: {e}")
            continue

    if result is None:
        raise BulletinGenerationError(f"Bulletin LLM call failed after retry: {last_error}")
    return result


async def classify_articles_for_bulletin(
    db: Session,
    articles: List[models.Article],
    category_names: List[str],
    blocks: Optional[Dict[int, Dict[str, Any]]] = None,
    *,
    model: str,
) -> List[Dict[str, Any]]:
    """Batches `articles` and classifies each into (top_category, type). Entries whose
    top_category isn't in `category_names` are bucketed into the "DİĞER" fallback rather than
    dropped."""
    if not articles:
        return []

    await check_cost_limits()

    prompt_obj = crud.get_system_prompt(db, "bulletin_classification")
    system_prompt_template = (
        prompt_obj.prompt_text if (prompt_obj and prompt_obj.is_active and (prompt_obj.prompt_text or "").strip())
        else _BULLETIN_CLASSIFICATION_SYSTEM_PROMPT
    )
    system_prompt = system_prompt_template.replace("{category_list}", _build_category_list(category_names))

    results: List[Dict[str, Any]] = []
    batch_size = max(1, settings.bulletin_classification_batch_size)
    for batch in _chunked(articles, batch_size):
        lines = [
            _prompt_line(a, blocks[a.id]) if blocks and a.id in blocks else f"{a.id} | {a.title}"
            for a in batch
        ]
        user_prompt = "Aşağıdaki haberleri sınıflandır:\n\n" + "\n".join(lines)

        payload = await _call_json_completion(system_prompt, user_prompt, max_completion_tokens=1500, model=model)
        for entry in payload.get("classifications", []):
            article_id = _article_id(entry.get("article_id"))
            article_type = entry.get("type")

            if article_id is None or article_type not in _VALID_ARTICLE_TYPES:
                logger.warning(f"Dropping malformed bulletin classification entry: {entry}")
                continue
            top_category = _resolve_category(entry.get("top_category"), category_names)

            results.append({
                "article_id": article_id,
                "top_category": top_category,
                "subcategory": (entry.get("subcategory") or "").strip(),
                "type": article_type,
            })
    return results


def _clean_groups(payload_groups: Any, allowed_ids: Sequence[int], limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Validate an LLM grouping answer: known ids only, each id once, at most `limit` ids in
    total, non-empty upper-cased titles; groups with the same title are merged."""
    allowed = set(allowed_ids)
    used: set = set()
    groups: List[Dict[str, Any]] = []
    by_title: Dict[str, Dict[str, Any]] = {}
    for entry in payload_groups if isinstance(payload_groups, list) else []:
        if not isinstance(entry, dict):
            continue
        title = _tr_upper(str(entry.get("title") or "").strip())
        raw_ids = entry.get("article_ids")
        if not title or not isinstance(raw_ids, list):
            continue
        ids = []
        for raw in raw_ids:
            article_id = _article_id(raw)
            if article_id in allowed and article_id not in used:
                if limit is not None and len(used) >= limit:
                    break
                used.add(article_id)
                ids.append(article_id)
        if not ids:
            continue
        if title in by_title:
            by_title[title]["article_ids"].extend(ids)
        else:
            group = {"title": title, "article_ids": ids}
            by_title[title] = group
            groups.append(group)
    return groups


async def pick_bulletin_highlights(
    articles: List[models.Article],
    blocks: Dict[int, Dict[str, Any]],
    limit: int = HIGHLIGHT_LIMIT,
    *,
    model: str,
) -> List[Dict[str, Any]]:
    """One call picking at most `limit` of the most striking articles for "ÖNE ÇIKAN
    BAŞLIKLAR", grouped under short topic headings: [{"title", "article_ids"}]."""
    if not articles:
        return []

    await check_cost_limits()

    candidates = sorted(articles, key=_rank_key)[:_HIGHLIGHT_CANDIDATE_CAP]
    system_prompt = _HIGHLIGHTS_SYSTEM_PROMPT.replace("{limit}", str(limit))
    user_prompt = (
        "Aşağıdaki haberlerden ÖNE ÇIKAN BAŞLIKLAR bölümüne girecekleri seç:\n\n"
        + "\n".join(_prompt_line(a, blocks[a.id]) for a in candidates)
    )
    payload = await _call_json_completion(system_prompt, user_prompt, max_completion_tokens=800, model=model)
    return _clean_groups(payload.get("highlights"), [a.id for a in candidates], limit=limit)


async def group_category_articles(
    category_name: str,
    articles: List[models.Article],
    blocks: Dict[int, Dict[str, Any]],
    *,
    model: str,
) -> List[Dict[str, Any]]:
    """Group one category's articles under meaningful topic subheadings:
    [{"title", "article_ids"}]. Articles the model left out land in the "<KATEGORİ>: DİĞER
    GELİŞMELER" group, so nothing selected is lost."""
    if not articles:
        return []

    await check_cost_limits()

    other_label = f"{_tr_upper(category_name)}: {OTHER_GROUP_SUFFIX}"
    system_prompt = (
        _GROUPING_SYSTEM_PROMPT.replace("{category}", category_name).replace("{other_label}", other_label)
    )
    ordered = sorted(articles, key=_rank_key)
    user_prompt = (
        "Aşağıdaki haberleri alt başlıklar altında grupla:\n\n"
        + "\n".join(_prompt_line(a, blocks[a.id]) for a in ordered)
    )
    payload = await _call_json_completion(system_prompt, user_prompt, max_completion_tokens=2000, model=model)
    groups = _clean_groups(payload.get("groups"), [a.id for a in ordered])

    grouped = {i for g in groups for i in g["article_ids"]}
    leftovers = [a.id for a in ordered if a.id not in grouped]
    if leftovers:
        other = next((g for g in groups if g["title"] == other_label), None)
        if other is None:
            groups.append({"title": other_label, "article_ids": leftovers})
        else:
            other["article_ids"].extend(leftovers)
    # The catch-all group always goes last.
    groups.sort(key=lambda g: g["title"] == other_label)
    return groups


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def save_bulletin_file(buffer: io.BytesIO, stored_filename: str) -> str:
    """Write generated bulletin bytes to BULLETIN_STORAGE_DIR so it can be
    re-downloaded later; returns the stored path. Reads via getvalue(), which
    doesn't consume the buffer's read position, so the caller's own
    StreamingResponse can still stream the same buffer afterward."""
    storage_dir = Path(settings.bulletin_storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    path = storage_dir / stored_filename
    path.write_bytes(buffer.getvalue())
    return str(path)


def delete_bulletin_file(stored_path: str) -> None:
    """Best-effort delete — a manually-removed file is not an error."""
    Path(stored_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _render_groups(
    groups: List[Dict[str, Any]],
    articles_by_id: Dict[int, models.Article],
    blocks: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rendered = []
    for group in groups:
        members = sorted((articles_by_id[i] for i in group["article_ids"] if i in articles_by_id), key=_rank_key)
        items = [blocks[a.id] for a in members]
        if items:
            rendered.append({"title": group["title"], "items": items})
    return rendered


async def classify_for_bulletin(
    db: Session,
    articles: List[models.Article],
    categories: List[models.BulletinCategory],
    summaries: Optional[Dict[int, str]] = None,
    model: Optional[str] = None,
    summary_type: str = DEFAULT_BULLETIN_SUMMARY_TYPE,
) -> Dict[int, models.ArticleBulletinClassification]:
    """{article_id: classification} for `articles` against the current category set: cached rows
    are reused, the rest are classified by the LLM and stored. An article the model dropped is
    simply missing from the result (callers place it under DİĞER). Without `summaries`, the
    bulletin summaries (`summary_type`) are ensured first (generated where missing): the stored
    classification is reused by every later bulletin, so it must not come from a title-only prompt."""
    category_names = [c.name for c in categories]
    category_set_hash = compute_category_set_hash(category_names)
    articles_by_id = {a.id: a for a in articles}
    cached = crud.get_bulletin_classifications(db, list(articles_by_id.keys()), category_set_hash)
    uncached_articles = [a for a in articles if a.id not in cached]
    if not uncached_articles:
        return cached
    if summaries is None:
        summaries = await _ensure_bulletin_summaries(db, uncached_articles, summary_type)

    # Classification needs a header to work from; the type (yorum → ⭕️) is applied by the caller.
    draft_blocks = {a.id: _article_block(a, summaries.get(a.id), "haber") for a in uncached_articles}

    # Resolved once (or handed down by build_bulletin_sections): every row records the model that ran.
    model = model or get_classification_model(db)
    new_classifications = await classify_articles_for_bulletin(
        db, uncached_articles, category_names, draft_blocks, model=model,
    )
    for entry in new_classifications:
        article = articles_by_id.get(_article_id(entry["article_id"]))
        # Unknown id, or one the model listed twice: the first answer wins — a second insert
        # would hit the (article_id, category_set_hash) unique constraint.
        if article is None or article.id in cached:
            continue
        cached[article.id] = crud.create_bulletin_classification(
            db,
            article_id=article.id,
            category_set_hash=category_set_hash,
            top_category=entry["top_category"],
            subcategory=entry.get("subcategory") or "",
            article_type=entry["type"],
            model_used=model,
        )
    return cached


def placement_category(
    classification: Optional[models.ArticleBulletinClassification], category_names: List[str]
) -> str:
    """The section an article lands in: its classified category, or DİĞER when unclassified."""
    if classification is None:
        return _DIGER_CATEGORY_NAME
    return _resolve_category(classification.top_category, category_names)


async def build_bulletin_sections(
    db: Session,
    articles: List[models.Article],
    categories: List[models.BulletinCategory],
    summary_type: str = DEFAULT_BULLETIN_SUMMARY_TYPE,
) -> List[Dict[str, Any]]:
    """Orchestrates: bulletin summaries -> classification (cached) -> highlights -> per-category
    topic groups. Returns the body sections both the docx and the e-mail are rendered from."""
    category_names = [c.name for c in categories]
    articles_by_id = {a.id: a for a in articles}

    summaries = await _ensure_bulletin_summaries(db, articles, summary_type)
    model = get_classification_model(db)  # once per bulletin: every LLM step runs on the same model
    cached = await classify_for_bulletin(db, articles, categories, summaries, model=model)

    # An article the classifier dropped still belongs in the report — under DİĞER.
    placement: Dict[int, str] = {}
    blocks: Dict[int, Dict[str, Any]] = {}
    for article in articles:
        classification = cached.get(article.id)
        placement[article.id] = placement_category(classification, category_names)
        article_type = classification.article_type if classification else "haber"
        blocks[article.id] = _article_block(article, summaries.get(article.id), article_type)

    highlight_groups = await pick_bulletin_highlights(articles, blocks, model=model)
    highlighted = {i for g in highlight_groups for i in g["article_ids"]}

    ordered_categories = list(category_names)
    if _DIGER_CATEGORY_NAME not in ordered_categories:
        ordered_categories.append(_DIGER_CATEGORY_NAME)
    by_category: Dict[str, List[models.Article]] = {name: [] for name in ordered_categories}
    for article in articles:
        if article.id not in highlighted:
            by_category[placement[article.id]].append(article)

    category_groups = await asyncio.gather(*(
        group_category_articles(name, by_category[name], blocks, model=model) for name in ordered_categories
    ))

    sections = [{
        "title": ONE_CIKAN_BASLIKLAR_LABEL,
        "groups": _render_groups(highlight_groups, articles_by_id, blocks),
    }]
    for name, groups in zip(ordered_categories, category_groups):
        sections.append({"title": name, "groups": _render_groups(groups, articles_by_id, blocks)})
    return sections


def render_bulletin_report(
    db: Session,
    sections: List[Dict[str, Any]],
    generated_at: Optional[datetime] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> io.BytesIO:
    """Render already built `sections` into the Word template."""
    return docx_service.render_bulletin_docx(
        generated_at=generated_at or datetime.now(timezone.utc),
        sections=sections,
        feed_titles=_feed_titles(crud.get_feeds(db, active_only=True)),
        metadata=metadata,
    )


async def generate_bulletin_report(
    db: Session,
    articles: List[models.Article],
    categories: List[models.BulletinCategory],
    metadata: Optional[Dict[str, Any]] = None,
    summary_type: str = DEFAULT_BULLETIN_SUMMARY_TYPE,
) -> io.BytesIO:
    """Sections (see `build_bulletin_sections`) rendered into the Word template."""
    sections = await build_bulletin_sections(db, articles, categories, summary_type)
    return render_bulletin_report(db, sections, metadata=metadata)
