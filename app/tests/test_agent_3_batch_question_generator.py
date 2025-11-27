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

from crewai import Crew, Process

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.schemas.interview import AllSkillSources, AllInterviewQuestions
from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import question_generator

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_question_generator_agent_flow():
    """
    Tests the Question Generator Agent with real input from discovered_sources.json.
    Verifies that the Agent correctly calls the batch_question_generator tool.
    """
    logger.info("Starting Question Generator Agent Test (Full Flow)...")

    # 1. Load Real Data (Context)
    input_path = Path(__file__).parent / "discovered_sources.json"
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Transform to match AllSkillSources schema if needed
    if "skills" in data:
        data["all_sources"] = data.pop("skills")
        
    # Fix schema mismatches in extracted_content
    # The JSON file has strings/dicts, but schema expects List[str]
    for source in data.get("all_sources", []):
        if "extracted_content" in source:
            content = source["extracted_content"]
            # Flatten structured content into a single string summary
            summary_parts = []
            for field in ["core_concepts", "problem_solving", "best_practices", "challenges", "terminology"]:
                if field in content:
                    val = content[field]
                    if isinstance(val, list):
                        val_str = ", ".join(val)
                    elif isinstance(val, dict):
                        val_str = ", ".join([f"{k}: {v}" for k, v in val.items()])
                    else:
                        val_str = str(val)
                    summary_parts.append(f"**{field.replace('_', ' ').title()}**: {val_str}")
            
            source["extracted_content"] = "\n\n".join(summary_parts)

    
    try:
        # Validate and serialize to JSON string (simulating Task output from previous step)
        all_sources = AllSkillSources(**data)
        context_json = all_sources.json()
        logger.info(f"Loaded context for {len(all_sources.all_sources)} skills.")
    except Exception as e:
        logger.error(f"Failed to validate input data: {e}")
        return

    # 2. Setup Agent and Task
    agents = InterviewPrepAgents()
    tasks = InterviewPrepTasks()
    
    # We need to pass the tool to the agent. 
    # The agents.py method expects a dict of tools.
    tools_dict = {
        "question_generator": question_generator
    }
    
    question_agent = agents.question_generator_agent(tools_dict)
    
    # Create the task. 
    # Note: In a real Crew run, 'context' usually comes from previous tasks. 
    # Here we will manually inject it into the task description or use a mock context.
    # However, the Task definition in tasks.py expects 'context' arg to format the description.
    # But CrewAI tasks usually take context *dynamically*.
    # Let's look at tasks.py: generate_questions_task(self, agent, context=None)
    # It uses the context arg to format the description string.
    
    # We will pass the JSON string as the 'context' argument to the task creator, 
    # effectively baking it into the description for this standalone test.
    # Alternatively, we can rely on CrewAI's context passing if we mocked a previous task, 
    # but baking it in is simpler for a unit test of one agent.
    
    # Wait, the tool expects `all_skill_sources_json` as an argument.
    # The Agent needs to decide to call the tool and pass this JSON.
    # If we put the JSON in the description, the Agent (LLM) has to read it and pass it to the tool.
    # Given the size of the JSON, this might be heavy for the Agent's prompt context window if it's huge.
    # But `batch_question_generator` takes a string.
    
    # Let's try passing it as the context description.
    question_task = tasks.generate_questions_task(
        agent=question_agent,
        context=context_json 
    )
    
    # 3. Create Crew and Run
    crew = Crew(
        agents=[question_agent],
        tasks=[question_task],
        process=Process.sequential,
        verbose=True
    )

    logger.info("Kickoff Crew...")
    start_time = asyncio.get_event_loop().time()
    
    try:
        # kickoff_async is better for async tools
        result = await crew.kickoff_async()
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        logger.info(f"Crew execution completed in {duration:.2f} seconds.")

        # 4. Validate Output
        logger.info("Raw Crew Output:")
        # Crew output might be a string or object depending on version
        output_str = str(result)
        # logger.info(output_str[:500] + "...") # Print first 500 chars

        # Try parsing the result
        # The task enforces output_json=AllInterviewQuestions, so result should be that Pydantic model or dict
        # Or if it returns raw string, it should be JSON.
        
        # In recent CrewAI, result.raw is the string.
        if hasattr(result, 'raw'):
            output_str = result.raw
        
        # Clean up potential markdown blocks
        if output_str.startswith("```json"):
            output_str = output_str[7:-3]
        elif output_str.startswith("```"):
            output_str = output_str[3:-3]
            
        output_data = json.loads(output_str)
        final_output = AllInterviewQuestions(**output_data)
        
        logger.info(f"Successfully generated questions for {len(final_output.all_questions)} skills.")
        for item in final_output.all_questions:
             logger.info(f"Skill: {item.skill}, Questions: {len(item.questions)}")

    except Exception as e:
        logger.error(f"Crew execution failed: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(test_question_generator_agent_flow())
