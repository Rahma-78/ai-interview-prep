from crewai import Agent 
from typing import Dict, Callable

from app.core.llm import chat_groq
from app.core.config import settings

class InterviewPrepAgents:
    """
    Manages and defines the various agents used in the interview preparation system.
    Each agent has a specific role, goal, and set of tools to accomplish its tasks.
    """

    def __init__(self):
        """
        Initializes the InterviewPrepAgents with instances of the language models.
        """
        self.llm = chat_groq

    def resume_analyzer_agent(self, tools: Dict[str, Callable]) -> Agent:
        """
        Defines the agent responsible for analyzing resumes and extracting technical skills.
        """
        return Agent( 
            role="Expert technical skill extraction agent",
            goal=(
                f"Extract exactly {settings.SKILL_COUNT} high-impact technical skills from the resume that are ideal for verbal technical interviews. "
                "Focus on core competencies, architectural concepts, and design principles."
            ),
            backstory=(
                "You are an elite technical skills analyst specializing in preparing candidates for high-level engineering interviews. "
                "Your expertise lies in identifying skills that reveal a candidate's depth of understanding, problem-solving abilities, and architectural vision. "
                "You distinguish between surface-level tools and genuine technical competencies suitable for deep verbal discussion. "
                "You prioritize skills that enable questions about 'how' and 'why' rather than just 'what'."
            ),
            
            llm=self.llm,
            tools=[tools["file_text_extractor"]],
            verbose=settings.DEBUG_MODE,
            allow_delegation=False,
            max_iter=settings.AGENT_MAX_ITER,
            max_rpm=settings.AGENT_MAX_RPM,
            memory=False,
         )
