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
        f"From the content, extract the 10 most significant technical skills. "
        f"ignoring fluff and focusing on what matters for a technical role."
        f"Focus strictly on foundational concepts, and identify only core competencies."
    ),
            agent=agent,
            expected_output="JSON object with 'skills' key containing 10 specific, technical skill strings relevant to the candidate's background.",
            output_json=ExtractedSkills, # Enforce output format
            output_file="app/tests/extracted_skills.json" # Save output to file in the tests directory
        )

    def discover_and_extract_content_task(self, agent: Agent, skill: str) -> Task:
        """
        Defines the task for discovering sources and extracting content for a given skill.
        This task uses the 'grounded_source_discoverer' tool to find technical
        learning resources and provide them as context for the next agent.
        """
        return Task(
            description=f"Find high-quality technical learning resources for '{skill}'. "
                        f"Use the 'grounded_source_discoverer' tool to search for authoritative sources. "
                        f"Focus on extracting substantial text-based content that can be used as context for generating interview questions. "
                        "The tool will use Google Search grounding to find relevant information and return a JSON object containing the skill, a list of sources (with URL, title, and content), and a summary of the extracted content. "
                        "CRITICAL: Trust the tool's output completely. If it returns 2-3 sources, accept that. Do NOT try to invent sources or search again.",
            agent=agent,
            expected_output="A JSON object conforming to the AllSkillSources schema, containing the skill, sources, and the extracted content summary.",
            output_file="app/tests/discovered_sources.json"
        )

    def generate_questions_task(self, agent: Agent, skill: str, sources_content: str) -> Task:
        """
        Defines the task for generating interview questions based on extracted skills and source content.
        """
        return Task(  # type: ignore
            description=f"Generate insightful, non-coding interview questions for a candidate skilled in '{skill}'. "
                       "Base the questions ONLY on the information from these sources:\n{sources_content}. "
                       "Use the 'Question Generator Tool' to return only a JSON object with a single key 'questions' which is an array of unique question strings.",
            agent=agent,
            expected_output="A JSON string with a 'questions' key, containing an array of unique interview question strings.",
            output_json=AllInterviewQuestions # Enforce output format
        )
