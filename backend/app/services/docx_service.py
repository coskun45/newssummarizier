"""
Word (.docx) rendering for the on-demand bulletin report.

Mutates a bundled template in place instead of rebuilding the document from
scratch, so the icon legend and style definitions (Title/Heading1/Heading2
fonts, theme) come from the template verbatim rather than being
re-transcribed into Python constants. The "BAZI KAYNAKLAR" source list is
NOT static — it's replaced with the app's actually-configured RSS feeds.

Top-level categories render as Heading1, subcategories as Heading2 — this
matches the template's own bundled TOC field, whose \t switch maps
"Heading 1" to outline level 1 and "Heading 2" to level 2 (confirmed by
inspecting the template's field codes). Using Heading3 here, as an earlier
version of this module did, silently produced a broken-looking TOC that
skipped level 2 entirely once Word recomputed it.
"""
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from app.core.exceptions import BulletinGenerationError

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "resources" / "bulletin_template.docx"

TITLE_STYLE_ID = "Title"
HEADING1_STYLE_ID = "Heading1"
HEADING2_STYLE_ID = "Heading2"
NORMAL_STYLE_ID = "Normal"

GUNDEM_OZETI_LABEL = "GÜNDEM ÖZETİ"
ONE_CIKAN_BASLIKLAR_LABEL = "ÖNE ÇIKAN BAŞLIKLAR"
KAYNAKLAR_LABEL_PREFIX = "BAZI KAYNAKLAR"
DIGER_CATEGORY_NAME = "DİĞER"
NO_FEEDS_LINE = "Şu anda takip edilen bir RSS beslemesi yok."

_ICON_BY_TYPE = {"haber": "📌", "haber_detayi": "🔹", "yorum": "⭕️"}

_TURKISH_MONTHS = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan", 5: "Mayıs", 6: "Haziran",
    7: "Temmuz", 8: "Ağustos", 9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}

# Fold all four Turkish I-variants ('İ'/'I'/'ı'/'i') to the same character
# before lowercasing. Python's default .lower()/.upper() handle Ç/Ö/Ş/Ü/Ğ
# correctly but mishandle the dotted/dotless I pair — and the bundled
# template itself is inconsistent (e.g. "AMERIKA" with a plain ASCII 'I'
# where proper Turkish spelling is "AMERİKA"), so matching must tolerate
# both forms rather than "correctly" telling them apart.
_TR_I_FOLD = str.maketrans({"İ": "i", "I": "i", "ı": "i"})


def format_turkish_date(dt: datetime) -> str:
    """e.g. 01 Eylül 2026."""
    return f"{dt.day:02d} {_TURKISH_MONTHS[dt.month]} {dt.year}"


def _normalize(text: str) -> str:
    return text.strip().translate(_TR_I_FOLD).lower()


def _style_id(paragraph: Paragraph) -> Optional[str]:
    try:
        return paragraph.style.style_id
    except Exception:
        return None


def _insert_paragraph_after(paragraph: Paragraph, text: str, style=None) -> Paragraph:
    """python-docx has no public "insert paragraph after" API — this is the
    standard addnext()-based recipe, using the paragraph's own private
    `_parent` to construct a new Paragraph wrapping a freshly inserted <w:p>."""
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    new_para = Paragraph(new_p, paragraph._parent)
    if style is not None:
        new_para.style = style
    new_para.add_run(text)
    return new_para


def _heading1_spans(document: Document) -> List[tuple]:
    """[(heading1_paragraph, [child_paragraphs_until_next_heading1]), ...]."""
    paragraphs = document.paragraphs
    indices = [i for i, p in enumerate(paragraphs) if _style_id(p) == HEADING1_STYLE_ID]
    spans = []
    for pos, start in enumerate(indices):
        end = indices[pos + 1] if pos + 1 < len(indices) else len(paragraphs)
        spans.append((paragraphs[start], paragraphs[start + 1:end]))
    return spans


