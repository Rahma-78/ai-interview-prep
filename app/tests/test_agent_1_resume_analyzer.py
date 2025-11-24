import asyncio
import logging
import os
import sys
import json
from pathlib import Path

# Add the current directory to sys.path to allow imports from app
sys.path.append(os.getcwd())

from crewai import Crew as CrewAI, Process
from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import file_text_extractor

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def main():
    resume_path = "app/Rahma Ashraf AlShafi'i.pdf"
    if not os.path.exists(resume_path):
        logger.error(f"Resume file not found at {resume_path}")
        return

    logger.info(f"Starting skill extraction verification with resume: {resume_path}")
    
    agents = InterviewPrepAgents()
    tasks = InterviewPrepTasks()
    
    tools = {"file_text_extractor": file_text_extractor}
    
    resume_analyzer = agents.resume_analyzer_agent(tools)
    skills_task = tasks.extract_skills_task(resume_analyzer, resume_path)
    
    crew = CrewAI(
        agents=[resume_analyzer],
        tasks=[skills_task],
        process=Process.sequential,
        verbose=True
    )
    
    try:
        result = await crew.kickoff_async()
        logger.info("Extraction completed.")
        
        # Check output file
        output_path = "app/tests/extracted_skills.json"
        if os.path.exists(output_path):
            with open(output_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"Extracted Skills: {json.dumps(data, indent=2)}")
        else:
            logger.error(f"{output_path} not found.")
            
    except Exception as e:
        logger.error(f"Error during verification: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
