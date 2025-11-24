"""
Source discovery business logic for the second agent.

This module contains the core functionality for discovering and enhancing
technical learning resources using Gemini's Google Search grounding.
"""
import asyncio
import logging
import re
from typing import Optional, Dict, List, Any

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
    skill: str,
    error_message: Optional[str] = None
) -> Dict:
    """Create fallback content when primary search fails."""
    content_msg = f"Fallback response for {skill}. Consider manual search for better results."
    if error_message:
        content_msg += f"\n\nDEBUG INFO: Search failed with error: {error_message}"
    
    return {
        "skill": skill,
        "raw_content": content_msg
    }


async def discover_sources(skills: List[str]) -> List[Dict]:
    """
    Discover authoritative web sources using Gemini's native search grounding.
    
    This function uses Google Search grounding to find relevant technical resources
    for a list of skills, batching them to optimize requests.
    
    Args:
        skills: A list of skills/topics to search for.
        
    Returns:
        A list of dictionaries, each containing the skill and raw Gemini response text.
    """
    results = []
    chunk_size = 3
    
    # Process skills in batches of 3
    for i in range(0, len(skills), chunk_size):
        chunk = skills[i:i + chunk_size]
        logger.info(f"Processing batch: {chunk}")
        
        try:
            # Generate optimized queries for the chunk
            skills_with_queries = []
            for skill in chunk:
                try:
                    opt_query = optimize_search_query(skill)
                    skills_with_queries.append(f"- Skill: {skill} -> Query: {opt_query}")
                except Exception as e:
                    logger.warning(f"Query optimization failed for '{skill}': {e}. Using original.")
                    skills_with_queries.append(f"- Skill: {skill} -> Query: {skill}")
            
            skills_block = "\n".join(skills_with_queries)

            # Construct the prompt for the batch using "Split-Search" pattern
            prompt = f"You are an expert technical researcher. Perform a 'Split-Search' for the following skills using the specific queries provided:\n\n{skills_block}\n\n"
            prompt += "For EACH skill in the list, you MUST:\n"
            prompt += "1. Execute the EXACT provided search query for that skill.\n"
            prompt += "2. Find exactly equivalent number of high-quality technical sources of each skill (minimum 3 sources per skill). THIS IS A HARD REQUIREMENT.\n"
            prompt += "3. Extract dense technical content covering: core concepts, problem-solving, terminology, best practices, and challenges.\n\n"
            
            prompt += "CRITICAL OUTPUT RULES:\n"
            prompt += "- You MUST separate the response for each skill with the marker '## {SkillName}'.\n"
            prompt += "- Do NOT merge the results. Keep each skill's content distinct.\n"
            prompt += "- Ensure the content is suitable for an expert interviewer.\n"

            # Execute search with Google Search grounding
            try:
                client = get_genai_client()
            except Exception as e:
                logger.error(f"Failed to initialize GenAI client: {e}")
                results.extend([create_fallback_sources(s, error_message="LLM Client Initialization Failed") for s in chunk])
                continue

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
                contents=prompt,
                config=config,
                service_name='gemini',
                rate_limiter=gemini_search_limiter
            )

            response_text = response.text if response.text else ""
            
            # Parse the response to separate content for each skill
            batch_results = parse_batch_response(response_text, chunk, response)
            results.extend(batch_results)

        except asyncio.TimeoutError:
            logger.error(f"Search timed out for batch {chunk}")
            results.extend([create_fallback_sources(s, error_message="Search timed out.") for s in chunk])
        except (ResourceExhausted, TooManyRequests) as e:
            logger.error(f"Rate limit exceeded for batch {chunk}: {e}")
            results.extend([create_fallback_sources(s, error_message="Rate limit exceeded.") for s in chunk])
        except Exception as e:
            logger.error(f"Search failed for batch {chunk}: {e}", exc_info=True)
            results.extend([create_fallback_sources(s, error_message=str(e)) for s in chunk])

    return results

def parse_batch_response(text: str, skills: List[str], response: Any) -> List[Dict]:
    """
    Parses the batch response text to extract content for each skill.
    Uses markers '## {SkillName}' to split the text.
    Also maps grounding metadata to verify sources.
    """
    results = []
    
    # Create a map of skill to its content
    skill_content_map = {}
    
    # Find start indices of each skill marker
    skill_positions = []
    for skill in skills:
        # Case insensitive search for the marker
        pattern = re.compile(re.escape(f"## {skill}"), re.IGNORECASE)
        match = pattern.search(text)
        if match:
            skill_positions.append((match.start(), skill))
        else:
            logger.warning(f"Marker '## {skill}' not found in response.")
            
    # Sort by position
    skill_positions.sort(key=lambda x: x[0])
    
    # Extract content slices
    for i, (start_pos, skill) in enumerate(skill_positions):
        end_pos = skill_positions[i+1][0] if i + 1 < len(skill_positions) else len(text)
        
        content_chunk = text[start_pos:end_pos]
        
        # Remove the marker line
        lines = content_chunk.split('\n')
        if lines and lines[0].strip().lower().startswith(f"## {skill}".lower()):
            content_chunk = "\n".join(lines[1:]).strip()
        
        # Map citations
        sources_found = []
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'grounding_metadata') and candidate.grounding_metadata:
                metadata = candidate.grounding_metadata
                if hasattr(metadata, 'grounding_supports') and metadata.grounding_supports:
                    for support in metadata.grounding_supports:
                        # Check if support segment is within our chunk
                        seg_start = support.segment.start_index
                        seg_end = support.segment.end_index
                        
                        if seg_start >= start_pos and seg_end <= end_pos:
                            # This support belongs to this skill
                            if hasattr(metadata, 'grounding_chunks') and metadata.grounding_chunks:
                                for chunk_idx in support.grounding_chunk_indices:
                                    if chunk_idx < len(metadata.grounding_chunks):
                                        chunk_data = metadata.grounding_chunks[chunk_idx]
                                        if hasattr(chunk_data, 'web'):
                                            sources_found.append(chunk_data.web.uri)
        
        # Deduplicate sources
        sources_found = list(set(sources_found))
        
        logger.info(f"Skill '{skill}': Found {len(sources_found)} unique sources.")
        
        # Append sources to content for the Agent to see
        if sources_found:
            content_chunk += "\n\n### Discovered Sources:\n" + "\n".join(f"- {url}" for url in sources_found)
            
        skill_content_map[skill] = content_chunk

    # Fill results, handling missing skills
    for skill in skills:
        if skill in skill_content_map:
            results.append({"skill": skill, "raw_content": skill_content_map[skill]})
        else:
            results.append(create_fallback_sources(skill, error_message="Skill content not found in batch response."))
            
    return results
