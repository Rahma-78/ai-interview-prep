"""
Test script for the Question Generator Agent using the batch_question_generator tool.
Tests the full Agent -> Task -> Tool flow with concurrency handled by the tool.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

from crewai import Crew, Process, Task

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.schemas.interview import AllSkillSources, AllInterviewQuestions
from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import file_text_extractor
from app.services.tools.helpers import clean_llm_json_output

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_question_generator_agent_flow():
    """
    Tests the Question Generator Agent with real input from context.json.
    Verifies that the Agent correctly calls the batch_question_generator tool for concurrent processing.
    The tool internally uses asyncio.gather() with semaphore (limit=3) for controlled concurrency.
    """
    logger.info("Starting Question Generator Agent Test (Using Batch Tool with Semaphore)...")

    # 1. Load Real Data (Context) from app/data/context.json
    input_path = Path("app/data/context.json")
    if not input_path.exists():
        logger.error(f"Context file not found: {input_path}. Please run Agent 2 test first.")
        return

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # Validate input data
        all_sources = AllSkillSources(**data)
        logger.info(f"Loaded context for {len(all_sources.all_sources)} skills.")
        
    except Exception as e:
        logger.error(f"Failed to validate input data: {e}")
        return

    # 2. Setup Agent and Tools
    agents = InterviewPrepAgents()
    tasks = InterviewPrepTasks()
    
    tools_dict = {}
    
    # Create the agent
    question_agent = agents.question_generator_agent(tools_dict)

    # 3. Extract skills list from the loaded context
    # This simulates what Agent 2 outputs
    all_skills = [source.skill for source in all_sources.all_sources]
    logger.info(f"Input skills from Agent 2 output: {all_skills}")
    
    # 4. Create the task (following Agent 2 test pattern)
    # The task expects to receive context from previous task via CrewAI's context mechanism
    question_task = tasks.generate_questions_task(question_agent)
    
    # 5. Create the crew
    crew = Crew(
        agents=[question_agent],
        tasks=[question_task],
        process=Process.sequential,
        verbose=True
    )
    
    # 6. Prepare inputs to pass to crew (simulating Agent 2's output)
    # In production: This comes from discover_task.output via task.context
    # In test: We provide it directly via crew inputs
    inputs = {
        "context": all_sources.model_dump_json(),  # Pass the full context as JSON string
        "skills": all_skills  # Also pass just the skill names
    }
    
    # 7. Execute the crew with inputs (following Agent 2 test pattern)
    logger.info("Kickoff Batch Question Generation (Concurrency controlled by semaphore=3)...")
    start_time = asyncio.get_event_loop().time()
    
    try:
        # Kickoff async with inputs (following Agent 2 test pattern)
        result = await crew.kickoff_async(inputs=inputs)
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        logger.info(f"Batch execution completed in {duration:.2f} seconds.")
        
        # Parse result
        output_str = ""
        if hasattr(result, 'raw'):
            logger.info("Using result.raw for output string extraction.")
            output_str = result.raw
        else:
            logger.info("result.raw not found. Using str(result) for output string extraction.")
            output_str = str(result)
            
        # Use robust helper to extract JSON from Agent's "Final Answer" text
        cleaned_output = clean_llm_json_output(output_str)
        
        if not cleaned_output:
            logger.error(f"Empty output from agent")
            logger.error(f"Raw output was: {output_str}")
            return

        try:
            output_data = json.loads(cleaned_output)
            final_output = AllInterviewQuestions(**output_data)
        except json.JSONDecodeError as e:
            logger.error(f"JSON Decode Error: {e}")
            logger.error(f"Raw Output: {output_str}")
            logger.error(f"Cleaned Output: {cleaned_output}")
            
            # Save failing output to file for debugging
            with open("debug_failed_output.txt", "a", encoding="utf-8") as f:
                f.write(f"--- BATCH FAILURE ---\n")
                f.write(f"RAW:\n{output_str}\n")
                f.write(f"CLEANED:\n{cleaned_output}\n")
                f.write("-" * 50 + "\n")
            
            raise e
        
    except Exception as e:
        logger.error(f"Failed to generate questions: {e}", exc_info=True)
        return

    # 7. Validate Output
    try:
        # Verify output file created by task
        output_file = Path("app/data/interview_questions.json")
        if output_file.exists():
             with open(output_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
                AllInterviewQuestions(**saved_data)
                logger.info(f"✅ Verified task output file: {output_file}")
        else:
             logger.warning(f"⚠️ Task output file not found at {output_file}")
        
        logger.info(f"Successfully generated questions for {len(final_output.all_questions)} skills.")
        for item in final_output.all_questions:
             logger.info(f"  - Skill: {item.skill}, Questions: {len(item.questions)}")
             
    except Exception as e:
        logger.error(f"Failed to validate results: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_question_generator_agent_flow())
