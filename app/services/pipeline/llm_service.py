import asyncio
import logging
import time
from typing import Any, Optional, Type

from langchain_core.messages import HumanMessage
from app.schemas.interview import AllInterviewQuestions, ExtractedSkills
from app.services.pipeline.llm_parser import parse_llm_response
from app.core.config import settings

logger = logging.getLogger(__name__)

class LLMService:
    """
    Service for handling Direct LLM interactions, including token estimation and parsing.
    """
    
    @staticmethod
    def get_safe_token_limit() -> int:
        return settings.SAFE_TOKEN_LIMIT

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return len(text) // 4

    @staticmethod
    async def generate_questions(
        prompt: str, 
        batch_label: str = "Batch"
    ) -> Optional[AllInterviewQuestions]:
        """
        Call LLM to generate questions (Groq/GPT-OSS model).
        """
        from app.core.llm import chat_groq_question_generation
        
        result = await LLMService._execute_with_retry(
            lambda: chat_groq_question_generation.ainvoke([HumanMessage(content=prompt)]),
            label=f"{batch_label} (Questions)"
        )

        if not result:
            return None
            
        # Parse result
        response_text = result.content if hasattr(result, 'content') else str(result)
        return parse_llm_response(
            response_text,
            AllInterviewQuestions,
            fallback_data=AllInterviewQuestions(all_questions=[])
        )

    @staticmethod
    async def extract_skills(prompt: str) -> Optional[ExtractedSkills]:
        """
        Call LLM to extract skills (Groq/Llama model).
        """
        from app.core.llm import chat_groq_skill_extraction
        
        result = await LLMService._execute_with_retry(
            lambda: chat_groq_skill_extraction.ainvoke([HumanMessage(content=prompt)]),
            label="Skill Extraction"
        )
        
        if not result:
            return None
            
        # Parse result
        response_text = result.content if hasattr(result, 'content') else str(result)
        return parse_llm_response(
            response_text,
            ExtractedSkills,
            fallback_data=ExtractedSkills(skills=[])
        )

    @staticmethod
    async def _execute_with_retry(
        func, 
        label: str, 
        max_retries: int = None
    ) -> Optional[Any]:
        """
        Unified retry handler for LLM calls.
        """
        max_retries = max_retries or settings.RETRY_MAX_ATTEMPTS
        initial_delay = settings.RETRY_BASE_DELAY
        
        start_time = time.perf_counter()
        
        for attempt in range(max_retries + 1):
            try:
                # Apply delay on retry
                if attempt > 0:
                    delay = min(initial_delay * (2 ** (attempt - 1)), settings.RETRY_MAX_DELAY)
                    logger.warning(f"[{label}] Retry {attempt}/{max_retries} waiting {delay:.1f}s")
                    await asyncio.sleep(delay)
                
                # Execute
                response = await func()
                
                # Basic validation
                response_text = response.content if hasattr(response, 'content') else str(response)
                if not response_text or len(response_text) < 5:
                    raise ValueError("Empty or invalid response from LLM")
                    
                elapsed = time.perf_counter() - start_time
                logger.info(f"[{label}] Success in {elapsed:.2f}s (Attempt {attempt+1})")
                return response
                
            except Exception as e:
                # Check retryable
                is_retryable = LLMService._is_retryable(e)
                log_method = logger.warning if is_retryable else logger.error
                
                log_method(f"[{label}] Error (Attempt {attempt+1}): {e}")
                
                if not is_retryable or attempt == max_retries:
                    logger.error(f"[{label}] ❌ Failed after {attempt+1} attempts.")
                    return None
        return None

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        """Check if an error is retryable."""
        error_str = str(error).lower()
        retry_keywords = [
            "rate limit", "timeout", "unavailable", "bad gateway",
            "connection reset", "temporary failure", "503", "504", "502"
        ]
        return any(k in error_str for k in retry_keywords)
