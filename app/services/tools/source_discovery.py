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
    ResourceExhausted,
    TooManyRequests,
)

from app.services.tools.llm_config import get_genai_client, GEMINI_MODEL
from app.services.tools.helpers import optimize_search_query
from app.services.tools.utils import safe_api_call

logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
# Limits parallel requests to avoid 429 Errors. 
# Increase to 5-10 if you have a high-tier enterprise quota.
MAX_CONCURRENT_REQUESTS = 3 

def create_fallback_sources(
    skill: str,
    error_message: Optional[str] = None
) -> Dict:
    """Create fallback content when primary search fails."""
    content_msg = f"Fallback response for {skill}. Consider manual search for better results."
    if error_message:
        # Sanitize error message to prevent JSON issues
        clean_err = error_message.replace('"', "'").replace('\n', ' ')
        content_msg += f"\n\nDEBUG INFO: Search failed with error: {clean_err}"
    
    return {
        "skill": skill,
        "extracted_content": [content_msg],
    }

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
            prompt = (
                "You are an expert technical researcher. Perform a 'Split-Search' for the following skills.\n\n"
                f"{skills_block}\n\n"
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
            )

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
def parse_batch_response(raw_text: str, skills: List[str], grounding_meta: Any = None) -> List[Dict]:
    """
    Robustly parses batch response and maps grounding metadata using raw indices.
    """
    # 1. CLEANUP & NORMALIZE
    # We create a normalized map to handle casing issues (e.g., LLM writes "Python" vs "python")
    skill_map = {s.lower().strip(): s for s in skills}
    results_map = {s: {"content": "", "source_count": 0, "found": False} for s in skills}
    
    # 2. IDENTIFY SECTIONS (Inverted Logic)
    # Instead of searching for specific skills, we look for the structure (Headers)
    # Pattern: Start of line, ## or **, capture title, optional colon/whitespace, end of line
    header_pattern = re.compile(r'(?m)^(?:#{2,6}|\*\*)\s*(.+?)(?::)?\s*$')
    
    matches = list(header_pattern.finditer(raw_text))
    
    # Create sections with start/end indices based on the RAW text
    sections = []
    for i, match in enumerate(matches):
        section_title = match.group(1).lower().strip()
        start_idx = match.start()
        
        # End index is the start of the next header, or end of string
        end_idx = matches[i+1].start() if i + 1 < len(matches) else len(raw_text)
        
        # Fuzzy match the header title to our requested skills
        # This handles cases like LLM writing "## Python Logic" instead of "## Python"
        matched_skill = None
        for key in skill_map:
            if key == section_title or (key in section_title and len(section_title) < len(key) + 10):
                matched_skill = skill_map[key]
                break
        
        if matched_skill:
            sections.append({
                "skill": matched_skill,
                "start": start_idx,
                "end": end_idx,
                "content": raw_text[start_idx:end_idx].strip()
            })

    # 3. MAP GROUNDING METADATA
    # We do this logic BEFORE modifying the content strings significantly
    if grounding_meta and hasattr(grounding_meta, 'grounding_supports'):
        chunks = grounding_meta.grounding_chunks
        supports = grounding_meta.grounding_supports
        
        for section in sections:
            seen_urls = set()
            
            for support in supports:
                # API returns None for 0 indices sometimes, handle safely
                s_start = support.segment.start_index or 0
                s_end = support.segment.end_index or 0
                
                # Check intersection: Does the support segment fall inside this section?
                if s_start >= section["start"] and s_start < section["end"]:
                    
                    for chunk_idx in support.grounding_chunk_indices:
                        if chunk_idx < len(chunks):
                            url = chunks[chunk_idx].web.uri
                            if url not in seen_urls:
                                seen_urls.add(url)
            
            # Update the results map with the count
            results_map[section["skill"]]["source_count"] = len(seen_urls)

    # 4. FORMAT FINAL OUTPUT
    # Now we clean up the text (remove the header line) for the final user
    final_output = []
    
    for section in sections:
        skill = section["skill"]
        # Remove the first line (the header) to leave only the body
        lines = section["content"].split('\n')
        body_text = "\n".join(lines[1:]).strip() if len(lines) > 1 else lines[0]
        
        results_map[skill]["content"] = body_text
        results_map[skill]["found"] = True

    # Convert map to list, maintaining original order
    for skill in skills:
        data = results_map[skill]
        if data["found"]:
            final_output.append({
                "skill": skill,
                "extracted_content": [data["content"]],
                # "meta_source_count": data["source_count"] # Optional: Expose if needed
            })
            if data["source_count"] > 0:
                logger.info(f"Skill '{skill}' synthesized from {data['source_count']} sources.")
        else:
            # Fallback for missing sections
            logger.warning(f"Parser could not find section for '{skill}'")
            final_output.append({
                "skill": skill,
                "extracted_content": [f"Fallback: AI failed to structure response for {skill}."]
            })

    return final_output