from crewai import Agent
from dotenv import load_dotenv
from backend.tools import llm_groq, llm_openrouter, llm_gemini_flash
from typing import Generator, List, Dict, Any, Optional
import asyncio
import threading
import time
import os
import json
load_dotenv()


# ============================================================================
# SESSION CACHE FOR OPTIMIZATION
# ============================================================================

# Global cache for URL searches (persists during session)
SEARCH_CACHE: Dict[str, Dict] = {}


class InterviewPrepAgents:
    def __init__(self):
        # Store LLM instances as class attributes to avoid circular imports
        self.llm_groq = llm_groq
        self.llm_openrouter = llm_openrouter
        self.llm_gemini_flash = llm_gemini_flash
    
    def resume_analyzer_agent(self, tools=None):
        return Agent(  # type: ignore
            role="Senior Technical Recruiter",
            goal="Analyze the content of a provided resume to identify the top 10 most relevant technical skills.",
            backstory=(
        "You are an elite technical recruiter with over a decade of experience. "
        "You have a masterful ability to scan any resume and extract the most relevant technical skills, "
        "ignoring fluff and focusing on what matters for a technical role."
    ),
            llm=self.llm_groq,
            tools=[tools["file_text_extractor"]] if tools else [],
            verbose=False,  # Reduce verbose output to improve performance
            allow_delegation=False,
            max_iter=3,  # Limit iterations to reduce latency
            max_rpm=30,  # Increase requests per minute for faster processing
            memory=False,  # Disable memory to reduce overhead
            cache=False,  # Disable caching for faster first call
            response_format="json",  # Force JSON response for faster parsing
            max_tokens=1000,  # Limit tokens for faster response
            async_execution=True  # Enable async execution for better performance
        )

    def source_discoverer_agent(self, tools):
        return Agent(  # type: ignore
            role='Expert Research Analyst',
            goal='Find the best text-based web pages with technical resources for specific skills using Google Search, explicitly avoiding video platforms and multimedia websites. Prioritize articles, tutorials, documentation, and Q&A sites with written content.',
            backstory=(
        "You are a world-class digital researcher. Your goal is to provide the best source material for generating interview questions. "
        "You will use your search capabilities to find famous question websites, high-quality tutorials, and expert articles for each skill. "
        "You have a keen eye for identifying and filtering out video-based content (YouTube, Vimeo, TikTok, etc.) and only work with text-based resources."
    ),
            llm=self.llm_gemini_flash,  # Use Gemini for grounding
            tools=[tools["google_search_tool"], tools["smart_web_content_extractor"]],
            verbose=True,
            allow_delegation=False,
            async_execution=True  # Enable async execution for better performance
        )

    def question_generator_agent(self, tools):
        return Agent(  # type: ignore
            role='Question Generator',
            goal='Generate insightful, non-coding interview questions based on provided sources and skills.',
            backstory='An experienced technical interviewer who can craft challenging and relevant questions from given content.',
            llm=self.llm_openrouter,  # Use OpenRouter for question generation
            tools=[tools["question_generator"]], # This is now a function
            verbose=True,
            allow_delegation=False,
            async_execution=True  # Enable async execution for better performance
        )
