import asyncio
import logging
import time
from typing import List, Any, Dict, Optional

from app.core.llm import llm_openai
from app.schemas.interview import AllInterviewQuestions
from app.services.crew.parser import _parse_crew_result

logger = logging.getLogger(__name__)

class LLMService:
    """
    Service for handling Direct LLM interactions, including token estimation and parsing.
    """
    
    # Provider: OpenRouter gpt-oss-120b
    # - Context window: 128k tokens
    # - Max output: 4k tokens
    # - Safe input threshold: 50k tokens (leaves ~74k buffer)
    SAFE_TOKEN_LIMIT = 50000

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Roughly estimate token count (char count / 4)."""
        return len(text) // 4

    @staticmethod
    async def generate_questions(
        prompt: str, 
        batch_label: str = "Batch"
    ) -> Optional[AllInterviewQuestions]:
        """
        Call LLM to generate questions and parse the result.
        
        Args:
            prompt: The prompt to send to the LLM.
            batch_label: Label for logging purposes.
            
        Returns:
            Parsed AllInterviewQuestions object or None on failure.
        """
        try:
            messages = [{"role": "user", "content": prompt}]
            
            # Execute LLM call in thread pool to avoid blocking event loop
            logger.info(f"[{batch_label}] ⏱️ OpenRouter API call started")
            start_time = time.perf_counter()
            
            response_text = await asyncio.to_thread(llm_openai.call, messages=messages)
            
            elapsed = time.perf_counter() - start_time
            logger.info(f"[{batch_label}] ⏱️ OpenRouter API call completed in {elapsed:.2f}s")
            
            # Parse result using the generic parser
            questions_obj = _parse_crew_result(
                response_text,
                AllInterviewQuestions,
                fallback_data=AllInterviewQuestions(all_questions=[])
            )
            
            return questions_obj
            
        except Exception as e:
            logger.error(f"[{batch_label}] LLM call failed: {e}", exc_info=True)
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
        
        # Step 1: Import
        import_start = time.perf_counter()
        from app.core.llm import chat_groq
        from langchain_core.messages import HumanMessage
        from app.schemas.interview import ExtractedSkills
        import_elapsed = time.perf_counter() - import_start
        logger.info(f"⏱️ [Skill Extraction] Step 1 - Imports: {import_elapsed:.3f}s")
        
        try:
            # Step 2: Build messages
            msg_start = time.perf_counter()
            prompt_chars = len(prompt)
            prompt_tokens_est = prompt_chars // 4
            msg_elapsed = time.perf_counter() - msg_start
            logger.info(f"⏱️ [Skill Extraction] Step 2 - Message build: {msg_elapsed:.3f}s (prompt: {prompt_chars} chars, ~{prompt_tokens_est} tokens)")
            
            # Step 3: Execute LLM call using centralized ChatGroq (fast + quality)
            logger.info("⏱️ [Skill Extraction] Step 3 - LangChain Groq API call starting...")
            api_start = time.perf_counter()
            
            def _call_groq():
                messages = [HumanMessage(content=prompt)]
                return chat_groq.invoke(messages)
            
            response = await asyncio.to_thread(_call_groq)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            api_elapsed = time.perf_counter() - api_start
            response_chars = len(response_text) if response_text else 0
            logger.info(f"⏱️ [Skill Extraction] Step 3 - LangChain Groq API call: {api_elapsed:.2f}s (response: {response_chars} chars)")
            
            # Step 4: Parse result
            parse_start = time.perf_counter()
            skills_obj = _parse_crew_result(
                response_text,
                ExtractedSkills,
                fallback_data=ExtractedSkills(skills=[])
            )
            parse_elapsed = time.perf_counter() - parse_start
            logger.info(f"⏱️ [Skill Extraction] Step 4 - Parsing: {parse_elapsed:.3f}s")
            
            # Total time
            total_elapsed = time.perf_counter() - total_start
            logger.info(f"⏱️ [Skill Extraction] TOTAL: {total_elapsed:.2f}s")
            
            return skills_obj
            
        except Exception as e:
            logger.error(f"Skill extraction failed: {e}", exc_info=True)
            return None
