import asyncio
import logging
import time
from typing import Any, Optional

from app.schemas.interview import AllInterviewQuestions
from app.services.pipeline.llm_parser import parse_llm_response
from app.core.config import settings

logger = logging.getLogger(__name__)

class LLMService:
    """
    Service for handling Direct LLM interactions, including token estimation and parsing.
    """
    
    # OpenRouter concurrency semaphore (controls max concurrent question generation)
    _openrouter_semaphore = None
    
    @classmethod
    def _get_openrouter_semaphore(cls):
        """Lazy initialization of OpenRouter semaphore (DRY: single initialization point)."""
        if cls._openrouter_semaphore is None:
            from app.core.config import settings
            cls._openrouter_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_QUESTION_GEN)
        return cls._openrouter_semaphore
    
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
        initial_delay: float = 1.0,
        expected_skill_count: Optional[int] = None
    ) -> Optional[AllInterviewQuestions]:
        """
        Call LLM to generate questions and parse the result.
        Uses async streaming to eliminate timeout issues and reduce latency.
        Concurrency controlled by semaphore to prevent rate limiting.
        
        Args:
            prompt: The prompt to send to the LLM.
            batch_label: Label for logging purposes.
            max_retries: Maximum number of retry attempts (default: 3).
            initial_delay: Initial delay in seconds before first retry (default: 1.0).
            expected_skill_count: Expected number of skills in response. If provided,
                                 incomplete responses trigger automatic retry.
            
        Returns:
            Parsed AllInterviewQuestions object or None on failure.
        """
        from app.core.llm import chat_openrouter
        from langchain_core.messages import HumanMessage
        
        # Acquire concurrency semaphore for OpenRouter (SOLID: separation of concerns)
        semaphore = LLMService._get_openrouter_semaphore()
        
        async with semaphore:
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
                    
                    # Start streaming (rate limiting handled by semaphore)
                    logger.info(f"[{batch_label}] OpenRouter streaming started")
                    start_time = time.perf_counter()
                    
                    messages = [HumanMessage(content=prompt)]
                    
                    # Use streaming if enabled, otherwise fallback to blocking invoke
                    if settings.ENABLE_STREAMING:
                        # Stream response chunks as they arrive (optimized with list accumulation)
                        chunks = []
                        response_text = ""  # Initialize to prevent UnboundLocalError on timeout
                        last_chunk_time = time.perf_counter()
                        chunk_count = 0
                        
                        try:
                            async for chunk in chat_openrouter.astream(messages):
                                chunk_content = chunk.content if hasattr(chunk, 'content') else str(chunk)
                                chunks.append(chunk_content)
                                chunk_count += 1
                                
                                # Check timeout only every 10 chunks (reduces overhead)
                                if chunk_count % 10 == 0:
                                    current_time = time.perf_counter()
                                    timeout_threshold = settings.STREAM_CHUNK_TIMEOUT
                                    
                                    if current_time - last_chunk_time > timeout_threshold:
                                        raise asyncio.TimeoutError(f"No chunk received for {timeout_threshold}s")
                                    last_chunk_time = current_time
                            
                            # Join all chunks at once (much faster than concatenation)
                            response_text = ''.join(chunks)
                        
                        except Exception as stream_error:
                            # Handle stream interruption
                            if isinstance(stream_error, asyncio.TimeoutError):
                                logger.warning(f"[{batch_label}] Stream chunk timeout")
                            else:
                                logger.warning(f"[{batch_label}] Stream interrupted: {stream_error}")
                            
                            # If we received partial response, try to parse it
                            if len(response_text) > 100:
                                logger.info(f"[{batch_label}] Attempting to parse partial stream ({len(response_text)} chars)")
                            else:
                                raise  # Re-raise if too little data received
                        
                        elapsed = time.perf_counter() - start_time
                        logger.info(f"[{batch_label}] Streaming completed in {elapsed:.2f}s")
                        
                    else:
                        # Fallback: Blocking invoke with timeout
                        logger.info(f"[{batch_label}] Using blocking invoke (streaming disabled)")
                        
                        def _call_openrouter():
                            return chat_openrouter.invoke(messages)
                        
                        response = await asyncio.wait_for(
                            asyncio.to_thread(_call_openrouter),
                            timeout=120.0
                        )
                        response_text = response.content if hasattr(response, 'content') else str(response)
                        elapsed = time.perf_counter() - start_time
                        logger.info(f"[{batch_label}] Blocking call completed in {elapsed:.2f}s")
                    
                    # Validate response
                    if not response_text or len(response_text) < 10:
                        logger.error(f"[{batch_label}] Empty or invalid response from OpenRouter")
                        last_exception = ValueError("Empty or invalid response")
                        if attempt < max_retries:
                            continue
                        return None
                    
                    logger.debug(f"[{batch_label}] Response preview: {response_text[:200]}...")
                    
                    # Parse result using the generic parser
                    questions_obj = parse_llm_response(
                        response_text,
                        AllInterviewQuestions,
                        fallback_data=AllInterviewQuestions(all_questions=[])
                    )
                    
                    # Enhanced logging: Show what the LLM actually returned
                    if questions_obj and hasattr(questions_obj, 'all_questions'):
                        skill_count = len(questions_obj.all_questions)
                        if skill_count > 0:
                            skill_names = [item.skill for item in questions_obj.all_questions]
                            logger.info(
                                f"[{batch_label}] ✅ Parsed {skill_count} skill(s) from LLM response: {skill_names}"
                            )
                        else:
                            logger.warning(f"[{batch_label}] ⚠️ LLM response parsed but contains 0 skills!")
                    else:
                        logger.error(f"[{batch_label}] ❌ Failed to parse LLM response!")
                    
                    # Log success after retry
                    if attempt > 0:
                        logger.info(f"[{batch_label}] Succeeded after {attempt} retry attempt(s)")
                    
                    return questions_obj
                    
                except asyncio.TimeoutError:
                    last_exception = asyncio.TimeoutError(f"Timeout after {settings.STREAM_CHUNK_TIMEOUT}s (chunk timeout)")
                    logger.warning(f"[{batch_label}] Stream timeout (attempt {attempt + 1}/{max_retries + 1})")
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
            
            messages = [HumanMessage(content=prompt)]
            response = await chat_groq.ainvoke(messages)
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
