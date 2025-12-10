"""
Batch processing logic for interview preparation pipeline.

This module handles the parallel processing of skill batches:
- Source discovery for each batch
- Question generation with token optimization
- Event queue management for streaming results
"""
import asyncio
import logging
from typing import List, Set
from app.schemas.interview import AllSkillSources,SkillSources
from app.services.tools.source_discovery import discover_sources
from app.services.pipeline.llm_service import LLMService
from app.core.prompts import generate_questions_prompt, generate_contextfree_questions_prompt
from app.services.tools.rate_limiter import ERR_QUOTA_EXHAUSTED, ERR_MODEL_OVERLOADED, ERR_BILLING_REQUIRED

logger = logging.getLogger(__name__)

class BatchProcessor:
    """
    Processes skill batches through the source discovery and question generation pipeline.
    """
    
    def __init__(self, event_queue: asyncio.Queue):
        self.event_queue = event_queue
    
    def _classify_error(self, e: Exception) -> str:
        """Classify error type using consolidated patterns."""
        error_msg = str(e).lower()
        if e.__cause__: error_msg += f" {str(e.__cause__).lower()}"
        
        if any(k in error_msg for k in [ERR_MODEL_OVERLOADED, "503", "overloaded"]):
            return "service_overload"
        if any(k in error_msg for k in [ERR_QUOTA_EXHAUSTED, ERR_BILLING_REQUIRED, "quota", "limit", "exhausted"]):
            return "quota_error"
        return "unknown"
    
    async def process_batch(self, batch_index: int, batch_skills: List[str], total_batches: int):
        """Pipeline for a single batch running in parallel."""
        batch_label = f"Batch {batch_index}/{total_batches}"
        skills_processed = 0
        
        try:
            # --- Step 1: Source Discovery ---
            await self._emit_status(f"Finding sources for {batch_label}...")
            logger.info(f"[{batch_label}] Starting discovery for {batch_skills}")
            
            source_list = await discover_sources(batch_skills)
            
            # Convert dict results to SkillSources objects
         
            skill_sources_objects = [
                SkillSources(skill=s['skill'], extracted_content=s['extracted_content'])
                for s in source_list
            ]
            sources = AllSkillSources(all_sources=skill_sources_objects)
            
            # Identify skills with valid content
            valid_source_skills = {
                s['skill'] for s in source_list 
                if s.get('extracted_content') and "No sources found" not in s['extracted_content']
            }

            
            # --- Step 2: Question Generation ---
            await self._emit_status(f"Generating questions for {batch_label}...")
            
            # Split skills based on source availability
            skills_with_context = [s for s in batch_skills if s in valid_source_skills]
            skills_without_context = [s for s in batch_skills if s not in valid_source_skills]
            
            if skills_without_context:
                logger.info(f"[{batch_label}] Fallback to context-free for: {skills_without_context}")
                
            tasks = []
            
            # Process context-rich skills (recursive/batch)
            if skills_with_context:
                tasks.append(self._process_recursive_batch(skills_with_context, sources, batch_label))
                
            # Process context-free skills (parallel individual)
            for skill in skills_without_context:
                tasks.append(self._process_contextfree_skill(skill, batch_label))
                
            if tasks:
                results = await asyncio.gather(*tasks)
                skills_processed = sum(results)  # Sum of counts (recursive returns int, contextfree returns bool/int)
                
        except Exception as e:
            await self._handle_batch_error(e, batch_index, batch_label)
            skills_processed = 0
        finally:
            await self.event_queue.put({
                "type": "batch_completed",
                "content": {
                    "batch_index": batch_index,
                    "total_skills": len(batch_skills),
                    "processed_skills": skills_processed
                }
            })

    async def _emit_status(self, message: str) -> None:
        await self.event_queue.put({"type": "status", "content": message})

    async def _handle_batch_error(self, e: Exception, batch_index: int, batch_label: str) -> None:
        """Handle error with appropriate UI messaging."""
        error_type = self._classify_error(e)
        
        if error_type == "service_overload":
            logger.warning(f"[{batch_label}] Service overload")
            await self.event_queue.put({
                "type": "service_error",
                "content": {
                    "error": str(e),
                    "user_message": "AI service overloaded. Please retry shortly.",
                    "batch_index": batch_index
                }
            })
        elif error_type == "quota_error":
            logger.warning(f"[{batch_label}] Quota exhausted")
            await self.event_queue.put({
                "type": "quota_error",
                "content": {
                    "error": str(e),
                    "user_message": "API quota reached. Please try again later.",
                    "batch_index": batch_index
                }
            })
        else:
            logger.error(f"[{batch_label}] Unexpected error: {e}", exc_info=True)
            await self.event_queue.put({
                "type": "error",
                "content": {
                    "error": f"Batch {batch_index} failed: {e}",
                    "error_type": type(e).__name__
                }
            })

    async def _process_recursive_batch(self, skills: List[str], sources: AllSkillSources, batch_label: str) -> int:
        """Process batch recursively based on token limits."""
        context_str = self._build_context(sources, skills)
        token_est = LLMService.estimate_tokens(context_str)
        
        if token_est <= LLMService.get_safe_token_limit():
            return await self._process_batch_questions(skills, context_str, batch_label)
            
        # Split logic (simplified iterative)
        logger.info(f"[{batch_label}] Batch too large ({token_est} tokens), splitting...")
        mid = len(skills) // 2
        
        if mid == 0: # Single huge skill
            return 1 if await self._process_single_skill(skills[0], sources, batch_label) else 0
            
        left, right = skills[:mid], skills[mid:]
        results = await asyncio.gather(
            self._process_recursive_batch(left, sources, f"{batch_label}-L"),
            self._process_recursive_batch(right, sources, f"{batch_label}-R")
        )
        return sum(results)

    def _build_context(self, sources: AllSkillSources, skills: List[str] = None) -> str:
        """Build context string efficiently."""
        if not hasattr(sources, 'all_sources') or not sources.all_sources:
            return "No technical context available."
            
        parts = []
        target_skills = set(skills) if skills else None
        
        for item in sources.all_sources:
            if target_skills and item.skill not in target_skills:
                continue
            if item.extracted_content and item.extracted_content.strip():
                parts.append(f"Skill: {item.skill}\n{item.extracted_content.strip()}")
                
        return "\n\n---\n\n".join(parts) if parts else "No technical context available."


    async def _process_single_skill(self, skill: str, sources: AllSkillSources, batch_label: str) -> bool:
        """Process single context-rich skill."""
        context = self._build_context(sources, [skill])
        prompt = generate_questions_prompt(skill, context)
        return await self._execute_gen(prompt, [skill], batch_label)

    async def _process_contextfree_skill(self, skill: str, batch_label: str) -> bool:
        """Process single context-free skill."""
        prompt = generate_contextfree_questions_prompt(skill)
        return await self._execute_gen(prompt, [skill], batch_label)

    async def _process_batch_questions(self, skills: List[str], context: str, batch_label: str) -> int:
        """Process standard batch."""
        prompt = generate_questions_prompt(skills, context)
        return await self._execute_gen(prompt, skills, batch_label)

    async def _execute_gen(self, prompt: str, skills: List[str], batch_label: str) -> int:
        """Execute generation and queue results."""
        questions = await LLMService.generate_questions(prompt, batch_label)
        
        if not questions or not questions.all_questions:
            return 0
            
        count = 0
        for item in questions.all_questions:
            await self.event_queue.put({
                "type": "data", 
                "content": {"skill": item.skill, "questions": item.questions}
            })
            count += 1
        return count
