"""
Complete integration test for all three agents
Runs agents sequentially and passes output from one to the next
"""

import json
import os
import sys
import asyncio
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
"""
Complete integration test for all three agents using hybrid approach
Runs agents sequentially and passes output from one to the next
Uses hybrid approach: Agent 1 (direct async), Agents 2&3 (CrewAI)
"""

import json
import os
import sys
import asyncio
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.crew import InterviewPrepCrew


def run_complete_pipeline(resume_file_path: str):
    """
    Run the complete pipeline with hybrid approach.
    
    Args:
        resume_file_path: Path to the resume file
    
    Returns:
        dict: Final output with all questions organized by skill
    """
    
    print(f"\n{'='*80}")
    print(f"RUNNING COMPLETE INTERVIEW PREP PIPELINE (HYBRID APPROACH)")
    print(f"{'='*80}\n")
    
    try:
        # Create crew with hybrid approach
        crew = InterviewPrepCrew(file_path=resume_file_path)
        
        # Run the crew with hybrid async processing
        result = asyncio.run(crew.run_async())
        
        # Compile final result
        final_result = {
            "pipeline_status": "complete",
            "resume_file": resume_file_path,
            "method": "hybrid",
            "total_questions": sum(len(item.get("questions", [])) for item in result),
            "skills_processed": len(result),
            "output": result
        }
        
        # Save final result
        final_output_path = "backend/tests/final_pipeline_result.json"
        with open(final_output_path, "w", encoding="utf-8") as f:
            json.dump(final_result, f, indent=2, ensure_ascii=False)  # type: ignore
        
        print(f"\n{'='*80}")
        print(f"PIPELINE COMPLETE (HYBRID APPROACH)")
        print(f"{'='*80}\n")
        print(f"✓ Final result saved to: {final_output_path}")
        
        return final_result
        
    except Exception as e:
        print(f"Error in hybrid pipeline: {e}")
        return {
            "pipeline_status": "failed",
            "error": str(e),
            "method": "hybrid"
        }
    return final_result


if __name__ == "__main__":
    # Use sample resume
    sample_resume_path = "backend/tests/sample_resume.txt"
    
    if not os.path.exists(sample_resume_path):
        # Create a sample resume for testing
        sample_resume_content = """
        JOHN DOE
        Email: john@example.com | Phone: (555) 123-4567
        
        SUMMARY
        Experienced software engineer with 5+ years of expertise in full-stack development.
        
        SKILLS
        Programming Languages: Python, JavaScript, TypeScript, Java, C++
        Web Frameworks: Django, FastAPI, React, Vue.js, Express
        Databases: PostgreSQL, MongoDB, Redis, MySQL
        Tools & Platforms: Docker, Kubernetes, AWS, Git, Jenkins
        Methodologies: Agile, Scrum, TDD, Microservices
        
        EXPERIENCE
        Senior Software Engineer at Tech Corp (2021-Present)
        - Developed microservices using Python and FastAPI
        - Implemented CI/CD pipelines using Jenkins and Docker
        - Led a team of 4 developers
        
        Full-Stack Developer at StartupXYZ (2019-2021)
        - Built React frontend and Django backend applications
        - Managed PostgreSQL and MongoDB databases
        - Deployed applications on AWS using Kubernetes
        
        Junior Developer at TechStart (2018-2019)
        - Developed web applications using JavaScript and Express
        - Fixed bugs and improved application performance
        - Participated in code reviews and agile ceremonies
        
        EDUCATION
        Bachelor of Science in Computer Science
        University of Technology (2018)
        
        CERTIFICATIONS
        AWS Certified Solutions Architect
        Docker Certified Associate
        """
        
        os.makedirs(os.path.dirname(sample_resume_path), exist_ok=True)
        with open(sample_resume_path, "w") as f:
            f.write(sample_resume_content)
        print(f"Created sample resume at: {sample_resume_path}")
    
    # Run the complete pipeline
    result = run_complete_pipeline(sample_resume_path)
    
    if result:
        print("\nFinal Pipeline Result:")
        print(json.dumps(result, indent=2))
