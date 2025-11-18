# Project Debug Rules (Non-Obvious Only)

## Async Debugging Patterns
- **Rate Limiter Logging**: Check `async_rate_limiter` logs for API quota issues - it automatically handles backoff
- **Event Loop Issues**: Web content extractor creates new event loops when needed - never use `asyncio.get_event_loop()` directly
- **CrewOutput Debugging**: Use `str(result)` before JSON parsing - CrewOutput objects don't serialize directly

## File Processing Debugging
- **PDF Extraction**: Only PDF files supported - other formats return specific error messages
- **Temporary Files**: Look for `temp_{filename}` files in current directory - they're auto-created and cleaned up
- **File Path Issues**: Crew instances require `file_path` parameter even for testing - placeholder files work

## API Key Debugging
- **Environment Loading**: API keys loaded from `app/core/.env` via pydantic-settings - check file exists and has correct keys
- **Missing Keys**: Specific error messages for each missing API key - check `app/core/config.py` for exact key names
- **Key Validation**: All keys validated at startup - missing keys cause immediate application failure

## Test Debugging
- **Sequential Testing**: Agent tests must run in order (1 → 2 → 3) - each produces JSON output for the next
- **JSON File Dependencies**: Check for output files in `app/tests/`:
  - `extracted_skills.json` (Agent 1)
  - `discovered_sources.json` (Agent 2)  
  - `agent3_question_generator_output.json` (Agent 3)
- **CrewOutput Parsing**: Always use `json.loads(str(result))` - CrewOutput objects need string conversion

## Error Recovery Patterns
- **API Failures**: Tools return fallback results when APIs fail - check logs for fallback usage
- **JSON Parsing**: Graceful degradation with error messages in JSON format - never crashes the application
- **Async Errors**: All async operations wrapped in try/catch - check logs for specific error types

## Logging Patterns
- **Structured Logging**: All logging uses format: `%(asctime)s - %(levelname)s - %(message)s`
- **Debug Mode**: Controlled by `settings.DEBUG_MODE` - affects agent verbosity
- **Tool Logging**: Each tool has its own logger - check module-specific logs