from __future__ import annotations
import logging
import asyncio
from typing import List, Any

from app.schemas.interview import (
    AllSkillSources, 
    ExtractedSkills
)
from app.services.tools.tools import (
    file_text_extractor,
)
from app.services.crew.file_validator import FileValidator
from app.core.config import settings
from app.core.logger import log_async_execution_time
from app.services.tools.source_discovery import discover_sources
from app.services.crew.prompts import generate_questions_prompt, generate_skill_extraction_prompt
from app.services.crew.llm_service import LLMService

# Configure logging
logger = logging.getLogger(__name__)

class InterviewPrepCrew:
    """
    A professional implementation of an interview preparation pipeline.
    This class orchestrates the process of extracting skills from a resume,
    finding relevant sources, and generating interview questions using a
    direct LLM-based architecture (Logic-driven, not Agent-driven).
    
    Improvements:
    - Pure Logic/Service architecture (removed heavy CrewAI agents)
    - Dedicated LLM service for clean architecture
    - Centralized prompt generation (DRY)
    - Dynamic context handling with token optimization
    """

    def __init__(self, file_path: str, validate: bool = True):
        """
        Initialize the InterviewPrepCrew with the path to the resume file.

        Args:
            file_path: Path to the resume file to be processed
            validate: Whether to validate the file immediately (default: True)
        """
        self.file_path = file_path
        self.logger = logger
        self.file_validator = FileValidator(logger=self.logger)

        # Validate file immediately upon initialization
        if validate:
            self.file_validator.validate(self.file_path)
            
        self.logger.info("InterviewPrepCrew initialized in Direct LLM mode")

    async def _process_single_skill_questions(self, skill: str, sources: Any, event_queue: asyncio.Queue, batch_label: str):
        """Helper to process questions for a single skill."""
        try:
            # Find this skill's context
            skill_context = "No context available."
            if hasattr(sources, 'all_sources'):
                for source_item in sources.all_sources:
                    if source_item.skill == skill:
                        skill_context = f"Skill: {source_item.skill}\n{source_item.extracted_content.strip()}"
                        break
            
            token_est = LLMService.estimate_tokens(skill_context)
            
            # Critical Token Check
            self.logger.info(f"[{batch_label}] Token check for '{skill}': {token_est} tokens (Limit: {LLMService.SAFE_TOKEN_LIMIT})")
            if token_est > 0.8 * LLMService.SAFE_TOKEN_LIMIT:
                self.logger.warning(f"[{batch_label}] WARNING: Context for '{skill}' is reaching limit ({token_est}/{LLMService.SAFE_TOKEN_LIMIT})")

            self.logger.info(f"[{batch_label}] Processing '{skill}' individually (~{token_est} tokens)")
            
            prompt = generate_questions_prompt(skill, skill_context)
            questions_obj = await LLMService.generate_questions(prompt, batch_label)
            
            if questions_obj and hasattr(questions_obj, 'all_questions') and len(questions_obj.all_questions) > 0:
                for item in questions_obj.all_questions:
                    result_dict = {"skill": item.skill, "questions": item.questions}
                    await event_queue.put({"type": "data", "content": result_dict})
            else:
                self.logger.warning(f"[{batch_label}] No questions for '{skill}'")
                await event_queue.put({
                    "type": "error",
                    "content": {"skill": skill, "error": "No questions generated"}
                })
                
        except Exception as e:
            self.logger.error(f"[{batch_label}] Error processing '{skill}': {e}", exc_info=True)
            await event_queue.put({
                "type": "error",
                "content": {"skill": skill, "error": str(e)}
            })

    @log_async_execution_time
    async def run_async_generator(self):
        """
        Run the pipeline with parallel processing.
        Yields events as they happen for true streaming.
        """
        try:
            # ---------------------------------------------------------
            # 1. Extract Skills (Direct LLM)
            # ---------------------------------------------------------
            yield {"type": "status", "content": "step_1"}
            self.logger.info("Starting skill extraction...")

            # 1. Extract text from file
            resume_text = file_text_extractor(self.file_path)
            if not resume_text or resume_text.startswith("Error"):
                 self.logger.error(f"Failed to extract text: {resume_text}")
                 yield {"type": "error", "content": {"error": f"Failed to extract text: {resume_text}"}}
                 return

            # 2. Build Prompt
            prompt = generate_skill_extraction_prompt(resume_text, settings.SKILL_COUNT)

            # 3. Call LLM Service
            extracted_skills = await LLMService.extract_skills(prompt)

            if not extracted_skills or not extracted_skills.skills:
                self.logger.warning("No skills extracted.")
                yield {"type": "error", "content": {"error": "No skills extracted from resume"}}
                return

            skills_list = extracted_skills.skills
            self.logger.info(f"Extracted {len(skills_list)} skills: {skills_list}")
            self.logger.info("Skill extraction completed")


            # ---------------------------------------------------------
            # 2. Process Skills in Batches (Pipeline Architecture)
            # ---------------------------------------------------------
            yield {"type": "status", "content": "step_2"}
            yield {"type": "status", "content": "step_3"} # Signal both steps active

            # Chunk skills into batches
            BATCH_SIZE = settings.BATCH_SIZE
            skill_batches = [skills_list[i:i + BATCH_SIZE] for i in range(0, len(skills_list), BATCH_SIZE)]
            total_batches = len(skill_batches)
            
            self.logger.info(f"Processing {len(skills_list)} skills in {total_batches} batches (batch size: {BATCH_SIZE})")

            # Shared queue for all events
            event_queue = asyncio.Queue()
            
            # Semaphore to control concurrent pipelines (matches source discovery limit)
            pipeline_semaphore = asyncio.Semaphore(3)

            async def process_batch_pipeline(batch_index: int, batch_skills: List[str]):
                """
                Pipeline for a single batch:
                1. Discover Sources
                2. Generate Questions (Immediately)
                """
                batch_label = f"Batch {batch_index}/{total_batches}"
                
                async with pipeline_semaphore:
                    try:
                        # --- Step 1: Source Discovery ---
                        self.logger.info(f"[{batch_label}] Starting source discovery")
                        await event_queue.put({"type": "status", "content": f"Finding sources for {batch_label}..."})
                        
                        source_results_list = await discover_sources(batch_skills)
                        sources = AllSkillSources(all_sources=source_results_list)
                        
                        self.logger.info(f"[{batch_label}] Source discovery completed ({len(sources.all_sources)} sources)")

                        # --- Step 2: Question Generation ---
                        self.logger.info(f"[{batch_label}] Starting question generation (Pipeline transition)")
                        await event_queue.put({"type": "status", "content": f"Generating questions for {batch_label}..."})

                        # Optimize context format
                        if hasattr(sources, 'all_sources') and len(sources.all_sources) > 0:
                            context_parts = []
                            for source_item in sources.all_sources:
                                context_parts.append(f"Skill: {source_item.skill}\n{source_item.extracted_content.strip()}")
                            context_str = "\n\n---\n\n".join(context_parts)
                        else:
                            context_str = "No technical context available."
                        
                        # Token Check for Batch
                        token_estimate = LLMService.estimate_tokens(context_str)
                        self.logger.info(f"[{batch_label}] Token check for batch: {token_estimate} tokens (Limit: {LLMService.SAFE_TOKEN_LIMIT})")

                        if token_estimate > LLMService.SAFE_TOKEN_LIMIT:
                            self.logger.warning(f"[{batch_label}] Large context ({token_estimate} tokens) - switching to per-skill processing")
                            # Process each skill individually
                            for skill in batch_skills:
                                await self._process_single_skill_questions(skill, sources, event_queue, batch_label)
                        else:
                            if token_estimate > 0.8 * LLMService.SAFE_TOKEN_LIMIT:
                                self.logger.warning(f"[{batch_label}] WARNING: Batch context is reaching limit ({token_estimate}/{LLMService.SAFE_TOKEN_LIMIT})")
                            
                            # Normal batch processing
                            prompt = generate_questions_prompt(batch_skills, context_str)
                            questions_obj = await LLMService.generate_questions(prompt, batch_label)
                            
                            if questions_obj and hasattr(questions_obj, 'all_questions'):
                                for item in questions_obj.all_questions:
                                    result_dict = {"skill": item.skill, "questions": item.questions}
                                    await event_queue.put({"type": "data", "content": result_dict})
                                self.logger.info(f"[{batch_label}] Question generation completed")
                            else:
                                self.logger.error(f"[{batch_label}] No questions generated")
                                # Fallback to individual if batch fails empty? 
                                # For now just report error
                                for skill in batch_skills:
                                    await event_queue.put({"type": "error", "content": {"skill": skill, "error": "No questions generated"}})

                    except Exception as e:
                        self.logger.error(f"[{batch_label}] Pipeline error: {e}", exc_info=True)
                        await event_queue.put({"type": "error", "content": {"error": f"Batch {batch_index} failed: {e}"}})
                    finally:
                        await event_queue.put({"type": "batch_complete", "content": None})

            # Start all pipelines concurrently
            self.logger.info("Starting concurrent batch pipelines...")
            for i, batch in enumerate(skill_batches):
                asyncio.create_task(process_batch_pipeline(i + 1, batch))

            # Consumer loop
            completed_batches = 0
            while completed_batches < total_batches:
                event = await event_queue.get()
                
                if event["type"] == "batch_complete":
                    completed_batches += 1
                    self.logger.info(f"Progress: {completed_batches}/{total_batches} batches completed")
                else:
                    yield event

            self.logger.info("All batches completed.")

        except Exception as e:
            self.logger.error(f"Error in run_async_generator: {e}", exc_info=True)
            yield {"type": "error", "content": {"error": str(e)}}
