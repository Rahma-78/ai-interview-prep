from pydantic import BaseModel, Field
from typing import List, Dict

class ExtractedSkills(BaseModel):
    skills: List[str] = Field(description="A list of technical skills found in the resume.")

class SkillSources(BaseModel):
    skill: str = Field(description="The technical skill.")
    sources: List[Dict[str, str]] = Field(description="A list of sources with URL, and content.")
    extracted_content: str = Field(description="A summary of key themes and patterns found across sources.")

class AllSkillSources(BaseModel):
    all_sources: List[SkillSources] = Field(description="A list of all skills with their sources.")

class InterviewQuestions(BaseModel):
    skill: str = Field(description="The technical skill.")
    questions: List[str] = Field(description="A list of insightful interview questions for this skill.")

class AllInterviewQuestions(BaseModel):
    all_questions: List[InterviewQuestions] = Field(description="A list of all skills with their generated questions.")
