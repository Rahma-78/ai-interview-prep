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
from app.core.logger import setup_logger, log_async_execution_time

# Configure logging
logger = setup_logger()

class InterviewPrepCrew:
    """
    A professional implementation of an interview preparation pipeline using CrewAI.
    This class orchestrates the process of extracting skills from a resume,
    finding relevant sources, and generating interview questions.
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
    async def run_async(self, progress_callback: Optional[Callable[[str], Awaitable[None]]] = None) -> List[Dict[str, Any]]:
        """
        Run the pipeline with parallel processing for batches of skills using dedicated mini-crews.
        """
        start_time = time.time()
        
        try:
            # ---------------------------------------------------------
            # 1. Extract Skills (Sequential)
            # ---------------------------------------------------------
            if progress_callback: await progress_callback("step_1")
            
            resume_analyzer = self.agents.resume_analyzer_agent(self.tools)
            skills_task = self.tasks.extract_skills_task(resume_analyzer, self.file_path)
            
            # Execute skills extraction directly
            skills_crew = CrewAI(
                agents=[resume_analyzer],
                tasks=[skills_task],
                process=Process.sequential,
                verbose=settings.DEBUG_MODE
            )
            
            # Note: inputs is empty here assuming file_path is hardcoded into the task description
            # If your task uses {file_path}, pass inputs={'file_path': self.file_path}
            skills_result = await skills_crew.kickoff_async()
            
            # Parse skills using Pydantic validation
            try:
                # Try to get Pydantic object directly if supported by CrewAI version
                if hasattr(skills_result, 'pydantic') and skills_result.pydantic:
                     extracted_skills = skills_result.pydantic
                elif hasattr(skills_result, 'json_dict') and skills_result.json_dict:
                     extracted_skills = ExtractedSkills(**skills_result.json_dict)
                else:
                     # Fallback to parsing raw JSON
                     cleaned_json = clean_llm_json_output(skills_result.raw)
                     extracted_skills = ExtractedSkills.model_validate_json(cleaned_json)
                     
                skills_list = extracted_skills.skills
            except Exception as e:
                self.logger.error(f"Failed to parse skills output: {e}")
                return []

            if not skills_list:
                self.logger.warning("No skills extracted.")
                return []

            # ---------------------------------------------------------
            # 2. Process Skills in Batches (Mini-Crews)
            # ---------------------------------------------------------
            if progress_callback: await progress_callback("step_2")
            
            # Chunk skills into batches of 3 to optimize source discovery
            BATCH_SIZE = 3
            skill_batches = [skills_list[i:i + BATCH_SIZE] for i in range(0, len(skills_list), BATCH_SIZE)]
            
            # Semaphore to limit concurrent LLM requests (Prevents 429 Rate Limit Errors)
            # Adjust '3' based on your API tier limits.
            sem = asyncio.Semaphore(3)

            async def process_batch_crew(batch_skills: List[str]):
                async with sem:
                    try:
                        # Create dedicated agents and tasks for this batch
                        source_agent = self.agents.source_discoverer_agent(self.tools)
                        question_agent = self.agents.question_generator_agent(self.tools)
                        
                        # Tasks for this batch
                        discover_task = self.tasks.discover_sources_task(source_agent, batch_skills)
                        question_task = self.tasks.generate_questions_task(question_agent)
                        
                        # Set context dependency (Output of discover flows into question)
                        question_task.context = [discover_task]

                        # Create a mini-crew for this batch
                        batch_crew = CrewAI(
                            agents=[source_agent, question_agent],
                            tasks=[discover_task, question_task],
                            process=Process.sequential,
                            verbose=settings.DEBUG_MODE
                        )
                        
                        # Format input as a string to ensure LLM understands it clearly
                        formatted_skills = ", ".join(batch_skills)
                        
                        result = await batch_crew.kickoff_async(inputs={"skills": formatted_skills})
                        
                        # Parse result using Pydantic
                        if hasattr(result, 'pydantic') and result.pydantic:
                            questions_obj = result.pydantic
                        elif hasattr(result, 'json_dict') and result.json_dict:
                            questions_obj = AllInterviewQuestions(**result.json_dict)
                        else:
                            # Use cleaner before parsing raw JSON
                            cleaned_json = clean_llm_json_output(result.raw)
                            questions_obj = AllInterviewQuestions.model_validate_json(cleaned_json)
                        
                        # Format results for this batch
                        batch_results = []
                        
                        # Assuming 'all_questions' is a list in your Pydantic model
                        if hasattr(questions_obj, 'all_questions'):
                            for item in questions_obj.all_questions:
                                result_dict = {
                                    "skill": item.skill,
                                    "questions": item.questions
                                }
                                batch_results.append(result_dict)
                                
                                if progress_callback:
                                    # Send specific update via callback
                                    await progress_callback(f"data:{json.dumps(result_dict)}")
                        
                        return batch_results
                        
                    except Exception as e:
                        self.logger.error(f"Error processing batch {batch_skills}: {e}")
                        # Return error structure so we don't lose data for other batches
                        return [{"skill": skill, "questions": [], "error": str(e)} for skill in batch_skills]

            # Run all mini-crews in parallel (controlled by Semaphore)
            results_nested = await asyncio.gather(*[process_batch_crew(batch) for batch in skill_batches])
            
            # Flatten results
            final_results = [item for sublist in results_nested for item in sublist]
            
            return final_results

        except Exception as e:
            self.logger.error(f"Error in run_async: {e}", exc_info=True)
            return []