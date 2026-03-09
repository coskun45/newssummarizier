"""
Summary and categorization service using OpenAI.
"""
import tiktoken
import logging
from typing import Dict, Any, List, Optional
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.exceptions import SummarizationError, TopicCategorizationError, CostLimitExceededError
from app.db.database import SessionLocal
from app.db import crud
from app.agents.tools import extract_article_content, truncate_content

logger = logging.getLogger(__name__)

# Initialize OpenAI client lazily
_client: Optional[AsyncOpenAI] = None


def get_openai_client() -> AsyncOpenAI:
    """Get or create OpenAI client instance."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            max_retries=2,
        )
    return _client

# Pricing per 1K tokens (as of early 2024 - verify current pricing)
PRICING = {
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "gpt-4-turbo-preview": {"input": 0.01, "output": 0.03},
    "gpt-4": {"input": 0.03, "output": 0.06}
}


def count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """
    Count tokens in text using tiktoken.
    
    Args:
        text: Text to count tokens for
        model: Model name for encoder
        
    Returns:
        Token count
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except Exception as e:
        logger.warning(f"Failed to count tokens: {e}. Using approximation.")
        # Fallback: rough approximation
        return len(text) // 4


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Calculate API cost based on token usage.
    
    Args:
        model: Model name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        
    Returns:
        Cost in USD
    """
    pricing = PRICING.get(model, PRICING["gpt-3.5-turbo"])
    input_cost = (input_tokens / 1000) * pricing["input"]
    output_cost = (output_tokens / 1000) * pricing["output"]
    return input_cost + output_cost


async def check_cost_limits() -> None:
    """
    Check if cost limits have been exceeded.
    
    Raises:
        CostLimitExceededError: If daily or monthly limits exceeded
    """
    db = SessionLocal()
    try:
        daily_cost = crud.get_daily_cost(db)
        monthly_cost = crud.get_monthly_cost(db)
        
        if daily_cost >= settings.daily_cost_limit:
            raise CostLimitExceededError(
                f"Daily cost limit exceeded: ${daily_cost:.2f} / ${settings.daily_cost_limit:.2f}"
            )
        
        if monthly_cost >= settings.monthly_cost_limit:
            raise CostLimitExceededError(
                f"Monthly cost limit exceeded: ${monthly_cost:.2f} / ${settings.monthly_cost_limit:.2f}"
            )
    finally:
        db.close()


INTEREST_TOPICS = [
    "Ukrayna Savaşı",
    "ABD-İran Krizi",
    "Epstein Dosyası",
    "PKK ve SDG",
    "Migrasyon / Göç",
    "Avrupa Savunması ve Savunma Sanayi",
    "NATO",
    "Türkiye Siyaseti",
]

INTEREST_KEYWORDS = [
    "Turkey", "Türkei", "Turquie", "Turkish", "Turken", "Turk", "Turc", "Turchia", "Turco",
    "Turquía", "Turquia", "Turcos", "Turkiye", "Istanbul",
    "Pkk", "Sdg", "Kurds", "Kurden", "Dem parti", "Öcalan", "Ocalan", "Imrali",
    "Syria", "Syrie", "Syrien", "Suriye", "Damascus", "al-sharaa", "al charaa",
    "Al-shara", "El-Şara",
    "Trump",
    "Israil", "Israel", "Gazze", "Gaza",
    "Fetö", "Feto", "Fetullah", "Gülen", "Gulen", "Cemaat", "KHK", "MIT",
]

_CATEGORIZATION_SYSTEM_PROMPT = """Sen bir haber analiz asistanısın. Görevin haberleri değerlendirmek, sınıflandırmak ve önceliklendirmektir.
Her zaman geçerli JSON döndür, başka hiçbir şey yazma.

---

DEĞERLENDIRME KURALLARI:

1. ÖNEM FİLTRESİ
Haber aşağıdaki TOPIC listesi veya KEYWORD listesiyle ilgili DEĞİLSE → "unimportant" döndür.
İlgiliyse → "important" döndür ve 2. adıma geç.

TOPIC LİSTESİ:
{topic_list}

KEYWORD LİSTESİ (bu kelimelerden biri haberde geçiyorsa potansiyel olarak önemlidir):
Turkey, Türkei, Turquie, Turkish, Turken, Turk, Turc, Turchia, Turco, Turquía, Turquia, Turcos, Turkiye, Istanbul,
Pkk, Sdg, Kurds, Kurden, Dem parti, Öcalan, Ocalan, Imrali,
Syria, Syrie, Syrien, Suriye, Damascus, al-sharaa, al charaa, Al-shara, El-Şara,
Trump,
Israil, Israel, Gazze, Gaza,
Fetö, Feto, Fetullah, Gülen, Gulen, Cemaat, KHK, MIT

