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
    """Create fallback sources when primary search fails."""
    fallback_uris = [
        f"https://en.wikipedia.org/wiki/{search_query.replace(' ', '_')}",
        f"https://www.google.com/search?q={search_query.replace(' ', '+')}",
    ]
    
    content_msg = f"Fallback sources for {search_query}. Consider manual search for better results."
    if error_message:
        content_msg += f"\n\nDEBUG INFO: Search failed with error: {error_message}"
    
    skill_sources = SkillSources(
        skill=search_query,
        sources=[
            {"url": uri, "title": f"Fallback source for {search_query}", "content": ""}
            for uri in fallback_uris
        ],
        extracted_content=content_msg
    )
    
    return AllSkillSources(all_sources=[skill_sources])


async def discover_sources(search_query: str) -> AllSkillSources:
    """
    Discover authoritative web sources using Gemini's native search grounding.
    
    This function uses Google Search grounding to find relevant technical resources
    and returns both the sources and a summary of the content.
    
    Args:
        search_query: The skill/topic to search for
        
    Returns:
        AllSkillSources containing discovered sources and extracted content
    """
    try:
        optimized_query = optimize_search_query(search_query)
        logger.info(f"Discovering sources for '{optimized_query}' using Gemini native search")

        # Execute search with Google Search grounding
        client = get_genai_client()
        
        search_prompt = f"""
        Find technical resources of high quality technical content that would be useful for generating interview questions about '{optimized_query}' .

        IMPORTANT: Return ONLY 2-3 sources maximum. Focus on quality over quantity.
        
        Extract the most relevant technical content covering:
        - Core technical concepts and fundamentals
        - Common problem-solving approaches and patterns
        - Key terminology and definitions
        - Best practices and important considerations
        - Typical challenges and solutions
        
        Provide a comprehensive summary (300-500 words) suitable for generating interview questions.
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

        # Extract sources from grounding metadata
        sources = []
        source_content_map = {}  # Map chunk index to content snippets
        
        if response.candidates and response.candidates[0].grounding_metadata:
            gm = response.candidates[0].grounding_metadata
            response_text = response.text if response.text else ""
            
            # First, extract content snippets from grounding_supports
            if hasattr(gm, 'grounding_supports') and gm.grounding_supports:
                for support in gm.grounding_supports:
                    # Extract the text segment this support refers to
                    if hasattr(support, 'segment'):
                        start_idx = support.segment.start_index if hasattr(support.segment, 'start_index') else 0
                        end_idx = support.segment.end_index if hasattr(support.segment, 'end_index') else len(response_text)
                        snippet = response_text[start_idx:end_idx]
                        
                        # Map this snippet to the grounding chunk indices
                        if hasattr(support, 'grounding_chunk_indices'):
                            for chunk_idx in support.grounding_chunk_indices:
                                if chunk_idx not in source_content_map:
                                    source_content_map[chunk_idx] = []
                                source_content_map[chunk_idx].append(snippet)
            
            # Now extract sources with their content
            if hasattr(gm, 'grounding_chunks') and gm.grounding_chunks:
                # Limit to top 3 sources
                for idx, chunk in enumerate(gm.grounding_chunks[:3]):
                    if hasattr(chunk, 'web') and chunk.web:
                        # Get content snippets for this chunk
                        content_snippets = source_content_map.get(idx, [])
                        content = " ".join(content_snippets)[:800] if content_snippets else ""
                        
                        sources.append({
                            "url": chunk.web.uri,
                            "title": chunk.web.title,
                            "content": content
                        })
        
        # Get summary from response text (this is the grounded content)
        extracted_content = response.text[:2000] if response.text else ""
        
        # Fallback: if response.text is empty but we have sources with content, use that
        if not extracted_content and sources:
            logger.warning(f"Response text empty for '{search_query}', using source content as fallback")
            extracted_content = " ".join(s.get('content', '') for s in sources if s.get('content'))[:2000]
        
        # Clean and format the extracted content for better LLM processing
        if extracted_content:
            # Remove extra whitespace and normalize
            extracted_content = " ".join(extracted_content.split())
            # Ensure it ends with proper punctuation
            if extracted_content and not extracted_content[-1] in '.!?':
                # Find last complete sentence
                last_period = max(
                    extracted_content.rfind('.'),
                    extracted_content.rfind('!'),
                    extracted_content.rfind('?')
                )
                if last_period > 0:
                    extracted_content = extracted_content[:last_period + 1]
        
        # Format individual source content similarly
        for source in sources:
            if source.get('content'):
                content = source['content']
                # Clean whitespace
                content = " ".join(content.split())
                # Ensure complete sentences
                if content and not content[-1] in '.!?':
                    last_period = max(
                        content.rfind('.'),
                        content.rfind('!'),
                        content.rfind('?')
                    )
                    if last_period > 0:
                        content = content[:last_period + 1]
                source['content'] = content
        
        # Validation
        if len(sources) < 2:
            logger.warning(f"Insufficient sources found for '{search_query}' (found {len(sources)}, need at least 2)")
            return create_fallback_sources(
                search_query,
                error_message=f"Only {len(sources)} source(s) found in grounding metadata, need at least 2"
            )
        
        if len(extracted_content) < 100:
            logger.warning(f"Content too short for '{search_query}'. Returning fallback.")
            return create_fallback_sources(
                search_query, 
                error_message="Content too short (<100 chars) after extraction."
            )

        logger.info(f"Successfully discovered {len(sources)} sources for '{search_query}'")
        
        return AllSkillSources(all_sources=[
            SkillSources(
                skill=search_query,
                sources=sources,
                extracted_content=extracted_content
            )
        ])

    except asyncio.TimeoutError:
        logger.error(f"Search timed out for '{search_query}'")
        return create_fallback_sources(search_query, error_message="Search timed out.")
    except Exception as e:
        logger.error(f"Search failed for '{search_query}': {e}", exc_info=True)
        return create_fallback_sources(search_query, error_message=str(e))
