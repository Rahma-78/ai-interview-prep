# Project Architecture Rules (Non-Obvious Only)

## System Architecture Constraints
- **Multi-Agent Pipeline**: Three specialized agents with strict sequential dependency
- **CrewAI Orchestration**: Uses CrewAI framework but with custom async execution patterns
- **JSON-Based Communication**: Agents communicate via files, not direct object passing

## Agent Architecture Decisions
- **Specialized LLMs**: Each agent uses different LLM provider (Groq, Gemini, OpenRouter) for specific tasks
- **Async Execution**: All agents require `async_execution=True` despite synchronous appearance
- **Response Format Enforcement**: All agents use `response_format` parameter for structured JSON output

## Data Flow Architecture
- **Sequential Processing**: Agent 1 → Agent 2 → Agent 3 with file-based state management
- **Schema Validation**: All outputs validated against Pydantic schemas - ensures data consistency
- **File-Based State**: JSON files act as state between agents - creates clear boundaries

## Performance Architecture
- **Rate Limiting**: Global `async_rate_limiter` manages API quotas across all agents
- **Async Processing**: Despite synchronous appearance, most operations are async with proper await patterns
- **Caching**: Built-in caching for repeated searches - avoids duplicate API calls

## Error Handling Architecture
- **Graceful Degradation**: Tools return fallback results rather than crashing the pipeline
- **Structured Errors**: All errors returned in JSON format with specific error types
- **Async Recovery**: Rate limiter automatically handles API quota exhaustion with backoff

## Tool Architecture
- **Async Tool Requirements**: All CrewAI tools must use `async_execution=True` and proper `await` syntax
- **Tool Registration**: Tools must be explicitly passed as dictionaries to agents
- **Centralized Configuration**: All tool configurations managed through settings object

## Testing Architecture
- **Sequential Dependencies**: Tests must run in order due to JSON file dependencies
- **File-Based Test Data**: Tests generate JSON files that subsequent tests depend on
- **CrewOutput Parsing**: Results must be converted to strings before JSON parsing

## API Integration Architecture
- **Multiple Provider Strategy**: Different LLM providers for different task types
- **Search Integration**: Uses SerperDev API with custom query optimization
- **Content Extraction**: Smart web content extractor with LLM-based relevance filtering