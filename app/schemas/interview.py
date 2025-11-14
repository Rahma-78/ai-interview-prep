from pydantic import BaseModel, Field
from pydantic import BaseModel, Field
from typing import List, Dict, Any

class InterviewQuestion(BaseModel):
    skill: str
    query: str | None = None
    sources: List[Dict] | None = None
    questions: List[str] | None = None
    isLoading: bool = False # Changed to False as processing will be done by backend
    error: str | None = None

class ExtractedSkills(BaseModel):
    skills: List[str] = Field(description="A list of technical skills found in the resume.")

class Source(BaseModel):
    uri: str = Field(description="The URI of the discovered web page.")
    title: str = Field(description="The title of the discovered web page.")

class SkillSources(BaseModel):
    skill: str = Field(description="The technical skill.")
    sources: List[Source] = Field(description="A list of authoritative web sources for this skill.")

class AllSkillSources(BaseModel):
    all_sources: List[SkillSources] = Field(description="A list of all skills with their sources.")

class InterviewQuestions(BaseModel):
    skill: str = Field(description="The technical skill.")
    questions: List[str] = Field(description="A list of insightful interview questions for this skill.")

class AllInterviewQuestions(BaseModel):
    all_questions: List[InterviewQuestions] = Field(description="A list of all skills with their generated questions.")
