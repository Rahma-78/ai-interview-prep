"""
Test script for the third agent: Question Generator
Uses the output from Agent 1 (skills) and Agent 2 (sources) as input
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List

from crewai import Crew, Process

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.schemas.interview import (
    AllInterviewQuestions,
    AllSkillSources,
    SkillSources,
    Source,
)
from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import question_generator, smart_web_content_extractor

# Configure logging for tests
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


async def test_question_generator_agent(skills_from_agent1: list, sources_from_agent2: Dict[str, List[str]]):
    """
    Test the Question Generator Agent independently, with asynchronous processing of skills.
    Uses skills and sources from Agents 1 and 2 as input.
    
    Args:
        skills_from_agent1: List of skills from Agent 1 output
        sources_from_agent2: Dictionary of sources from Agent 2 output (full version)
    
    Returns:
        dict: Contains generated questions for each skill
    """
    
    if not skills_from_agent1 or len(skills_from_agent1) == 0:
        logging.error("Error: No skills provided from Agent 1")
        return None
    
    if not sources_from_agent2 or len(sources_from_agent2) == 0:
        logging.error("Error: No sources provided from Agent 2")
        return None
    
    logging.info(f"\n{'='*60}")
    logging.info(f"Testing Question Generator Agent")
    logging.info(f"Skills to process: {len(skills_from_agent1)}")
    logging.info(f"{'='*60}\n")
    
    agents = InterviewPrepAgents()
    tasks = InterviewPrepTasks()
    
    tools = {
        "question_generator": question_generator,
    }
    
    question_gen_agent = agents.question_generator_agent(tools)
    
    all_questions: Dict[str, Dict] = {}

    async def _process_single_skill(skill: str) -> Dict:
        logging.info(f"\n[Processing Skill] {skill}")
        logging.info("-" * 60)
        
        uris_for_skill = sources_from_agent2.get(skill, [])
        
        if not uris_for_skill:
            logging.warning(f"  Warning: No URIs found for skill: {skill}")
            return {
                "questions": [],
                "status": "no_sources",
                "error": "No URIs available for content extraction"
            }
        
        skill_sources_obj = AllSkillSources(all_sources=[
            SkillSources(
                skill=skill,
                sources=[Source(uri=uri, title=f"Source for {skill}") for uri in uris_for_skill]
            )
        ])
        
        logging.info(f"  [Step 1] Extracting web content for skill: {skill} from {len(uris_for_skill)} URIs...")
        sources_content = await smart_web_content_extractor(search_query=skill, urls=skill_sources_obj.json())
        
        if "Could not extract content" in sources_content or not sources_content:
            logging.warning(f"  Warning: Could not extract relevant content for skill: {skill}")
            return {
                "questions": [],
                "status": "no_content",
                "error": "Failed to extract content from sources"
            }
            
        logging.info(f"  [Step 2] Generating questions for skill: {skill}")
        logging.info(f"  Source content length: {len(sources_content)} characters")
        
        question_task = tasks.generate_questions_task(
            question_gen_agent,
            skill=skill,
            sources_content=sources_content
        )
        
        question_crew = Crew(  
            agents=[question_gen_agent],
            tasks=[question_task],
            process=Process.sequential,
            verbose=True
        )
        
        question_result = await question_crew.kickoff_async()  
        logging.info(f"  [Step 2 Complete] Questions generated")
        
        try:
            parsed_result = AllInterviewQuestions(**json.loads(str(question_result)))
            questions_list = []
            for item in parsed_result.all_questions:
                if item.skill.lower() == skill.lower():
                    questions_list = item.questions
                    break
            
            logging.info(f"  Generated {len(questions_list)} questions")
            for idx, question in enumerate(questions_list[:3], 1):
                logging.info(f"    {idx}. {question[:80]}..." if len(question) > 80 else f"    {idx}. {question}")
            
            return {
                "questions": questions_list,
                "status": "success"
            }
        except (json.JSONDecodeError, ValueError) as e:
            logging.warning(f"  Warning: Could not parse questions as AllInterviewQuestions JSON: {e}")
            logging.debug(f"  Raw result: {question_result}")
            return {
                "questions": [],
                "status": "parse_error",
                "raw_response": str(question_result)
            }

    # Run all skill processing concurrently
    tasks_to_run = [_process_single_skill(skill) for skill in skills_from_agent1]
    results_from_concurrent_tasks = await asyncio.gather(*tasks_to_run)

    for skill_idx, result_dict in enumerate(results_from_concurrent_tasks):
        skill = skills_from_agent1[skill_idx]
        all_questions[skill] = result_dict
    
    # Save results to JSON
    output_data = {
        "skills": skills_from_agent1,
        "interview_questions": all_questions,
        "status": "success"
    }
    
    output_path = "app/tests/agent3_question_generator_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)  # type: ignore
    logging.info(f"\n✓ Result saved to: {output_path}")
    
    # Create a summary version without raw responses
    output_summary = {
        "skills": skills_from_agent1,
        "interview_questions": {
            skill: {
                "question_count": len(data.get("questions", [])),
                "status": data["status"]
            }
            for skill, data in all_questions.items()
        },
        "total_questions": sum(len(data.get("questions", [])) for data in all_questions.values()),
        "status": "success"
    }
    
    output_summary_path = "app/tests/agent3_question_generator_summary.json"
    with open(output_summary_path, "w", encoding="utf-8") as f:
        json.dump(output_summary, f, indent=2, ensure_ascii=False)  # type: ignore
    logging.info(f"✓ Summary saved to: {output_summary_path}")
    
    logging.info(f"\n{'='*60}")
    logging.info(f"Question Generator Agent Test Complete")
    logging.info(f"{'='*60}\n")
    
    return output_summary


if __name__ == "__main__":
    agent1_output_path = str(Path(__file__).parent.parent / "extracted_skills.json")
    
    if not os.path.exists(agent1_output_path):
        logging.error(f"Error: Agent 1 output not found at {agent1_output_path}")
        logging.error("Please run test_agent_1_resume_analyzer.py first (using hybrid approach)")
        sys.exit(1)
    
    with open(agent1_output_path, "r", encoding="utf-8") as f:
        agent1_result = json.load(f)
    
    skills = agent1_result.get("skills", [])
    
    if not skills:
        logging.error("Error: No skills found in Agent 1 output")
        sys.exit(1)
    
    agent2_output_path_full = str(Path(__file__).parent.parent / "discovered_sources.json")
    
    if not os.path.exists(agent2_output_path_full):
        logging.error(f"Error: Agent 2 output not found at {agent2_output_path_full}")
        logging.error("Please run test_agent_2_source_discoverer.py first (using hybrid approach)")
        sys.exit(1)
    
    with open(agent2_output_path_full, "r", encoding="utf-8") as f:
        sources = json.load(f)
    
    if not sources:
        logging.warning("Warning: No sources found in Agent 2 output")
    
    result = asyncio.run(test_question_generator_agent(skills, sources))
    
    if result:
        logging.info("\nTest Results Summary (Hybrid Approach):")
        logging.info(json.dumps(result, indent=2))
