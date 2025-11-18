# Project Documentation Rules (Non-Obvious Only)

## Architecture Context
- **Multi-Agent System**: Three specialized agents with distinct LLMs and responsibilities
- **Sequential Processing**: Agent 1 → Agent 2 → Agent 3 pipeline with JSON file dependencies
- **CrewAI Framework**: Uses CrewAI for orchestration but with custom async patterns

## Agent-Specific Details
- **Agent 1 (Resume Analyzer)**: Uses Groq LLM with specific constraints - extracts technical skills from PDFs
- **Agent 2 (Source Discoverer)**: Uses Gemini Flash for web search and content extraction
- **Agent 3 (Question Generator)**: Uses OpenRouter for generating interview questions from sources

## File Structure Insights
- **Test Dependencies**: Each agent test depends on previous agent's JSON output
- **Centralized Configuration**: All settings in `app/core/config.py` via pydantic-settings
- **Tool Organization**: Tools in `app/services/tools/` with specific async requirements

## Data Flow Patterns
- **JSON Communication**: Agents communicate via JSON files, not direct object passing
- **Schema Validation**: All outputs validated against Pydantic schemas in `app/schemas/interview.py`
- **Async Processing**: Despite synchronous appearance, most operations are async with proper await patterns

## API Integration Details
- **Multiple LLM Providers**: Groq, Gemini, OpenRouter - each with specific configurations
- **Rate Limiting**: Global `async_rate_limiter` manages API quotas across all providers
- **Search Integration**: Uses SerperDev API for Google searches with custom query optimization

## Error Handling Approach
- **Graceful Degradation**: Tools return fallback results rather than crashing
- **Structured Errors**: All errors returned in JSON format with specific error types
- **Async Recovery**: Rate limiter automatically handles API quota exhaustion

## Testing Architecture
- **Sequential Testing**: Must run tests in order due to JSON file dependencies
- **Output Files**: Tests generate specific JSON files that subsequent tests depend on
- **CrewOutput Parsing**: Results must be converted to strings before JSON parsing