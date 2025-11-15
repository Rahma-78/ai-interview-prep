from __future__ import annotations

from crewai_tools import SerperDevTool

# Initialize SerperDevTool at module level to avoid circular dependency
_serper_tool = SerperDevTool(
    name="Google Search Tool",
    description="A tool to perform Google searches using SerperDev API."
)

def get_serper_tool() -> SerperDevTool:
    """
    Returns the initialized SerperDevTool instance.
    
    Returns:
        SerperDevTool: The configured SerperDevTool instance for Google searches.
    """
    return _serper_tool