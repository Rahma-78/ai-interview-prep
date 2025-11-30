"""
Test script for the Question Generator Agent using the batch_question_generator tool.
Tests the full Agent -> Task -> Tool flow.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import List

from crewai import Crew, Process, Task

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.schemas.interview import AllSkillSources, AllInterviewQuestions, InterviewQuestions
from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import question_generator
from app.services.tools.helpers import clean_llm_json_output

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_question_generator_agent_flow():
    """
    Tests the Question Generator Agent with real input from discovered_sources.json.
    Verifies that the Agent correctly calls the question_generator tool for each skill concurrently.
    """
    logger.info("Starting Question Generator Agent Test (Concurrent Flow)...")

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
    
    tools_dict = {
        "question_generator": question_generator
    }
    
    # Create the agent once (stateless enough for this test)
    question_agent = agents.question_generator_agent(tools_dict)

    # 3. Define Helper for Single Task Execution
    async def run_single_skill_task(source):
        skill = source.skill
        # Context is now handled via file, so we don't need to extract it here
            
        logger.info(f"Creating task for skill: {skill}")
        
        # Create a specific task for this skill
        # Note: We manually construct the task description here because the helper 
        # in tasks.py is designed for the full pipeline (taking only agent).
        # But we want to test per-skill execution.
        
        description = (
            f"Generate insightful, non-coding interview questions for the skill: '{skill}'. "
            "You will find the context for this skill in 'app/data/context.json'. "
            "Use the 'question_generator' tool to generate questions for this specific skill. "
            "Pass ONLY the skill name to the tool."
        )
        
        task = Task(
            description=description,
            agent=question_agent,
            expected_output="A JSON string conforming to the InterviewQuestions schema.",
        )
        
        # Create a temporary Crew for this single task
        # Note: In a real app, you might add all tasks to one Crew, 
        # but for maximum control over "per-item" execution as requested, 
        # running parallel Crews or parallel Tasks is effective.
        # Here we use a Crew per task to isolate the execution context completely.
        crew = Crew(
            agents=[question_agent],
            tasks=[task],
            process=Process.sequential, # Sequential within the crew (1 task), but crews run in parallel
            verbose=True
        )
        
        try:
            # Kickoff async
            result = await crew.kickoff_async()
            
            # Parse result
            output_str = ""
            if hasattr(result, 'raw'):
                output_str = result.raw
            else:
                output_str = str(result)
                
            # Parse result
            output_str = ""
            if hasattr(result, 'raw'):
                output_str = result.raw
            else:
                output_str = str(result)
                
            # Use robust helper to extract JSON from Agent's "Final Answer" text
            cleaned_output = clean_llm_json_output(output_str)
            
            if not cleaned_output:
                 logger.error(f"Empty output from agent for {skill}")
                 logger.error(f"Raw output was: {output_str}")
                 return InterviewQuestions(skill=skill, questions=[f"Error: Empty agent output. Raw: {output_str[:100]}..."])

            try:
                output_data = json.loads(cleaned_output)
                return InterviewQuestions(**output_data)
            except json.JSONDecodeError as e:
                logger.error(f"JSON Decode Error for {skill}: {e}")
                logger.error(f"Raw Output: {output_str}")
                logger.error(f"Cleaned Output: {cleaned_output}")
                
                # Save failing output to file for debugging
                with open("debug_failed_output.txt", "a", encoding="utf-8") as f:
                    f.write(f"--- FAILURE FOR {skill} ---\n")
                    f.write(f"RAW:\n{output_str}\n")
                    f.write(f"CLEANED:\n{cleaned_output}\n")
                    f.write("-" * 50 + "\n")
                
                raise e
            
        except Exception as e:
            logger.error(f"Failed to generate questions for {skill}: {e}")
            return InterviewQuestions(skill=skill, questions=[f"Error: {str(e)}"])

    # 4. Run All Tasks Concurrently (in Batches of 3)
    logger.info("Kickoff Concurrent Execution (Batch Size: 3)...")
    start_time = asyncio.get_event_loop().time()
    
    # Create coroutines for all sources
    all_coroutines = [run_single_skill_task(source) for source in all_sources.all_sources]
    
    results = []
    chunk_size = 3
    
    for i in range(0, len(all_coroutines), chunk_size):
        chunk = all_coroutines[i:i + chunk_size]
        logger.info(f"Processing batch {i//chunk_size + 1} of {(len(all_coroutines) + chunk_size - 1) // chunk_size}...")
        
        # Run the current chunk concurrently
        chunk_results = await asyncio.gather(*chunk)
        results.extend(chunk_results)
        
        # Optional: Add a small delay between batches to be extra safe with rate limits
        if i + chunk_size < len(all_coroutines):
            await asyncio.sleep(2) 
    
    end_time = asyncio.get_event_loop().time()
    duration = end_time - start_time
    logger.info(f"Concurrent execution completed in {duration:.2f} seconds.")

    # 5. Aggregate and Validate Output
    try:
        final_output = AllInterviewQuestions(all_questions=list(results))
        
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
             logger.info(f"Skill: {item.skill}, Questions: {len(item.questions)}")
             
    except Exception as e:
        logger.error(f"Failed to aggregate results: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_question_generator_agent_flow())
