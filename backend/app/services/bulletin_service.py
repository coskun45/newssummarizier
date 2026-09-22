"""
On-demand Word bulletin report generation: LLM classification of articles into
the user's top-level bulletin categories + dynamic subcategories, an LLM-picked
"gündem özeti" digest, and docx rendering.

Deliberately separate from summary_service.py: this is a batch workflow
triggered by an API route (see api/routes/bulletin.py), not a step in the
always-on LangGraph ingestion pipeline, and it writes to its own tables
(BulletinCategory, ArticleBulletinClassification) rather than Article/Summary.
It reuses summary_service's OpenAI plumbing (client, cost tracking) instead of
duplicating it.
"""
import hashlib
import io
import json
import logging
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.agents.tools import truncate_content
from app.core.config import settings
from app.core.exceptions import BulletinGenerationError
from app.db import crud, models
from app.services import docx_service
from app.services.summary_service import check_cost_limits, get_openai_client

logger = logging.getLogger(__name__)

_VALID_ARTICLE_TYPES = {"haber", "haber_detayi", "yorum"}
_DIGER_CATEGORY_NAME = "DİĞER"

_BULLETIN_CLASSIFICATION_SYSTEM_PROMPT = """Sen bir haber editörüsün. Görevin, verilen haberleri belirtilen üst düzey kategorilere ve senin üreteceğin alt başlıklara ayırmaktır.
Her zaman geçerli JSON döndür, başka hiçbir şey yazma.

ÜST DÜZEY KATEGORİLER (yalnızca bu listeden birebir bir isim seç; hiçbiri uymuyorsa "DİĞER" yaz):
{category_list}

Her haber için:
1. top_category: yukarıdaki listeden birebir bir isim, ya da "DİĞER".
2. subcategory: haberin somut konusunu yansıtan kısa bir Türkçe alt başlık (ör. "Ukrayna Savaşı", "Avrupa Göç Gündemi"). Aynı konudaki haberlere AYNI alt başlığı ver.
3. type: "haber" (ana/bağımsız haber), "haber_detayi" (aynı konudaki tamamlayıcı/ikincil haber) veya "yorum" (analiz, köşe yazısı, yorum niteliğinde) değerlerinden biri.

ÇIKTI FORMATI (yalnızca geçerli JSON):
{"classifications": [{"article_id": 123, "top_category": "AVRUPA", "subcategory": "Avrupa Göç Gündemi", "type": "haber"}]}
"""

_BULLETIN_DIGEST_SYSTEM_PROMPT = """Sen bir haber editörüsün. Görevin, verilen haber listesinden en dikkat çekici olanları seçip bir "gündem özeti" hazırlamaktır.

En fazla {limit} haber seç (hepsini seçmek zorunda değilsin). Her biri için tek cümlelik, bilgilendirici bir Türkçe özet cümlesi yaz.

ÇIKTI FORMATI (yalnızca geçerli JSON):
{"digest": [{"article_id": 123, "blurb": "Tek cümlelik özet."}]}
"""

_PRIORITY_RANK = {"high": 0, "med": 1, "low": 2, None: 3}
_DIGEST_CANDIDATE_CAP = 200


def compute_category_set_hash(category_names: List[str]) -> str:
    """Short, order-independent, case-fold-independent fingerprint of the
    current top-level category set, used as the classification cache key."""
    normalized = sorted(c.strip().casefold() for c in category_names)
    return hashlib.sha256("|".join(normalized).encode("utf-8")).hexdigest()[:16]


def _article_source(article: models.Article) -> str:
    try:
        return urlparse(article.url).hostname or ""
    except Exception:
        return ""


def _format_feed_lines(feeds: List[models.Feed]) -> List[str]:
    """One line per actively-followed RSS feed, for the "BAZI KAYNAKLAR"
    section — replaces the template's static example source list."""
    lines = []
    for feed in feeds:
        try:
            hostname = urlparse(feed.url).hostname or ""
        except Exception:
            hostname = ""
        title = feed.title or hostname or feed.url
        lines.append(f"{title}: {feed.url}")
    return lines


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


def _article_snippet(article: models.Article) -> str:
    """Prefer the existing brief summary (already paid for) over a fresh LLM
    call; falls back to truncated raw/cleaned content."""
    brief = next((s.summary_text for s in article.summaries if s.summary_type == "brief"), None)
    if brief:
        return brief
    content = article.cleaned_content or article.raw_content or article.title
    return truncate_content(_strip_html(content), max_tokens=150)


def _build_category_list(category_names: List[str]) -> str:
    return "\n".join(f"- {name}" for name in category_names)


