from crewai import Agent 
from typing import List, Dict, Callable

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
            role="Expert technical skill extraction agent",
            goal=(
                "Extract exactly 10 high-impact technical skills from the resume that are ideal for verbal technical interviews. "
                "Focus on core competencies, architectural concepts, and design principles."
            ),
            backstory=(
                "You are an elite technical skills analyst specializing in preparing candidates for high-level engineering interviews. "
                "Your expertise lies in identifying skills that reveal a candidate's depth of understanding, problem-solving abilities, and architectural vision. "
                "You distinguish between surface-level tools and genuine technical competencies suitable for deep verbal discussion. "
                "You prioritize skills that enable questions about 'how' and 'why' rather than just 'what'."
            ),
            llm=self.llm_groq,
            tools=[tools["file_text_extractor"]],
            verbose=settings.DEBUG_MODE,  # Reduce verbose output to improve performance
            allow_delegation=False,
            max_iter=settings.AGENT_MAX_ITER,  # Limit iterations to reduce latency
            max_rpm=settings.AGENT_MAX_RPM,  # Increase requests per minute for faster processing
            memory=False,  # Disable memory to reduce overhead
            cache=False,  # Disable caching for faster first call
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
                "The tool returns 'raw_content' text. You MUST parse this text and structure it into the 'extracted_content' schema fields (core_concepts, problem_solving, etc.). "
                "Do not fabricate sources or hallucinate content. If the tool returns few results, work with what is provided."
            ),
            llm=self.llm_gemini,  # Use Gemini for both agent orchestration and grounded search
            tools=[tools["grounded_source_discoverer"]],
            verbose=settings.DEBUG_MODE,
            allow_delegation=False,
            max_iter=settings.AGENT_MAX_ITER,
            max_rpm=settings.AGENT_MAX_RPM,
            cache=False,
            response_format=AllSkillSources  # Enforce output format
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
