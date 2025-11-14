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
import ast # Import the ast module
from crewai import Crew, Process
# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import file_text_extractor, google_search_tool, smart_web_content_extractor, question_generator
from app.schemas.interview import ExtractedSkills
async def test_agent_1_resume_analyzer(resume_file_path: str):
    """
    Test Agent 1 functionality (Resume Analyzer) using async CrewAI implementation.
    This mirrors the updated crew approach where Agent 1 uses CrewAI with async execution for resume analysis.
 
    """
    
    if not os.path.exists(resume_file_path):
        # Error message for missing file, kept as a comment for debugging if needed
        print(f"Error: Resume file not found at {resume_file_path}")
        return None

    start_time = time.time()
    
    try:
        # Create Agent 1 using CrewAI with async execution
        agents = InterviewPrepAgents()
        
        # Define tools for the agent
        tools_dict = {
            "file_text_extractor": file_text_extractor,
            "google_search_tool": google_search_tool,
            "smart_web_content_extractor": smart_web_content_extractor,
            "question_generator": question_generator
        }
        agent_1 = agents.resume_analyzer_agent(tools_dict)
        
        # Create tasks for Agent 1
        tasks = InterviewPrepTasks()
        skills_task = tasks.extract_skills_task(agent_1, resume_file_path)
        
        # Create a crew with just Agent 1 (following the same pattern as other agent tests)
        mini_crew = Crew(
            agents=[agent_1],
            tasks=[skills_task],
            # process=Process.sequential, # Process is now set via config or default
            # verbose=True, # Verbose is now set via config or default
            # max_rpm=30 # Removed for consistency with crew/crew.py
        )
        mini_crew.process = Process.sequential
        mini_crew.verbose = True
        
        # Run the crew asynchronously
        # print("[Step 1] Running Async CrewAI for resume analysis...") # Removed print
        crew_start = time.time()
        result = await mini_crew.kickoff_async()
        crew_time = time.time() - crew_start
        # Parse the result
        skills_list = []
        result_data = {}
        
        # print(f"Raw result type: {type(result)}") # Removed print
        # print(f"Raw result: {result}") # Removed print

        try:
            # Initialize processed_result with the raw result string
            processed_result = str(result).strip()

            # If it starts with a single quote or looks like a Python dict, convert it
            if processed_result.startswith("{") and "'" in processed_result:
                try:
                    # Safely evaluate as a Python literal (dictionary)
                    dict_result = ast.literal_eval(processed_result)
                    # Convert the dictionary to a proper JSON string
                    processed_result = json.dumps(dict_result)
                except (ValueError, SyntaxError) as e:
                    # print(f"Warning: Could not evaluate result as Python literal: {e}") # Removed print
                    # If literal_eval fails, processed_result remains its original string value
                    pass

            # The result from kickoff_async should be a JSON string representing ExtractedSkills
            parsed_result = ExtractedSkills(**json.loads(processed_result))
            skills_list = parsed_result.skills
            
        except json.JSONDecodeError as e:
            # print(f"Warning: Could not parse result as JSON: {e}") # Removed print
            # print(f"Raw result string: {processed_result}") # Removed print
            return {
                "skills": [],
                "extraction_time": time.time() - start_time,
                "error": f"Failed to parse CrewAI result as JSON: {e}"
            }
        except Exception as e:
            # print(f"Error processing result: {e}") # Removed print
            import traceback
            traceback.print_exc()
            return {
                "skills": [],
                "extraction_time": time.time() - start_time,
                "error": str(e)
            }
        
        extraction_time = time.time() - start_time
       
        
        # Save skills to JSON file
        output_path = "tests/extracted_skills.json" # Updated path
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"skills": skills_list}, f, indent=2, ensure_ascii=False)
        # print(f"\nSkills saved to: {output_path}") # Removed print
        
        # print(f"\n{'='*60}") # Removed print
        # print(f"Agent 1 Resume Analyzer Test Complete") # Removed print
        # print(f"{'='*60}\n") # Removed print
        
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
        # print(f"Error in Agent 1 test (outer block): {e}") # Removed print
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
    sample_resume_path = str(Path(__file__).parent.parent / "Rahma Ashraf AlShafi'i.pdf")
    
    if not os.path.exists(sample_resume_path):
        print(f"Error: Resume file not found at {sample_resume_path}")
        print("Please ensure the resume file exists before running the test.")
        exit(1)
    
    # Run Agent 1 test
    # print("\n" + "="*60) # Removed print
    # print("RUNNING AGENT 1: RESUME ANALYZER TEST") # Removed print
    # print("="*60 + "\n") # Removed print
    
    # Test Agent 1 functionality
    # print("Testing Agent 1 Resume Analyzer...") # Removed print
    direct_result = asyncio.run(test_agent_1_resume_analyzer(sample_resume_path))
    
    # Show results
    # print("\n" + "="*60) # Removed print
    # print("AGENT 1 RESUME ANALYZER RESULTS") # Removed print
    # print("="*60) # Removed print
    
    if direct_result:
        skills_list = direct_result.get("skills", [])
        extraction_time = direct_result.get("extraction_time", 0)
        llm_time = direct_result.get("llm_time", 0)
        text_extraction_time = direct_result.get("text_extraction_time", 0)
        success = direct_result.get("success", False)
        error = direct_result.get("error", None)
        
        # print(f"Method: CrewAI (Agent 1)") # Removed print
        # print(f"Success: {success}") # Removed print
        # if error: # Removed print
        #     print(f"Error: {error}") # Removed print
        # print(f"Skills found: {len(skills_list)}") # Removed print
        # print(f"Total extraction time: {extraction_time:.3f}s") # Removed print
        # print(f"LLM call time: {llm_time:.3f}s") # Removed print
        # print(f"Text extraction time: {text_extraction_time:.3f}s") # Removed print
        # print(f"Output file: {direct_result.get('output_file', 'N/A')}") # Removed print
        
        # print(f"\nExtracted Skills:") # Removed print
        # for idx, skill in enumerate(skills_list, 1): # Removed print
        #     print(f"  {idx}. {skill}") # Removed print
    
    # print("\n" + "="*60) # Removed print
    # print("AGENT 1 RESUME ANALYZER TEST COMPLETE") # Removed print
    # print("="*60 + "\n") # Removed print
