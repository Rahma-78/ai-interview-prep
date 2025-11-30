import logging
from typing import Optional, Dict, List, Any
import re
from app.schemas.interview import AllSkillSources, SkillSources

logger = logging.getLogger(__name__)

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


def optimize_search_query(skill: str) -> str:
    """
    Generates an effective Google search query for technical interview questions.

    Args:
        skill: The skill to search for.

    Returns:
        An optimized search query string.
    """
    skill = skill.strip().lower()
    # Core phrase for direct, relevant results
    base =  f'"{skill}" "technical interview questions" '
   
    # Exclude common video platforms and non-technical sites
    exclude = "-youtube -vimeo -tiktok -facebook -twitter -instagram -reddit -quora"
    # Combine for a more effective search
    query = f"{base} {exclude}"
    return query



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
    if grounding_meta and hasattr(grounding_meta, 'grounding_supports') and grounding_meta.grounding_supports:
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
            })
            if data["source_count"] > 0:
                logger.info(f"Skill '{skill}' synthesized from {data['source_count']} sources.")
        else:
            # Fallback for missing sections
            logger.warning(f"Parser could not find section for '{skill}'")
            final_output.append({
                "skill": skill,
                "extracted_content": [f"AI failed to structure response for {skill}."]
            })

    return final_output


def clean_llm_json_output(text: str) -> str:
    """
    Robustly extracts JSON object from LLM response using Regex.
    Handles markdown code blocks, text prefixes/suffixes, and whitespace.
    """
    if not text:
        return ""
        
    # 1. Try to find JSON inside markdown code blocks
    markdown_pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
    match = re.search(markdown_pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1)

    # 2. If no markdown, try to find the first outer-most JSON object
    # This looks for the first '{' and the last '}'
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return text[start_idx : end_idx + 1]

    # 3. Fallback: Return original text (stripped) if no pattern matches
    # Try to strip common prefixes/suffixes if regex failed
    text = text.strip()
    
    # Remove "**Final Answer**:" or "Final Answer:" prefixes
    text = re.sub(r"^\**Final Answer\**:\s*", "", text, flags=re.IGNORECASE).strip()
    
    # Remove leading/trailing backticks if present (e.g. `{"foo": "bar"}`)
    if text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()
        
    return text