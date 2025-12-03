from pydantic import BaseModel, Field
from typing import Optional

# --- Shared/Base Models ---

class SkillBasedModel(BaseModel):
    """Base model for any entity related to a specific technical skill."""
    skill: str = Field(
        ..., 
        description="The specific technical skill (e.g., 'Python', 'Kubernetes', 'React')."
    )

# --- Agent/LLM Extraction Models ---

class ExtractedSkills(BaseModel):
    """Schema for the initial extraction of skills from a resume."""
    skills: list[str] = Field(
        ..., 
        description="A list of distinct technical hard skills found in the text. Exclude soft skills."
    )

class SkillSources(SkillBasedModel):
    """Schema for web search results and summaries linked to a skill."""
    extracted_content: str = Field(
        ..., 
        description="A list of technical summaries, documentation snippets, or interview angles derived from web sources."
    )

class AllSkillSources(BaseModel):
    """Collection wrapper for skill sources."""
    all_sources: list[SkillSources] = Field(
        ..., 
        description="A collection of sources and summaries for multiple skills."
    )

class InterviewQuestions(SkillBasedModel):
    """Schema for generating interview questions for a specific skill."""
    questions: list[str] = Field(
        ..., 
        description="A list of technical, interview questions."
    )

class AllInterviewQuestions(BaseModel):
    """Collection wrapper for interview questions."""
    all_questions: list[InterviewQuestions] = Field(
        ..., 
        description="A complete list of interview questions grouped by skill."
    )

# --- Frontend/API State Models ---

class InterviewQuestionState(InterviewQuestions):
    """
    Schema for the API response/Frontend state.
    Inherits 'skill' and 'questions' from InterviewQuestions and adds UI state fields.
    """
    questions: list[str] = Field(default_factory=list, description="A list of technical, interview questions.")
    isLoading: bool = Field(default=False, description="Frontend loading state flag.")
    error: Optional[str] = Field(default=None, description="Error message if generation failed.")