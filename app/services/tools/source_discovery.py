"""
Source discovery business logic for the second agent.

This module contains the core functionality for discovering and enhancing
technical learning resources using Gemini's Google Search grounding.
"""
import asyncio
import logging
from typing import Optional

from google.genai import types

from app.schemas.interview import AllSkillSources, SkillSources
from app.services.tools.llm_config import get_genai_client, GEMINI_MODEL
from app.services.tools.helpers import optimize_search_query

logger = logging.getLogger(__name__)


def create_fallback_sources(
    search_query: str,
    error_message: Optional[str] = None
) -> AllSkillSources:
    """Create fallback content when primary search fails."""
    content_msg = f"Fallback response for {search_query}. Consider manual search for better results."
    if error_message:
        content_msg += f"\n\nDEBUG INFO: Search failed with error: {error_message}"
    
    skill_sources = SkillSources(
        skill=search_query,
        extracted_content=content_msg
    )
    
    return AllSkillSources(all_sources=[skill_sources])


async def discover_sources(search_query: str) -> AllSkillSources:
    """
    Discover authoritative web sources using Gemini's native search grounding.
    
    This function uses Google Search grounding to find relevant technical resources
    and returns the skill along with the raw response text from Gemini.
    
    Args:
        search_query: The skill/topic to search for
        
    Returns:
        AllSkillSources containing the skill and raw Gemini response text
    """
    try:
        optimized_query = optimize_search_query(search_query)
        logger.info(f"Discovering sources for '{optimized_query}' using Gemini native search")

        # Execute search with Google Search grounding
        client = get_genai_client()
        
        search_prompt = f"""
        Find resources of high quality technical content about '{optimized_query}' that would be useful for generating interview questions .

        IMPORTANT: Return ONLY 2-3 sources maximum. Focus on quality over quantity.
        
        Extract the most relevant technical content covering:
        - Core technical concepts and fundamentals
        - Common problem-solving approaches and patterns
        - Key terminology and definitions
        - Best practices and important considerations
        - Typical challenges and solutions
        
        Provide a comprehensive summary suitable for generating interview questions.
        """

        # Configure Google Search grounding tool
        grounding_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        
        config = types.GenerateContentConfig(
            tools=[grounding_tool]
        )

        # Execute grounded search
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=search_prompt,
            config=config
        )

        # Get raw response text from Gemini
        response_text = response.text if response.text else ""
        
        # Validate response text
        if len(response_text) < 100:
            logger.warning(f"Response text too short for '{search_query}'. Returning fallback.")
            return create_fallback_sources(
                search_query,
                error_message="Response text too short (<100 chars) from Gemini."
            )

        logger.info(f"Successfully retrieved response text for '{search_query}'")
        
        # Return only skill and raw response text
        return AllSkillSources(all_sources=[
            SkillSources(
                skill=search_query,
                extracted_content=response_text  # Raw Gemini response text
            )
        ])

    except asyncio.TimeoutError:
        logger.error(f"Search timed out for '{search_query}'")
        return create_fallback_sources(search_query, error_message="Search timed out.")
    except Exception as e:
        logger.error(f"Search failed for '{search_query}': {e}", exc_info=True)
        return create_fallback_sources(search_query, error_message=str(e))