def _chunked(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


async def _call_json_completion(system_prompt: str, user_prompt: str, max_completion_tokens: int) -> Dict[str, Any]:
    """Shared OpenAI JSON-mode call: JSON-fence stripping + one retry on a bad
    parse, mirroring summary_service.categorize_and_prioritize_article."""
    model = settings.default_model
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
            temperature=0.1,
            max_completion_tokens=max_completion_tokens,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if content is None:
            last_error = ValueError("OpenAI response content was empty (possibly content-filtered)")
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
) -> List[Dict[str, Any]]:
    """Batches `articles` and classifies each into (top_category, dynamic
    subcategory, type). Entries whose top_category isn't in `category_names`
    are bucketed into the "DİĞER" fallback rather than dropped."""
    if not articles:
        return []

    await check_cost_limits()

    prompt_obj = crud.get_system_prompt(db, "bulletin_classification")
    system_prompt_template = (
        prompt_obj.prompt_text if (prompt_obj and prompt_obj.is_active)
        else _BULLETIN_CLASSIFICATION_SYSTEM_PROMPT
    )
    system_prompt = system_prompt_template.replace("{category_list}", _build_category_list(category_names))

    results: List[Dict[str, Any]] = []
    batch_size = max(1, settings.bulletin_classification_batch_size)
    for batch in _chunked(articles, batch_size):
        lines = [f"{a.id} | {a.title} | {_article_snippet(a)}" for a in batch]
        user_prompt = "Aşağıdaki haberleri sınıflandır:\n\n" + "\n".join(lines)

        payload = await _call_json_completion(system_prompt, user_prompt, max_completion_tokens=1500)
        for entry in payload.get("classifications", []):
            article_id = entry.get("article_id")
            subcategory = entry.get("subcategory")
            article_type = entry.get("type")
            top_category = entry.get("top_category")

            if article_id is None or not subcategory or article_type not in _VALID_ARTICLE_TYPES:
                logger.warning(f"Dropping malformed bulletin classification entry: {entry}")
                continue
            if top_category not in category_names:
                top_category = _DIGER_CATEGORY_NAME

            results.append({
                "article_id": article_id,
                "top_category": top_category,
                "subcategory": subcategory.strip(),
                "type": article_type,
            })
    return results


async def pick_bulletin_digest(articles: List[models.Article], limit: int = 8) -> List[Dict[str, Any]]:
    """Single call picking the most noteworthy ~`limit` articles with a
    one-sentence Turkish blurb each. Not cached — cheap, single call, and
    reflects this run's specific selection rather than a per-article fact."""
    if not articles:
        return []

    await check_cost_limits()

    ranked = sorted(
        articles,
        key=lambda a: (
            _PRIORITY_RANK.get(a.priority, 3),
            -(a.published_at.timestamp() if a.published_at else 0),
        ),
    )
    candidates = ranked[:_DIGEST_CANDIDATE_CAP]
    candidate_ids = {a.id for a in candidates}

    system_prompt = _BULLETIN_DIGEST_SYSTEM_PROMPT.replace("{limit}", str(limit))
    lines = [f"{a.id} | {a.title} | {_article_snippet(a)}" for a in candidates]
    user_prompt = "Aşağıdaki haberlerden gündem özeti için en dikkat çekici olanları seç:\n\n" + "\n".join(lines)

    payload = await _call_json_completion(system_prompt, user_prompt, max_completion_tokens=1000)

    digest: List[Dict[str, Any]] = []
    for entry in payload.get("digest", [])[:limit]:
        article_id = entry.get("article_id")
        blurb = entry.get("blurb")
        if article_id not in candidate_ids or not blurb:
            continue
        digest.append({"article_id": article_id, "blurb": blurb.strip()})
    return digest


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


async def generate_bulletin_report(
    db: Session,
    articles: List[models.Article],
    categories: List[models.BulletinCategory],
) -> io.BytesIO:
    """Orchestrates: cache lookup -> classify the uncached subset -> persist ->
    pick the digest -> group -> render the docx."""
    category_names = [c.name for c in categories]
    category_set_hash = compute_category_set_hash(category_names)

    articles_by_id = {a.id: a for a in articles}
    cached = crud.get_bulletin_classifications(db, list(articles_by_id.keys()), category_set_hash)
    uncached_articles = [a for a in articles if a.id not in cached]

    new_classifications = await classify_articles_for_bulletin(db, uncached_articles, category_names)
    for entry in new_classifications:
        article = articles_by_id.get(entry["article_id"])
        if article is None:
            continue
        row = crud.create_bulletin_classification(
            db,
            article_id=article.id,
            category_set_hash=category_set_hash,
            top_category=entry["top_category"],
            subcategory=entry["subcategory"],
            article_type=entry["type"],
            model_used=settings.default_model,
        )
        cached[article.id] = row

    digest_picks = await pick_bulletin_digest(articles)
    digest_items = []
    for pick in digest_picks:
        classification = cached.get(pick["article_id"])
        digest_items.append({
            "blurb": pick["blurb"],
            "article_type": classification.article_type if classification else "haber",
        })

    categorized: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for article in articles:
        classification = cached.get(article.id)
        if classification is None:
            # Not classified this run (e.g. dropped as malformed by the LLM
            # call) — leave it out of the grouped sections rather than guess.
            continue
        top_bucket = categorized.setdefault(classification.top_category, {})
        sub_bucket = top_bucket.setdefault(classification.subcategory, [])
        sub_bucket.append({
            "synopsis": _article_snippet(article),
            "source": _article_source(article),
            "article_type": classification.article_type,
        })

    feed_lines = _format_feed_lines(crud.get_feeds(db, active_only=True))

    return docx_service.render_bulletin_docx(
        generated_at=datetime.now(timezone.utc),
        digest_items=digest_items,
        categorized=categorized,
        category_order=category_names,
        feed_lines=feed_lines,
    )
