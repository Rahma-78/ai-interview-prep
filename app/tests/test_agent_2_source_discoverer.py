
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from crewai import Crew as CrewAI, Process

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import grounded_source_discoverer
from app.schemas.interview import AllSkillSources
from app.core.config import settings

# Configure logging for tests
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


async def test_source_discoverer_agent(skills_from_agent1: list):
    """
    Test the Source Discoverer Agent.
    Takes structured skill list from Agent 1 (JSON input).
    
    Returns clean JSON with skills and their sources (URL + content).
    
    Args:
        skills_from_agent1: List of skills extracted from Agent 1
    
    Returns:
        dict: Clean format with skills mapped to sources
    """
    
    if not skills_from_agent1 or len(skills_from_agent1) == 0:
        logging.error("Error: No skills provided from Agent 1")
        return None
    
    logging.info("=" * 80)
    logging.info("SOURCE DISCOVERER AGENT")
    logging.info("=" * 80)
    logging.info(f"Input skills: {len(skills_from_agent1)}")
    
    agents = InterviewPrepAgents()
    tasks = InterviewPrepTasks()
    
    # Tool configuration must match the agent's requirements
    tools = {
        "grounded_source_discoverer": grounded_source_discoverer
    }
    
    # Create agent with proper tool registration
    source_discoverer = agents.source_discoverer_agent(tools)
    
    logging.info("=" * 80)
    logging.info("SEARCHING FOR RESOURCES (BATCHED)")
    logging.info("=" * 80)

    # Create a single task for all skills (Batching Strategy)
    # Note: We do not pass 'skills' explicitly here if the task definition relies on context,
    # but since we are running this in isolation without the previous task's output in context,
    # we might need to manually inject the context or modify the task to accept input.
    # However, the task definition in tasks.py was updated to be generic.
    # In a real Crew run, the output of the previous task is passed.
    # Here, we can simulate the previous task's output or just pass the skills if the tool allows.
    
    # Wait, the task definition in tasks.py is:
    # def discover_and_extract_content_task(self, agent: Agent) -> Task:
    #    description="... skills extracted in the previous task ..."
    
    # Since we are testing in isolation, we need to ensure the agent gets the skills.
    # CrewAI agents can receive input via the `inputs` argument in `kickoff`.
    
    # Create a single task for all skills (Batching Strategy)
    # We pass the skills explicitly to the task description for the test environment
    discover_task = tasks.discover_and_extract_content_task(source_discoverer, skills=skills_from_agent1)
    
    search_crew = CrewAI(
        agents=[source_discoverer],
        tasks=[discover_task],
        process=Process.sequential,
        verbose=True
    )
    
    # Pass the skills as input to the crew, simulating the output of the previous task
    # The agent/tool needs to know the skills.
    # The tool `grounded_source_discoverer` takes `skills: List[str]`.
    # CrewAI will try to map the input to the tool arguments.
    
    inputs = {"skills": skills_from_agent1}
    
    try:
        # Use kickoff_async for async agents
        search_result = await search_crew.kickoff_async(inputs=inputs)
        
        logging.info("Search completed.")
        
        # Parse the result
        # Parse the result
        if hasattr(search_result, 'raw'):
            raw_output = search_result.raw
            # Strip markdown code blocks if present
            if "```json" in raw_output:
                raw_output = raw_output.replace("```json", "").replace("```", "")
            elif "```" in raw_output:
                raw_output = raw_output.replace("```", "")
            
            try:
                result_data = json.loads(raw_output)
            except json.JSONDecodeError:
                logging.warning("Failed to parse JSON directly, attempting to find JSON substring")
                # Fallback: try to find the first { and last }
                start = raw_output.find('{')
                end = raw_output.rfind('}') + 1
                if start != -1 and end != -1:
                    result_data = json.loads(raw_output[start:end])
                else:
                    raise
        elif isinstance(search_result, dict):
            result_data = search_result
        else:
            result_data = json.loads(str(search_result))

        # Save results
        output_path = "app/tests/discovered_sources.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, indent=2, ensure_ascii=False)
        
        logging.info(f"\n Results saved to: {output_path}")
        
        return {
            "input_skills": skills_from_agent1,
            "status": "success"
        }

    except Exception as e:
        logging.error(f"Error during search execution: {e}", exc_info=True)
        return {
            "input_skills": skills_from_agent1,
            "status": "failed"
        }


if __name__ == "__main__":
    agent1_output_path = "app/tests/extracted_skills.json"
    
    if not os.path.exists(agent1_output_path):
        logging.error(f"Error: Agent 1 output not found at {agent1_output_path}")
        logging.error("Please run test_agent_1_resume_analyzer.py first")
        sys.exit(1)
    
    with open(agent1_output_path, "r", encoding="utf-8") as f:
        agent1_result = json.load(f)
    
    skills = agent1_result.get("skills", [])
    
    if not skills:
        logging.error("Error: No skills found in Agent 1 output")
        sys.exit(1)
    
    # Run async function
    result = asyncio.run(test_source_discoverer_agent(skills))
    
    if result:
        logging.info("\nTest Results Summary:")
        logging.info(json.dumps({
            "input_skills": result["input_skills"],
            "status": result["status"]
        }, indent=2))
