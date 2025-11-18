# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project Stack
- **Backend**: FastAPI with Python 3.9+
- **AI Framework**: CrewAI for multi-agent orchestration
- **LLMs**: Multiple providers (Groq, Gemini, OpenRouter) via CrewAI
- **Testing**: Pytest with async test patterns
- **File Processing**: PyPDF2 for PDF text extraction

## Build/Test Commands

### Run Single Test Agent
```bash
# Test Agent 1 (Resume Analyzer)
python app/tests/test_agent_1_resume_analyzer.py

# Test Agent 2 (Source Discoverer) - requires Agent 1 output
python app/tests/test_agent_2_source_discoverer.py

# Test Agent 3 (Question Generator) - requires Agent 1 & 2 outputs
python app/tests/test_agent_3_question_generator.py
```

### Run Full Pipeline
```bash
# Run FastAPI server
python app/main.py

# Run complete test pipeline (sequential agent testing)
# Requires running each test agent in order: 1 → 2 → 3
```

### Install Dependencies
```bash
pip install -r app/requirements.txt
```

## Critical Non-Obvious Patterns

### Agent Architecture
- **CrewAI Configuration**: Each agent has specific LLM assignments and constraints:
  - Agent 1 (Resume Analyzer): Uses Groq LLM with `max_iter=3`, `max_rpm=30`, `cache=False`
  - Agent 2 (Source Discoverer): Uses Gemini Flash with `async_execution=True`
  - Agent 3 (Question Generator): Uses OpenRouter with `temperature=0.7`
- **Response Format Enforcement**: All agents use `response_format` parameter for structured JSON output

### Async Processing Requirements
- **Rate Limiting**: Global `async_rate_limiter` instance in `app/services/tools/utils.py` manages API quotas
- **Async Tool Execution**: All CrewAI tools must use `async_execution=True` and `await` properly
- **Event Loop Handling**: Web content extractor creates new event loops when needed

### File Processing Constraints
- **PDF Only**: `file_text_extractor` only supports PDF files (returns error for other formats)
- **Temporary Files**: API creates `temp_{filename}` files and cleans them up automatically
- **Resume Path**: Crew instances require `file_path` parameter even for testing

### API Key Configuration
- **Environment Variables**: API keys loaded from `app/core/.env` via `pydantic-settings`
- **Key Requirements**: 
  - `GROQ_API_KEY` for skill extraction
  - `GEMINI_API_KEY` for web content extraction  
  - `OPENROUTER_API_KEY` for question generation
  - `SERPER_API_KEY` for Google search functionality

### Test Data Dependencies
- **Sequential Testing**: Agent tests must be run in order (1 → 2 → 3) as each produces output for the next
- **JSON Output Files**: Tests save results to:
  - `app/tests/extracted_skills.json` (Agent 1)
  - `app/tests/discovered_sources.json` (Agent 2)
  - `app/tests/agent3_question_generator_output.json` (Agent 3)

### Error Handling Patterns
- **CrewOutput Parsing**: Results must be converted to strings before JSON parsing: `json.loads(str(result))`
- **Async Error Recovery**: Rate limiter automatically handles quota exhaustion with backoff
- **Graceful Degradation**: Tools return fallback results when APIs fail

### Import Structure
- **Centralized Settings**: All configuration via `app.core.config.settings`
- **Tool Registration**: Tools must be explicitly passed as dictionaries to agents
- **Schema Validation**: All outputs validated against Pydantic schemas in `app/schemas/interview.py`