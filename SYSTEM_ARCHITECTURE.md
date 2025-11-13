# AI Interview Prep - System Architecture & Data Flow

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AI INTERVIEW PREP SYSTEM                         │
└─────────────────────────────────────────────────────────────────────┘

USER INPUT:
    Resume File (PDF/DOCX/TXT)
           ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    AGENT 1: RESUME ANALYZER                         │
├─────────────────────────────────────────────────────────────────────┤
│ Role: Extract skills from resume                                    │
│ LLM: Groq (llama3-70b)                                              │
│ Tasks:                                                               │
│   1. Extract text from file (PDF/DOCX/TXT)                          │
│   2. Identify key technical skills                                  │
├─────────────────────────────────────────────────────────────────────┤
│ OUTPUT: agent1_resume_analyzer_output.json                          │
│ {                                                                    │
│   "resume_file": "path/to/resume.txt",                              │
│   "extracted_text_length": 5432,                                    │
│   "skills": ["Python", "JavaScript", "Docker", "AWS", "React"],    │
│   "status": "success"                                               │
│ }                                                                    │
└─────────────────────────────────────────────────────────────────────┘
           ↓ (Skills List)
┌─────────────────────────────────────────────────────────────────────┐
│                 AGENT 2: SOURCE DISCOVERER                          │
├─────────────────────────────────────────────────────────────────────┤
│ Role: Find interview prep sources for each skill                    │
│ LLM: Gemini 1.5 Flash (for grounding)                               │
│ For each skill:                                                      │
│   1. Search for relevant interview questions (Google Search)        │
│   2. Extract content from discovered URLs                           │
├─────────────────────────────────────────────────────────────────────┤
│ OUTPUT: agent2_source_discoverer_output_full.json                   │
│ {                                                                    │
│   "sources_discovered": {                                            │
│     "Python": {                                                      │
│       "urls": ["https://...", "https://..."],                       │
│       "full_content": "...extracted content..."                     │
│     },                                                               │
│     "JavaScript": { ... }                                           │
│   }                                                                  │
│ }                                                                    │
└─────────────────────────────────────────────────────────────────────┘
           ↓ (Skills + Web Content)
┌─────────────────────────────────────────────────────────────────────┐
│               AGENT 3: QUESTION GENERATOR                           │
├─────────────────────────────────────────────────────────────────────┤
│ Role: Generate interview questions based on sources                 │
│ LLM: DeepSeek via OpenRouter (for quality Q&A)                      │
│ For each skill:                                                      │
│   1. Use source content to generate interview questions             │
│   2. Format as JSON with unique questions                           │
├─────────────────────────────────────────────────────────────────────┤
│ OUTPUT: agent3_question_generator_output.json                       │
│ {                                                                    │
│   "interview_questions": {                                           │
│     "Python": {                                                      │
│       "questions": [                                                │
│         "What are decorators in Python and how do they work?",     │
│         "Explain the difference between lists and tuples...",      │
│         ...                                                          │
│       ],                                                             │
│       "status": "success"                                           │
│     },                                                               │
│     "JavaScript": { ... }                                           │
│   },                                                                 │
│   "total_questions": 42                                             │
│ }                                                                    │
└─────────────────────────────────────────────────────────────────────┘
           ↓
OUTPUT: Final Interview Prep Questions organized by skill
```

## Data Flow Diagram

```
STEP 1: Extract & Analyze
┌──────────────┐
│ Resume File  │
│ (PDF/DOCX)   │
└──────┬───────┘
       │
       ↓
┌─────────────────────────────────┐
│ Extract Text (file_text_extractor) │
└────────────┬────────────────────┘
             │
             ↓
      ┌─────────────┐
      │Resume Text  │
      └────────┬────┘
               │
               ↓
    ┌─────────────────────┐
    │Skill Extractor Tool │
    │(with Groq LLM)      │
    └────────┬────────────┘
             │
             ↓
       ┌──────────────────┐
       │Skills JSON       │
       │[Python, JS, ...]│
       └────────┬─────────┘
                │
                ↓ [SAVED: agent1_resume_analyzer_output.json]


