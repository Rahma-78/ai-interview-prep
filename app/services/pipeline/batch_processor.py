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
from typing import List

from app.schemas.interview import AllSkillSources
from app.services.tools.source_discovery import discover_sources
from app.services.pipeline.llm_service import LLMService
from app.core.prompts import generate_questions_prompt, generate_contextfree_questions_prompt
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
        batch_outcome = "failure"  # Track outcome: 'success', 'partial', or 'failure'
        skills_processed = 0
        
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
                    count_with_sources = 0
                    if skills_with_sources:
                        count_with_sources = await self._process_recursive_batch(skills_with_sources, sources, batch_label)
                    
                    # Process skills without sources in parallel with context-free prompt
                    contextfree_results = []
                    if skills_with_missing_sources:
                        contextfree_results = await asyncio.gather(*[
                            self._process_contextfree_skill(skill, batch_label)
                            for skill in skills_with_missing_sources
                        ])
                    
                    # Count successful context-free skills
                    count_contextfree = sum(1 for success in contextfree_results if success)
                    skills_processed = count_with_sources + count_contextfree
                else:
                    # All skills have sources - delegate to recursive processor
                    skills_processed = await self._process_recursive_batch(batch_skills, sources, batch_label)
                
                # Determine batch outcome
                if skills_processed == len(batch_skills):
                    batch_outcome = "success"
                elif skills_processed > 0:
                    batch_outcome = "partial"
                else:
                    batch_outcome = "failure"

            except Exception as e:
                # Optimized Logging: Don't dump stack traces for known operational errors
                error_text = str(e).lower()
                is_quota_error = any(k in error_text for k in ["quota exhausted", "daily limit", "resource_exhausted"]) or \
                                 any(k in str(e.__cause__).lower() for k in ["quota exhausted", "daily limit", "resource_exhausted"] if e.__cause__)
                
                if is_quota_error:
                    self.logger.warning(f"[{batch_label}] Quota exhaustion detected ({str(e)[:100]}...)")
                elif "source discovery failed" in error_text:
                     # This is a known operational error from source_discovery
                    self.logger.error(f"[{batch_label}] Pipeline error: {e}")
                else:
                    # Unexpected crash - log full traceback
                    self.logger.error(f"[{batch_label}] Unexpected Pipeline Error: {e}", exc_info=True)

                batch_outcome = "failure"
                skills_processed = 0
                
                if is_quota_error:
                    # Emit distinct quota_error event for clear UI messaging
                    self.logger.warning(f"[{batch_label}] Quota exhaustion detected - notifying UI")
                    await self.event_queue.put({
                        "type": "quota_error",
                        "content": {
                            "error": str(e),
                            "error_type": "QuotaExhausted",
                            "user_message": (
                                "The LLM provider has reached its API request limit. "
                                "This is not a system error. Please try again later or contact support."
                            ),
                            "batch_index": batch_index
                        }
                    })
                else:
                    # Generic error handling
                    await self.event_queue.put({
                        "type": "error",
                        "content": {
                            "error": f"Batch {batch_index} failed: {e}",
                            "error_type": type(e).__name__
                        }
                    })
            finally:
                # Send distinct completion event based on outcome
                event_type = f"batch_{batch_outcome}"
                completion_msg = {
                    "success": f"✅ {batch_label} SUCCESS: {skills_processed}/{len(batch_skills)} skills",
                    "partial": f"⚠️  {batch_label} PARTIAL: {skills_processed}/{len(batch_skills)} skills",
                    "failure": f"❌ {batch_label} FAILED: 0/{len(batch_skills)} skills"
                }
                
                self.logger.info(completion_msg[batch_outcome])
                await self.event_queue.put({
                    "type": event_type,
                    "content": {
                        "batch_index": batch_index,
                        "total_skills": len(batch_skills),
                        "processed_skills": skills_processed,
                        "outcome": batch_outcome
                    }
                })
    
    async def _process_recursive_batch(self, skills: List[str], sources: AllSkillSources, batch_label: str) -> int:
        """
        Recursively process a batch of skills with token-aware splitting.
        
        This method handles the initial token check and delegates to the splitting logic
        if needed. Simplifies the main process_batch method by centralizing all
        token-checking and recursive splitting logic.
        
        Args:
            skills: List of skills to process
            sources: All source data
            batch_label: Label for logging
            
        Returns:
            Number of skills successfully processed
        """
        # Build context and check tokens
        context_str = self._build_context(sources, skills)
        token_estimate = LLMService.estimate_tokens(context_str)
        safe_limit = LLMService.get_safe_token_limit()
        
        self.logger.info(f"[{batch_label}] Token check: {token_estimate} tokens (Limit: {safe_limit})")
        
        if token_estimate > safe_limit:
            # Exceeds limit - use splitting strategy
            return await self._process_with_splitting(skills, sources, batch_label)
        else:
            # Fits within limit - process as batch
            if token_estimate > 0.8 * safe_limit:
                self.logger.warning(f"[{batch_label}] WARNING: Batch context is reaching limit ({token_estimate}/{safe_limit})")
            return await self._process_batch_questions(skills, context_str, batch_label)
    
    async def _process_with_splitting(self, skills: List[str], sources: AllSkillSources, batch_label: str) -> int:
        """
        Process skills with batch-splitting fallback using an ITERATIVE stack-based approach.
        This prevents potential stack overflow with deeply nested recursive calls.
        """
        total_processed = 0
        stack = [(skills, batch_label)]
        
        while stack:
            current_skills, current_label = stack.pop()
            
            if not current_skills:
                continue
                
            if len(current_skills) == 1:
                # Base case: process single skill
                success = await self._process_single_skill(current_skills[0], sources, current_label)
                if success:
                    total_processed += 1
                continue
            
            # Build context for current chunk
            context_str = self._build_context(sources, current_skills)
            token_estimate = LLMService.estimate_tokens(context_str)
            safe_limit = LLMService.get_safe_token_limit()
            
            if token_estimate <= safe_limit:
                # Fits within limit -> Process as batch
                self.logger.info(f"[{current_label}] Split batch fits: {len(current_skills)} skills, {token_estimate} tokens")
                count = await self._process_batch_questions(current_skills, context_str, current_label)
                total_processed += count
            else:
                # Too large -> Split and push to stack
                mid = len(current_skills) // 2
                left_half = current_skills[:mid]
                right_half = current_skills[mid:]
                
                self.logger.info(f"[{current_label}] Splitting batch: {len(current_skills)} -> {len(left_half)} + {len(right_half)}")
                
                # Push right half first so left half is processed first (LIFO)
                stack.append((right_half, f"{current_label}-R"))
                stack.append((left_half, f"{current_label}-L"))
                
        return total_processed
    
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
    
    async def _validate_and_queue_results(self, questions_obj, expected_skills: List[str], batch_label: str) -> int:
        """
        Validate LLM response completeness and queue results (Count-based validation).
        
        Validates that the LLM returned the expected NUMBER of skills.
        Does NOT validate skill names (LLM may reformat them - hyphens, quotes, etc).
        The LLM's returned skill names are treated as canonical.
        
        Args:
            questions_obj: Parsed AllInterviewQuestions object from LLM
            expected_skills: List of skills that were requested (used only for count)
            batch_label: Label for logging
            
        Returns:
            Number of skills actually processed (0 if complete failure, partial count if incomplete)
        """
        if not questions_obj or not hasattr(questions_obj, 'all_questions') or len(questions_obj.all_questions) == 0:
            # No questions at all - complete failure
            self.logger.error(
                f"[{batch_label}] ⚠️ COMPLETE LLM FAILURE! "
                f"Expected {len(expected_skills)} skills, received 0."
            )
            for skill in expected_skills:
                await self.event_queue.put({
                    "type": "error",
                    "content": {"skill": skill, "error": "No questions generated"}
                })
            return 0  # Complete failure
        
        # COUNT-BASED VALIDATION: Compare counts, not names
        expected_count = len(expected_skills)
        received_count = len(questions_obj.all_questions)
        
        if received_count < expected_count:
            # LLM returned fewer skills than expected - this is a real issue
            received_skill_names = [item.skill for item in questions_obj.all_questions]
            self.logger.error(
                f"[{batch_label}] ⚠️ INCOMPLETE LLM RESPONSE! "
                f"Expected {expected_count} skills, received {received_count}. "
                f"LLM returned: {received_skill_names}"
            )
            
            # Queue what we got, but mark as incomplete
            for item in questions_obj.all_questions:
                result_dict = {"skill": item.skill, "questions": item.questions}
                await self.event_queue.put({"type": "data", "content": result_dict})
            
            return received_count  # Return actual count (partial)
        
        # Success: Count matches (trust LLM's skill names as canonical)
        for item in questions_obj.all_questions:
            result_dict = {"skill": item.skill, "questions": item.questions}
            await self.event_queue.put({"type": "data", "content": result_dict})
        
        return expected_count  # Return full count (success)
    
    async def _process_single_skill(self, skill: str, sources: AllSkillSources, batch_label: str) -> bool:
        """
        Process questions for a single skill (fallback for large contexts).
        
        Returns:
            True if skill was successfully processed, False otherwise
        """
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
            questions_obj = await LLMService.generate_questions(
                prompt, 
                batch_label,
                expected_skill_count=1  # Single skill processing
            )
            
            # Use centralized validation (returns count)
            processed_count = await self._validate_and_queue_results(questions_obj, [skill], batch_label)
            if processed_count == 0:
                self.logger.warning(f"[{batch_label}] Failed to process '{skill}'")
                return False
            return True
                
        except Exception as e:
            self.logger.error(f"[{batch_label}] Error processing '{skill}': {e}", exc_info=True)
            await self.event_queue.put({
                "type": "error",
                "content": {"skill": skill, "error": str(e)}
            })
            return False
    
    async def _process_contextfree_skill(self, skill: str, batch_label: str) -> bool:
        """
        Process a single skill using context-free prompt (no sources available).
        Generates verbal, conceptual technical questions.
        
        Returns:
            True if skill was successfully processed, False otherwise
        """
        try:
            self.logger.info(f"[{batch_label}] Processing '{skill}' with context-free prompt (no sources)")
            
            # Use context-free prompt directly
            prompt = generate_contextfree_questions_prompt(skill)
            questions_obj = await LLMService.generate_questions(
                prompt, 
                f"{batch_label}-{skill}",
                expected_skill_count=1  # Single skill processing
            )
            
            # Use centralized validation (returns count)
            processed_count = await self._validate_and_queue_results(questions_obj, [skill], batch_label)
            if processed_count == 0:
                self.logger.warning(f"[{batch_label}] Failed to process context-free '{skill}'")
                return False
            return True
                
        except Exception as e:
            self.logger.error(f"[{batch_label}] Error processing context-free '{skill}': {e}", exc_info=True)
            await self.event_queue.put({
                "type": "error",
                "content": {"skill": skill, "error": str(e)}
            })
            return False
    
    async def _process_batch_questions(self, batch_skills: List[str], context_str: str, batch_label: str) -> int:
        """
        Process questions for entire batch.
        
        Returns:
            Number of skills successfully processed
        """
        prompt = generate_questions_prompt(batch_skills, context_str)
        questions_obj = await LLMService.generate_questions(
            prompt, 
            batch_label,
            expected_skill_count=len(batch_skills)  # Expect all batch skills
        )
        
        # Use centralized validation (returns count)
        processed_count = await self._validate_and_queue_results(questions_obj, batch_skills, batch_label)
        
        # Log completion status
        if processed_count == len(batch_skills):
            self.logger.info(f"[{batch_label}] Question generation completed successfully")
        else:
            self.logger.warning(
                f"[{batch_label}] Question generation completed with incomplete results"
            )
        
        return processed_count
