"""
Summary and categorization service using OpenAI.
"""
import tiktoken
import logging
from typing import Dict, Any, List
from openai import AsyncOpenAI
from app.core.config import settings
from app.core.exceptions import SummarizationError, TopicCategorizationError, CostLimitExceededError
from app.db.database import SessionLocal
from app.db import crud

logger = logging.getLogger(__name__)

# Initialize OpenAI client
client = AsyncOpenAI(api_key=settings.openai_api_key)

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


async def categorize_article_topics(title: str, content: str) -> List[Dict[str, Any]]:
    """
    Categorize article into topics using OpenAI.
    
    Args:
        title: Article title
        content: Article content
        
    Returns:
        List of topics with confidence scores
        
    Raises:
        TopicCategorizationError: If categorization fails
    """
    try:
        await check_cost_limits()
        
        # Get available topics from database
        db = SessionLocal()
        try:
            topics = crud.get_topics(db)
            topic_names = [t.name for t in topics]
            
            # Get system prompt from database
            system_prompt_obj = crud.get_system_prompt(db, "classification")
            if system_prompt_obj and system_prompt_obj.is_active:
                system_prompt = system_prompt_obj.prompt_text
            else:
                # Fallback to default
                system_prompt = "You are a news categorization assistant. Return only valid JSON."
        finally:
            db.close()
        
        if not topic_names:
            logger.warning("No topics found in database")
            return []
        
        # Create prompt
        prompt = f"""Analyze the following German news article and categorize it into one or more of these topics: {', '.join(topic_names)}.

Title: {title}

Content: {content[:1000]}

Return ONLY a JSON array with objects containing "name" (topic name) and "confidence" (0.0-1.0).
Example: [{{"name": "Politik", "confidence": 0.9}}, {{"name": "Wirtschaft", "confidence": 0.5}}]

Include only topics with confidence >= 0.5. Return at least one topic."""
        
        model = settings.default_model
        input_tokens = count_tokens(prompt, model)
        
        # Get system prompt from database
        db = SessionLocal()
        try:
            system_prompt_obj = crud.get_system_prompt(db, "classification")
            if system_prompt_obj and system_prompt_obj.is_active:
                system_prompt = system_prompt_obj.prompt_text
            else:
                # Fallback to default
                system_prompt = "You are a news categorization assistant. Return only valid JSON."
        finally:
            db.close()
        
        # Call OpenAI
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=200
        )
        
        output_tokens = response.usage.completion_tokens
        cost = calculate_cost(model, input_tokens, output_tokens)
        
        # Parse response
        import json
        result_text = response.choices[0].message.content.strip()
        
        # Remove markdown code blocks if present
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
        
        categorized_topics = json.loads(result_text)
        
        logger.info(f"Categorized article into {len(categorized_topics)} topics. Cost: ${cost:.4f}")
        
        return categorized_topics
        
    except CostLimitExceededError:
        raise
    except Exception as e:
        logger.error(f"Topic categorization failed: {e}")
        raise TopicCategorizationError(f"Failed to categorize topics: {str(e)}")


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
        prompt = f"""Summarize the following German news article.

Title: {title}

Content:
{content}

Instructions: {instructions}

Write the summary in German."""
        
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
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            max_tokens=max_tokens
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
