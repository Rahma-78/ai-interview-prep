"""Main interview preparation crew orchestration."""

from __future__ import annotations
import json
import asyncio
from typing import Dict, List, Any, Callable, Awaitable, Optional
from datetime import datetime

from crewai import Crew as CrewAI, Process

from app.schemas.interview import (
    AllInterviewQuestions, 
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
from app.core.config import settings
from app.core.logger import setup_logger, log_async_execution_time

# Import our modular components
from .history_manager import HistoryManager
from .file_validator import FileValidator
from .run_metadata import RunMetadata

logger = setup_logger()


class InterviewPrepCrew:
    """
    Orchestrates interview preparation pipeline using CrewAI.
    
    Architecture:
    - Uses composition over inheritance
    - Delegates responsibilities to specialized classes
    - Follows SOLID principles
    - Each method has single, clear purpose
    
    Dependencies (injected via composition):
    - HistoryManager: Manages data persistence
    - FileValidator: Validates input files
    - RunMetadata: Tracks run statistics
    - InterviewPrepAgents: Provides AI agents
    - InterviewPrepTasks: Defines tasks
    """

    def __init__(self, file_path: str, validate: bool = True):
        """
        Initialize the crew.

        Args:
            file_path: Path to resume file
            validate: Whether to validate file immediately
        """
        self.file_path = file_path
        self.logger = logger
        
        # Inject dependencies (Dependency Injection pattern)
        self.validator = FileValidator(logger)
        self.history = HistoryManager(logger=logger)
        self.agents = InterviewPrepAgents()
        self.tasks = InterviewPrepTasks()
        self.tools = {
            "file_text_extractor": file_text_extractor,
            "grounded_source_discoverer": grounded_source_discoverer,
        }
        
        # Validate if requested
        if validate:
            self.validator.validate(file_path)

    async def _extract_skills(
        self, 
        metadata: RunMetadata,
        progress_callback: Optional[Callable[[str], Awaitable[None]]]
    ) -> List[str]:
        """
        Extract skills from resume.
        
        Args:
            metadata: Run metadata to update
            progress_callback: Optional progress callback
            
        Returns:
            List of extracted skills
            
        Raises:
            Exception: If skill extraction fails
        """
        if progress_callback:
            await progress_callback("step_1_extraction")
        
        # Create crew
        agent = self.agents.resume_analyzer_agent(self.tools)
        task = self.tasks.extract_skills_task(agent, self.file_path)
        
        crew = CrewAI(
            agents=[agent],
            tasks=[task],
            process=Process.sequential,
            verbose=settings.DEBUG_MODE
        )
        
        # Execute
        result = await crew.kickoff_async()
        
        # Parse and validate
        try:
            extracted = ExtractedSkills(**result.json_dict)
            skills_list = extracted.skills
            
            if not skills_list:
                raise ValueError("No skills extracted")
            
            metadata.skill_count = len(skills_list)
            self.logger.info(f"Extracted {len(skills_list)} skills: {skills_list}")
            
            # Save to history
            self.history.save(extracted.dict(), "extracted_skills.json", metadata.run_id)
            
            if progress_callback:
                await progress_callback(f"step_1_complete:{len(skills_list)}")
            
            return skills_list
            
        except Exception as e:
            self.logger.error(f"Failed to parse skills: {e}")
            metadata.add_error("extraction", str(e))
            metadata.mark_failed()
            raise

    async def _process_batch(
        self,
        batch_skills: List[str],
        batch_num: int,
        total_batches: int,
        semaphore: asyncio.Semaphore,
        metadata: RunMetadata,
        progress_callback: Optional[Callable[[str], Awaitable[None]]]
    ) -> List[Dict[str, Any]]:
        """
        Process a single batch of skills.
        
        Args:
            batch_skills: Skills in this batch
            batch_num: Batch number (0-indexed)
            total_batches: Total number of batches
            semaphore: Concurrency control semaphore
            metadata: Run metadata to update
            progress_callback: Optional progress callback
            
        Returns:
            List of results for each skill in batch
        """
        async with semaphore:
            self.logger.info(f"Batch {batch_num + 1}/{total_batches}: {batch_skills}")
            
            try:
                # Create agents and tasks
                source_agent = self.agents.source_discoverer_agent(self.tools)
                question_agent = self.agents.question_generator_agent(self.tools)
                
                discover_task = self.tasks.discover_sources_task(source_agent, batch_skills)
                question_task = self.tasks.generate_questions_task(question_agent)
                question_task.context = [discover_task]
                
                # Execute batch crew
                batch_crew = CrewAI(
                    agents=[source_agent, question_agent],
                    tasks=[discover_task, question_task],
                    process=Process.sequential,
                    verbose=settings.DEBUG_MODE
                )
                
                result = await batch_crew.kickoff_async(inputs={"skills": batch_skills})
                
                # Parse result
                output_str = result.raw if hasattr(result, 'raw') else str(result)
                cleaned_output = clean_llm_json_output(output_str)
                
                if not cleaned_output:
                    raise ValueError("Empty output from agent")
                
                output_data = json.loads(cleaned_output)
                questions_obj = AllInterviewQuestions(**output_data)
                
                # Stream results immediately
                batch_results = []
                for item in questions_obj.all_questions:
                    result_dict = {
                        "skill": item.skill,
                        "questions": item.questions
                    }
                    batch_results.append(result_dict)
                    
                    # IMMEDIATE streaming - user sees results right away
                    if progress_callback:
                        await progress_callback(f"data:{json.dumps(result_dict)}")
                
                metadata.increment_success()
                self.logger.info(f"Batch {batch_num + 1} completed: {len(batch_results)} skills")
                
                if progress_callback:
                    await progress_callback(f"step_2_batch_complete:{batch_num + 1}")
                
                return batch_results
                
            except Exception as e:
                self.logger.error(f"Batch {batch_num + 1} error: {e}", exc_info=True)
                metadata.increment_failure()
                metadata.add_error(f"batch_{batch_num + 1}", str(e), batch_skills)
                return [{"skill": skill, "questions": [], "error": str(e)} for skill in batch_skills]

    async def _process_batches(
        self,
        skills: List[str],
        metadata: RunMetadata,
        progress_callback: Optional[Callable[[str], Awaitable[None]]]
    ) -> List[Dict[str, Any]]:
        """
        Process all skill batches in parallel.
        
        Args:
            skills: List of all skills to process
            metadata: Run metadata to update
            progress_callback: Optional progress callback
            
        Returns:
            Flattened list of all results
        """
        # Create batches
        batches = [
            skills[i:i + settings.BATCH_SIZE] 
            for i in range(0, len(skills), settings.BATCH_SIZE)
        ]
        metadata.batch_count = len(batches)
        
        self.logger.info(
            f"Processing {len(skills)} skills in {len(batches)} batches "
            f"(batch_size={settings.BATCH_SIZE}, max_concurrent={settings.MAX_CONCURRENT_BATCHES})"
        )
        
        if progress_callback:
            await progress_callback(f"step_2_batch_start:0,{len(batches)}")
        
        # Process batches with semaphore for concurrency control
        semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_BATCHES)
        
        tasks = [
            self._process_batch(batch, idx, len(batches), semaphore, metadata, progress_callback)
            for idx, batch in enumerate(batches)
        ]
        
        results_nested = await asyncio.gather(*tasks)
        
        # Flatten results
        return [item for sublist in results_nested for item in sublist]

    @log_async_execution_time
    async def run_async(
        self, 
        progress_callback: Optional[Callable[[str], Awaitable[None]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Run the interview preparation pipeline.
        
        Pipeline stages:
        1. Validation & Cleanup
        2. Skill Extraction
        3. Batch Processing (source discovery + question generation)
        4. Finalization & Save
        
        Args:
            progress_callback: Optional callback for progress updates
            
        Returns:
            List of interview questions per skill
        """
        # Initialize run
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        metadata = RunMetadata(run_id)
        
        try:
            # Step 0: Validation & Cleanup
            self.validator.validate(self.file_path)
            self.history.clear_all()
            
            if progress_callback:
                await progress_callback("step_0_validation")
            
            # Step 1: Extract Skills
            skills = await self._extract_skills(metadata, progress_callback)
            
            # Step 2: Process Batches
            results = await self._process_batches(skills, metadata, progress_callback)
            
            # Step 3: Finalization
            if progress_callback:
                await progress_callback("step_3_finalization")
            
            # Save final results
            all_questions = AllInterviewQuestions(
                all_questions=[
                    InterviewQuestions(skill=r["skill"], questions=r.get("questions", []))
                    for r in results if "skill" in r
                ]
            )
            
            self.history.save(all_questions.dict(), "interview_questions.json", run_id)
            
            # Save metadata
            metadata.mark_success()
            self.history.save(metadata.to_dict(), "run_metadata.json", run_id)
            
            if progress_callback:
                await progress_callback("step_3_complete")
            
            self.logger.info(
                f"Pipeline completed: {metadata.batches_succeeded}/{metadata.batch_count} batches succeeded, "
                f"{metadata.batches_failed} failed, duration: {metadata.to_dict()['duration_seconds']}s"
            )
            
            return results
            
        except Exception as e:
            self.logger.error(f"Fatal error: {e}", exc_info=True)
            metadata.add_error("pipeline", str(e))
            metadata.mark_failed()
            
            # Save error metadata
            self.history.save(metadata.to_dict(), "run_metadata.json", run_id)
            
            return []
