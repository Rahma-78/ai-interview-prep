from __future__ import annotations
import json
import logging
import time
from typing import Dict, List, Any, Callable, Awaitable, Optional
import asyncio
from pathlib import Path

from crewai import Crew as CrewAI, Process, Task

from app.schemas.interview import AllInterviewQuestions, AllSkillSources, SkillSources
from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import (
    file_text_extractor,
    grounded_source_discoverer,
    batch_question_generator,
)
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

    def __init__(self, file_path: str):
        """
        Initialize the InterviewPrepCrew with the path to the resume file.

        Args:
            file_path: Path to the resume file to be processed
        """
        self.file_path = file_path
        self.agents = InterviewPrepAgents()
        self.tools = {
            "file_text_extractor": file_text_extractor,
            "grounded_source_discoverer": grounded_source_discoverer,
            "batch_question_generator": batch_question_generator,
        }
        self.tasks = InterviewPrepTasks()
        self.logger = logger

    def _create_tasks_with_dependencies(self) -> List[Task]:
        """
        Create all tasks with proper dependencies between them.

        Returns:
            List of tasks with their dependencies properly configured
        """
        # Create agents - each agent is specialized for a specific role
        resume_analyzer = self.agents.resume_analyzer_agent(self.tools)
        source_discoverer = self.agents.source_discoverer_agent(self.tools)
        question_generator_agent = self.agents.question_generator_agent(self.tools)

        # Create the first task - extract skills from resume
        # This task processes the resume file and extracts technical skills
        skills_task = self.tasks.extract_skills_task(resume_analyzer, self.file_path)

        # Create the second task - discover sources based on skills
        # This task uses the skills extracted from the previous task to find relevant sources
        # Note: We do not pass 'skills' explicitly; CrewAI passes the output of skills_task via context.
        discover_task = self.tasks.discover_and_extract_content_task(
            source_discoverer
        )

        # Create the third task - generate questions based on skills and sources
        # This task uses both the extracted skills and discovered sources to generate questions
        question_task = self.tasks.generate_questions_task(
            question_generator_agent
        )

        # Set up task dependencies - CrewAI will automatically pass outputs
        # This creates a pipeline: skills_task → discover_task → question_task
        discover_task.context = [skills_task]
        question_task.context = [skills_task, discover_task]

        return [skills_task, discover_task, question_task]

    def _format_results(self, crew_result) -> List[Dict[str, Any]]:
        """
        Format and validate the crew results.

        Args:
            crew_result: The result from the crew execution

        Returns:
            Formatted list of skills and questions

        Raises:
            json.JSONDecodeError: If the result cannot be parsed as JSON
            Exception: If the result doesn't match the expected schema
        """
        # The crew_result object's .raw attribute contains the raw JSON string output
        result_data = json.loads(crew_result.raw)
        parsed_result = AllInterviewQuestions(**result_data)

        formatted_results = []
        for item in parsed_result.all_questions:
            formatted_results.append({
                "skill": item.skill,
                "questions": item.questions
            })

        return formatted_results

    @log_async_execution_time
    async def run_async(self, progress_callback: Optional[Callable[[str], Awaitable[None]]] = None) -> List[Dict[str, Any]]:
        """
        Run the pipeline with parallel processing for each skill.
        """
        start_time = time.time()
        
        try:
            # 1. Extract Skills (Sequential)
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
            
            skills_result = await skills_crew.kickoff_async()
            
            # Parse skills from result
            try:
                skills_data = json.loads(skills_result.raw)
                skills_list = skills_data.get("skills", [])
            except Exception as e:
                self.logger.error(f"Failed to parse skills output: {e}")
                return []

            if not skills_list:
                self.logger.warning("No skills extracted.")
                return []

            # 2. Process Skills in Parallel
            if progress_callback: await progress_callback("step_2")
            
            # Import tools directly to use their logic
            from app.services.tools.source_discovery import discover_sources
            from app.services.tools.tools import _generate_single_skill_questions
            
            # Containers for accumulated data to save to files
            accumulated_sources: List[SkillSources] = []
            accumulated_questions: List[Any] = [] # List[InterviewQuestions]

            async def process_skill(skill: str):
                try:
                    # A. Discover Sources
                    # We call the underlying logic function directly.
                    # discover_sources is async and returns List[Dict]
                    sources_list = await discover_sources([skill])
                    
                    # Extract context string from the sources and build SkillSources object
                    context = ""
                    for source in sources_list:
                         if "extracted_content" in source:
                             # extracted_content is a list of strings (paragraphs)
                             context += "\n".join(source["extracted_content"])
                             
                             # Add to accumulated sources
                             accumulated_sources.append(
                                 SkillSources(
                                     skill=skill,
                                     extracted_content=source["extracted_content"]
                                 )
                             )
                    
                    # B. Generate Questions
                    # We use the helper function directly.
                    # _generate_single_skill_questions is async and returns InterviewQuestions object
                    questions_obj = await _generate_single_skill_questions(skill, context)
                    
                    # Add to accumulated questions
                    accumulated_questions.append(questions_obj)
                    
                    # C. Stream Result
                    result_dict = {
                        "skill": questions_obj.skill,
                        "questions": questions_obj.questions
                    }
                    
                    # Send specific update via callback
                    if progress_callback:
                        await progress_callback(f"data:{json.dumps(result_dict)}")
                        
                    return result_dict
                    
                except Exception as e:
                    self.logger.error(f"Error processing skill {skill}: {e}")
                    return {"skill": skill, "questions": [], "error": str(e)}


        except Exception as e:
            self.logger.error(f"Error in run_async: {e}", exc_info=True)
            return []