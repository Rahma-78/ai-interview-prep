
import asyncio
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
                verbose=True
            )
            # Use kickoff_async for async agents
            search_result = await search_crew.kickoff_async()
            
            # Parse the result from the tool - CrewAI returns objects, not JSON strings
            try:
                # CrewAI returns result objects, so we need to access their raw attribute or convert to dict
                if hasattr(search_result, 'raw'):
                    # If it has a raw attribute, try to parse it as JSON
                    try:
                        result_dict = json.loads(search_result.raw)
                    except json.JSONDecodeError:
                        # If JSON parsing fails, try to extract from the raw string
                        raw_str = str(search_result.raw)
                        # Look for JSON-like content in the raw string
                        json_match = re.search(r'\{.*\}', raw_str, re.DOTALL)
                        if json_match:
                            result_dict = json.loads(json_match.group())
                        else:
                            result_dict = {"all_sources": [{"skill": skill, "sources": [], "extracted_content": ""}]}
                elif isinstance(search_result, dict):
                    # If it's already a dict, use it directly
                    result_dict = search_result
                else:
                    # Try to convert the result to a dict
                    result_dict = {"all_sources": [{"skill": skill, "sources": [], "extracted_content": ""}]}
                
                # Handle the case where result_dict might have 'all_sources' key directly
                if 'all_sources' in result_dict:
                    try:
                        parsed_result = AllSkillSources(**result_dict)
                        source_entries = parsed_result.all_sources
                    except Exception:
                        # If schema validation fails, use the raw data
                        source_entries = result_dict.get('all_sources', [])
                else:
                    # Fallback: treat result_dict as containing source entries directly
                    source_entries = result_dict if isinstance(result_dict, list) else [result_dict]
                
                # Extract the first source entry (should contain the skill)
                if source_entries:
                    source_entry = source_entries[0]
                    # Handle both dict and SkillSources object
                    if isinstance(source_entry, dict):
                        sources = source_entry.get('sources', [])
                        extracted_content = source_entry.get('extracted_content', '')
                    else:
                        # Handle SkillSources object
                        sources = source_entry.sources if hasattr(source_entry, 'sources') else []
                        extracted_content = source_entry.extracted_content if hasattr(source_entry, 'extracted_content') else ""
                    all_sources[skill] = {
                        "sources": sources,
                        "source": "grounded_search",
                        "status": "success" if sources else "no_sources",
                        "sources_found_count": len(sources),
                        "extracted_content": extracted_content
                    }
                    logging.info(f"   Found {len(sources)} sources for {skill}")
                else:
                    all_sources[skill] = {
                        "sources": [],
                        "source": "grounded_search",
                        "status": "no_sources",
                        "sources_found_count": 0,
                        "extracted_content": ""
                    }
                    logging.info(f"   No sources found for {skill}")
                    
            except Exception as e:
                logging.error(f"Error parsing result for {skill}: {e}")
                logging.error(f"Raw response type: {type(search_result)}")
                # Use fallback extraction
                try:
                    # Try to extract data from CrewAI result
                    if hasattr(search_result, 'raw') and search_result.raw:
                        raw_str = str(search_result.raw)
                        # Look for questions array in the raw response
                        questions_match = re.search(r'"questions":\s*\[(.*?)\]', raw_str, re.DOTALL)
                        if questions_match:
                            questions_str = questions_match.group(1)
                            # Extract individual questions (handling escaped quotes)
                            questions = re.findall(r'"((?:[^"\\]|\\.)*)"', questions_str)
                            logging.info(f"   Fallback extraction successful for {skill}: {len(questions)} questions found")
                        else:
                            questions = []
                    else:
                        questions = []
                    
                    all_sources[skill] = {
                        "sources": [],
                        "source": "grounded_search",
                        "status": "no_sources",
                        "sources_found_count": 0,
                        "extracted_content": ""
                    }
                except Exception as fallback_error:
                    logging.error(f"Fallback extraction also failed for {skill}: {fallback_error}")
                    all_sources[skill] = {
                        "sources": [],
                        "source": "error",
                        "status": "failed",
                        "sources_found_count": 0,
                        "extracted_content": ""
                    }
                
        except Exception as e:
            logging.error(f"Error processing {skill}: {str(e)}", exc_info=True)
            all_sources[skill] = {
                "sources": [],
                "source": "error",
                "status": "failed",
                "sources_found_count": 0,
                "extracted_content": ""
            }
    
    logging.info("=" * 80)
    logging.info("PROCESSING COMPLETE")
    logging.info("=" * 80)
    logging.info(f"  Input skills: {len(skills_from_agent1)}")
    logging.info(f"  Skills processed: {len(all_sources)}")
    logging.info(f"  Successful searches: {len([r for r in all_sources.values() if r.get('status') == 'success'])}")
    logging.info(f"  Failed searches: {len([r for r in all_sources.values() if r.get('status') == 'failed'])}")
    
    output_data = {
        "skills_with_sources": all_sources,
        "input_skills": skills_from_agent1,
        "status": "success" if all_sources else "failed"
    }
    
    # Save in proper schema format
    schema_output = {
        "all_sources": [
            {
                "skill": skill,
                "sources": data["sources"],
                "extracted_content": data["extracted_content"]
            }
            for skill, data in all_sources.items()
        ]
    }
    
    # Validate against schema
    try:
        # Convert dict objects to proper SkillSources objects
        skill_sources_list = []
        for item in schema_output["all_sources"]:
            skill_sources = SkillSources(
                skill=item["skill"],
                sources=item["sources"],
                extracted_content=item["extracted_content"]
            )
            skill_sources_list.append(skill_sources)
        
        validated_output = AllSkillSources(all_sources=skill_sources_list)
        logging.info("Schema validation successful")
    except Exception as e:
        logging.error(f"Schema validation failed: {e}")
        # Fallback to basic format
        validated_output = schema_output
    
    output_path = "app/tests/discovered_sources.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema_output, f, indent=2, ensure_ascii=False)
    
    logging.info(f"\n Results saved to: {output_path}")
    logging.info("=" * 80)
    
    return output_data


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