2. ÖNCELİK SEVİYESİ (yalnızca önemli haberler için)
- "high": Büyük jeopolitik gelişme, kriz, askeri hareketlilik, önemli politik karar veya uluslararası etkisi olan olaylar.
- "med": Politik açıklamalar, diplomatik gelişmeler, önemli fakat sınırlı etkili gelişmeler.
- "low": Arka plan haberleri, analizler, küçük ölçekli gelişmeler veya dolaylı ilişkili haberler.

3. KONU SINIFLANDIRMASI (yalnızca önemli haberler için)
Haberi aşağıdaki konulardan bir veya birkaçına sınıflandır (bir haber birden fazla konuya girebilir):
{topic_list}

---

ÇIKTI FORMATI (yalnızca geçerli JSON):

Önemsiz haber için:
{"importance": "unimportant", "priority": null, "topics": []}

Önemli haber için:
{"importance": "important", "priority": "high", "topics": [{"name": "Ukrayna Savaşı", "confidence": 0.95}, {"name": "NATO", "confidence": 0.7}]}

Sadece confidence >= 0.5 olan konuları dahil et.
"""

def _build_topic_list(topics) -> str:
    """Format DB topics as a bullet list for injection into the system prompt."""
    lines = []
    for t in topics:
        if t.description:
            lines.append(f"- {t.name}: {t.description}")
        else:
            lines.append(f"- {t.name}")
    return "\n".join(lines)


_CATEGORIZATION_USER_PROMPT_TEMPLATE = """Aşağıdaki haberi analiz et ve şu kurallara göre değerlendir:

HABER BAŞLIĞI: {title}

HABER İÇERİĞİ:
{content}

"""


async def categorize_and_prioritize_article(title: str, content: str) -> Dict[str, Any]:
    """
    Evaluate article importance, assign priority, and classify into topics.

    Returns a dict with keys: importance, priority, topics.
    - importance: "important" | "unimportant"
    - priority: "high" | "med" | "low" | None
    - topics: list of {"name": str, "confidence": float}

    Raises:
        TopicCategorizationError: If the LLM call or parsing fails
    """
    import json
    try:
        await check_cost_limits()

        db = SessionLocal()
        try:
            prompt_obj = crud.get_system_prompt(db, "classification")
            system_prompt = prompt_obj.prompt_text if (prompt_obj and prompt_obj.is_active) else _CATEGORIZATION_SYSTEM_PROMPT
            db_topics = crud.get_topics(db)
        finally:
            db.close()

        system_prompt = system_prompt.replace("{topic_list}", _build_topic_list(db_topics))

        user_prompt = _CATEGORIZATION_USER_PROMPT_TEMPLATE.replace("{title}", title).replace("{content}", content[:2000])

        model = settings.default_model
        input_tokens = count_tokens(system_prompt + user_prompt, model)

        response = await get_openai_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_completion_tokens=300,
        )

        output_tokens = response.usage.completion_tokens
        cost = calculate_cost(model, input_tokens, output_tokens)

        result_text = response.choices[0].message.content.strip()
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]

        result = json.loads(result_text)
        importance = result.get("importance", "unimportant")
        priority = result.get("priority")
        topics = result.get("topics", [])

        logger.info(
            f"Categorized article: importance={importance}, priority={priority}, "
            f"topics={len(topics)}, cost=${cost:.4f}"
        )
        return {"importance": importance, "priority": priority, "topics": topics}

    except CostLimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Article categorization failed: {e}")
        raise TopicCategorizationError(f"Failed to categorize article: {str(e)}")


async def generate_summary(
    title: str,
    content: str,
    summary_type: str = "standard"
) -> Dict[str, Any]:
    """
    Generate article summary using OpenAI.
    
    Args:
        title: Article title
        content: Article content
        summary_type: Type of summary ('brief', 'standard', 'detailed')
        
    Returns:
        Dictionary with summary_text, model_used, tokens_used, cost
        
    Raises:
        SummarizationError: If summarization fails
    """
    try:
        await check_cost_limits()
        
        # Select model and parameters based on summary type
        if summary_type == "brief":
            model = settings.default_model
            max_tokens = settings.max_tokens_output_brief
            instructions = "Provide a very brief summary in 2-3 sentences. Focus on the main point."
        elif summary_type == "standard":
            model = settings.default_model
            max_tokens = settings.max_tokens_output_standard
            instructions = "Provide a concise summary in one paragraph. Include key facts and main points."
        elif summary_type == "detailed":
            model = settings.detailed_model
            max_tokens = settings.max_tokens_output_detailed
            instructions = "Provide a detailed summary with multiple paragraphs. Include key facts, important figures, main actors involved, and potential impact or consequences."
        else:
            raise ValueError(f"Invalid summary type: {summary_type}")
        
        # Create prompt
        prompt = f"""Summarize the following news article.

    Title: {title}

    Content:
    {content}

    Instructions: {instructions}

    Write the summary in Turkish."""
        
        input_tokens = count_tokens(prompt, model)
        
        # Get system prompt from database
        db = SessionLocal()
        try:
            system_prompt_obj = crud.get_system_prompt(db, "summarization")
            if system_prompt_obj and system_prompt_obj.is_active:
                system_prompt = system_prompt_obj.prompt_text
            else:
                # Fallback to default
                system_prompt = """
                 You are a professional news summarization assistant. Your publishes content in Turkish. 
