from pydantic import BaseModel, Field
from typing import List, Dict, Union

class ExtractedSkills(BaseModel):
    skills: List[str] = Field(description="A list of technical skills found in the resume.")

class TechnicalResourceContent(BaseModel):
    """Structured technical content from a resource."""
    core_concepts: List[str] = Field(description="Dense summary of core technical concepts and fundamentals.")
    problem_solving: List[str] = Field(description="Common problem-solving approaches and patterns.")
    terminology: List[str] = Field(description="Key terminology and definitions.")
    best_practices: List[str] = Field(description="Best practices and important considerations.")
    challenges: List[str] = Field(description="Typical challenges and solutions.")

class SkillSources(BaseModel):
    """
    Represents the discovered sources for a specific technical skill.
    """
    skill: str = Field(description="The technical skill (e.g., 'Python', 'Machine Learning').")
    extracted_content: TechnicalResourceContent = Field(description="The structured technical content extracted from sources.")

class AllSkillSources(BaseModel):
    all_sources: List[SkillSources] = Field(description="A list of all skills with their sources.")

class InterviewQuestions(BaseModel):
    skill: str = Field(description="The technical skill.")
    questions: List[str] = Field(description="A list of insightful interview questions for this skill.")

class AllInterviewQuestions(BaseModel):
    all_questions: List[InterviewQuestions] = Field(description="A list of all skills with their generated questions.")
