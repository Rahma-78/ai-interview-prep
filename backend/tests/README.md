# Interview Prep AI Agent Testing Guide

## Overview

This directory contains comprehensive test scripts for the three-agent AI interview preparation system. Each agent operates independently and passes its output to the next agent as JSON files.

## Agents

### Agent 1: Resume Analyzer
- **Role**: Extracts text from resume files and identifies key technical skills
- **Input**: PDF/DOCX/TXT resume file path
- **Output**: List of technical skills
- **Test File**: `test_agent_1_resume_analyzer.py`

### Agent 2: Source Discoverer
- **Role**: Finds relevant web sources and extracts content for each skill
- **Input**: List of skills from Agent 1
- **Output**: URLs and extracted content for each skill
- **Test File**: `test_agent_2_source_discoverer.py`

### Agent 3: Question Generator
- **Role**: Generates interview questions based on skills and source content
- **Input**: Skills from Agent 1 + Source content from Agent 2
- **Output**: List of interview questions for each skill
- **Test File**: `test_agent_3_question_generator.py`

## Running Tests

### Quick Start: Run Complete Pipeline

```bash
cd backend/tests
python run_complete_pipeline.py
```

This will run all three agents sequentially and generate all output files.

### Individual Agent Testing

#### Test Agent 1 (Resume Analyzer)

```bash
python test_agent_1_resume_analyzer.py
```

**Output files:**
- `step1_extracted_resume_text.json` - Raw extracted text
- `step2_identified_skills.json` - Identified skills
- `agent1_resume_analyzer_output.json` - Final output (skills list)

#### Test Agent 2 (Source Discoverer)

```bash
python test_agent_2_source_discoverer.py
```

**Requirements:** Agent 1 must be run first to generate `agent1_resume_analyzer_output.json`

**Output files:**
- `agent2_source_discoverer_output.json` - Summary (URLs and content lengths)
- `agent2_source_discoverer_output_full.json` - Full content from sources

#### Test Agent 3 (Question Generator)

```bash
python test_agent_3_question_generator.py
```

**Requirements:** Agent 1 and Agent 2 must be run first

**Output files:**
- `agent3_question_generator_output.json` - All questions
- `agent3_question_generator_summary.json` - Summary (question counts)

## Output JSON Structure

### Agent 1 Output Format
```json
{
  "resume_file": "path/to/resume.txt",
  "extracted_text_length": 5432,
  "skills": [
    "Python",
    "JavaScript",
    "Docker",
    "AWS",
    "React"
  ],
  "status": "success"
}
```

### Agent 2 Output Format (Summary)
```json
{
  "skills": ["Python", "JavaScript"],
  "sources_discovered": {
    "Python": {
      "urls": ["https://...", "https://..."],
      "content_length": 15234,
      "status": "success"
    }
  },
  "status": "success"
}
```

### Agent 3 Output Format
```json
{
  "skills": ["Python", "JavaScript"],
  "interview_questions": {
    "Python": {
      "question_count": 8,
      "status": "success"
    }
  },
  "total_questions": 16,
  "status": "success"
}
```

## Testing with Your Own Resume

### Option 1: Replace Sample Resume
Edit `backend/tests/sample_resume.txt` with your resume content.

### Option 2: Use Custom Path
In any test script, modify the path at the bottom:

```python
if __name__ == "__main__":
    resume_path = "path/to/your/resume.pdf"  # or .docx, .txt
    result = test_resume_analyzer_agent(resume_path)
```

## Supported Resume Formats

- PDF (.pdf)
- Word Document (.docx)
- Plain Text (.txt)

## Key Features

✅ **No Dump Files**: Intermediate results are saved as clean JSON files only when needed
✅ **Modular Testing**: Test each agent independently
✅ **Clear Output**: JSON files with both summary and detailed versions
✅ **File Path Handling**: Agents accept resume file paths directly
✅ **Error Handling**: Graceful error messages and fallbacks

## Troubleshooting

### Agent 1 Issues
- Ensure resume file exists and is readable
- Check file extension (.pdf, .docx, or .txt)
- Verify PyPDF2 or python-docx is installed

### Agent 2 Issues
- Requires internet connection for Google Search
- Verify SerperDevTool API key is set in `.env`
- Check error messages for specific failed URLs

### Agent 3 Issues
- Requires Agent 2 output with content
- Check LLM API keys are configured
- Verify JSON parsing of generated questions

## Environment Setup

Ensure all required API keys are in your `.env` file:
```
GROQ_API_KEY=your_groq_key
OPENROUTER_API_KEY=your_openrouter_key
GOOGLE_API_KEY=your_google_key
SERPER_API_KEY=your_serper_key
```

## File Organization

```
backend/tests/
├── __init__.py
├── test_agent_1_resume_analyzer.py
├── test_agent_2_source_discoverer.py
├── test_agent_3_question_generator.py
├── run_complete_pipeline.py
├── sample_resume.txt
├── agent1_resume_analyzer_output.json
├── agent2_source_discoverer_output.json
├── agent2_source_discoverer_output_full.json
├── agent3_question_generator_output.json
└── agent3_question_generator_summary.json
```

## Next Steps

After successful testing:
1. Review JSON outputs to verify quality
2. Integrate with main.py for API endpoints
3. Modify resume files as needed for your use case
4. Adjust LLM prompts in tools.py for better results
