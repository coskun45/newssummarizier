"""
Word (.docx) rendering for the on-demand bulletin report.

The bundled template (`resources/bulletin_template.docx`) is a real edition of
the bulletin. Everything up to and including the "BAZI KAYNAKLAR" source list
(title, İçindekiler content control, icon legend, sources) is kept; the body
after it is rebuilt for each run.

New paragraphs are deep copies of the template's own paragraphs (a Heading1, a
Heading3, a bold "📌" article header, a "🔹" bullet, a blank spacer) with only
their text replaced. The template's look lives in direct paragraph/run
formatting (bold, 13pt/23pt, 240 spacing — a Google Docs export), not in the
style definitions, so a paragraph created with just a style name would lose it.

Categories render as Heading1 and their topic groups as Heading3, exactly like
the template; its TOC field maps "Heading 1" to level 1 and "Heading 3" to
level 3. The TOC's cached result is rebuilt here too (one hyperlinked entry per
heading, no page numbers — the field has \\n), so Word shows a correct
İçindekiler on open without `updateFields`, which makes Word ask the reader
whether to update fields every time the file is opened.
"""
import copy
import io
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.core.exceptions import BulletinGenerationError

logger = logging.getLogger(__name__)

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "resources" / "bulletin_template.docx"

TITLE_STYLE_ID = "Title"
HEADING1_STYLE_ID = "Heading1"
HEADING3_STYLE_ID = "Heading3"

KAYNAKLAR_LABEL_PREFIX = "BAZI KAYNAKLAR"
RSS_SOURCES_LABEL = "RSS Beslemeleri"
HEADER_ICONS = ("📌", "⭕️", "⭕")
BULLET_ICON = "🔹"
BOOKMARK_PREFIX = "_bulten_"

_TURKISH_MONTHS = {
    1: "Ocak", 2: "Şubat", 3: "Mart", 4: "Nisan", 5: "Mayıs", 6: "Haziran",
    7: "Temmuz", 8: "Ağustos", 9: "Eylül", 10: "Ekim", 11: "Kasım", 12: "Aralık",
}

# lxml refuses control characters that are invalid in XML 1.0; scraped/LLM text can contain them.
_XML_INVALID_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_W_P = qn("w:p")
_W_R = qn("w:r")
_W_T = qn("w:t")
_W_HYPERLINK = qn("w:hyperlink")
_W_BOOKMARK_START = qn("w:bookmarkStart")
_W_BOOKMARK_END = qn("w:bookmarkEnd")
_W_FLDCHAR = qn("w:fldChar")
_W_INSTRTEXT = qn("w:instrText")


def format_turkish_date(dt: datetime) -> str:
    """e.g. 01 Eylül 2026."""
    return f"{dt.day:02d} {_TURKISH_MONTHS[dt.month]} {dt.year}"


def _clean(text: str) -> str:
    return _XML_INVALID_RE.sub("", text or "")


def _p_text(p) -> str:
    return "".join(t.text or "" for t in p.iter(_W_T))


def _p_style(p) -> Optional[str]:
    ppr = p.pPr
    if ppr is None or ppr.pStyle is None:
        return None
    return ppr.pStyle.val


def _is_field_run(r) -> bool:
    return r.find(_W_FLDCHAR) is not None or r.find(_W_INSTRTEXT) is not None


def _set_run_text(r, text: str) -> None:
    for t in r.findall(_W_T):
        r.remove(t)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = _clean(text)
    r.append(t)


def _clone_with_text(proto, *texts: str):
    """Copy `proto` keeping its paragraph/run formatting; the i-th text goes into its i-th run
    (the source-list line has a bold label run and a plain text run). Extra runs are dropped."""
    p = copy.deepcopy(proto)
    for el in p.findall(_W_BOOKMARK_START) + p.findall(_W_BOOKMARK_END):
        p.remove(el)
    runs = p.findall(_W_R)
    if not runs:
        runs = [OxmlElement("w:r")]
        p.append(runs[0])
    while len(runs) < len(texts):
        extra = copy.deepcopy(runs[-1])
        runs[-1].addnext(extra)
        runs.append(extra)
    for r, text in zip(runs, texts):
        _set_run_text(r, text)
    for r in runs[len(texts):]:
        p.remove(r)
    return p


