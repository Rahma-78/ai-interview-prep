import logging
from typing import List

from crewai import Task
from crewai.agent import Agent

from app.schemas.interview import AllInterviewQuestions, AllSkillSources, ExtractedSkills

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from app.services.tools.tools import (
    file_text_extractor,
    google_search_tool,
    smart_web_content_extractor,
    question_generator,
)


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
            tools=[file_text_extractor],  # type: ignore
            expected_output="JSON object with 'skills' key containing 10 specific, technical skill strings relevant to the candidate's background.",
            output_json=ExtractedSkills, # Enforce output format
            output_file="app/tests/extracted_skills.json" # Save output to file in the tests directory
        )

    def search_sources_task(self, agent: Agent, skill: str) -> Task:
        """
        Defines the task for searching high-quality web sources for a given skill.
        """
        return Task(  # type: ignore
            description=f"Find high-quality technical interview questions and learning resources for '{skill}'. "
                       f"Use the 'Google Search Tool' to automatically optimize the search query. "
                       "Search for authoritative sources like tutorials, educational websites, documentation, and interview question websites. "
                       "Focus on text-based content (articles, documentation, Q&A sites, blogs, guides). "
                       "The output should be a JSON string containing a list of URLs (strings). "
                       "Return ALL found URLs (up to 5-10 results for better coverage). "
                       "CRITICAL: Make only ONE search attempt. If the search returns no results, return an empty list. Do NOT try multiple search queries or variations.",
            agent=agent,
            tools=[google_search_tool],  # type: ignore
            expected_output="A JSON string containing a list of high-quality, text-based, authoritative URLs. If no results are found, return an empty list.",
            output_json=AllSkillSources # Enforce output format
        )

    def extract_web_content_task(self, agent: Agent, urls_reference: str, skill: str) -> Task:
        """
        Defines the task for extracting relevant content from web pages.
        """
        return Task(  # type: ignore
            description=f"Extract relevant, contextual content about '{skill}' from the provided list of URLs: {urls_reference}. "
                       f"Use the 'Smart Web Content Extractor Tool' to get the most useful information based on the query: '{skill}'.",
            agent=agent,
            tools=[smart_web_content_extractor],  # type: ignore
            expected_output="A single string containing the combined, relevant textual content from all provided URLs."
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
            tools=[question_generator],  # type: ignore
            expected_output="A JSON string with a 'questions' key, containing an array of unique interview question strings.",
            output_json=AllInterviewQuestions # Enforce output format
        )
