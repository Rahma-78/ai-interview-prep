from crewai import Agent 
from typing import Callable, Dict, List

from app.schemas.interview import AllInterviewQuestions, AllSkillSources, ExtractedSkills
from app.services.tools.llm_config import llm_gemini, llm_groq, llm_openrouter
from app.core.config import settings # Import settings

# ============================================================================
# SESSION CACHE FOR OPTIMIZATION
# ============================================================================

class InterviewPrepAgents:
    """
    Manages and defines the various agents used in the interview preparation system.
    Each agent has a specific role, goal, and set of tools to accomplish its tasks.
    """

    def __init__(self):
        """
        Initializes the InterviewPrepAgents with instances of the language models.
        """
        self.llm_gemini = llm_gemini
        self.llm_groq = llm_groq
        self.llm_openrouter = llm_openrouter


    def resume_analyzer_agent(self, tools: Dict[str, Callable]) -> Agent:
        """
        Defines the agent responsible for analyzing resumes and extracting technical skills.
        """
        return Agent( 
            role="Senior Technical Recruiter",
            goal="Analyze the content of a provided resume to identify the top 10 most relevant technical skills that are best suited for generating deep, conceptual verbal interview questions.",
            backstory=(
                "You are an elite technical recruiter with over a decade of experience. "
                "You have a masterful ability to scan any resume and extract the most relevant technical skills, "
                "ignoring fluff and focusing on what matters for a technical role."
            ),
            llm=self.llm_groq,
            tools=[tools["file_text_extractor"]],
            verbose=False,  # Reduce verbose output to improve performance
            allow_delegation=False,
            max_iter=3,  # Limit iterations to reduce latency
            max_rpm=30,  # Increase requests per minute for faster processing
            memory=False,  # Disable memory to reduce overhead
            cache=False,  # Disable caching for faster first call
            response_format=ExtractedSkills,  # Force JSON response for faster parsing
            async_execution=True  # Enable async execution for better performance
         )

    def source_discoverer_agent(self, tools: Dict[str, Callable]) -> Agent:
        """
        Defines the agent responsible for discovering authoritative web sources for technical skills using Gemini's native search grounding.
        """
        return Agent(  # type: ignore
            role='Expert Research Analyst',
            goal='Find the best text-based web pages with technical resources for specific skills using Gemini\'s native search grounding.',
            backstory=(
                "You are a world-class digital researcher with access to Gemini\'s native search capabilities. "
                "Your goal is to provide the best source material for generating interview questions. "
                "You MUST rely strictly on the output of the 'grounded_source_discoverer' tool. "
                "Do not fabricate sources or hallucinate content. If the tool returns few results, work with what is provided."
            ),
            llm=self.llm_gemini,  # Use Gemini for both agent orchestration and grounded search
            tools=[tools["grounded_source_discoverer"]],
            verbose=settings.DEBUG_MODE,
            allow_delegation=False,
            max_iter=3,
            max_rpm=30,
            cache=False,
            async_execution=True,  # Enable async execution for better performance
            
        )

    def question_generator_agent(self, tools: Dict[str, Callable]) -> Agent:
        """
        Defines the agent responsible for generating insightful interview questions.
        """
        return Agent(  # type: ignore
            role='Question Generator',
            goal='Generate insightful, non-coding interview questions based on provided sources and skills.',
            backstory='An experienced technical interviewer who can craft challenging and relevant questions from given content.',
            llm=self.llm_openrouter,  # Use OpenRouter for question generation
            tools=[tools["question_generator"]],
            verbose=settings.DEBUG_MODE,
            allow_delegation=False,
            async_execution=True,  # Enable async execution for better performance
            response_format=AllInterviewQuestions  # Enforce output format
        )
