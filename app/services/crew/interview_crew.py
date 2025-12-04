from __future__ import annotations
import json
import logging
import time
import asyncio
from typing import Dict, List, Any, Callable, Awaitable, Optional
from pathlib import Path

from crewai import Crew as CrewAI, Process, Task

from app.schemas.interview import (
    AllInterviewQuestions, 
    AllSkillSources, 
    SkillSources, 
    ExtractedSkills, 
    InterviewQuestions
)
from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import (
    file_text_extractor,
    grounded_source_discoverer,
)
from app.services.tools.helpers import clean_llm_json_output
from app.services.crew.file_validator import FileValidator
from app.core.config import settings
from app.core.logger import log_async_execution_time

# Configure logging
logger = logging.getLogger(__name__)

class InterviewPrepCrew:
    """
    A professional implementation of an interview preparation pipeline using CrewAI.
    This class orchestrates the process of extracting skills from a resume,
    finding relevant sources, and generating interview questions.

    Improvements:
    - Separate semaphores for source discovery and question generation
    - Granular locking (semaphores released immediately after API calls)
    - Generic parser following DRY principle
    """

    def __init__(self, file_path: str, validate: bool = True):
        """
        Initialize the InterviewPrepCrew with the path to the resume file.

        Args:
            file_path: Path to the resume file to be processed
            validate: Whether to validate the file immediately (default: True)
        """
        self.file_path = file_path
        self.agents = InterviewPrepAgents()
        self.tools = {
            "file_text_extractor": file_text_extractor,
            "grounded_source_discoverer": grounded_source_discoverer,
        }
        self.tasks = InterviewPrepTasks()
        self.logger = logger

        # Validate file immediately upon initialization
        if validate:
            self.file_validator = FileValidator(logger=self.logger)
            self.file_validator.validate(self.file_path)

    @log_async_execution_time
    async def run_async_generator(self):
        """
        Run the pipeline with parallel processing for batches of skills using dedicated mini-crews.
        Yields events as they happen for true streaming.
        
        Yields:
            Dict[str, Any]: Event dictionary with 'type' and 'content'.
            Types: 'status', 'data', 'error'
        """
        start_time = time.time()

        try:
            # ---------------------------------------------------------
            # 1. Extract Skills (Sequential)
            # ---------------------------------------------------------
            yield {"type": "status", "content": "step_1"}

            resume_analyzer = self.agents.resume_analyzer_agent(self.tools)
            skills_task = self.tasks.extract_skills_task(resume_analyzer, self.file_path)

            # Execute skills extraction directly
            skills_crew = CrewAI(
                agents=[resume_analyzer],
                tasks=[skills_task],
                process=Process.sequential,
                verbose=settings.DEBUG_MODE
            )

            skills_result = await skills_crew.kickoff_async()

            # Parse skills using generic parser
            extracted_skills = self._parse_crew_result(
                skills_result, 
                ExtractedSkills,
                fallback_data=ExtractedSkills(skills=[])
            )
            skills_list = extracted_skills.skills

            if not skills_list:
                self.logger.warning("No skills extracted.")
                return

            # ---------------------------------------------------------
            # 2. Process Skills in Batches (Mini-Crews with Granular Locking)
            # ---------------------------------------------------------
            yield {"type": "status", "content": "step_2"}

            # Chunk skills into batches of 3 to optimize source discovery
            BATCH_SIZE = 3
            skill_batches = [skills_list[i:i + BATCH_SIZE] for i in range(0, len(skills_list), BATCH_SIZE)]

            # Separate semaphores for independent rate limiting
            # Adjust based on your API tier and rate limits
            source_sem = asyncio.Semaphore(3)  # Source discovery rate limit
            question_sem = asyncio.Semaphore(3)  # Question generation rate limit

            async def process_batch_crew(batch_skills: List[str]):
                """
                Process a single batch with granular locking.
                """
                try:
                    self.logger.info(f"Starting batch processing for skills: {batch_skills}")
                    formatted_skills = ", ".join(batch_skills)

                    # ---------------------------------------------------------
                    # PHASE 1: Source Discovery
                    # ---------------------------------------------------------
                    async with source_sem:
                        source_agent = self.agents.source_discoverer_agent(self.tools)
                        discover_task = self.tasks.discover_sources_task(source_agent, batch_skills)

                        source_crew = CrewAI(
                            agents=[source_agent],
                            tasks=[discover_task],
                            process=Process.sequential,
                            verbose=settings.DEBUG_MODE
                        )

                        self.logger.info(f"Kickoff source crew for batch: {batch_skills}")
                        source_result = await source_crew.kickoff_async(inputs={"skills": formatted_skills})
                        self.logger.info(f"Finished source crew for batch: {batch_skills}")

                    # Parse sources outside semaphore (not an API call)
                    sources = self._parse_crew_result(
                        source_result,
                        AllSkillSources,
                        fallback_data=AllSkillSources(all_sources=[])
                    )

                    # ---------------------------------------------------------
                    # PHASE 2: Question Generation
                    # ---------------------------------------------------------
                    async with question_sem:
                        question_agent = self.agents.question_generator_agent(self.tools)
                        question_task = self.tasks.generate_questions_task(question_agent)

                        question_crew = CrewAI(
                            agents=[question_agent],
                            tasks=[question_task],
                            process=Process.sequential,
                            verbose=settings.DEBUG_MODE
                        )

                        # Pass sources as context to question generation
                        context_str = sources.model_dump_json() if sources else "{}"
                        self.logger.info(f"Kickoff question crew for batch: {batch_skills} with context size: {len(context_str)}")
                        question_result = await question_crew.kickoff_async(
                            inputs={
                                "skills": formatted_skills,
                                "context": context_str
                            }
                        )
                        self.logger.info(f"Finished question crew for batch: {batch_skills}")

                    # Parse questions outside semaphore (not an API call)
                    questions_obj = self._parse_crew_result(
                        question_result, 
                        AllInterviewQuestions,
                        fallback_data=AllInterviewQuestions(all_questions=[])
                    )

                    # Format results for this batch
                    batch_results = []

                    if hasattr(questions_obj, 'all_questions'):
                        for item in questions_obj.all_questions:
                            result_dict = {
                                "skill": item.skill,
                                "questions": item.questions
                            }
                            batch_results.append(result_dict)
                    
                    return batch_results

                except Exception as e:
                    self.logger.error(f"Error processing batch {batch_skills}: {e}", exc_info=True)
                    # Return error structure so we don't lose data for other batches
                    return [{"skill": skill, "questions": [], "error": str(e)} for skill in batch_skills]

            # Create tasks for all batches
            tasks = [process_batch_crew(batch) for batch in skill_batches]
            
            # Yield step 3 status before starting to yield results
            yield {"type": "status", "content": "step_3"}

            # Process batches as they complete
            for future in asyncio.as_completed(tasks):
                try:
                    batch_results = await future
                    for result in batch_results:
                        if "error" in result:
                            yield {"type": "error", "content": result}
                        else:
                            yield {"type": "data", "content": result}
                except Exception as e:
                    self.logger.error(f"Error in batch execution: {e}", exc_info=True)
                    yield {"type": "error", "content": {"error": str(e)}}

        except Exception as e:
            self.logger.error(f"Error in run_async_generator: {e}", exc_info=True)
            yield {"type": "error", "content": {"error": str(e)}}

    def _parse_crew_result(
        self,
        result: Any,
        schema_class: type,
        fallback_data: Any = None
    ) -> Any:
        """
        Generic parser for CrewAI results following DRY and Single Responsibility principles.

        Args:
            result: The CrewAI result object
            schema_class: Pydantic model class to validate against
            fallback_data: Data to return on failure (optional)

        Returns:
            Validated Pydantic model instance

        Raises:
            ValueError: If parsing fails and no fallback_data provided
        """
        try:
            # Step 1: Try direct Pydantic object if supported by CrewAI version
            if hasattr(result, 'pydantic') and result.pydantic:
                return result.pydantic
            elif hasattr(result, 'json_dict') and result.json_dict:
                return schema_class(**result.json_dict)
            else:
                # Step 2: Fallback to parsing raw JSON
                cleaned_json = clean_llm_json_output(result.raw)
                import json
                data = json.loads(cleaned_json)
                return schema_class(**data)  # Two-step parsing with coercion

        except Exception as e:
            self.logger.error(
                f"Error parsing {schema_class.__name__}: {e}",
                exc_info=True
            )
            self.logger.error(f"Raw output (first 500 chars): {str(result)[:500]}...")

            if fallback_data is not None:
                return fallback_data
            raise ValueError(f"Failed to parse {schema_class.__name__}: {e}")
