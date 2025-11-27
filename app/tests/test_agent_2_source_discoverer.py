import asyncio
import json
import logging
import os
import sys
import re
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

def extract_json_from_text(text: str):
    """
    Robustly extracts JSON from text that might contain Markdown code blocks
    or conversational filler.
    """
    # 1. Try to find a JSON code block first
    code_block_pattern = r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```"
    match = re.search(code_block_pattern, text, re.DOTALL)
    if match:
        return match.group(1)

    # 2. If no code block, try to find the first valid JSON array or object
    # This looks for the outermost [ ... ] or { ... }
    json_pattern = r"(\{[\s\S]*\}|\[[\s\S]*\])"
    match = re.search(json_pattern, text, re.DOTALL)
    if match:
        return match.group(1)

    # 3. Fallback: Return original text (will likely fail parsing, but worth a try)
    return text

async def test_source_discoverer_agent(skills_from_agent1: list):
    """
    Test the Source Discoverer Agent using the updated Async Tool.
    """
    
    if not skills_from_agent1 or len(skills_from_agent1) == 0:
        logging.error("Error: No skills provided from Agent 1")
        return None
    
    logging.info("=" * 80)
    logging.info("SOURCE DISCOVERER AGENT (ASYNC TEST)")
    logging.info("=" * 80)
    logging.info(f"Input skills: {len(skills_from_agent1)}")
    
    agents = InterviewPrepAgents()
    tasks = InterviewPrepTasks()
    
    # Ensure the tool is correctly mapped
    tools = {
        "grounded_source_discoverer": grounded_source_discoverer
    }
    
    source_discoverer = agents.source_discoverer_agent(tools)
    
    logging.info("=" * 80)
    logging.info("SEARCHING FOR RESOURCES (BATCHED)")
    logging.info("=" * 80)

    # Pass skills explicitly in the inputs
    discover_task = tasks.discover_and_extract_content_task(source_discoverer, skills=skills_from_agent1)
    
    search_crew = CrewAI(
        agents=[source_discoverer],
        tasks=[discover_task],
        process=Process.sequential,
        verbose=False 
    )
    
    inputs = {"skills": skills_from_agent1}
    
    try:
        # Kickoff async
        search_result = await search_crew.kickoff_async(inputs=inputs)
        
        logging.info("Search completed. Parsing output...")
        
        # --- IMPROVED OUTPUT HANDLING ---
        raw_output = ""
        if hasattr(search_result, 'raw'):
            raw_output = search_result.raw
        elif isinstance(search_result, dict) and 'raw' in search_result:
             raw_output = search_result['raw']
        else:
            raw_output = str(search_result)

        # Use robust extraction helper
        clean_json_text = extract_json_from_text(raw_output)
        
        parsed_data = None
        
        try:
            parsed_data = json.loads(clean_json_text)
            logging.info("✅ JSON Parsing Successful!")
        except json.JSONDecodeError as e:
            logging.error(f"JSON Parse Error: {e}")
            logging.error(f"Failed Text Snippet: {clean_json_text[:200]}...")
            raise ValueError("Could not parse Agent output into valid JSON.")

        # --- SCHEMA VALIDATION ---
        final_model = None
        
        try:
            if isinstance(parsed_data, list):
                # If agent returned a list of items, wrap it in the expected schema
                final_model = AllSkillSources(all_sources=parsed_data)
            elif isinstance(parsed_data, dict):
                if "all_sources" in parsed_data:
                    final_model = AllSkillSources(**parsed_data)
                else:
                    # Handle edge case where a single dict might be returned (unlikely but possible)
                    # or if the agent returned a dict that IS one source
                    logging.warning("Received dict without 'all_sources' key. Attempting to parse as single entry wrapped in list.")
                    # Assuming parsed_data fits the inner schema, we wrap it
                    final_model = AllSkillSources(all_sources=[parsed_data])
            else:
                raise ValueError(f"Unexpected data type: {type(parsed_data)}")
            
            logging.info("✅ Schema Validation Successful!")
            
        except Exception as e:
            logging.error(f"Schema Validation Failed: {e}")
            # Debug dump
            debug_path = "app/tests/debug_failed_schema.json"
            with open(debug_path, "w", encoding="utf-8") as f:
                json.dump(parsed_data, f, indent=2)
            logging.info(f"Debug data saved to {debug_path}")
            raise e

        # Save the Validated Results
        output_path = "app/tests/discovered_sources.json"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_model.model_dump_json(indent=2))
        
        logging.info(f"Results saved to: {output_path}")
        
        return {
            "input_skills": skills_from_agent1,
            "status": "success",
            "source_count": len(final_model.all_sources)
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
        sys.exit(1)
    
    with open(agent1_output_path, "r", encoding="utf-8") as f:
        agent1_result = json.load(f)
    
    # Handle different potential structures of Agent 1 output
    skills = []
    if isinstance(agent1_result, list):
        skills = agent1_result
    elif isinstance(agent1_result, dict):
        skills = agent1_result.get("skills", [])
    
    if not skills:
        logging.error("Error: No skills found in Agent 1 output")
        sys.exit(1)
    
    # Run the async test
    result = asyncio.run(test_source_discoverer_agent(skills))
    
    if result:
        logging.info("\nTest Results Summary:")
        logging.info(json.dumps({
            "status": result["status"],
            "sources_found": result.get("source_count", 0)
        }, indent=2))