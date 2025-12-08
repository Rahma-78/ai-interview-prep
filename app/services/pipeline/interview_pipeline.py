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

    def __init__(self, file_path: str, validate: bool = True, correlation_id: str = None):
        """
        Initialize the InterviewPipeline.

        Args:
            file_path: Path to the resume file
            validate: Whether to validate the file immediately
            correlation_id: Optional correlation ID for request tracking (auto-generated if not provided)
        """
        self.file_path = file_path
        self.logger = logger
        self.file_validator = FileValidator(logger=self.logger)
        
        # Set correlation ID for tracking
        self.correlation_id = correlation_id or str(uuid.uuid4())
        set_correlation_id(self.correlation_id)

        if validate:
            self.file_validator.validate(self.file_path)
            
        self.logger.info(f"InterviewPipeline initialized in Direct LLM mode (correlation_id={self.correlation_id})")

    @log_async_execution_time
    async def run_async_generator(self):
        """
        Run the pipeline with parallel processing and global timeout.
        Yields events as they happen for true streaming.
        """
        # Ensure correlation ID is set for this execution context
        set_correlation_id(self.correlation_id)
        
        try:
            # Wrap entire pipeline in global timeout
            gen = self._pipeline_execution()
            loop = asyncio.get_running_loop()
            end_time = loop.time() + settings.GLOBAL_TIMEOUT_SECONDS

            while True:
                remaining_time = end_time - loop.time()
                if remaining_time <= 0:
                    raise asyncio.TimeoutError()
                
                try:
                    event = await asyncio.wait_for(gen.__anext__(), timeout=remaining_time)
                    yield event
                except StopAsyncIteration:
                    break
                
        except asyncio.TimeoutError:
            error_msg = f"Pipeline execution exceeded {settings.GLOBAL_TIMEOUT_SECONDS}s timeout"
            self.logger.error(error_msg)
            yield {
                "type": "error",
                "content": {
                    "error": error_msg,
                    "error_type": "PipelineTimeoutError"
                }
            }
        except Exception as e:
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
            # Step transitions will be sent by batch_processor when processing actually starts


            BATCH_SIZE = settings.BATCH_SIZE
            skill_batches = [skills_list[i:i + BATCH_SIZE] for i in range(0, len(skills_list), BATCH_SIZE)]
            total_batches = len(skill_batches)
            
            self.logger.info(f"Processing {len(skills_list)} skills in {total_batches} batches")

            # Create shared queue and batch processor
            event_queue = asyncio.Queue()
            batch_processor = BatchProcessor(event_queue)

            # Start all pipelines concurrently
            self.logger.info("Starting concurrent batch pipelines...")
            for i, batch in enumerate(skill_batches):
                asyncio.create_task(batch_processor.process_batch(i + 1, batch, total_batches))

            # Consumer loop - yield events as they come
            completed_batches = 0
            successful_batches = 0
            partial_batches = 0
            failed_batches = 0
            all_results = []
            quota_error_detected = False
            
            while completed_batches < total_batches:
                event = await event_queue.get()
                
                # Handle distinct completion events
                if event["type"] == "batch_success":
                    successful_batches += 1
                    completed_batches += 1
                elif event["type"] == "batch_partial":
                    partial_batches += 1
                    completed_batches += 1
                elif event["type"] == "batch_failure":
                    failed_batches += 1
                    completed_batches += 1
                else:
                    if event["type"] == "data":
                        all_results.append(event["content"])
                    elif event["type"] == "quota_error":
                        quota_error_detected = True
                        self.logger.warning("Quota error event received - forwarding to UI")
                    # Yield all non-completion events to frontend
                    yield event
            
            # Log final progress with outcome breakdown
            self.logger.info(
                f"Progress: {completed_batches}/{total_batches} batches "
                f"({successful_batches} success, {partial_batches} partial, {failed_batches} failure)"
            )

            self.logger.info("All batches completed.")

            
            # ---------------------------------------------------------
            # 3. Pipeline Complete - Results Ready for Download
            # ---------------------------------------------------------
            # Note: Results are no longer auto-saved to disk.
            # Users can download via the UI download button which calls /download-results endpoint.
            self.logger.info(f"Pipeline complete. Generated {len(all_results)} skill result sets.")
            
            # Yield completion event with download readiness
            yield {
                "type": "complete",
                "content": {
                    "total_results": len(all_results),
                    "message": "All questions generated successfully. Click Download to save results."
                }
            }

        except Exception as e:
            self.logger.error(f"Error in pipeline execution: {e}", exc_info=True)
            yield {"type": "error", "content": {"error": str(e), "error_type": type(e).__name__}}

