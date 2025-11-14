"""
Test script for the first agent: Resume Analyzer
Tests the extract_resume_text_task and identify_skills_task using original CrewAI approach
"""

import json
import os
import sys
import asyncio
import time
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import CrewAI components
from crewai import Crew, Process
from backend.agents import InterviewPrepAgents
from backend.tasks import InterviewPrepTasks
from backend.tools import file_text_extractor

async def test_agent_1_resume_analyzer(resume_file_path: str):
    """
    Test Agent 1 functionality (Resume Analyzer) using async CrewAI implementation.
    This mirrors the updated crew approach where Agent 1 uses CrewAI with async execution for resume analysis.
    
    Args:
        resume_file_path: Path to the resume file (PDF, DOCX, or TXT)
    
    Returns:
        dict: Contains extracted skills and performance metrics, matching crew format
    """
    
    if not os.path.exists(resume_file_path):
        print(f"Error: Resume file not found at {resume_file_path}")
        return None
    
    print(f"\n{'='*60}")
    print(f"Testing Agent 1: Resume Analyzer (Async CrewAI)")
    print(f"Resume file: {resume_file_path}")
    print(f"{'='*60}\n")
    
    start_time = time.time()
    
    try:
        # Create Agent 1 using CrewAI with async execution
        agents = InterviewPrepAgents()
        agent_1 = agents.resume_analyzer_agent()
        
        # Create tasks for Agent 1
        tasks = InterviewPrepTasks()
        skills_task = tasks.extract_skills_task(agent_1, resume_file_path)
        
        # Create a crew with just Agent 1 (following the same pattern as other agent tests)
        mini_crew = Crew(
            agents=[agent_1],
            tasks=[skills_task],
            process=Process.sequential,
            verbose=True,
            max_rpm=30
        )
        
        # Run the crew asynchronously
        print("[Step 1] Running Async CrewAI for resume analysis...")
        crew_start = time.time()
        result = await mini_crew.kickoff_async()
        crew_time = time.time() - crew_start
        # Parse the result
        skills_list = []
        result_data = {}
        
        print(f"Raw result type: {type(result)}")
        print(f"Raw result: {result}")

        try:
            if isinstance(result, dict):
                result_data = result
            elif isinstance(result, str):
                # Assuming LLM is instructed to return JSON, try to parse it
                result_data = json.loads(result)
            
            skills_list = result_data.get("skills", [])
            
        except json.JSONDecodeError as e:
            print(f"Warning: Could not parse result as JSON: {e}")
            print(f"Raw result string: {result}")
            return {
                "skills": [],
                "extraction_time": time.time() - start_time,
                "error": "Failed to parse CrewAI result as JSON"
            }
        except Exception as e:
            print(f"Error processing result: {e}")
            import traceback
            traceback.print_exc()
            return {
                "skills": [],
                "extraction_time": time.time() - start_time,
                "error": str(e)
            }
        
        extraction_time = time.time() - start_time
        
        print(f"SUCCESS: Extracted {len(skills_list)} skills using CrewAI")
        for idx, skill in enumerate(skills_list, 1):
            print(f"   {idx}. {skill}")
        
        # Save skills to JSON file
        output_path = "tests/extracted_skills.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"skills": skills_list}, f, indent=2, ensure_ascii=False)
        print(f"\nSkills saved to: {output_path}")
        
        print(f"\n{'='*60}")
        print(f"Agent 1 Resume Analyzer Test Complete")
        print(f"{'='*60}\n")
        
        # Return data matching crew format
        return {
            "skills": skills_list,
            "output_file": output_path,
            "extraction_time": extraction_time,
            "crew_time": crew_time,
            "method": "crewai",
            "success": True
        }
                
    except Exception as e:
        print(f"Error in Agent 1 test (outer block): {e}")
        import traceback
        traceback.print_exc()
        return {
            "skills": [],
            "extraction_time": time.time() - start_time,
            "error": str(e)
        }
        


if __name__ == "__main__":
    # Example usage: provide path to resume file
    # You can modify this to accept command line arguments
    
    # For testing, create a sample resume file if it doesn't exist
    sample_resume_path =   "backend/Rahma Ashraf AlShafi'i.pdf"
    
    if not os.path.exists(sample_resume_path):
        print(f"Error: Resume file not found at {sample_resume_path}")
        print("Please ensure the resume file exists before running the test.")
        exit(1)
    
    # Run Agent 1 test
    print("\n" + "="*60)
    print("RUNNING AGENT 1: RESUME ANALYZER TEST")
    print("="*60 + "\n")
    
    # Test Agent 1 functionality
    print("Testing Agent 1 Resume Analyzer...")
    direct_result = asyncio.run(test_agent_1_resume_analyzer(sample_resume_path))
    
    # Show results
    print("\n" + "="*60)
    print("AGENT 1 RESUME ANALYZER RESULTS")
    print("="*60)
    
    if direct_result:
        skills_list = direct_result.get("skills", [])
        extraction_time = direct_result.get("extraction_time", 0)
        llm_time = direct_result.get("llm_time", 0)
        text_extraction_time = direct_result.get("text_extraction_time", 0)
        success = direct_result.get("success", False)
        error = direct_result.get("error", None)
        
        print(f"Method: CrewAI (Agent 1)")
        print(f"Success: {success}")
        if error:
            print(f"Error: {error}")
        print(f"Skills found: {len(skills_list)}")
        print(f"Total extraction time: {extraction_time:.3f}s")
        print(f"LLM call time: {llm_time:.3f}s")
        print(f"Text extraction time: {text_extraction_time:.3f}s")
        print(f"Output file: {direct_result.get('output_file', 'N/A')}")
        
        print(f"\nExtracted Skills:")
        for idx, skill in enumerate(skills_list, 1):
            print(f"  {idx}. {skill}")
    
    print("\n" + "="*60)
    print("AGENT 1 RESUME ANALYZER TEST COMPLETE")
    print("="*60 + "\n")
