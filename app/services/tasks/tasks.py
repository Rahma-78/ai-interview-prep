import logging
from typing import List

from crewai import Task
from crewai.agent import Agent

from app.schemas.interview import AllInterviewQuestions, AllSkillSources, ExtractedSkills

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')




class InterviewPrepTasks:
    """
    Manages and defines the various tasks for the interview preparation system.
    Each task is assigned to a specific agent and has a clear description and expected output.
    """

    def extract_skills_task(self, agent: Agent, file_path: str) -> Task:
        """
        Defines the task for extracting technical skills from a resume.
        """
        
        return Task(  # type: ignore
            description=(
            f"Use the file text extractor tool to read the resume at '{file_path}'. "
            f"Analyze the content deeply to extract exactly 10 technical skills that meet these criteria:\n"
            f"1. **Strict Extraction**: Extract skills *strictly* as they appear in the 'Skills' section of the resume. Do NOT infer generic activities.\n"
            f"2. **Conceptual Depth**: extracted skills must support deep discussion, architectural reasoning and conceptual analysis.\n"
            f"3. **Verbal Suitability**: Prioritize skills where a candidate can demonstrate understanding through explanation rather than just coding syntax.\n"
            f"4. **Diversity**: Ensure the list covers the full breadth of the all candidate's skills. Avoid listing multiple redundant tools choose broader concept.\n"
            f"5. **Exclusions**: Strictly avoid generic soft skills or broad terms that lack technical substance for a deep interview.\n"
            f"CRITICAL: The extracted skills must be suitable for generating non-coding interview questions, ignoring fluff and focusing on what matters for a technical interview."
            ),
            agent=agent,
            expected_output="JSON object with 'skills' key containing 10 specific, technical skill strings relevant to the candidate's background.",   
            output_file="app/tests/extracted_skills.json", # Save output to file in the tests directory
            output_json=ExtractedSkills # Enforce output format
        )

    def discover_and_extract_content_task(self, agent: Agent, skills: List[str] = None) -> Task:
        """
        Defines the task for discovering sources and extracting content for a list of skills.
        This task uses the 'grounded_source_discoverer' tool to find technical
        learning resources and provide them as context for the next agent.
        """
        if skills:
            description = (
                f"Find high-quality technical resources for the following skills: {skills}. "
                f"Use the 'grounded_source_discoverer' tool to search for authoritative sources for ALL these skills. "
            )
        else:
            description = (
                "Find high-quality technical resources for the skills extracted in the previous task. "
                "Use the 'grounded_source_discoverer' tool to search for authoritative sources for ALL these skills. "
            )
            
        description += (
            "The tool will batch the searches and return content for each skill. "
            "Focus on extracting substantial text-based content that can be used as context for generating interview questions. "
            "CRITICAL: The final output must be a strict JSON object matching the 'AllSkillSources' schema. "
            "The 'extracted_content' field must contain ONLY the technical summary text. "
            "Do NOT include any URLs, links, or 'Sources' sections in the content."
         )

        return Task(
            description=description,
            agent=agent,
            expected_output="A JSON object conforming to the AllSkillSources schema, containing the list of skills and their extracted content.",
            output_json=AllSkillSources

        )

    def generate_questions_task(self, agent: Agent, context: str = None) -> Task:
        """
        Defines the task for generating interview questions based on extracted skills and source content.
        This task processes a BATCH of skills using the 'question_generator' tool.
        """
        description = (
            "Generate insightful, non-coding interview questions for the provided batch of skills. "
            "You will receive a JSON object conforming to 'AllSkillSources' which contains skills and their context. "
            "Use the 'question_generator' tool to process ALL skills in parallel. "
            "The tool will return a JSON object with questions for each skill."
        )
        
        return Task(  # type: ignore
            description=description,
            agent=agent,
            expected_output="A JSON string conforming to the AllInterviewQuestions schema, containing questions for all skills.",
            output_json=AllInterviewQuestions # Enforce output format
        )
