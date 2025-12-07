"""
Batch processing logic for interview preparation pipeline.

This module handles the parallel processing of skill batches:
- Source discovery for each batch
- Question generation with token optimization
- Event queue management for streaming results

Follows Single Responsibility Principle - focuses only on batch processing.
"""
import asyncio
import logging
from typing import List, Any

from app.schemas.interview import AllSkillSources
from app.services.tools.source_discovery import discover_sources
from app.core.prompts import generate_questions_prompt
from app.services.pipeline.llm_service import LLMService
from app.core.config import settings

logger = logging.getLogger(__name__)


class BatchProcessor:
    """
    Processes skill batches through the source discovery and question generation pipeline.
    
    Responsibilities:
    - Manage concurrent batch processing with semaphore
    - Handle token limits and fallback to per-skill processing
    - Put results into event queue for streaming
    """
    
    def __init__(self, event_queue: asyncio.Queue, max_concurrent: int = None):
        """
        Initialize the batch processor.
        
        Args:
            event_queue: Queue to push events to
            max_concurrent: Maximum concurrent batch pipelines (defaults to settings.MAX_CONCURRENT_BATCHES)
        """
        self.event_queue = event_queue
        if max_concurrent is None:
            max_concurrent = settings.MAX_CONCURRENT_BATCHES
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.logger = logger
        self._first_source_discovery = True
        self._first_question_generation = True
    
    async def process_batch(self, batch_index: int, batch_skills: List[str], total_batches: int):
        """
        Pipeline for a single batch:
        1. Discover Sources
        2. Generate Questions (Immediately)
        
        Args:
            batch_index: Current batch number (1-indexed)
            batch_skills: List of skills in this batch
            total_batches: Total number of batches for logging
        """
        batch_label = f"Batch {batch_index}/{total_batches}"
        
        async with self.semaphore:
            try:
                # --- Step 1: Source Discovery ---
                # Send step_2 transition for the first batch
                if self._first_source_discovery:
                    self._first_source_discovery = False
                    await self.event_queue.put({"type": "status", "content": "step_2"})
                
                self.logger.info(f"[{batch_label}] Starting source discovery")
                await self.event_queue.put({"type": "status", "content": f"Finding sources for {batch_label}..."})
                
                source_results_list = await discover_sources(batch_skills)
                sources = AllSkillSources(all_sources=source_results_list)
                
                self.logger.info(f"[{batch_label}] Source discovery completed ({len(sources.all_sources)} sources)")
                
                # Check if any skills are missing sources
                skills_with_missing_sources = []
                for skill in batch_skills:
                    has_source = False
                    if hasattr(sources, 'all_sources'):
                        for source_item in sources.all_sources:
                            if source_item.skill == skill and source_item.extracted_content and source_item.extracted_content.strip():
                                has_source = True
                                break
                    if not has_source:
                        skills_with_missing_sources.append(skill)
                
                # --- Step 2: Question Generation ---
                # Send step_3 transition for the first batch
                if self._first_question_generation:
                    self._first_question_generation = False
                    await self.event_queue.put({"type": "status", "content": "step_3"})
                
                self.logger.info(f"[{batch_label}] Starting question generation (Pipeline transition)")
                await self.event_queue.put({"type": "status", "content": f"Generating questions for {batch_label}..."})

                # Only split if some skills are missing sources
                if skills_with_missing_sources:
                    self.logger.info(f"[{batch_label}] Detected {len(skills_with_missing_sources)} skills without sources - splitting batch")
                    
                    # Split skills into those with sources and those without
                    skills_with_sources = [s for s in batch_skills if s not in skills_with_missing_sources]
                    
                    # Log the split
                    self.logger.info(f"[{batch_label}] {len(skills_with_missing_sources)} skills without sources will use context-free prompts: {skills_with_missing_sources}")
                    if skills_with_sources:
                        self.logger.info(f"[{batch_label}] {len(skills_with_sources)} skills with sources will use context-based prompts: {skills_with_sources}")
                    
                    # Process skills with sources as a batch (if any) - delegate to recursive processor
                    if skills_with_sources:
                        await self._process_recursive_batch(skills_with_sources, sources, batch_label)
                    
                    # Process skills without sources in parallel with context-free prompt
                    if skills_with_missing_sources:
                        await asyncio.gather(*[
                            self._process_contextfree_skill(skill, batch_label)
                            for skill in skills_with_missing_sources
                        ])
                else:
                    # All skills have sources - delegate to recursive processor
                    await self._process_recursive_batch(batch_skills, sources, batch_label)

            except Exception as e:
                self.logger.error(f"[{batch_label}] Pipeline error: {e}", exc_info=True)
                await self.event_queue.put({
                    "type": "error",
                    "content": {
                        "error": f"Batch {batch_index} failed: {e}",
                        "error_type": type(e).__name__
                    }
                })
            finally:
                await self.event_queue.put({"type": "batch_complete", "content": None})
    
    async def _process_recursive_batch(self, skills: List[str], sources: AllSkillSources, batch_label: str):
        """
        Recursively process a batch of skills with token-aware splitting.
        
        This method handles the initial token check and delegates to the splitting logic
        if needed. Simplifies the main process_batch method by centralizing all
        token-checking and recursive splitting logic.
        
        Args:
            skills: List of skills to process
            sources: All source data
            batch_label: Label for logging
        """
        # Build context and check tokens
        context_str = self._build_context(sources, skills)
        token_estimate = LLMService.estimate_tokens(context_str)
        safe_limit = LLMService.get_safe_token_limit()
        
        self.logger.info(f"[{batch_label}] Token check: {token_estimate} tokens (Limit: {safe_limit})")
        
        if token_estimate > safe_limit:
            # Exceeds limit - use splitting strategy
            await self._process_with_splitting(skills, sources, batch_label)
        else:
            # Fits within limit - process as batch
            if token_estimate > 0.8 * safe_limit:
                self.logger.warning(f"[{batch_label}] WARNING: Batch context is reaching limit ({token_estimate}/{safe_limit})")
            await self._process_batch_questions(skills, context_str, batch_label)
    
    async def _process_with_splitting(self, skills: List[str], sources: AllSkillSources, batch_label: str):
        """
        Process skills with batch-splitting fallback.
        
        If token limit exceeded, recursively splits batch in half instead of 
        processing per-skill (more efficient, fewer API calls).
        """
        if len(skills) <= 1:
            # Single skill - process individually
            for skill in skills:
                await self._process_single_skill(skill, sources, batch_label)
            return
        
        # Build context for current skill set
        context_str = self._build_context(sources, skills)
        token_estimate = LLMService.estimate_tokens(context_str)
        safe_limit = LLMService.get_safe_token_limit()
        
        if token_estimate <= safe_limit:
            # Fits within limit - process as batch
            self.logger.info(f"[{batch_label}] Split batch fits: {len(skills)} skills, {token_estimate} tokens")
            await self._process_batch_questions(skills, context_str, batch_label)
        else:
            # Still too large - split in half and recurse
            mid = len(skills) // 2
            left_half = skills[:mid]
            right_half = skills[mid:]
            
            self.logger.info(f"[{batch_label}] Splitting batch: {len(skills)} -> {len(left_half)} + {len(right_half)}")
            
            await self._process_with_splitting(left_half, sources, f"{batch_label}-L")
            await self._process_with_splitting(right_half, sources, f"{batch_label}-R")
    
    def _build_context(self, sources: AllSkillSources, skills: List[str] = None) -> str:
        """
        Unified context builder - replaces three redundant methods.
        
        Builds context string from sources, optionally filtered by specific skills.
        Centralizes source validation to prevent AttributeError on empty sources.
        
        Args:
            sources: AllSkillSources object containing source data
            skills: Optional list of skills to filter by. If None, includes all sources.
        
        Returns:
            Formatted context string or "No technical context available."
        """
        context_parts = []
        
        # Validate sources structure
        if not hasattr(sources, 'all_sources') or not sources.all_sources:
            return "No technical context available."
        
        # Build context parts
        for source_item in sources.all_sources:
            # Filter by skills if provided
            if skills is not None and source_item.skill not in skills:
                continue
            
            # Validate that the source has actual content
            if source_item.extracted_content and source_item.extracted_content.strip():
                context_parts.append(f"Skill: {source_item.skill}\n{source_item.extracted_content.strip()}")
        
        # Return formatted context or fallback message
        return "\n\n---\n\n".join(context_parts) if context_parts else "No technical context available."
    
    async def _process_single_skill(self, skill: str, sources: AllSkillSources, batch_label: str):
        """Process questions for a single skill (fallback for large contexts)."""
        try:
            # Use unified context builder for single skill
            skill_context = self._build_context(sources, [skill])
            
            # Check if we have valid context
            if skill_context == "No technical context available.":
                self.logger.info(f"[{batch_label}] No context for '{skill}' - generating context-free verbal questions")
            
            token_est = LLMService.estimate_tokens(skill_context)
            safe_limit = LLMService.get_safe_token_limit()
            
            if token_est > 0.8 * safe_limit:
                self.logger.warning(f"[{batch_label}] WARNING: Context for '{skill}' is reaching limit ({token_est}/{safe_limit})")

            self.logger.info(f"[{batch_label}] Processing '{skill}' individually (~{token_est} tokens)")
            
            prompt = generate_questions_prompt(skill, skill_context)
            questions_obj = await LLMService.generate_questions(prompt, batch_label)
            
            if questions_obj and hasattr(questions_obj, 'all_questions') and len(questions_obj.all_questions) > 0:
                for item in questions_obj.all_questions:
                    result_dict = {"skill": item.skill, "questions": item.questions}
                    await self.event_queue.put({"type": "data", "content": result_dict})
            else:
                self.logger.warning(f"[{batch_label}] No questions for '{skill}'")
                await self.event_queue.put({
                    "type": "error",
                    "content": {"skill": skill, "error": "No questions generated"}
                })
                
        except Exception as e:
            self.logger.error(f"[{batch_label}] Error processing '{skill}': {e}", exc_info=True)
            await self.event_queue.put({
                "type": "error",
                "content": {"skill": skill, "error": str(e)}
            })
    
    async def _process_contextfree_skill(self, skill: str, batch_label: str):
        """
        Process a single skill using context-free prompt (no sources available).
        Generates verbal, conceptual technical questions.
        """
        try:
            self.logger.info(f"[{batch_label}] Processing '{skill}' with context-free prompt (no sources)")
            
            # Use context-free prompt directly
            from app.core.prompts import generate_contextfree_questions_prompt
            prompt = generate_contextfree_questions_prompt(skill)
            questions_obj = await LLMService.generate_questions(prompt, f"{batch_label}-{skill}")
            
            if questions_obj and hasattr(questions_obj, 'all_questions') and len(questions_obj.all_questions) > 0:
                for item in questions_obj.all_questions:
                    result_dict = {"skill": item.skill, "questions": item.questions}
                    await self.event_queue.put({"type": "data", "content": result_dict})
                self.logger.info(f"[{batch_label}] Context-free questions generated for '{skill}'")
            else:
                self.logger.warning(f"[{batch_label}] No questions generated for '{skill}'")
                await self.event_queue.put({
                    "type": "error",
                    "content": {"skill": skill, "error": "No questions generated"}
                })
                
        except Exception as e:
            self.logger.error(f"[{batch_label}] Error processing context-free '{skill}': {e}", exc_info=True)
            await self.event_queue.put({
                "type": "error",
                "content": {"skill": skill, "error": str(e)}
            })
    
    async def _process_batch_questions(self, batch_skills: List[str], context_str: str, batch_label: str):
        """Process questions for entire batch."""
        prompt = generate_questions_prompt(batch_skills, context_str)
        questions_obj = await LLMService.generate_questions(prompt, batch_label)
        
        if questions_obj and hasattr(questions_obj, 'all_questions') and len(questions_obj.all_questions) > 0:
            for item in questions_obj.all_questions:
                result_dict = {"skill": item.skill, "questions": item.questions}
                await self.event_queue.put({"type": "data", "content": result_dict})
            self.logger.info(f"[{batch_label}] Question generation completed")
        else:
            error_reason = "No questions generated (API may have failed or timed out)"
            if questions_obj is None:
                error_reason = "API call failed or timed out"
            
            self.logger.error(f"[{batch_label}] {error_reason}")
            for skill in batch_skills:
                await self.event_queue.put({"type": "error", "content": {"skill": skill, "error": error_reason}})
