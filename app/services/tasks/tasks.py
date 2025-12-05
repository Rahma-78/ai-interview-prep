import logging
from typing import List

from crewai import Task
from crewai.agent import Agent

from app.schemas.interview import AllInterviewQuestions, AllSkillSources, ExtractedSkills, InterviewQuestions
from app.core.config import settings

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
            "\n".join([f"Use the file text extractor tool to analyze the resume at '{file_path}' and extract exactly {settings.SKILL_COUNT} technical skills based on the following criteria:",
                    "Extraction Criteria:",
                    "Foundational Focus: Prioritize foundational concepts over specific tools.",
                    "Core Competencies: Extract technical skills as listed in the 'Skills' section; do not infer generic activities.",
                    "Conceptual Depth: Skills must support deep discussions and conceptual analysis.",
                    "Verbal Suitability: Favor skills that allow candidates to explain concepts rather than just coding syntax.",
                    "Diversity: Ensure the list encompasses the full range of the candidate's skills. Avoid redundancy by selecting broader concepts.",
                    "Exclusions: Avoid generic soft skills or vague terms lacking technical substance.",
                    "Critical Requirement: Skills must be suitable for generating non-coding interview questions, focusing on substantive technical knowledge."])),
            agent=agent,
            expected_output=f"JSON object with 'skills' key containing {settings.SKILL_COUNT} specific, technical skill strings relevant to the candidate's background.",   
            output_file="app/data/extracted_skills.json"
        )

    def discover_sources_task(self, agent: Agent, skills: List[str] = None) -> Task:
        """
        Defines the task for discovering sources and extracting content for a list of skills.
        This task uses the 'grounded_source_discoverer' tool to find technical
        learning resources and provide them as context for the next agent.
        """
      
        description = ("\\n".join(["Find high-quality technical resources for the following skills: {skills}. "
                "Use the 'grounded_source_discoverer' tool to search for authoritative sources for ALL these skills. "
                "The tool will batch the searches and return content for each skill. "
                "CRITICAL OUTPUT FORMAT: You MUST wrap the tool's output in the correct JSON structure: "
                "{\"all_sources\": [<tool output array>]}. "
                "The tool returns an array like: [{\"skill\": \"...\", \"extracted_content\": \"...\"},  ...]. "
                "You must wrap this array under the 'all_sources' key to match the AllSkillSources schema. "
                "Example: {\"all_sources\": [{\"skill\": \"Python\", \"extracted_content\": \"...\"},  ...]}. "
                "The 'extracted_content' field must contain ONLY the technical summary text for generating interview questions. "
                "Do NOT include URLs, links, or 'Sources' sections."]))
                

        return Task(
            description=description,
            agent=agent,
            expected_output="A JSON object conforming to the AllSkillSources schema: {\"all_sources\": [{\"skill\": \"...\", \"extracted_content\": \"...\"}]}",
            output_file="app/data/context.json"
    
        )
    def generate_questions_task(self, agent: Agent, skills: List[str] = None) -> Task:
        """
        Defines the task for generating interview questions using batch processing.
        """
        description = (
            "Generate insightful, non-coding interview questions for the following skills: {skills}. "
            "You have received a list of 'skills' and their 'context': {context}. "
            "Use the provided context to generate questions for each skill. "
            "IMPORTANT: Your final output must be a VALID JSON object matching the 'AllInterviewQuestions' schema. "
            "CRITICAL FORMAT: The 'questions' field must be an array of PLAIN STRING questions, NOT objects. "
            "CORRECT: \"questions\": [\"What is...\", \"How does...\"] "
            "WRONG: \"questions\": [{\"question\": \"What is...\"}, {\"question\": \"How does...\"}] "
            "Use DOUBLE QUOTES for all keys and strings. Do NOT use single quotes. "
            "Do NOT wrap the output in markdown code blocks (e.g., ```json ... ```). Return ONLY the raw JSON string. "
            "Ensure the JSON is complete and properly closed with ']}'."
        )
        
        return Task(  # type: ignore
            description=description,
            agent=agent,
            output_file="app/data/interview_questions.json",
            expected_output="JSON: {\"all_questions\": [{\"skill\": \"...\", \"questions\": [\"question1\", \"question2\", ...]}]}",
            output_pydantic=AllInterviewQuestions
        )
