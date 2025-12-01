from pydantic import BaseModel, Field
from typing import List, Dict, Union, Optional

class ExtractedSkills(BaseModel):
    skills: List[str] = Field(description="A list of technical skills found in the resume.")

class SkillSources(BaseModel):
    """
    Represents the discovered sources for a specific technical skill.
    """
    skill: str = Field(description="The technical skill (e.g., 'Python', 'Machine Learning').")
    extracted_content: List[str] = Field(description="A list of comprehensive technical summaries and potential interview angles extracted from sources.")

class AllSkillSources(BaseModel):
    all_sources: List[SkillSources] = Field(description="A list of all skills with their summaries.")

class InterviewQuestions(BaseModel):
    skill: str = Field(description="The technical skill.")
    questions: List[str] = Field(description="A list of insightful interview questions for this skill.")

class AllInterviewQuestions(BaseModel):
    all_questions: List[InterviewQuestions] = Field(description="A list of all skills with their generated questions.")

class InterviewQuestion(BaseModel):
    """
    Schema for the API response, representing questions for a single skill.
    Includes frontend-specific fields like isLoading.
    """
    skill: str
    questions: List[str] = []
    isLoading: bool = False
    error: Optional[str] = None
