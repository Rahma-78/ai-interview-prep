"""
Source discovery business logic for the second agent.

This module contains the core functionality for discovering and enhancing
technical learning resources using Gemini's Google Search grounding.
"""
import asyncio
import logging
from typing import Optional, Dict

from google.genai import types
from google.api_core.exceptions import (
    ClientError,
    ResourceExhausted,
    ServiceUnavailable,
    TooManyRequests,
)

from app.schemas.interview import AllSkillSources, SkillSources
from app.services.tools.llm_config import get_genai_client, GEMINI_MODEL
from app.services.tools.helpers import optimize_search_query
from app.services.tools.utils import execute_with_retry, AsyncRateLimiter
from app.core.config import settings

logger = logging.getLogger(__name__)

# Create dedicated rate limiter for Gemini search tool only
# This isolates its quota management from other services
gemini_search_limiter = AsyncRateLimiter(requests_per_minute=settings.GEMINI_RPM)


def create_fallback_sources(
    search_query: str,
    error_message: Optional[str] = None
) -> Dict:
    """Create fallback content when primary search fails."""
    content_msg = f"Fallback response for {search_query}. Consider manual search for better results."
    if error_message:
        content_msg += f"\n\nDEBUG INFO: Search failed with error: {error_message}"
    
    return {
        "skill": search_query,
        "raw_content": content_msg
    }


async def discover_sources(search_query: str) -> Dict:
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
        try:
            optimized_query = optimize_search_query(search_query)
            logger.info(f"Discovering sources for '{optimized_query}' using Gemini native search")
        except Exception as e:
            logger.warning(f"Query optimization failed for '{search_query}': {e}. Using original query.")
            optimized_query = search_query

        # Execute search with Google Search grounding
        try:
            client = get_genai_client()
        except Exception as e:
            logger.error(f"Failed to initialize GenAI client: {e}")
            return create_fallback_sources(search_query, error_message="LLM Client Initialization Failed")
        
        search_prompt = f"""
        Find resources of high quality technical content about '{optimized_query}' that would be useful for generating interview questions.

        IMPORTANT: Return ONLY 2-3 sources maximum. Focus on quality over quantity.
        
        Extract the most relevant technical content suitable for generating interview questions covering:
        - Core technical concepts and fundamentals
        - Common problem-solving approaches and patterns
        - Key terminology and definitions
        - Best practices and important considerations
        - Typical challenges and solutions
        
        CRITICAL FORMATTING INSTRUCTION:
        - Do NOT list the selected resources or URLs in the response body.
        - Ensure the content is dense, informative, and suitable for an expert interviewer context.
        """

        # Configure Google Search grounding tool
        grounding_tool = types.Tool(
            google_search=types.GoogleSearch()
        )
        
        config = types.GenerateContentConfig(
            tools=[grounding_tool]
        )

        # Execute grounded search with retry logic using dedicated rate limiter
        response = await execute_with_retry(
            asyncio.to_thread,
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=search_prompt,
            config=config,
            service_name='gemini',
            rate_limiter=gemini_search_limiter  # Use dedicated limiter for isolation
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
        return {
            "skill": search_query,
            "raw_content": response_text
        }

    except asyncio.TimeoutError:
        logger.error(f"Search timed out for '{search_query}'")
        return create_fallback_sources(search_query, error_message="Search timed out.")
    except (ResourceExhausted, TooManyRequests) as e:
        logger.error(f"Rate limit exceeded for '{search_query}': {e}")
        return create_fallback_sources(search_query, error_message="Rate limit exceeded. Please try again later.")
    except ServiceUnavailable as e:
        logger.error(f"Service unavailable for '{search_query}': {e}")
        return create_fallback_sources(search_query, error_message="Service temporarily unavailable.")
    except ClientError as e:
        logger.error(f"Client error for '{search_query}': {e}")
        return create_fallback_sources(search_query, error_message=f"Client error: {str(e)}")
    except Exception as e:
        logger.error(f"Search failed for '{search_query}': {e}", exc_info=True)
        return create_fallback_sources(search_query, error_message=str(e))
