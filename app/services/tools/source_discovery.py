"""
Source discovery business logic for the second agent.

This module contains the core functionality for discovering and enhancing
technical learning resources using Gemini's Google Search grounding.
"""
import asyncio
import logging
import time
from typing import Dict, List, Tuple, Optional, Any
from google.genai import types
from google.api_core.exceptions import (
    ResourceExhausted,
    TooManyRequests,
)

from app.core.llm import get_genai_client, GEMINI_MODEL
from app.services.tools.helpers import optimize_search_query, parse_batch_response, create_fallback_sources
from app.services.tools.rate_limiter import safe_api_call
from app.core.config import settings
from app.core.exceptions import SourceDiscoveryError

logger = logging.getLogger(__name__)


def _build_skills_block_with_queries(skills: List[str]) -> str:
    """Build formatted skills block with optimized search queries."""
    skills_with_queries = []
    for skill in skills:
        try:
            opt_query = optimize_search_query(skill)
            skills_with_queries.append(f"- Skill: {skill} -> Query: {opt_query}")
        except Exception as e:
            logger.warning(f"Query optimization failed for '{skill}': {e}")
            skills_with_queries.append(f"- Skill: {skill} -> Query: {skill}")
    
    return "\n".join(skills_with_queries)


def _build_detailed_prompt(skills_block: str) -> str:
    """Build detailed prompt for initial source discovery with query optimization."""
    from app.core.config import settings
    max_sources = settings.MAX_SOURCES_PER_SKILL
    
    return "\n".join([
        "You are an expert technical researcher. Perform a 'Split-Search' for the following skills.\n",
        f"{skills_block}\n",
        "INSTRUCTIONS:\n",
        "1. GOAL: Extract dense, technical content for expert interviewers Focus on fundamental concepts and definitions and  practical scenarios.\n",
        "2. SOURCE REQUIREMENTS:\n",
        f"   - ##STRICLY## Find AT MOST {max_sources} DIVERSE technical sources for EACH skill\n",
        "   - Ensure comprehensive coverage from multiple perspectives\n",
        "3. SOURCE HANDLING: Use Google Search to find information, BUT:\n",
        "   - Synthesize the knowledge into your own words.\n",
        "   - Do NOT output a 'Sources' or 'References' list.\n",
        "   - Do NOT output URLs or website titles in the text.\n",
        "   - The final output must look like pure expert knowledge.\n",
        "\n4. CRITICAL OUTPUT FORMAT (follow this EXACTLY):\n",
        "   For EACH skill, create ONE section with this EXACT structure:\n",
        "   \n",
        "   ## Artificial Intelligence\n",
        "   [Technical content paragraphs here...]\n",
        "   \n",
        "   ## Machine Learning\n",
        "   [Technical content paragraphs here...]\n",
        "   \n",
        "   RULES:\n",
        "   - Header MUST start with '## ' (two hashes and ONE space)\n",
        "   - Header MUST match the skill name EXACTLY (preserve capitalization, spaces, special chars)\n",
        "   - Do NOT add colons, quotes, or extra words to headers\n",
        "   - Do NOT skip any skills - provide ALL {len(skills_block.split('\n'))} sections\n",
        "   - Separate each section with blank lines for clarity\n"
    ])


def _build_simplified_prompt(skills: List[str]) -> str:
    """Build simplified retry prompt without query optimization."""
    skills_block = "\n".join([f"- {skill}" for skill in skills])
    skill_count = len(skills)
    
    return (
        "You are an expert technical researcher. Search for the following skills and provide technical content.\n\n"
        f"{skills_block}\n\n"
        f"Create {skill_count} section(s) using this EXACT format:\n\n"
        "## [Exact Skill Name From Above]\n"
        "[Technical content paragraphs...]\n\n"
        "CRITICAL RULES:\n"
        "- Use '## ' (two hashes + ONE space) before each skill name\n"
        "- Match skill names EXACTLY as listed above (same capitalization, punctuation)\n"
        "- Do NOT add colons, quotes, or extra words to headers\n"
        f"- You MUST create exactly {skill_count} section(s) - one for each skill listed\n"
    )


