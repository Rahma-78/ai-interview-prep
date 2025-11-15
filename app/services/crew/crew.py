from __future__ import annotations # Added for postponed evaluation of type annotations
import asyncio
import json
import logging
import time

from crewai import Crew, Process # Moved import to top

from app.schemas.interview import AllInterviewQuestions
from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import (
    file_text_extractor,
    google_search_tool,
    question_generator,
    smart_web_content_extractor,
)
from app.core.config import settings # Import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class InterviewPrepCrew:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.agents = InterviewPrepAgents()
        self.tools = {
            "file_text_extractor": file_text_extractor,
            "google_search_tool": google_search_tool,
            "smart_web_content_extractor": smart_web_content_extractor,
            "question_generator": question_generator
        }
        self.tasks = InterviewPrepTasks()

    async def run_async(self):
        """
        Run the entire pipeline asynchronously using CrewAI for all agents.
        This maintains consistency with the original CrewAI approach while providing async execution.
        """
        start_time = time.time()
        
        try:
            resume_analyzer = self.agents.resume_analyzer_agent(self.tools)
            source_discoverer = self.agents.source_discoverer_agent(self.tools)
            question_generator_agent = self.agents.question_generator_agent(self.tools)
            
            skills_task = self.tasks.extract_skills_task(resume_analyzer, self.file_path)
            search_task = self.tasks.search_sources_task(source_discoverer, "{extract_skills_task}")
            extract_task = self.tasks.extract_web_content_task(source_discoverer, urls_reference="{search_sources_task}", skill="{extract_skills_task}")
            question_task = self.tasks.generate_questions_task(question_generator_agent, "{extract_skills_task}", sources_content="{extract_web_content_task}")

            full_crew = Crew(
                agents=[resume_analyzer, source_discoverer, question_generator_agent],
                tasks=[skills_task, search_task, extract_task, question_task],
                process=Process.sequential,
                verbose=settings.DEBUG_MODE, # Use DEBUG_MODE for verbose output
            )
            
            crew_result = await full_crew.kickoff_async()
            
            try:
                # The crew_result object's .raw attribute contains the raw JSON string output
                result_data = json.loads(crew_result.raw)
                parsed_result = AllInterviewQuestions(**result_data)
                
                formatted_results = []
                for item in parsed_result.all_questions:
                    formatted_results.append({
                        "skill": item.skill,
                        "questions": item.questions
                    })
                
                total_time = time.time() - start_time
                logging.info(f"CrewAI processing completed in {total_time:.3f}s")
                logging.info(f"Total skills with questions: {len(formatted_results)}")
                
                return formatted_results
                
            except json.JSONDecodeError as e:
                logging.error(f"Error parsing CrewAI result as JSON: {e}", exc_info=True)
                return [{"skill": "Unknown", "questions": [], "error": f"Failed to parse CrewAI result as JSON: {e}"}]
            except Exception as e:
                logging.error(f"Error validating CrewAI result against schema: {e}", exc_info=True)
                return [{"skill": "Unknown", "questions": [], "error": f"Failed to validate CrewAI result: {e}"}]
            
        except Exception as e:
            logging.error(f"Error in CrewAI async run: {e}", exc_info=True)
            return [{"skill": "Unknown", "questions": [], "error": f"Error in CrewAI processing: {e}"}]