class _Prototypes:
    """Template paragraphs every generated paragraph is copied from."""

    def __init__(self, body):
        paragraphs = list(body.iter(_W_P))
        first_h1 = next(
            (i for i, p in enumerate(paragraphs) if _p_style(p) == HEADING1_STYLE_ID), None
        )
        if first_h1 is None:
            raise BulletinGenerationError("Bulletin template has no Heading1 paragraph")
        content = paragraphs[first_h1:]

        def find(predicate, what):
            found = next((p for p in content if predicate(p)), None)
            if found is None:
                raise BulletinGenerationError(f"Bulletin template has no {what} paragraph")
            return copy.deepcopy(found)

        self.heading1 = find(lambda p: _p_style(p) == HEADING1_STYLE_ID and _p_text(p).strip(), "Heading1")
        self.heading3 = find(lambda p: _p_style(p) == HEADING3_STYLE_ID and _p_text(p).strip(), "Heading3")
        self.header = find(lambda p: _p_style(p) is None and _p_text(p).startswith("📌"), "article header")
        self.bullet = find(lambda p: _p_style(p) is None and _p_text(p).startswith(BULLET_ICON), "bullet")
        self.blank = find(lambda p: _p_style(p) is None and not _p_text(p).strip(), "blank")


def _set_title(body, generated_at: datetime) -> None:
    for p in body.iter(_W_P):
        if _p_style(p) == TITLE_STYLE_ID:
            runs = p.findall(_W_R)
            if runs:
                _set_run_text(runs[0], f"{format_turkish_date(generated_at)} Dünya Bülteni")
                for r in runs[1:]:
                    p.remove(r)
            return


def _append_rss_sources(body, feed_titles: List[str]) -> None:
    """Keep the template's "Ülke: kaynaklar" list and add the app's followed RSS feeds as one
    more line in the same format (bold label run + plain text run)."""
    if not feed_titles:
        return
    children = list(body)
    label_idx = next(
        (i for i, el in enumerate(children)
         if el.tag == _W_P and _p_text(el).strip().startswith(KAYNAKLAR_LABEL_PREFIX)),
        None,
    )
    if label_idx is None:
        logger.warning("BAZI KAYNAKLAR paragraph not found in bulletin template; RSS feeds not listed")
        return
    last_line = None
    for el in children[label_idx + 1:]:
        if el.tag != _W_P or not _p_text(el).strip() or _p_style(el):
            break
        last_line = el
    if last_line is None or len(last_line.findall(_W_R)) < 2:
        logger.warning("Bulletin template source list has no 'Ülke: kaynaklar' line to copy")
        return
    line = _clone_with_text(last_line, RSS_SOURCES_LABEL, ": " + ", ".join(feed_titles))
    last_line.addnext(line)


def _clear_body_after_sources(body) -> None:
    """Drop the template's example edition: every body element from the first Heading1 on,
    except the final section properties."""
    children = list(body)
    start = next(
        (i for i, el in enumerate(children) if el.tag == _W_P and _p_style(el) == HEADING1_STYLE_ID),
        None,
    )
    if start is None:
        return
    for el in children[start:]:
        if el.tag != qn("w:sectPr"):
            body.remove(el)


def _max_bookmark_id(body) -> int:
    ids = [int(el.get(qn("w:id"))) for el in body.iter(_W_BOOKMARK_START)
           if (el.get(qn("w:id")) or "").lstrip("-").isdigit()]
    return max(ids, default=0)


def _add_bookmark(p, name: str, bookmark_id: int) -> None:
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bookmark_id))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bookmark_id))
    first_run = p.find(_W_R)
    if first_run is not None:
        first_run.addprevious(start)
    else:
        p.append(start)
    start.addnext(end)


