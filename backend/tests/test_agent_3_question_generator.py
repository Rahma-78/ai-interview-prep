"""
Test script for the third agent: Question Generator
Uses the output from Agent 1 (skills) and Agent 2 (sources) as input
"""

import json
import os
import sys
from pathlib import Path

# CrewAI telemetry is now enabled for testing
# os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from crewai import Crew, Process
from backend.agents import InterviewPrepAgents
from backend.tasks import InterviewPrepTasks
from backend.tools import question_generator


def test_question_generator_agent(skills_from_agent1: list, sources_from_agent2: dict):
    """
    Test the Question Generator Agent independently.
    Uses skills and sources from Agents 1 and 2 as input.
    
    Args:
        skills_from_agent1: List of skills from Agent 1 output
        sources_from_agent2: Dictionary of sources from Agent 2 output (full version)
    
    Returns:
        dict: Contains generated questions for each skill
    """
    
    if not skills_from_agent1 or len(skills_from_agent1) == 0:
        print("Error: No skills provided from Agent 1")
        return None
    
    if not sources_from_agent2 or len(sources_from_agent2) == 0:
        print("Error: No sources provided from Agent 2")
        return None
    
    print(f"\n{'='*60}")
    print(f"Testing Question Generator Agent")
    print(f"Skills to process: {len(skills_from_agent1)}")
    print(f"{'='*60}\n")
    
    # Initialize agents and tasks
    agents = InterviewPrepAgents()
    tasks = InterviewPrepTasks()
    
    tools = {
        "question_generator": question_generator,
    }
    
    # Create the question generator agent
    question_gen_agent = agents.question_generator_agent(tools)
    
    all_questions = {}
    
    # Process each skill
    for skill in skills_from_agent1:
        print(f"\n[Processing Skill] {skill}")
        print("-" * 60)
        
        # Get the source content for this skill from Agent 2 output
        sources_content = sources_from_agent2.get(skill, {}).get("full_content", "")
        
        if not sources_content:
            print(f"  Warning: No source content found for skill: {skill}")
            all_questions[skill] = {
                "questions": [],
                "status": "no_sources",
                "error": "No source content available for question generation"
            }
            continue
        
        print(f"  [Step 1] Generating questions for skill: {skill}")
        print(f"  Source content length: {len(sources_content)} characters")
        
        # Create the question generation task
        question_task = tasks.generate_questions_task(
            question_gen_agent,
            skill=skill,
            sources_content=sources_content
        )
        
        question_crew = Crew(  # type: ignore
            agents=[question_gen_agent],
            tasks=[question_task],
            process=Process.sequential,
            verbose=True
        )
        
        question_result = question_crew.kickoff()  # type: ignore
        print(f"  [Step 1 Complete] Questions generated")
        
        # Parse questions
        try:
            questions_data = json.loads(str(question_result))
            questions_list = questions_data.get("questions", [])
            print(f"  Generated {len(questions_list)} questions")
            for idx, question in enumerate(questions_list[:3], 1):  # Show first 3 questions
                print(f"    {idx}. {question[:80]}..." if len(question) > 80 else f"    {idx}. {question}")
            
            all_questions[skill] = {
                "questions": questions_list,
                "status": "success"
            }
        except json.JSONDecodeError as e:
            print(f"  Warning: Could not parse questions as JSON: {e}")
            print(f"  Raw result: {question_result}")
            all_questions[skill] = {
                "questions": [],
                "status": "parse_error",
                "raw_response": str(question_result)
            }
    
    # Save results to JSON
    output_data = {
        "skills": skills_from_agent1,
        "interview_questions": all_questions,
        "status": "success"
    }
    
    output_path = "backend/tests/agent3_question_generator_output.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)  # type: ignore
    print(f"\n✓ Result saved to: {output_path}")
    
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
    
    output_summary_path = "backend/tests/agent3_question_generator_summary.json"
    with open(output_summary_path, "w", encoding="utf-8") as f:
        json.dump(output_summary, f, indent=2, ensure_ascii=False)  # type: ignore
    print(f"✓ Summary saved to: {output_summary_path}")
    
    print(f"\n{'='*60}")
    print(f"Question Generator Agent Test Complete")
    print(f"{'='*60}\n")
    
    return output_summary


if __name__ == "__main__":
    # Load skills from Agent 1 output (using hybrid approach)
    agent1_output_path = "backend/tests/extracted_skills.json"
    
    if not os.path.exists(agent1_output_path):
        print(f"Error: Agent 1 output not found at {agent1_output_path}")
        print("Please run test_agent_1_resume_analyzer.py first (using hybrid approach)")
        sys.exit(1)
    
    with open(agent1_output_path, "r", encoding="utf-8") as f:
        agent1_result = json.load(f)
    
    skills = agent1_result.get("skills", [])
    
    if not skills:
        print("Error: No skills found in Agent 1 output")
        sys.exit(1)
    
    # Load sources from Agent 2 output (full version)
    agent2_output_path_full = "backend/tests/discovered_sources.json"
    
    if not os.path.exists(agent2_output_path_full):
        print(f"Error: Agent 2 output not found at {agent2_output_path_full}")
        print("Please run test_agent_2_source_discoverer.py first (using hybrid approach)")
        sys.exit(1)
    
    with open(agent2_output_path_full, "r", encoding="utf-8") as f:
        agent2_result = json.load(f)
    
    sources = agent2_result.get("skills_with_resources", {})
    
    if not sources:
        print("Warning: No sources found in Agent 2 output")
    
    # Run the test using hybrid approach (Agent 1: direct async, Agents 2&3: CrewAI)
    result = test_question_generator_agent(skills, sources)
    
    if result:
        print("\nTest Results Summary (Hybrid Approach):")
        print(json.dumps(result, indent=2))
