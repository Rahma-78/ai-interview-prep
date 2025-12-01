import logging
from typing import List

from crewai import Task
from crewai.agent import Agent

from app.schemas.interview import AllInterviewQuestions, AllSkillSources, ExtractedSkills, InterviewQuestions

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
            "\n".join([f"Use the file text extractor tool to analyze the resume at '{file_path}' and extract exactly 9 technical skills based on the following criteria"
                    "Extraction Criteria:"
                    "Foundational Focus: Prioritize foundational concepts over specific tools."
                    "Core Competencies:Extract Technical skills as listed in the 'Skills' section; do not infer generic activities."
                    "Conceptual Depth: Skills must support deep discussions and conceptual analysis."
                    "Verbal Suitability: Favor skills that allow candidates to explain concepts rather than just coding syntax."
                    "Diversity:Ensure the list encompasses the full range of the candidate's skills. Avoid redundancy by selecting broader concepts."
                    "Exclusions: Avoid generic soft skills or vague terms lacking technical substance."
                    "Critical Requirement: Skills must be suitable for generating non-coding interview questions, focusing on substantive technical knowledge."])),
            agent=agent,
            expected_output="JSON object with 'skills' key containing 10 specific, technical skill strings relevant to the candidate's background.",   
            output_file="app/data/extracted_skills.json", # Save output to file in the data directory
            output_json=ExtractedSkills # Enforce output format
        )

    def discover_and_extract_content_task(self, agent: Agent, skills: List[str] = None) -> Task:
        """
        Defines the task for discovering sources and extracting content for a list of skills.
        This task uses the 'grounded_source_discoverer' tool to find technical
        learning resources and provide them as context for the next agent.
        """
      
        description = ("\n".join(["Find high-quality technical resources for the following skills: {skills}. "
                "Use the 'grounded_source_discoverer' tool to search for authoritative sources for ALL these skills. "
                "The tool will batch the searches and return content for each skill. "
                "CRITICAL: The final output must be a strict JSON object matching the 'AllSkillSources' schema. "
                "The 'extracted_content' field must contain ONLY the technical summary text that can be used as context for generating interview questions. "
                "Do NOT include any URLs, links, or 'Sources' sections in the content."]))

        return Task(
            description=description,
            agent=agent,
            expected_output="A JSON object conforming to the AllSkillSources schema, containing the list of skills and their extracted content.",
            output_json=AllSkillSources,
            output_file="app/data/context.json" # Save output to file for the next agent
        )
    def generate_questions_task(self, agent: Agent) -> Task:
        """
        Defines the task for generating interview questions using batch processing.
        """
        description = (
            "Generate insightful, non-coding interview questions for the following skills: {skills}. "
            "You have received a list of 'skills' and their 'context'. "
            "You MUST use the 'batch_question_generator' tool with the EXACT list of skills provided above. "
            "Do NOT add, remove, or modify any skills. "
            "The tool will automatically load the context."
            "IMPORTANT: Your final output must be a VALID JSON object. Use DOUBLE QUOTES for all keys and strings. Do NOT use single quotes."
            "CRITICAL: Do NOT wrap the output in markdown code blocks (e.g., ```json ... ```). Return ONLY the raw JSON string."
            "Ensure there are no trailing characters or extra braces at the end of the JSON object."
        )
        
        return Task(  # type: ignore
            description=description,
            agent=agent,
            expected_output="A JSON object conforming to the AllInterviewQuestions schema with all_questions list.",
            output_file="app/data/interview_questions.json", # Save output to file
            output_json=AllInterviewQuestions
        )
