# Project Coding Rules (Non-Obvious Only)

## Agent Configuration
- **Agent 1 (Resume Analyzer)**: Must use `max_iter=3`, `max_rpm=30`, `cache=False` for Groq LLM
- **Agent 2 (Source Discoverer)**: Must use `async_execution=True` for Gemini Flash
- **Agent 3 (Question Generator)**: Must use `temperature=0.7` for OpenRouter
- **Response Format**: All agents require `response_format` parameter for structured JSON output

## Async Processing Requirements
- **Rate Limiter**: Global `async_rate_limiter` in `app/services/tools/utils.py` must be awaited before API calls
- **Event Loop**: Web content extractor creates new event loops when needed - never use `asyncio.get_event_loop()` directly
- **Tool Execution**: All CrewAI tools must use `async_execution=True` and proper `await` syntax

## File Processing Constraints
- **PDF Only**: `file_text_extractor` only supports PDF files - returns error for other formats
- **Temporary Files**: API creates `temp_{filename}` files and cleans them up automatically
- **File Path**: Crew instances require `file_path` parameter even for testing

## API Key Configuration
- **Centralized Settings**: All API keys loaded from `app.core.config.settings` via pydantic-settings
- **Required Keys**: 
  - `GROQ_API_KEY` for skill extraction
  - `GEMINI_API_KEY` for web content extraction  
  - `OPENROUTER_API_KEY` for question generation
  - `SERPER_API_KEY` for Google search functionality

## Test Dependencies
- **Sequential Testing**: Agent tests must be run in order (1 → 2 → 3) as each produces output for the next
- **JSON Output**: Tests save results to specific JSON files that subsequent tests depend on
- **CrewOutput Parsing**: Results must be converted to strings before JSON parsing: `json.loads(str(result))`

## Import Structure
- **Tool Registration**: Tools must be explicitly passed as dictionaries to agents
- **Schema Validation**: All outputs validated against Pydantic schemas in `app/schemas/interview.py`
- **Centralized LLM**: LLM instances managed in `app/services/tools/llm.py` via settings object