STEP 2: Search & Extract Sources
┌──────────────────────┐
│ Skills from Step 1   │
└──────────┬───────────┘
           │
    For each skill:
           │
           ↓
    ┌─────────────────────────┐
    │ Google Search Tool      │
    │ (SerperDev)             │
    └──────┬──────────────────┘
           │
           ↓
      ┌────────────┐
      │ URLs List  │
      └────┬───────┘
           │
           ↓
  ┌──────────────────────────────┐
  │Smart Web Content Extractor  │
  │ (with Gemini Flash LLM)      │
  └──────┬───────────────────────┘
         │
         ↓
    ┌──────────────────┐
    │Source Content    │
    │(relevant text)   │
    └────────┬─────────┘
             │
             ↓ [SAVED: agent2_source_discoverer_output_full.json]


STEP 3: Generate Questions
┌────────────────────────────────┐
│Skills + Source Content from    │
│Steps 1 & 2                     │
└──────────┬─────────────────────┘
           │
    For each skill:
           │
           ↓
    ┌────────────────────────────┐
    │Question Generator Tool     │
    │(DeepSeek via OpenRouter)   │
    │(LiteLLM)                   │
    └──────┬─────────────────────┘
           │
           ↓
      ┌───────────────────────┐
      │Generated Questions    │
      │(as JSON Array)        │
      └────────┬──────────────┘
               │
               ↓ [SAVED: agent3_question_generator_output.json]
```

## Key Technical Details

### Agent Configurations

#### Agent 1: Resume Analyzer
```python
Agent(
    role='Resume Analyzer',
    goal='Extract all text from a resume file and identify key technical skills',
    llm=llm_groq,  # Groq llama3-70b for accuracy
    tools=[file_text_extractor, skill_extractor]
)
```

#### Agent 2: Source Discoverer
```python
Agent(
    role='Source Discoverer',
    goal='Find the best web pages with technical interview questions',
    llm=llm_gemini_flash,  # Gemini for content extraction
    tools=[google_search_tool, smart_web_content_extractor]
)
```

#### Agent 3: Question Generator
```python
Agent(
    role='Question Generator',
    goal='Generate insightful interview questions based on sources',
    llm=llm_openrouter,  # DeepSeek for quality questions
    tools=[question_generator]
)
```

## Error Fixes Applied

### Issue 1: CrewOutput Type Mismatch ✅
```python
# BEFORE (Error):
skills_data = json.loads(skill_result)  # skill_result is CrewOutput

# AFTER (Fixed):
skill_result_str = str(skill_result)
skills_data = json.loads(skill_result_str)
```

### Issue 2: Parameter Type Mismatch ✅
```python
# BEFORE (Error):
extract_task = self.tasks.extract_web_content_task(
    source_discoverer, 
    urls="{search_sources_task}",  # expects list[str]
    skill=skill
)

# AFTER (Fixed):
extract_task = self.tasks.extract_web_content_task(
    source_discoverer,
    urls_reference="{search_sources_task}",  # now accepts string reference
    skill=skill
)
```

## Features Implemented

✅ **Modular Agent Testing**: Each agent can be tested independently
✅ **JSON-Based Communication**: Clean JSON files between agents
✅ **No Dump Files**: Only structured output files
✅ **Resume File Path Support**: Direct file path parameter
✅ **Multiple Format Support**: PDF, DOCX, TXT
✅ **Error Handling**: Graceful fallbacks with error messages
✅ **Sample Data**: Auto-generated sample resume for testing

## Running the System

### Test Single Agent:
```bash
python backend/tests/test_agent_1_resume_analyzer.py
```

### Test All Agents Sequentially:
```bash
python backend/tests/run_complete_pipeline.py
```

### Use in Production:
```python
from backend.crew import InterviewPrepCrew

crew = InterviewPrepCrew(file_path="path/to/resume.pdf")
result = crew.run()
# Returns: [{"skill": "Python", "questions": [...], ...}]
```

## Environment Requirements

```
GROQ_API_KEY=your_key
OPENROUTER_API_KEY=your_key
GOOGLE_API_KEY=your_key
SERPER_API_KEY=your_key
```

## Success Criteria Met

✅ Errors fixed in crew.py
✅ Each agent tested independently
✅ Results saved as JSON between agents
✅ First agent accepts PDF resume path
✅ No dump result files created
✅ Full testing infrastructure in place
