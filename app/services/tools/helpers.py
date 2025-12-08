import logging
from typing import Optional, Dict, List, Any
import re
import json
import json_repair


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
        "extracted_content": content_msg,
    }



def optimize_search_query(skill: str) -> str:
    """
    Generates an effective Google search query for technical interview questions.
    Handles acronyms by expanding them for better search results.

    Args:
        skill: The skill to search for.

    Returns:
        An optimized search query string.
    """
    skill = skill.strip()
    
    # Extract acronym from parentheses if present
    # e.g., "Large Language Models (LLMs)" → use "Large Language Models" + "LLMs"
    acronym_match = re.match(r'(.+?)\s*\(([A-Z]+)\)', skill)
    
    if acronym_match:
        # Use both full name and acronym for better coverage
        full_name = acronym_match.group(1).strip()
        acronym = acronym_match.group(2).strip()
        base = f'("{full_name}" OR "{acronym}") "technical interview questions"'
    else:
        # Regular skill without acronym
        base = f'"{skill}" "technical interview questions"'
    
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
    
    # DEBUG: Log header detection for validation
    logger.debug(f"Detected {len(matches)} headers for {len(skills)} skills")
    if matches:
        detected_headers = [m.group(1).strip() for m in matches]
        logger.debug(f"Detected headers: {detected_headers}")
    
    if len(matches) < len(skills):
        logger.warning(f"Header count mismatch: found {len(matches)} headers but expected {len(skills)} skills")
    
    # Create sections with start/end indices based on the RAW text
    sections = []
    for i, match in enumerate(matches):
        section_title = match.group(1).strip()
        section_title_lower = section_title.lower()
        start_idx = match.start()
        
        # End index is the start of the next header, or end of string
        end_idx = matches[i+1].start() if i + 1 < len(matches) else len(raw_text)
        
        # Fuzzy matching strategies (in order of priority)
        matched_skill = None
        
        for key in skill_map:
            # Strategy 1: Exact match (case-insensitive)
            if key == section_title_lower:
                matched_skill = skill_map[key]
                break
            
            # Strategy 2: Skill name contained in header
            # e.g., "python" in "python programming"
            if key in section_title_lower:
                matched_skill = skill_map[key]
                break
            
            # Strategy 3: Header contained in skill name (common with acronyms)
            # e.g., "llms" in "large language models (llms)"
            if section_title_lower in key:
                matched_skill = skill_map[key]
                break
            
            # Strategy 4: Acronym extraction and matching
            # Extract acronyms from skill: "Large Language Models (LLMs)" → "LLMs"
            acronym_match = re.search(r'\(([A-Za-z]+)\)', skill_map[key])
            if acronym_match:
                acronym_lower = acronym_match.group(1).lower()
                if acronym_lower == section_title_lower or acronym_lower in section_title_lower:
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
        chunks = grounding_meta.grounding_chunks or []
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
                "extracted_content": data["content"],
            })
            if data["source_count"] > 0:
                logger.info(f"Skill '{skill}' synthesized from {data['source_count']} sources.")
        else:
            # Section not found - likely Gemini didn't find relevant sources
            logger.warning(f"No section found for '{skill}' - source discovery may have failed")
            final_output.append({
                "skill": skill,
                "extracted_content": f"No sources found for '{skill}'. The search may have returned limited content or the response format was incompatible with parsing. Consider manual research for this skill."
            })

    return final_output

def clean_llm_json_output(raw_text: str) -> str:
    """
    Cleans LLM output to extract valid JSON using json_repair.
    """
    if not raw_text:
        return ""
        
    # Remove markdown code blocks first
    text = re.sub(r'```json\s*', '', raw_text)
    text = re.sub(r'```', '', text)
    
    # Attempt 1: Standard JSON parsing (Fastest)
    try:
        decoded_object = json.loads(text)
        return json.dumps(decoded_object)
    except json.JSONDecodeError:
        pass
    
    # Attempt 2: json_repair (Slower but robust)
    try:
        decoded_object = json_repair.loads(text)
        return json.dumps(decoded_object)
    except Exception as e:
        logger.warning(f"Failed to repair JSON: {e}")
        # Fallback to simple extraction if repair fails
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            return text[start_idx:end_idx+1]
        return text.strip()