def _build_body(body, protos: _Prototypes, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Append the sections before the sectPr; returns the TOC entries (level, text, bookmark)."""
    sect_pr = body.find(qn("w:sectPr"))

    def append(p):
        if sect_pr is not None:
            sect_pr.addprevious(p)
        else:
            body.append(p)

    toc_entries: List[Dict[str, Any]] = []
    next_id = _max_bookmark_id(body) + 1

    def heading(proto, text: str, level: int):
        nonlocal next_id
        p = _clone_with_text(proto, text)
        name = f"{BOOKMARK_PREFIX}{next_id}"
        _add_bookmark(p, name, next_id)
        next_id += 1
        append(p)
        toc_entries.append({"level": level, "text": text, "bookmark": name})

    for section in sections:
        groups = [g for g in section.get("groups", []) if g.get("items")]
        if not groups:
            continue
        heading(protos.heading1, section["title"], 1)
        for group in groups:
            heading(protos.heading3, group["title"], 3)
            for item in group["items"]:
                append(_clone_with_text(protos.header, item["header"]))
                for bullet in item.get("bullets", []):
                    append(_clone_with_text(protos.bullet, bullet))
                append(copy.deepcopy(protos.blank))
    return toc_entries


def _rebuild_toc(body, entries: List[Dict[str, Any]]) -> None:
    """Replace the TOC content control's cached entries with the real headings."""
    sdt_content = next(
        (sc for sdt in body.iter(qn("w:sdt")) for sc in sdt.findall(qn("w:sdtContent"))
         if any(i.text and "TOC" in i.text for i in sc.iter(_W_INSTRTEXT))),
        None,
    )
    if sdt_content is None:
        logger.warning("No TOC content control in bulletin template; İçindekiler not rebuilt")
        return
    old = sdt_content.findall(_W_P)
    if not old:
        return

    begin_runs = [copy.deepcopy(r) for r in old[0].findall(_W_R) if _is_field_run(r)]
    end_runs = [copy.deepcopy(r) for r in old[-1].findall(_W_R)
                if r.find(_W_FLDCHAR) is not None and r.find(_W_FLDCHAR).get(qn("w:fldCharType")) == "end"]
    has_link = [p for p in old if p.find(_W_HYPERLINK) is not None]

    def entry_proto(indented: bool):
        match = next((p for p in has_link if (p.find(f"{qn('w:pPr')}/{qn('w:ind')}") is not None) == indented),
                     None)
        match = match if match is not None else (has_link[0] if has_link else old[0])
        proto = copy.deepcopy(match)
        for r in proto.findall(_W_R):
            if _is_field_run(r):
                proto.remove(r)
        return proto

    level1, level3 = entry_proto(False), entry_proto(True)

    for p in old:
        sdt_content.remove(p)

    new_paragraphs = []
    for entry in entries:
        p = copy.deepcopy(level1 if entry["level"] == 1 else level3)
        link = p.find(_W_HYPERLINK)
        if link is None:
            continue
        link.set(qn("w:anchor"), entry["bookmark"])
        runs = link.findall(_W_R)
        if runs:
            _set_run_text(runs[0], entry["text"])
            for r in runs[1:]:
                link.remove(r)
        new_paragraphs.append(p)

    if not new_paragraphs:
        new_paragraphs.append(copy.deepcopy(level1))
        link = new_paragraphs[0].find(_W_HYPERLINK)
        if link is not None:
            new_paragraphs[0].remove(link)

    first, last = new_paragraphs[0], new_paragraphs[-1]
    anchor = first.find(qn("w:pPr"))
    for r in begin_runs:
        if anchor is not None:
            anchor.addnext(r)
        else:
            first.insert(0, r)
        anchor = r
    for r in end_runs:
        last.append(r)
    for p in new_paragraphs:
        sdt_content.append(p)


def _fix_toc_field_locale_independence(body) -> None:
    """The template's TOC field selects entries purely via \\t — a literal, English-only
    style-name list (" TOC \\h \\u \\z \\n \\t \"Heading 1,1,...\"") with no \\o switch. \\t
    matches a paragraph by its LOCALIZED style display name, which Word does not translate on a
    non-English install (e.g. German "Überschrift 1", confirmed via Word COM automation), so a
    manual "update field" there found zero entries. \\o "1-6" additionally matches by outline
    level, which is locale-independent, so add it alongside \\t rather than replacing it."""
    for instr_text in body.iter(_W_INSTRTEXT):
        text = instr_text.text or ""
        if text.strip().startswith("TOC") and "\\o" not in text and "\\t" in text:
            instr_text.text = text.replace("\\t", '\\o "1-6" \\t', 1)


def _drop_update_fields(document) -> None:
    """The TOC is pre-rendered, so Word must not be told to refresh fields on open (it would
    ask the reader for permission every time)."""
    settings_element = document.settings.element
    for el in settings_element.findall(qn("w:updateFields")):
        settings_element.remove(el)


def render_bulletin_docx(
    generated_at: datetime,
    sections: List[Dict[str, Any]],
    feed_titles: Optional[List[str]] = None,
) -> io.BytesIO:
    """Render the bulletin as an in-memory .docx (no temp file on disk).

    `sections` is the body in order: [{"title": "AVRUPA", "groups": [{"title": "AVRUPA GÖÇ
    GÜNDEMİ", "items": [{"header": "📌 Kaynak - Başlık", "bullets": ["🔹 ..."]}]}]}].
    Sections/groups without items are left out.
    """
    if not TEMPLATE_PATH.exists():
        raise BulletinGenerationError(f"Bulletin template not found at {TEMPLATE_PATH}")

    try:
        document = Document(str(TEMPLATE_PATH))
        body = document.element.body
        protos = _Prototypes(body)

        _set_title(body, generated_at)
        _append_rss_sources(body, feed_titles or [])
        _clear_body_after_sources(body)
        toc_entries = _build_body(body, protos, sections)
        _rebuild_toc(body, toc_entries)
        _fix_toc_field_locale_independence(body)
        _drop_update_fields(document)

        buffer = io.BytesIO()
        document.save(buffer)
        buffer.seek(0)
        return buffer
    except BulletinGenerationError:
        raise
    except Exception as e:
        logger.error(f"Failed to render bulletin docx: {e}")
        raise BulletinGenerationError(f"Failed to render bulletin docx: {str(e)}")
