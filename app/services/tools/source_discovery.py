"""
Source discovery business logic for the second agent.

This module contains the core functionality for discovering and enhancing
technical learning resources using Gemini's Google Search grounding.
"""
import asyncio
import logging
from typing import Dict, List
from google.genai import types
from google.api_core.exceptions import (
    ResourceExhausted,
    TooManyRequests,
)

from app.services.tools.llm_config import get_genai_client, GEMINI_MODEL
from app.services.tools.helpers import optimize_search_query, parse_batch_response, create_fallback_sources
from app.services.tools.utils import safe_api_call

logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
# Limits parallel requests to avoid 429 Errors. 
# Increase to 5-10 if you have a high-tier enterprise quota.
MAX_CONCURRENT_REQUESTS = 3 

async def discover_sources(skills: List[str]) -> List[Dict]:
    """
    Discover authoritative web sources using Gemini's native search grounding.
    
    Returns:
        List[Dict]: Contains 'skill', 'extracted_content' (summary only), 
                   
    """
    results = []
    chunk_size = 3
    
    # Batch skills to optimize token usage
    batches = [skills[i:i + chunk_size] for i in range(0, len(skills), chunk_size)]
    
    # Semaphore limits the number of active tasks at once
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    
    # Initialize client once to save overhead
    try:
        client = get_genai_client()
    except Exception as e:
        logger.error(f"Failed to initialize GenAI client: {e}")
        return [create_fallback_sources(s, error_message="Client Init Failed") for s in skills]

    async def process_batch(chunk: List[str]) -> List[Dict]:
        async with semaphore:
            logger.info(f"Processing batch: {chunk}")
            
            # 1. Optimize Queries
            skills_with_queries = []
            for skill in chunk:
                try:
                    opt_query = optimize_search_query(skill)
                    skills_with_queries.append(f"- Skill: {skill} -> Query: {opt_query}")
                except Exception as e:
                    logger.warning(f"Query optimization failed for '{skill}': {e}")
                    skills_with_queries.append(f"- Skill: {skill} -> Query: {skill}")
            
            skills_block = "\n".join(skills_with_queries)

            # 2. Construct Prompt (STRICT NO-LINK OUTPUT POLICY)
            prompt = ("\n".join(["You are an expert technical researcher. Perform a 'Split-Search' for the following skills.\n"
                f"{skills_block}\n"
                "INSTRUCTIONS:\n"
                "For EACH skill, generate a response separated by the marker '## {SkillName}'.\n"
                "1. GOAL: Extract dense, technical content for expert interviewers (trade-offs, misconceptions, patterns).\n"
                "2. SOURCE HANDLING: Use Google Search to find information, BUT:\n"
                "   - Synthesize the knowledge into your own words.\n"
                "   - Do NOT output a 'Sources' or 'References' list.\n"
                "   - Do NOT output URLs or website titles in the text.\n"
                "   - The final output must look like pure expert knowledge.\n"
                "3. FORMAT:\n"
                "   ## {SkillName}\n"
                "   [Deep technical summary paragraphs...]\n"
                "   (Repeat for all skills)\n"
                "   IMPORTANT: You MUST provide a section for EVERY requested skill. Do not combine them.\n"
                "   ENSURE the header is exactly '## {SkillName}' with no extra colons or words.\n"
            ]))

            # 3. Configure Tool
            grounding_tool = types.Tool(google_search=types.GoogleSearch())
            config = types.GenerateContentConfig(tools=[grounding_tool])

            try:
                # 4. Execute Safe API Call
                response = await safe_api_call(
                    asyncio.to_thread,
                    client.models.generate_content,
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=config
                )

                response_text = response.text if response.text else ""
                
                # Extract Metadata for internal logging
                grounding_meta = None
                if response.candidates and response.candidates[0].grounding_metadata:
                    grounding_meta = response.candidates[0].grounding_metadata

                # Handle empty text with metadata (Edge case)
                if not response_text and grounding_meta:
                     response_text = "Search completed but no summary generated."

                return parse_batch_response(response_text, chunk, grounding_meta)

            except asyncio.TimeoutError:
                logger.error(f"Search timed out for batch {chunk}")
                return [create_fallback_sources(s, "Search timed out") for s in chunk]
            except (ResourceExhausted, TooManyRequests) as e:
                logger.error(f"Rate limit exceeded for batch {chunk}: {e}")
                return [create_fallback_sources(s, "Rate limit exceeded") for s in chunk]
            except Exception as e:
                logger.error(f"Search failed for batch {chunk}: {e}", exc_info=True)
                return [create_fallback_sources(s, str(e)) for s in chunk]

    # Process all batches with concurrency control
    batch_results_list = await asyncio.gather(*[process_batch(batch) for batch in batches])
    
    # Flatten results
    for batch_res in batch_results_list:
        results.extend(batch_res)

    return results
