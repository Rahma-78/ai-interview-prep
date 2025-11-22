

import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path

from crewai import Crew as CrewAI, Process

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import grounded_source_discoverer
from app.schemas.interview import AllSkillSources, SkillSources
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
    logging.info("SEARCHING FOR RESOURCES")
    logging.info("=" * 80)

    
    all_sources = {}
    
    for skill in skills_from_agent1:
        try:
            logging.info(f"\nProcessing skill: {skill}")
            
            discover_task = tasks.discover_and_extract_content_task(source_discoverer, skill)
            search_crew = CrewAI(
                agents=[source_discoverer],
                tasks=[discover_task],
                process=Process.sequential,
                verbose=False
            )
            # Use kickoff_async for async agents
            search_result = await search_crew.kickoff_async()
            
            # Parse the result from the tool - CrewAI returns objects, not JSON strings
            try:
                # CrewAI returns result objects, so we need to access their raw attribute
                if hasattr(search_result, 'raw'):
                    result_dict = json.loads(search_result.raw)
                elif isinstance(search_result, dict):
                    result_dict = search_result
                else:
                    raise ValueError(f"Unexpected result type: {type(search_result)}")
                
                # Handle the case where result_dict might have 'all_sources' key directly
                if 'all_sources' in result_dict:
                    source_entries = result_dict['all_sources']
                else:
                    # Fallback: treat result_dict as containing source entries directly
                    source_entries = result_dict if isinstance(result_dict, list) else [result_dict]
                
                # Extract the first source entry (should contain the skill)
                if source_entries:
                    source_entry = source_entries[0]
                    # Handle both dict and SkillSources object
                    if isinstance(source_entry, dict):
                        extracted_content = source_entry.get('extracted_content', {})
                    else:
                        # Handle SkillSources object
                        extracted_content = source_entry.extracted_content.model_dump() if hasattr(source_entry, 'extracted_content') else {}
                    
                    all_sources[skill] = {
                        "extracted_content": extracted_content,
                        "status": "success"
                    }
                    logging.info(f"   Content extracted for {skill}")
                else:
                    all_sources[skill] = {
                        "extracted_content": {},
                        "status": "no_content"
                    }
                    logging.info(f"   No content found for {skill}")
                    
            except Exception as e:
                logging.error(f"Error parsing result for {skill}: {e}")
                logging.error(f"Raw response type: {type(search_result)}")
                all_sources[skill] = {
                    "extracted_content": {},
                    "status": "failed"
                }
                
        except Exception as e:
            logging.error(f"Error processing {skill}: {str(e)}", exc_info=True)
            all_sources[skill] = {
                "extracted_content": {},
                "status": "failed"
            }
    
    logging.info("=" * 80)
    logging.info("PROCESSING COMPLETE")
    logging.info("=" * 80)
    logging.info(f"  Input skills: {len(skills_from_agent1)}")
    logging.info(f"  Skills processed: {len(all_sources)}")
    logging.info(f"  Successful searches: {len([r for r in all_sources.values() if r.get('status') == 'success'])}")
    logging.info(f"  Failed searches: {len([r for r in all_sources.values() if r.get('status') == 'failed'])}")
    
    # Save in proper schema format
    schema_output = {
        "all_sources": [
            {
                "skill": skill,
                "extracted_content": data["extracted_content"]
            }
            for skill, data in all_sources.items()
        ]
    }
    
    output_path = "app/tests/discovered_sources.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema_output, f, indent=2, ensure_ascii=False)
    
    logging.info(f"\n Results saved to: {output_path}")
    logging.info("=" * 80)
    
    return {
        "input_skills": skills_from_agent1,
        "status": "success" if all_sources else "failed"
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
