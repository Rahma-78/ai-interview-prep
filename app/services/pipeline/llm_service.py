import asyncio
import logging
import time
from typing import List, Any, Dict, Optional

from app.schemas.interview import AllInterviewQuestions
from app.services.pipeline.llm_parser import parse_llm_response
from app.core.config import settings

logger = logging.getLogger(__name__)

class LLMService:
    """
    Service for handling Direct LLM interactions, including token estimation and parsing.
    """
    
    # Token limit is now configurable via settings
    @staticmethod
    def get_safe_token_limit() -> int:
        """Get the configured safe token limit."""
        return settings.SAFE_TOKEN_LIMIT

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Roughly estimate token count (char count / 4)."""
        return len(text) // 4

    @staticmethod
    def _is_retryable_error(error: Exception) -> bool:
        """Check if an error is retryable (transient server errors, timeouts, etc.)."""
        error_str = str(error).lower()
        
        # Check for HTTP 500-level errors
        if "500" in error_str or "502" in error_str or "503" in error_str or "504" in error_str:
            return True
        
        # Check for common transient error messages
        retryable_patterns = [
            "internal server error",
            "service unavailable",
            "bad gateway",
            "gateway timeout",
            "connection reset",
            "connection refused",
            "temporary failure",
            "rate limit",  # Sometimes rate limits should be retried after backoff
        ]
        
        return any(pattern in error_str for pattern in retryable_patterns)

    @staticmethod
    async def generate_questions(
        prompt: str, 
        batch_label: str = "Batch",
        max_retries: int = 3,
        initial_delay: float = 1.0
    ) -> Optional[AllInterviewQuestions]:
        """
        Call LLM to generate questions and parse the result.
        Uses LangChain ChatOpenAI for fast inference (bypasses CrewAI overhead).
        Includes rate limiting and retry logic with exponential backoff.
        
        Args:
            prompt: The prompt to send to the LLM.
            batch_label: Label for logging purposes.
            max_retries: Maximum number of retry attempts (default: 3).
            initial_delay: Initial delay in seconds before first retry (default: 1.0).
            
        Returns:
            Parsed AllInterviewQuestions object or None on failure.
        """
        from app.core.llm import chat_openrouter
        from langchain_core.messages import HumanMessage
        from app.services.tools.rate_limiter import rate_limiter
        
        last_exception = None
        
        for attempt in range(max_retries + 1):  # +1 for initial attempt
            try:
                # Log retry attempt if not first try
                if attempt > 0:
                    delay = initial_delay * (2 ** (attempt - 1))  # Exponential backoff
                    logger.warning(
                        f"[{batch_label}] Retry attempt {attempt}/{max_retries} after {delay:.1f}s delay"
                    )
                    await asyncio.sleep(delay)
                
                # Execute LLM call in thread pool to avoid blocking event loop
                logger.info(f"[{batch_label}] OpenRouter API call started")
                start_time = time.perf_counter()
                
                # Apply rate limiting before making the API call
                await rate_limiter.acquire_slot('openrouter')
                
                def _call_openrouter():
                    messages = [HumanMessage(content=prompt)]
                    return chat_openrouter.invoke(messages)
                
                # Add 120s timeout to prevent hanging
                response = await asyncio.wait_for(
                    asyncio.to_thread(_call_openrouter),
                    timeout=120.0
                )
                response_text = response.content if hasattr(response, 'content') else str(response)
                
                # Validate response
                if not response_text or len(response_text) < 10:
                    logger.error(f"[{batch_label}] Empty or invalid response from OpenRouter")
                    # Treat empty response as retryable
                    last_exception = ValueError("Empty or invalid response")
                    if attempt < max_retries:
                        continue
                    return None
                
                elapsed = time.perf_counter() - start_time
                logger.info(f"[{batch_label}] OpenRouter API call completed in {elapsed:.2f}s")
                logger.debug(f"[{batch_label}] Response preview: {response_text[:200]}...")
                
                # Parse result using the generic parser
                questions_obj = parse_llm_response(
                    response_text,
                    AllInterviewQuestions,
                    fallback_data=AllInterviewQuestions(all_questions=[])
                )
                
                # Log success after retry
                if attempt > 0:
                    logger.info(f"[{batch_label}] Succeeded after {attempt} retry attempt(s)")
                
                return questions_obj
                
            except asyncio.TimeoutError:
                last_exception = asyncio.TimeoutError(f"Timeout after 120s")
                logger.warning(f"[{batch_label}] OpenRouter API call timed out (attempt {attempt + 1}/{max_retries + 1})")
                # Timeout is retryable
                if attempt < max_retries:
                    continue
                    
            except Exception as e:
                last_exception = e
                
                # Check if error is retryable
                if LLMService._is_retryable_error(e):
                    logger.warning(
                        f"[{batch_label}] Retryable error (attempt {attempt + 1}/{max_retries + 1}): {e}"
                    )
                    if attempt < max_retries:
                        continue
                else:
                    # Non-retryable error, fail immediately
                    logger.error(f"[{batch_label}] Non-retryable LLM error: {e}", exc_info=True)
                    return None
        
        # All retries exhausted
        logger.error(
            f"[{batch_label}] LLM call failed after {max_retries + 1} attempts. Last error: {last_exception}",
            exc_info=True
        )
        return None

    @staticmethod
    async def extract_skills(prompt: str) -> Optional[Any]:
        """
        Call LLM to extract skills and parse the result.
        Uses LangChain's ChatGroq for fast inference with structured output support.
        
        Args:
            prompt: The prompt to send to the LLM.
            
        Returns:
            Parsed ExtractedSkills object or None on failure.
        """
        total_start = time.perf_counter()
        
        try:
            # Step 1: Import (Optimized)
            from app.core.llm import chat_groq
            from langchain_core.messages import HumanMessage
            from app.schemas.interview import ExtractedSkills
            
            # Step 2: Build messages
            prompt_chars = len(prompt)
            
            # Step 3: Execute LLM call using centralized ChatGroq (fast + quality)
            logger.info("[Skill Extraction] LangChain Groq API call starting...")
            
            def _call_groq():
                messages = [HumanMessage(content=prompt)]
                return chat_groq.invoke(messages)
            
            response = await asyncio.to_thread(_call_groq)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Step 4: Parse result
            skills_obj = parse_llm_response(
                response_text,
                ExtractedSkills,
                fallback_data=ExtractedSkills(skills=[])
            )
            
            # Total time
            total_elapsed = time.perf_counter() - total_start
            logger.info(f"[Skill Extraction] TOTAL: {total_elapsed:.2f}s (Prompt: {prompt_chars} chars)")
            
            return skills_obj
            
        except Exception as e:
            logger.error(f"Skill extraction failed: {e}", exc_info=True)
            return None