def _extract_grounding_metadata(response: Any) -> Optional[Any]:
    """Extract and normalize grounding metadata from Gemini response."""
    if not (response.candidates and response.candidates[0].grounding_metadata):
        return None
    
    grounding_meta = response.candidates[0].grounding_metadata
    # Ensure grounding_chunks is a list, not None
    if getattr(grounding_meta, "grounding_chunks", None) is None:
        grounding_meta.grounding_chunks = []
    
    return grounding_meta


def _log_response_debug_info(response_text: str, context: str):
    """Log debug information about the Gemini response."""
    # Lazy evaluation: Only formats string if logging level is valid
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"Raw Gemini response length: {len(response_text)} chars for {context}")
        if response_text:
             preview = response_text[:500].replace('\n', ' ')
             logger.debug(f"Response preview: {preview}...")
        else:
             logger.warning(f"Empty response received from Gemini for {context}")


def _separate_failed_skills(parsed_results: List[Dict]) -> Tuple[List[str], List[Dict]]:
    """Separate failed skills from successful results based on fallback content detection."""
    failed_skills = []
    successful_results = []
    
    for result in parsed_results:
        if "No sources found" in result.get("extracted_content", ""):
            failed_skills.append(result["skill"])
        else:
            successful_results.append(result)
    
    return failed_skills, successful_results


async def _call_gemini_api(
    client: Any,
    prompt: str,
    config: types.GenerateContentConfig,
    context: str
) -> Tuple[str, Optional[Any]]:
    """
    Execute Gemini API call and return response text with metadata.
    
    Args:
        client: GenAI client instance
        prompt: Prompt to send to Gemini
        config: Generation config with tools
        context: Context string for logging (e.g., "batch: ['skill1', 'skill2']")
    
    Returns:
        Tuple of (response_text, grounding_metadata)
    """
    logger.info(f"⏱️ Gemini API call started for {context}")
    start_time = time.perf_counter()
    
    # Create async wrapper for synchronous Gemini SDK call
    async def _async_wrapper():
        return await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=prompt,
            config=config
        )
    
    response = await safe_api_call(_async_wrapper, service='gemini')
    
    elapsed = time.perf_counter() - start_time
    logger.info(f"⏱️ Gemini API call completed in {elapsed:.2f}s for {context}")
    
    response_text = response.text if response.text else ""
    _log_response_debug_info(response_text, context)
    
    grounding_meta = _extract_grounding_metadata(response)
    
    # Handle empty text with metadata edge case
    if not response_text and grounding_meta:
        response_text = "Search completed but no summary generated."
    
    return response_text, grounding_meta


async def _retry_failed_skills(
    client: Any,
    config: types.GenerateContentConfig,
    failed_skills: List[str],
    successful_results: List[Dict],
    original_results: List[Dict]
) -> List[Dict]:
    """
    Retry source discovery for failed skills IN PARALLEL with simplified prompt.
    
    Each failed skill is retried individually in parallel for maximum concurrency.
    
    Args:
        client: GenAI client instance
        config: Generation config with tools
        failed_skills: List of skills that failed parsing
        successful_results: Successfully parsed results from initial attempt
        original_results: Original results including fallbacks
    
    Returns:
        Combined list of successful and retry results
    """
    logger.info(f"Retrying source discovery for {len(failed_skills)} failed skill(s) IN PARALLEL: {failed_skills}")
    
    async def retry_single_skill(skill: str) -> Dict:
        """Retry a single skill with simplified prompt."""
        try:
            logger.debug(f"Retry attempt for single skill: {skill}")
            
            # Build simplified prompt for single skill
            retry_prompt = _build_simplified_prompt([skill])
            
            # Call API with retry prompt
            retry_text, retry_meta = await _call_gemini_api(
                client,
                retry_prompt,
                config,
                f"retry skill: {skill}"
            )
            
            # Parse retry results (should return 1 item)
            retry_results = parse_batch_response(retry_text, [skill], retry_meta)
            return retry_results[0] if retry_results else create_fallback_sources(skill, "Retry parsing failed")
            
        except Exception as retry_error:
            logger.warning(f"Retry failed for skill '{skill}': {retry_error}")
            return create_fallback_sources(skill, f"Retry error: {retry_error}")
    
    # Execute all retries in parallel with asyncio.gather
    retry_results = await asyncio.gather(*[retry_single_skill(skill) for skill in failed_skills])
    
    # Merge successful original results with retry results
    return successful_results + list(retry_results)


