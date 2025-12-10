import logging
from typing import Optional, Dict, List, Any
import re

logger = logging.getLogger(__name__)

# Compile regex patterns once at module level for performance
_ACRONYM_PATTERN = re.compile(r'(.+?)\s*\(([A-Z]+)\)')
_HEADER_PATTERN = re.compile(r'(?m)^(?:#{2,6}|\*\*)\s*(.+?)(?::)?\s*$')


def create_fallback_sources(
    skill: str,
    error_message: Optional[str] = None
) -> Dict:
    """Create fallback content when primary search fails."""
    content_msg = f"Fallback response for {skill}. Consider manual search for better results."
    if error_message:
        clean_err = error_message.replace('"', "'").replace('\n', ' ')
        content_msg += f"\n\nDEBUG INFO: Search failed with error: {clean_err}"
    
    return {
        "skill": skill,
        "extracted_content": content_msg,
    }


def optimize_search_query(skill: str) -> str:
    """
    Generates an effective Google search query for technical interview questions.
    Uses pre-compiled regex for performance.
    """
    skill = skill.strip()
    
    # Extract acronym from parentheses if present (using compiled pattern)
    acronym_match = _ACRONYM_PATTERN.match(skill)
    
    if acronym_match:
        # Use both full name and acronym
        full_name = acronym_match.group(1).strip()
        acronym = acronym_match.group(2).strip()
        base = f'("{full_name}" OR "{acronym}") "technical interview questions"'
    else:
        base = f'"{skill}" "technical interview questions"'
    
    exclude = "-youtube -vimeo -tiktok -facebook -twitter -instagram -reddit -quora"
    return f"{base} {exclude}"


def parse_batch_response(raw_text: str, skills: List[str], grounding_meta: Any = None) -> List[Dict]:
    """
    Parse batch response and map grounding metadata.
    
    Optimized for single-pass processing using pre-compiled regex patterns.
    Handles common response format variations from Gemini.
    """
    
    def normalize_for_matching(text: str) -> str:
        """Normalize text for flexible matching while preserving semantic meaning."""
        normalized = text.lower().strip()
        # Normalize common variations
        normalized = normalized.replace('&', 'and')  # "Data Manipulation & Visualization" -> "and"
        normalized = re.sub(r'["""'']', '', normalized)  # Remove various quote styles
        normalized = re.sub(r'\s+', ' ', normalized)  # Normalize whitespace
        normalized = re.sub(r'[^\w\s-]', '', normalized)  # Remove special chars except hyphens
        return normalized
    
    # Normalize skill names for matching (single pass)
    skill_map = {normalize_for_matching(s): s for s in skills}
    results_map = {s: {"content": "", "source_count": 0, "found": False} for s in skills}
    
    # Find section headers using pre-compiled pattern
    matches = list(_HEADER_PATTERN.finditer(raw_text))
    
    if len(matches) < len(skills):
        logger.warning(
            f"Header mismatch: found {len(matches)} headers but expected {len(skills)} skills. "
            f"Headers found: {[m.group(1).strip() for m in matches][:5]}... "
            f"Expected: {skills[:5]}..."
        )
    
    # Extract sections in single pass
    sections = []
    unmatched_headers = []
    
    for i, match in enumerate(matches):
        header_text = match.group(1).strip()
        header_normalized = normalize_for_matching(header_text)
        start_idx = match.start()
        end_idx = matches[i+1].start() if i + 1 < len(matches) else len(raw_text)
        
        # Optimized fuzzy matching - try strategies in order of likelihood
        matched_skill = None
        
        # Strategy 1: Exact normalized match (most common, check first)
        if header_normalized in skill_map:
            matched_skill = skill_map[header_normalized]
        else:
            # Strategy 2 & 3: Substring matching (less common)
            for normalized_key, original_skill in skill_map.items():
                # Check if one is substring of the other
                if normalized_key in header_normalized or header_normalized in normalized_key:
                    matched_skill = original_skill
                    break
        
        if matched_skill:
            # Extract content once
            content = raw_text[start_idx:end_idx].strip()
            sections.append({
                "skill": matched_skill,
                "start": start_idx,
                "end": end_idx,
                "content": content,
                "header_text": header_text  # Store original header for debugging
            })
        else:
            unmatched_headers.append(header_text)
    
    # Log unmatched headers for debugging
    if unmatched_headers:
        logger.warning(
            f"Could not match {len(unmatched_headers)} header(s) to skills: {unmatched_headers[:3]}... "
            f"Expected skills: {[s for s in skills if s not in [sec['skill'] for sec in sections]][:3]}"
        )

    # Map grounding metadata (single pass over supports)
    if grounding_meta and hasattr(grounding_meta, 'grounding_supports') and grounding_meta.grounding_supports:
        chunks = grounding_meta.grounding_chunks or []
        supports = grounding_meta.grounding_supports
        
        for section in sections:
            section_start = section["start"]
            section_end = section["end"]
            seen_urls = set()
            
            # Single pass over supports
            for support in supports:
                s_start = support.segment.start_index or 0
                
                # Check if support falls in this section
                if section_start <= s_start < section_end:
                    for chunk_idx in support.grounding_chunk_indices:
                        if chunk_idx < len(chunks):
                            url = chunks[chunk_idx].web.uri
                            seen_urls.add(url)
            
            results_map[section["skill"]]["source_count"] = len(seen_urls)

    # Format final output (single pass)
    final_output = []
    
    for section in sections:
        skill = section["skill"]
        # Remove header line (extract body only once)
        lines = section["content"].split('\n', 1)  # Split only once
        body_text = lines[1].strip() if len(lines) > 1 else lines[0].strip()
        
        # Additional cleanup: remove the header if it's still at the start
        if body_text.startswith('##'):
            lines_cleaned = body_text.split('\n', 1)
            body_text = lines_cleaned[1].strip() if len(lines_cleaned) > 1 else ""
        
        results_map[skill]["content"] = body_text
        results_map[skill]["found"] = True
    
    # Convert to list in original order
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
            logger.warning(f"No section found for '{skill}' - source discovery may have failed")
            final_output.append({
                "skill": skill,
                "extracted_content": f"No sources found for '{skill}'. Consider manual research for this skill."
            })

    return final_output