You create short contents in Turkish.
Your aim here is to give an overview of the news, not to give so many details. 

MY INSTRUCTIONS WILL BE LIKE THAT:

You get content in Turkish, English or in a different language. 
SUMMARIZE the text in Turkish. Never summarize in another language. 

MY EXPECTATIONS FOR THE OUTPUT: 

SOURCE and TITLE: 

Write the SOURCE and the TITLE for the summary.  
You must find the SOURCE in the text, if I don’t provide you one. 
The TITLE must be a translation of the original one into Turkish. 
Don’t write the title in another language, always in Turkish. 
If there is no topic in the text, produce a proper one. 
SOURCE and TITLE must always be written in BOLD. This rule never changes. 
SOURCE and TITLE must always be written in BOLD!
SOURCE and TITLE must always be written in BOLD!!
SOURCE and TITLE must always be written in BOLD!!!
For the TITLE always use the “pin emoji” I gave you, then leave a blank, then write the SOURCE of the news then use a dash and write the TITLE.

Follow the examples: 

📌 DW Türkçe - Avrupa savunmada Türkiye’yle nasıl bir işbirliği istiyor?
📌 Bloomberg - Almanya sahaya dönüyor: Merz'in Avrupa liderliğini üstlenme şansı var📌 Reuters - Hindistan’ın geçmiş Keşmir saldırılarına verdiği askeri yanıtlar

AUTHOR / COLUMNIST:
If you see the author or the columnist of the text inside the text or if I give you the name of the author or columnist, you can add it after the source, before the title. 

The format then must be same with the following examples: 
📌 DW Türkçe / Max Bird - Avrupa savunmada Türkiye’yle nasıl bir işbirliği istiyor?
📌 Bloomberg / March Champion - Almanya sahaya dönüyor: Merz'in Avrupa liderliğini üstlenme şansı var
📌 Reuters / Larry King - Hindistan’ın geçmiş Keşmir saldırılarına verdiği askeri yanıtlar


SUMMERY BULLETS: 

After the TITLE, create the summary.
Write the summary with “blue diamond emojis” I gave you in the example output. 
Use the diamond then leave a blank, then write the sentence. 
The SUMMARY is always in Turkish.
The SUMMARY must include just the important parts from the text.
Just a short summary like the OUTPUT examples. Not very detailed.
I want you to summarize the text maximum in 4 points. 
I want you to summarize the text maximum in 4 points. 
I want you to summarize the text maximum in 4 points. 
But you can summarize it with 3, 2 or even 1 point if it is too short and you can give the important parts in 3, 2 or 1 point.
Summarize the text mostly using the original sentences from the text, if it is possible. 
If it is not possible, of course summarize it in your own style. 
But never add your own comments. 
Never add your comments!!!
Never add something that is not included in the text, a sentence, a short info a background etc.
Don’t make assumptions! 

I gave you all the emojis I use for summaries. 
Never use another emoji other than the examples.
Never apply a header to the content. (e.g. Header 1, Header 2 etc.)
Never use italic anywhere.


EXAMPLE OUTPUT:
For example in that example that part is BOLD: 

📌 Bloomberg - Ulusal Güvenlik Danışmanı Waltz, Signal Grubu Skandalı Sonrası Görevden Ayrılıyor

