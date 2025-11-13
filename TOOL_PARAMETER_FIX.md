# SerperDev Tool Parameter Validation Fix

## Problem
When running test agent 2, you encountered this error:
```
Arguments validation failed: 1 validation error for SerperDevToolSchema
search_query
  Field required [type=missing, input_value={'query': 'Machine Learning...}]
```

## Root Cause
The `SerperDevTool` from `crewai_tools` expects a parameter named `search_query`, but the agents were calling it with a `query` parameter. This caused a Pydantic validation error.

## Solution Applied

### Changes Made in `backend/tools/tools.py`

#### 1. Wrapped SerperDevTool with Custom Function
**Before:**
```python
google_search_tool = SerperDevTool()  # Direct tool with incorrect parameter mapping
```

**After:**
```python
_serper_tool = SerperDevTool()  # type: ignore

@tool
def google_search_tool(search_query: str) -> str:
    """Performs a Google search for a given query and returns relevant snippets and URLs."""
    try:
        result = _serper_tool.run(search_query=search_query)
        return str(result) if result else "No results found"
    except Exception as e:
        return f"Error performing search: {e}"
```

**Benefits:**
- Ensures the parameter is always named `search_query` correctly
- Provides error handling
- Makes the tool interface clearer to agents

#### 2. Updated Web Content Extractor
**Before:**
```python
def smart_web_content_extractor(urls: list[str], query: str) -> str:
```

**After:**
```python
def smart_web_content_extractor(search_query: str, urls: list = None) -> str:
```

**Improvements:**
- Reordered parameters for consistency
- Added proper type handling for URLs (handles JSON strings, dicts, lists)
- Added parsing for different URL formats returned by agents
- Better error handling for malformed input

## How It Works Now

1. **Google Search Tool**: Agents call it with `search_query` → wrapped tool calls SerperDev correctly
2. **Web Content Extractor**: Agents can now pass URLs in multiple formats → tool normalizes them internally
3. **Parameter Validation**: All parameters match Pydantic schemas → no validation errors

## Testing

Run your test again:
```bash
python backend/tests/test_agent_2_source_discoverer.py
```

The SerperDev parameter validation error should now be resolved.

## Key Takeaways
- CrewAI tools require exact parameter matching with their Pydantic schemas
- When wrapping third-party tools, ensure parameter names align with what the library expects
- JSON responses from agents should be parsed into the format expected by downstream tools
