from crewai import Task
import json

# Import tools directly from the backend module
try:
    from backend.tools import (
        file_text_extractor,
        google_search_tool,
        smart_web_content_extractor,
        question_generator
    )
    tools_available = True
except ImportError as e:
    print(f"Warning: Could not import tools: {e}")
    tools_available = False

# Create placeholder tools if import fails
if not tools_available:
    from crewai.tools import tool
    
    @tool
    def file_text_extractor(file_path: str) -> str:
        """Extracts all text content from a PDF file. Returns the extracted text."""
        return "PDF text extraction not available"
    
    @tool
    def google_search_tool(search_query: str) -> str:
        """Performs a Google search for a given query and returns relevant snippets and URLs."""
        return '{"organic": []}'
    
    @tool
    def smart_web_content_extractor(search_query: str, urls=None) -> str:
        """Extracts relevant, contextual content from a list of URLs based on a specific query."""
        return "No URLs provided for content extraction"
    
    @tool
    def question_generator(skill: str, sources_content: str) -> str:
        """Generates insightful, non-coding interview questions based on provided skill and source content."""
        return '{"questions": []}'


class InterviewPrepTasks:

    def extract_skills_task(self, agent, file_path: str):
        return Task(  # type: ignore
            description=(f"1. Utilize the 'File Text Extractor Tool' to extract text from: {file_path}. "
                       "2. Objective: Analyze the extracted text to identify the 10 most important technical skills relevant to the role."
                       "3.Criteria: Ignore any filler content and focus exclusively on skills pertinent to technical roles."
                       "4. Prioritize skills from technical sections. "
                       ),
            agent=agent,
            tools=[file_text_extractor],  # type: ignore
            expected_output="JSON object with 'skills' key containing 10 specific, technical skill strings relevant to the candidate's background."
        )

    def search_sources_task(self, agent, skill: str):
        # Create optimized search query for higher quality results
        optimized_query = f"{skill} interview questions tutorial best practices -youtube -vimeo"
        
        return Task(  # type: ignore
            description=f"Find high-quality technical interview questions and learning resources for '{skill}'. "
                       f"Use the 'Google Search Tool' with this optimized query: '{optimized_query}'. "
                       "Search for authoritative sources like tutorials, educational websites, documentation, and interview question websites. "
                       "Focus on text-based content (articles, documentation, Q&A sites, blogs, guides). "
                       "The output should be a JSON string containing a list of dictionaries, where each dictionary has a 'link' key with the URL. "
                       "Return ALL found URLs (up to 5-10 results for better coverage). "
                       "CRITICAL: Make only ONE search attempt. If the search returns no results, return an empty list. Do NOT try multiple search queries or variations.",
            agent=agent,
            tools=[google_search_tool],  # type: ignore
            expected_output="A JSON string containing a list of dictionaries with 'link' keys, prioritizing high-quality, text-based, authoritative sources. If no results are found, return an empty list."
        )

    def extract_web_content_task(self, agent, urls_reference: str, skill: str):
        return Task(  # type: ignore
            description=f"Extract relevant, contextual content about '{skill}' from the provided list of URLs: {urls_reference}. "
                       f"Use the 'Smart Web Content Extractor Tool' to get the most useful information based on the query: '{skill}'.",
            agent=agent,
            tools=[smart_web_content_extractor],  # type: ignore
            expected_output="A single string containing the combined, relevant textual content from all provided URLs."
        )

    def generate_questions_task(self, agent, skill: str, sources_content: str):
        return Task(  # type: ignore
            description=f"Generate insightful, non-coding interview questions for a candidate skilled in '{skill}'. "
                       "Base the questions ONLY on the information from these sources:\n{sources_content}. "
                       "Use the 'Question Generator Tool' to return only a JSON object with a single key 'questions' which is an array of unique question strings.",
            agent=agent,
            tools=[question_generator],  # type: ignore
            expected_output="A JSON string with a 'questions' key, containing an array of unique interview question strings."
        )

