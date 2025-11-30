from __future__ import annotations # Added for postponed evaluation of type annotations
import json
import logging
import time
from typing import Dict, List, Any

from crewai import Crew as CrewAI, Process, Task

from app.schemas.interview import AllInterviewQuestions
from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import (
    file_text_extractor,
    grounded_source_discoverer,
    question_generator,
   
)
from app.core.config import settings # Import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
            "question_generator": question_generator,
        }
        self.tasks = InterviewPrepTasks()
        self.logger = logging.getLogger(__name__)

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

    async def run_async(self) -> List[Dict[str, Any]]:
        """
        Run the entire pipeline asynchronously using CrewAI's sequential execution.
        This implementation uses a single crew with properly defined task dependencies.

        Returns:
            List of dictionaries containing skills and their associated interview questions
        """
        start_time = time.time()

        try:
            # Create all tasks with their dependencies
            tasks = self._create_tasks_with_dependencies()

            # Create a single crew with all agents and tasks
            agents = [task.agent for task in tasks if task.agent is not None]
            crew = CrewAI(
                agents=agents,
                tasks=tasks,
                process=Process.sequential,
                verbose=settings.DEBUG_MODE,
                share_crew=False)
            

            # Execute the crew
            crew_result = await crew.kickoff_async()

            # Process and format the results
            formatted_results = self._format_results(crew_result)

            total_time = time.time() - start_time
            self.logger.info(f"CrewAI processing completed in {total_time:.3f}s")
            self.logger.info(f"Total skills with questions: {len(formatted_results)}")

            return formatted_results

        except json.JSONDecodeError as e:
            self.logger.error(f"Error parsing CrewAI result as JSON: {e}", exc_info=True)
            return [{"skill": "Unknown", "questions": [], "error": f"Failed to parse CrewAI result as JSON: {e}"}]
        except Exception as e:
            self.logger.error(f"Error in CrewAI async run: {e}", exc_info=True)
            return [{"skill": "Unknown", "questions": [], "error": f"Error in CrewAI processing: {e}"}]