async def discover_sources(skills: List[str]) -> List[Dict]:
    """
    Discover authoritative web sources using Gemini's native search grounding.
    
    NOTE: Semaphore removed - concurrency is controlled by batch_processor.py
    This allows full parallelization when multiple batches call this function.
    
    Returns:
        List[Dict]: Contains 'skill', 'extracted_content' (summary only), 
                   
    Raises:
        SourceDiscoveryError: If source discovery fails critically
    """
    results = []
    chunk_size = 3
    
    # Batch skills to optimize token usage
    batches = [skills[i:i + chunk_size] for i in range(0, len(skills), chunk_size)]
    
    # Initialize client once to save overhead
    try:
        client = get_genai_client()
    except Exception as e:
        error_msg = f"Failed to initialize GenAI client: {e}"
        logger.error(error_msg)
        raise SourceDiscoveryError(error_msg, details={"skills": skills}) from e

    async def process_batch(chunk: List[str]) -> List[Dict]:
        """Process a single batch of skills with parallel retry logic."""
        # Build prompt with optimized queries
        skills_block = _build_skills_block_with_queries(chunk)
        prompt = _build_detailed_prompt(skills_block)
        
        # Configure grounding tool
        grounding_tool = types.Tool(google_search=types.GoogleSearch())
        config = types.GenerateContentConfig(tools=[grounding_tool])

        try:
            # Execute initial API call
            response_text, grounding_meta = await _call_gemini_api(
                client,
                prompt,
                config,
                f"batch: {chunk}"
            )
            
        except asyncio.TimeoutError:
            logger.error(f"Search timed out for batch {chunk}")
            return [create_fallback_sources(s, "Search timed out") for s in chunk]
        except (ResourceExhausted, TooManyRequests) as e:
            logger.error(f"Rate limit exceeded for batch {chunk}: {e}")
            return [create_fallback_sources(s, "Rate limit exceeded") for s in chunk]
        except Exception as e:
            logger.error(f"Search failed for batch {chunk}: {e}", exc_info=True)
            raise SourceDiscoveryError(
                f"Source discovery failed for batch {chunk}",
                details={"batch": chunk, "error": str(e)}
            ) from e
        
        # Parse initial response (outside try block - parsing errors should propagate)
        parsed_results = parse_batch_response(response_text, chunk, grounding_meta)
        
        # Separate failed and successful skills
        failed_skills, successful_results = _separate_failed_skills(parsed_results)
        
        # Retry failed skills in PARALLEL if any
        if failed_skills:
            return await _retry_failed_skills(
                client,
                config,
                failed_skills,
                successful_results,
                parsed_results
            )
        
        return parsed_results

    # Process all batches with concurrency control
    try:
        batch_results_list = await asyncio.gather(*[process_batch(batch) for batch in batches])
    except SourceDiscoveryError:
        # Re-raise source discovery errors
        raise
    except Exception as e:
        logger.error(f"Unexpected error during batch processing: {e}", exc_info=True)
        raise SourceDiscoveryError(
            "Unexpected error during source discovery",
            details={"skills": skills, "error": str(e)}
        ) from e
    
    # Flatten results
    for batch_res in batch_results_list:
        results.extend(batch_res)

    return results

