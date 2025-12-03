from crewai import Agent 
from typing import List, Dict, Callable

from app.schemas.interview import AllInterviewQuestions, AllSkillSources, ExtractedSkills, InterviewQuestions
from app.services.tools.llm_config import llm_gemini, llm_groq, llm_openrouter, llm_deepseek
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
        self.llm_gemini = llm_gemini
        self.llm_groq = llm_groq
        self.llm_openrouter = llm_openrouter
        self.llm_deepseek = llm_deepseek


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
            
            llm=self.llm_openrouter,
            tools=[tools["file_text_extractor"]],
            verbose=settings.DEBUG_MODE,
            allow_delegation=False,
            max_iter=settings.AGENT_MAX_ITER,
            max_rpm=settings.AGENT_MAX_RPM,
            memory=False,
            cache=False,
         

         )

    def source_discoverer_agent(self, tools: Dict[str, Callable]) -> Agent:
        """
        Defines the agent responsible for discovering authoritative web sources for technical skills using Gemini's native search grounding.
        """
        return Agent(  # type: ignore
            role='Expert Research Analyst',
            goal='Find the best text-based web pages with technical resources for specific skills using Gemini\'s native search grounding.',
            backstory=(
                "You are a world-class digital researcher with access to Gemini's native search capabilities. "
                "Your goal is to provide the best source material for generating interview questions. "
                "You MUST rely strictly on the output of the 'grounded_source_discoverer' tool. "
                "Do not fabricate sources or hallucinate content. If the tool returns few results, work with what is provided."
            ),
            llm=self.llm_gemini,  # Use Gemini for both agent orchestration and grounded search
            tools=[tools["grounded_source_discoverer"]],
            verbose=settings.DEBUG_MODE,
            allow_delegation=False,
            max_iter=settings.AGENT_MAX_ITER,
            max_rpm=settings.AGENT_MAX_RPM,
            cache=False,
            response_format=AllSkillSources  # Enforce correct JSON schema
        )


    def question_generator_agent(self, tools: Dict[str, Callable]) -> Agent:
        """
        Defines the agent responsible for generating insightful interview questions.
        Receives batched context from source discoverer and generates questions for all skills in the batch.
        """
        return Agent(  # type: ignore
            role='Batch Question Generator',
            goal=f'Generate insightful, non-coding interview questions for batches of skills (typically {settings.BATCH_SIZE} skills per batch) using provided context.',
            backstory=(
                "You are an experienced technical interviewer who efficiently processes batches of skills in parallel workflows. "
                "You receive context from the source discovery phase containing technical content for multiple skills. "
                "Your expertise lies in crafting challenging, conceptually deep questions that assess a candidate's understanding. "
                "You use the provided context as a knowledge base combined with your technical expertise to generate questions for ALL skills in each batch."
            ),
            llm=self.llm_deepseek,  
            verbose=settings.DEBUG_MODE,
            allow_delegation=False,
            response_format=AllInterviewQuestions  # Enforce correct JSON schema
        )
