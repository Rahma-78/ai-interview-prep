import logging

from crewai import Task
from crewai.agent import Agent

from app.schemas.interview import ExtractedSkills
from app.core.config import settings


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
