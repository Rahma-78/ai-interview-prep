from backend.agents import InterviewPrepAgents
from backend.tasks import InterviewPrepTasks
from backend.tools import file_text_extractor, google_search_tool, smart_web_content_extractor, question_generator
import json
import asyncio
import time

class InterviewPrepCrew:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.agents = InterviewPrepAgents()
        # Tools are now functions/variables
        self.tools = {
            "file_text_extractor": file_text_extractor,
            "google_search_tool": google_search_tool,
            "smart_web_content_extractor": smart_web_content_extractor,
            "question_generator": question_generator
        }
        # InterviewPrepTasks no longer takes tools in __init__
        self.tasks = InterviewPrepTasks()

    async def run_async(self):
        """
        Run the entire pipeline asynchronously using CrewAI for all agents.
        This maintains consistency with the original CrewAI approach while providing async execution.
        """
        start_time = time.time()
        
        try:
            # Create all agents using CrewAI with async execution enabled
            resume_analyzer = self.agents.resume_analyzer_agent(self.tools)
            source_discoverer = self.agents.source_discoverer_agent(self.tools)
            question_generator_agent = self.agents.question_generator_agent(self.tools)
            
            # Define tasks for the full pipeline
            skills_task = self.tasks.extract_skills_task(resume_analyzer, self.file_path)
            search_task = self.tasks.search_sources_task(source_discoverer, "{extract_skills_task}")
            extract_task = self.tasks.extract_web_content_task(source_discoverer, urls_reference="{search_sources_task}", skill="{extract_skills_task}")
            question_task = self.tasks.generate_questions_task(question_generator_agent, "{extract_skills_task}", sources_content="{extract_web_content_task}")

            # Create the full crew with all agents
            from crewai import Crew, Process
            full_crew = Crew(
                agents=[resume_analyzer, source_discoverer, question_generator_agent],
                tasks=[skills_task, search_task, extract_task, question_task],
                process=Process.sequential,
                verbose=True,
                max_rpm=30,
                # Enable async mode for the crew
            )
            
            # Run the crew asynchronously
            result = await full_crew.kickoff_async()
            
            # Parse the result
            result_str = str(result)
            try:
                result_data = json.loads(result_str)
                skills = result_data.get("skills", [])
                
                # Format the result for the API
                all_interview_questions = []
                for skill in skills:
                    all_interview_questions.append({"skill": skill, "questions": []})
                
                total_time = time.time() - start_time
                print(f"✅ CrewAI processing completed in {total_time:.3f}s")
                print(f"   - Skills extracted: {len(skills)}")
                
                return all_interview_questions
                
            except json.JSONDecodeError as e:
                print(f"Error parsing CrewAI result: {e}")
                return [{"skill": "Unknown", "questions": [], "error": "Failed to parse CrewAI result"}]
            
        except Exception as e:
            print(f"Error in CrewAI async run: {e}")
            return [{"skill": "Unknown", "questions": [], "error": f"Error in CrewAI processing: {e}"}]
    
    def cleanup(self):
        """Clean up resources"""
        pass

    def run(self):
        """
        Synchronous version that uses async processing internally for better performance
        """
        # Run the async version in an event loop
        try:
            # Try to get the current event loop if we're in an async context
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're in a running async context, create a task
                return asyncio.create_task(self.run_async())
            else:
                # If no loop is running, run it directly
                return loop.run_until_complete(self.run_async())
        except RuntimeError:
            # No event loop exists, create one
            return asyncio.run(self.run_async())