def _remove_paragraph(paragraph: Paragraph) -> None:
    element = paragraph._element
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _set_paragraph_text(paragraph: Paragraph, text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = text
        for extra in paragraph.runs[1:]:
            extra.text = ""
    else:
        paragraph.add_run(text)


def _set_title(document: Document, generated_at: datetime) -> Optional[Paragraph]:
    text = f"{format_turkish_date(generated_at)} Dünya Bülteni"
    for p in document.paragraphs:
        if _style_id(p) == TITLE_STYLE_ID:
            _set_paragraph_text(p, text)
            return p
    return None


def _replace_kaynaklar_section(
    document: Document,
    styles_by_id: Dict[str, Any],
    feed_lines: List[str],
) -> None:
    """Replace the template's static "BAZI KAYNAKLAR" country/source list with
    the app's actually-configured RSS feeds, one line per feed."""
    normal_style = styles_by_id.get(NORMAL_STYLE_ID)

    label_paragraph = None
    for p in document.paragraphs:
        if p.text.strip().startswith(KAYNAKLAR_LABEL_PREFIX):
            label_paragraph = p
            break
    if label_paragraph is None:
        logger.warning("BAZI KAYNAKLAR paragraph not found in bulletin template; skipping source list refresh")
        return

    # Remove every paragraph between the label and the next Heading1 (the
    # template's static source list + trailing spacers).
    node = label_paragraph._p.getnext()
    while node is not None and node.tag == qn("w:p"):
        candidate = Paragraph(node, label_paragraph._parent)
        if _style_id(candidate) == HEADING1_STYLE_ID:
            break
        next_node = node.getnext()
        _remove_paragraph(candidate)
        node = next_node

    anchor = label_paragraph
    for line in (feed_lines or [NO_FEEDS_LINE]):
        anchor = _insert_paragraph_after(anchor, line, normal_style)


def _enable_auto_update_fields(document: Document) -> None:
    """Set updateFields=true in word/settings.xml so Word silently recomputes
    every field (notably the İçindekiler/TOC) when the file is opened,
    instead of showing whatever stale result was last cached in the bundled
    template — python-docx has no API for this, so it's raw OOXML insertion,
    same recipe as the paragraph-insertion helpers above."""
    settings_element = document.settings.element
    existing = settings_element.find(qn("w:updateFields"))
    if existing is not None:
        existing.set(qn("w:val"), "true")
        return
    update_fields = OxmlElement("w:updateFields")
    update_fields.set(qn("w:val"), "true")
    settings_element.insert(0, update_fields)


def _rebuild_category_sections(
    document: Document,
    styles_by_id: Dict[str, Any],
    title_paragraph: Optional[Paragraph],
    digest_items: List[Dict[str, Any]],
    categorized: Dict[str, Dict[str, List[Dict[str, Any]]]],
    category_order: List[str],
) -> None:
    normal_style = styles_by_id.get(NORMAL_STYLE_ID)
    heading1_style = styles_by_id.get(HEADING1_STYLE_ID)
    heading2_style = styles_by_id.get(HEADING2_STYLE_ID)

    # The template has no standalone "GÜNDEM ÖZETİ" body paragraph — that text
    # only ever appeared as a cached Table-of-Contents entry. Its closest real
    # counterpart is "ÖNE ÇIKAN BAŞLIKLAR" (also dropped in v1, see plan): a
    # leading, cross-region highlights section in the same document slot. We
    # repurpose that heading — rename it and clear its stale example
    # subheadings — as the home for the LLM-picked digest.
    digest_anchor: Optional[Paragraph] = None
    existing_by_name: Dict[str, Paragraph] = {}
    for heading_p, children in _heading1_spans(document):
        if _normalize(heading_p.text) == _normalize(ONE_CIKAN_BASLIKLAR_LABEL):
            for child in children:
                _remove_paragraph(child)
            _set_paragraph_text(heading_p, GUNDEM_OZETI_LABEL)
            digest_anchor = heading_p
            continue
        # Clear stale example subheadings/body left over from the template's
        # last real edition — fresh ones are generated for this run below.
        for child in children:
            _remove_paragraph(child)
        existing_by_name[_normalize(heading_p.text)] = heading_p

    if digest_anchor is None:
        if title_paragraph is not None:
            digest_anchor = _insert_paragraph_after(title_paragraph, GUNDEM_OZETI_LABEL, heading1_style)
        else:
            logger.warning("Could not find a Title paragraph to anchor the GÜNDEM ÖZETİ section on")

    if digest_anchor is not None:
        for item in digest_items:
            icon = _ICON_BY_TYPE.get(item.get("article_type"), "📌")
            text = f"{icon} {item['blurb']}"
            digest_anchor = _insert_paragraph_after(digest_anchor, text, normal_style)

    ordered_names = list(category_order) + [DIGER_CATEGORY_NAME]

    # Any template Heading1 that doesn't correspond to a current category
    # (e.g. the user removed/renamed it since the template was last edited)
    # is stale — its content was already cleared above, so drop the empty
    # heading too rather than leaving it stranded in the output.
    valid_keys = {_normalize(name) for name in ordered_names}
    for key, stray in list(existing_by_name.items()):
        if key not in valid_keys:
            _remove_paragraph(stray)
            del existing_by_name[key]

    for name in ordered_names:
        groups = categorized.get(name)
        anchor = existing_by_name.get(_normalize(name))

        if not groups:
            # No articles landed here this run — don't leave an empty heading.
            if anchor is not None:
                _remove_paragraph(anchor)
            continue

        if anchor is None:
            anchor = document.add_paragraph(name, style=heading1_style)

        for subcategory, items in groups.items():
            anchor = _insert_paragraph_after(anchor, subcategory, heading2_style)
            for item in items:
                article_type = item.get("article_type")
                icon = _ICON_BY_TYPE.get(article_type, "📌")
                source = item.get("source")
                suffix = f" ({source})" if source and article_type != "haber_detayi" else ""
                text = f"{icon} {item['synopsis']}{suffix}"
                anchor = _insert_paragraph_after(anchor, text, normal_style)


def render_bulletin_docx(
    generated_at: datetime,
    digest_items: List[Dict[str, Any]],
    categorized: Dict[str, Dict[str, List[Dict[str, Any]]]],
    category_order: List[str],
    feed_lines: Optional[List[str]] = None,
) -> io.BytesIO:
    """Render the bulletin as an in-memory .docx (no temp file on disk).

    The template's "İçindekiler" (Table of Contents) field can't be computed
    by python-docx directly, so `_enable_auto_update_fields` sets Word's
    updateFields document setting instead — this makes Word recompute every
    field (the TOC included) from the document's real Heading1/Heading2
    structure as soon as the file is opened, rather than showing whatever
    stale result was cached in the bundled template.
    """
    if not TEMPLATE_PATH.exists():
        raise BulletinGenerationError(f"Bulletin template not found at {TEMPLATE_PATH}")

    try:
        document = Document(str(TEMPLATE_PATH))
        styles_by_id = {s.style_id: s for s in document.styles if s.style_id}

        title_paragraph = _set_title(document, generated_at)
        _replace_kaynaklar_section(document, styles_by_id, feed_lines or [])
        _rebuild_category_sections(
            document, styles_by_id, title_paragraph, digest_items, categorized, category_order
        )
        _enable_auto_update_fields(document)

        buffer = io.BytesIO()
        document.save(buffer)
        buffer.seek(0)
        return buffer
    except BulletinGenerationError:
        raise
    except Exception as e:
        logger.error(f"Failed to render bulletin docx: {e}")
        raise BulletinGenerationError(f"Failed to render bulletin docx: {str(e)}")