That part is never BOLD: 
🔹 ABD Başkanı Donald Trump’ın ikinci dönemindeki en üst düzey danışmanlarından biri olan Ulusal Güvenlik Danışmanı Michael Waltz ve yardimcisi Alex Wong görevinden ayrılıyor. 
🔹 Waltz’ın istifası, Yemen’de İran destekli Husilere yönelik saldırı planlarının konuşulduğu Signal sohbet grubuna Atlantic editörü Jeffrey Goldberg’i yanlışlıkla eklemesi sonrası oluşan krizle bağlantılı. 
🔹 Aşırı sağcı aktivist Laura Loomer, Nisan ayında bazı üst düzey ulusal güvenlik yetkililerinin görevden alınmasını kendisinin sağladığını iddia etmişti. """
        finally:
            db.close()
        
        # Call OpenAI  
        response = await get_openai_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_completion_tokens=max_tokens
        )
        
        summary_text = response.choices[0].message.content.strip()
        output_tokens = response.usage.completion_tokens
        total_tokens = input_tokens + output_tokens
        cost = calculate_cost(model, input_tokens, output_tokens)
        
        logger.info(f"Generated {summary_type} summary. Tokens: {total_tokens}, Cost: ${cost:.4f}")
        
        return {
            "summary_text": summary_text,
            "model_used": model,
            "tokens_used": total_tokens,
            "cost": cost
        }
        
    except CostLimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Summary generation failed: {e}")
        raise SummarizationError(f"Failed to generate summary: {str(e)}")


async def process_article_by_id(article_id: int) -> dict:
    """
    Process a single article by ID: extract content (if needed), categorize topics, generate summaries.
    Returns a dict with result metadata.
    """
    db = SessionLocal()
    try:
        article = crud.get_article(db, article_id)
        if not article:
            raise SummarizationError(f"Article not found: {article_id}")

        # Extract content if missing
        content = article.cleaned_content or article.raw_content or ""
        if not article.cleaned_content:
            try:
                extracted = await extract_article_content(article.url)
                if extracted:
                    content = extracted
                    crud.update_article_content(db=db, article_id=article.id, cleaned_content=content)
                    crud.update_article_status(db=db, article_id=article.id, status="scraped")
                    crud.create_log(db=db, article_id=article.id, agent_name="web_scraper", status="success", message=f"Extracted {len(content)} characters")
                else:
                    crud.create_log(db=db, article_id=article.id, agent_name="web_scraper", status="skipped", message="Using RSS content as fallback")
            except Exception as e:
                crud.create_log(db=db, article_id=article.id, agent_name="web_scraper", status="error", message="Extraction failed, using RSS fallback", error_details=str(e))

        total_cost = 0.0

        # Evaluate importance, priority, and classify topics
        is_important = False
        try:
            categorization = await categorize_and_prioritize_article(
                title=article.title,
                content=truncate_content(content, 2000)
            )
            importance = categorization.get("importance", "unimportant")
            priority = categorization.get("priority")
            topics = categorization.get("topics", [])

            crud.update_article_importance(db=db, article_id=article.id, importance=importance, priority=priority)

            if importance == "unimportant":
                crud.update_article_status(db=db, article_id=article.id, status="filtered")
                crud.create_log(db=db, article_id=article.id, agent_name="topic_categorizer", status="success", message="Article filtered as unimportant — skipping summarization")
                return {"article_id": article.id, "status": "filtered", "cost": 0.0}

            is_important = True
            for topic in topics:
                topic_db = crud.get_topic_by_name(db, topic["name"]) if isinstance(topic, dict) else None
                if topic_db:
                    crud.add_article_topic(db=db, article_id=article.id, topic_id=topic_db.id, confidence=topic.get("confidence", 1.0))

            crud.create_log(db=db, article_id=article.id, agent_name="topic_categorizer", status="success", message=f"Important ({priority}): classified into {len(topics)} topics")
        except Exception as e:
            crud.create_log(db=db, article_id=article.id, agent_name="topic_categorizer", status="error", message="Topic categorization failed", error_details=str(e))

        # Generate summaries (only for important articles)
        if is_important:
            try:
                enabled_summary_types = crud.get_setting(db, "enabled_summary_types") or "brief,standard,detailed"
                enabled_types = [x.strip() for x in enabled_summary_types.split(",") if x.strip()]
                summary_types_map = {
                    "brief": ("brief", "brief"),
                    "standard": ("standard", "standard"),
                    "detailed": ("detailed", "detailed")
                }
                summary_types = [summary_types_map[st] for st in enabled_types if st in summary_types_map]

                for summary_type, _ in summary_types:
                    try:
                        result = await generate_summary(title=article.title, content=truncate_content(content), summary_type=summary_type)
                        total_cost += result.get("cost", 0.0)
                        crud.create_summary(db=db, article_id=article.id, summary_text=result["summary_text"], summary_type=summary_type, model_used=result.get("model_used"), tokens_used=result.get("tokens_used", 0), cost=result.get("cost", 0.0))
                    except Exception as e:
                        crud.create_log(db=db, article_id=article.id, agent_name="summarizer", status="error", message=f"Failed to generate {summary_type} summary", error_details=str(e))

            except Exception as e:
                logger.error(f"Summary generation loop failed: {e}")

        # Mark as summarized
        crud.update_article_status(db=db, article_id=article.id, status="summarized")
        crud.create_log(db=db, article_id=article.id, agent_name="article_processor", status="success", message=f"Article processing completed. Cost: ${total_cost:.4f}")

        return {"article_id": article.id, "status": "summarized", "cost": total_cost}

    finally:
        db.close()
