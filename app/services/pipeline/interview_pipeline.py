"""
Interview Preparation Pipeline Orchestrator.

This module orchestrates the interview preparation pipeline:
1. File validation
2. Skill extraction from resume
3. Batch processing (source discovery + question generation)
4. Result persistence

Follows Single Responsibility Principle - orchestration only, delegates to specialized classes.
"""
from __future__ import annotations
import logging
import asyncio
import uuid
from typing import List

from app.schemas.interview import ExtractedSkills
from app.services.tools.extractors import file_text_extractor
from app.services.pipeline.file_validator import FileValidator
from app.services.pipeline.batch_processor import BatchProcessor
from app.core.config import settings
from app.core.logger import log_async_execution_time, set_correlation_id, get_correlation_id
from app.core.exceptions import PipelineTimeoutError
from app.core.prompts import generate_skill_extraction_prompt
from app.services.pipeline.llm_service import LLMService

logger = logging.getLogger(__name__)


class InterviewPipeline:
    """
    Orchestrates the interview preparation pipeline.
    
    This class coordinates:
    - Resume text extraction and validation
    - Skill extraction via LLM
    - Parallel batch processing (source discovery + questions)
    - Result streaming (no automatic persistence)
    
    Architecture: Logic-driven (Direct LLM calls), not Agent-driven.
    """

    def __init__(self, file_path: str, correlation_id: str = None):
        """
        Initialize the InterviewPipeline.

        Args:
            file_path: Path to the resume file (already validated by API layer)
            correlation_id: Optional correlation ID for request tracking (auto-generated if not provided)
        """
        self.file_path = file_path
        self.logger = logger
        
        # Set correlation ID for tracking
        self.correlation_id = correlation_id or str(uuid.uuid4())
        set_correlation_id(self.correlation_id)
            
        self.logger.info(f"InterviewPipeline initialized in Direct LLM mode (correlation_id={self.correlation_id})")

    @log_async_execution_time
    async def run_async_generator(self):
        """
        Run the pipeline with parallel processing.
        Yields events as they happen for true streaming.
        """
        
        try:
            # Run pipeline directly without global timeout wrapper
            # Individual services (LLM, Search) have their own timeouts
            async for event in self._pipeline_execution():
                yield event
                
        except Exception as e:
            # Optimize logging: Avoid stack trace for expected pipeline interruptions
            error_msg = str(e).lower()
            if "quota" in error_msg or "rate limit" in error_msg:
                 self.logger.error(f"Pipeline stopped due to quota/rate limit: {e}")
            else:
                 self.logger.error(f"Error in run_async_generator: {e}", exc_info=True)
            
            yield {
                "type": "error",
                "content": {
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            }
    
    async def _pipeline_execution(self):
        """
        Internal pipeline execution logic.
        Separated for timeout handling.
        """
        try:
            # ---------------------------------------------------------
            # 1. Extract Skills (Direct LLM)
            # ---------------------------------------------------------
            yield {"type": "status", "content": "step_1"}
            self.logger.info("Starting skill extraction...")

            # Extract text from PDF (synchronous - fast enough, no need for async wrapper)
            resume_text = file_text_extractor(self.file_path)
            if not resume_text or resume_text.startswith("Error"):
                self.logger.error(f"Failed to extract text: {resume_text}")
                yield {"type": "error", "content": {"error": f"Failed to extract text: {resume_text}"}}
                return

            prompt = generate_skill_extraction_prompt(resume_text, settings.SKILL_COUNT)
            extracted_skills = await LLMService.extract_skills(prompt)

            if not extracted_skills or not extracted_skills.skills:
                self.logger.warning("No skills extracted.")
                yield {"type": "error", "content": {"error": "No skills extracted from resume"}}
                return

            skills_list = extracted_skills.skills
            self.logger.info(f"Extracted {len(skills_list)} skills: {skills_list}")

            # ---------------------------------------------------------
            # 2. Process Skills in Batches (Pipeline Architecture)
            # ---------------------------------------------------------
            yield {"type": "status", "content": "step_2"}
            
            BATCH_SIZE = settings.BATCH_SIZE
            skill_batches = [skills_list[i:i + BATCH_SIZE] for i in range(0, len(skills_list), BATCH_SIZE)]
            total_batches = len(skill_batches)
            
            self.logger.info(f"Processing {len(skills_list)} skills in {total_batches} batches")

            # Create shared queue and batch processor
            event_queue = asyncio.Queue()
            batch_processor = BatchProcessor(event_queue)

            # Start all pipelines concurrently with staggering to reduce Gemini API contention
            self.logger.info("Starting concurrent batch pipelines...")
            
            # Emit step_3 when first batch starts (question generation phase)
            first_batch_started = False
            
            for i, batch in enumerate(skill_batches):
                # Stagger batch starts to prevent simultaneous Gemini API hits (performance optimization)
                if i > 0:
                    await asyncio.sleep(settings.GEMINI_BATCH_STAGGER_DELAY)
                else:
                    # First batch starting - emit step_3
                    yield {"type": "status", "content": "step_3"}
                    first_batch_started = True
                asyncio.create_task(batch_processor.process_batch(i + 1, batch, total_batches))

            # Consumer loop - stream events as they come
            completed_batches = 0
            
            while completed_batches < total_batches:
                event = await event_queue.get()
                
                # Handle batch completion event
                if event["type"] == "batch_completed":
                    completed_batches += 1
                    self.logger.info(f"Progress: {completed_batches}/{total_batches} batches completed")
                else:
                    # Stream all other events to frontend immediately
                    yield event

            self.logger.info("All batches completed.")

            
            # ---------------------------------------------------------
            # 3. Pipeline Complete - Results Ready for Download
            # ---------------------------------------------------------
            # Note: Results are no longer auto-saved to disk.
            # Users can download via the UI download button which calls /download-results endpoint.
            self.logger.info("Pipeline complete.")
            
            # Yield completion event
            yield {
                "type": "complete",
                "content": {
                    "message": "All questions generated successfully. Click Download to save results."
                }
            }

        except Exception as e:
            self.logger.error(f"Error in pipeline execution: {e}", exc_info=True)
            yield {"type": "error", "content": {"error": str(e), "error_type": type(e).__name__}}

