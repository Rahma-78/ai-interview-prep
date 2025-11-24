"""
Test script for the first agent: Resume Analyzer
Tests the extract_resume_text_task and identify_skills_task using original CrewAI approach
"""

import ast
import asyncio
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path

from crewai import Crew as CrewAI, Process

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from app.schemas.interview import ExtractedSkills
from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import file_text_extractor

# Configure logging for tests
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def test_agent_1_resume_analyzer(resume_file_path: str):
    """
    Tests the functionality of Agent 1 (Resume Analyzer) using the async CrewAI implementation.

    This test mirrors the updated crew approach where Agent 1 uses CrewAI with async execution
    for resume analysis, extracting technical skills from a provided PDF resume.

    Args:
        resume_file_path (str): The path to the resume PDF file to be analyzed.

    Returns:
        dict: A dictionary containing the extracted skills, timing information,
              and success status, or an error message if the process fails.
    """
    
    if not os.path.exists(resume_file_path):
        logging.error(f"Error: Resume file not found at {resume_file_path}")
        return None

    start_time = time.time()
    
    try:
        agents = InterviewPrepAgents()
        
        tools_dict = {
            "file_text_extractor": file_text_extractor,
        }
        agent_1 = agents.resume_analyzer_agent(tools_dict)
        
        tasks = InterviewPrepTasks()
        # Convert path to forward slashes to prevent LLM from stripping backslashes in tool calls
        safe_resume_path = resume_file_path.replace('\\', '/')
        skills_task = tasks.extract_skills_task(agent_1, safe_resume_path)
        
        mini_crew = CrewAI (  
            agents=[agent_1],
            tasks=[skills_task],
            process=Process.sequential,
            verbose=True,
        )
        
        logging.info("[Step 1] Running Async CrewAI for resume analysis...")
        crew_start = time.time()
        result = await mini_crew.kickoff_async()
        crew_time = time.time() - crew_start
        
        skills_list = []
        processed_result = "" # Initialize to an empty string to prevent unbound error
        
        logging.debug(f"Raw result type: {type(result)}")
        logging.debug(f"Raw result: {result}")

        try:
            processed_result = str(result).strip()

            if processed_result.startswith("{") and "'" in processed_result:
                try:
                    dict_result = ast.literal_eval(processed_result)
                    processed_result = json.dumps(dict_result)
                except (ValueError, SyntaxError) as e:
                    logging.warning(f"Could not evaluate result as Python literal: {e}")
                    pass

            parsed_result = ExtractedSkills(**json.loads(processed_result))
            skills_list = parsed_result.skills
            
        except json.JSONDecodeError as e:
            logging.error(f"Could not parse result as JSON: {e}")
            logging.debug(f"Raw result string: {processed_result}")
            return {
                "skills": [],
                "extraction_time": time.time() - start_time,
                "error": f"Failed to parse CrewAI result as JSON: {e}"
            }
        except Exception as e:
            logging.error(f"Error processing result: {e}", exc_info=True)
            return {
                "skills": [],
                "extraction_time": time.time() - start_time,
                "error": str(e)
            }
        
        extraction_time = time.time() - start_time
       
        output_path = "app/tests/extracted_skills.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"skills": skills_list}, f, indent=2, ensure_ascii=False)
        logging.info(f"\nSkills saved to: {output_path}")
        
        logging.info(f"\n{'='*60}")
        logging.info(f"Agent 1 Resume Analyzer Test Complete")
        logging.info(f"{'='*60}\n")
        
        return {
            "skills": skills_list,
            "output_file": output_path,
            "extraction_time": extraction_time,
            "crew_time": crew_time,
            "method": "crewai",
            "success": True
        }
                
    except Exception as e:
        logging.error(f"Error in Agent 1 test (outer block): {e}", exc_info=True)
        return {
            "skills": [],
            "extraction_time": time.time() - start_time,
            "error": str(e)
        }
        


if __name__ == "__main__":
    # Use absolute path to ensure file is found regardless of execution location
    sample_resume_path = str((Path(__file__).parent.parent / "Rahma Ashraf AlShafi'i.pdf").resolve())
    
    if not os.path.exists(sample_resume_path):
        logging.error(f"Error: Resume file not found at {sample_resume_path}")
        logging.error("Please ensure the resume file exists before running the test.")
        sys.exit(1)
    
    logging.info("\n" + "="*60)
    logging.info("RUNNING AGENT 1: RESUME ANALYZER TEST")
    logging.info("="*60 + "\n")
    
    logging.info("Testing Agent 1 Resume Analyzer...")
    direct_result = asyncio.run(test_agent_1_resume_analyzer(sample_resume_path))
    
    logging.info("\n" + "="*60)
    logging.info("AGENT 1 RESUME ANALYZER RESULTS")
    logging.info("="*60)
    
    if direct_result:
        skills_list = direct_result.get("skills", [])
        extraction_time = direct_result.get("extraction_time", 0)
        llm_time = direct_result.get("llm_time", 0)
        text_extraction_time = direct_result.get("text_extraction_time", 0)
        success = direct_result.get("success", False)
        error = direct_result.get("error", None)
        
        logging.info(f"Method: CrewAI (Agent 1)")
        logging.info(f"Success: {success}")
        if error:
            logging.error(f"Error: {error}")
        logging.info(f"Skills found: {len(skills_list)}")
        logging.info(f"Total extraction time: {extraction_time:.3f}s")
        logging.info(f"LLM call time: {llm_time:.3f}s")
        logging.info(f"Text extraction time: {text_extraction_time:.3f}s")
        logging.info(f"Output file: {direct_result.get('output_file', 'N/A')}")
        
        logging.info(f"\nExtracted Skills:")
        for idx, skill in enumerate(skills_list, 1):
            logging.info(f"  {idx}. {skill}")
    
    logging.info("\n" + "="*60)
    logging.info("AGENT 1 RESUME ANALYZER TEST COMPLETE")
    logging.info("="*60 + "\n")
