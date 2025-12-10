import logging
import re
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

# Compile regex patterns once at module level for performance
_HEADER_PATTERN = re.compile(r'(?m)^(?:#{2,6}|\*\*)\s*(.+?)(?::)?\s*$')
_CLEANUP_PATTERN = re.compile(r'[^\w\s-]')
_WHITESPACE_PATTERN = re.compile(r'\s+')

def create_fallback_sources(
    skill: str,
    error_message: Optional[str] = None
) -> Dict[str, str]:
    """Create fallback content when primary search fails."""
    content_msg = f"Fallback response for {skill}. Consider manual search for better results."
    if error_message:
        # Sanitize error message
        clean_err = error_message.replace('"', "'").replace('\n', ' ')
        content_msg += f"\n\nDEBUG INFO: Search failed with error: {clean_err}"
    
    return {
        "skill": skill,
        "extracted_content": content_msg,
    }

def optimize_search_query(skill: str) -> str:
    """
    Generates an effective Google search query for technical interview questions.
    """
    skill = skill.strip()
    return f'"{skill}" "technical interview questions" -youtube -vimeo -tiktok -facebook -twitter -instagram -reddit -quora'

def _normalize_text(text: str) -> str:
    """Normalize text for flexible matching while preserving semantic meaning."""
    normalized = text.lower().strip()
    normalized = normalized.replace('&', 'and')
    normalized = _CLEANUP_PATTERN.sub('', normalized)  # Remove special chars except hyphens
    normalized = _WHITESPACE_PATTERN.sub(' ', normalized)  # Normalize whitespace
    return normalized

def parse_batch_response(raw_text: str, skills: List[str], grounding_meta: Any = None) -> List[Dict[str, Any]]:
    """
    Parse batch response and map grounding metadata.
    
    Optimized for single-pass processing using pre-compiled regex patterns.
    """
    # Create normalization map once
    skill_map = {_normalize_text(s): s for s in skills}
    results_map = {s: {"content": "", "source_count": 0, "found": False} for s in skills}
    
    # Find all sections locally - generator for memory efficiency
    matches = list(_HEADER_PATTERN.finditer(raw_text))
    
    for i, match in enumerate(matches):
        header_text = match.group(1).strip()
        header_normalized = _normalize_text(header_text)
        
        # Calculate content boundaries
        start_idx = match.start()
        end_idx = matches[i+1].start() if i + 1 < len(matches) else len(raw_text)
        
        # Simplified Matching Strategy
        # 1. Exact normalized match
        # 2. Substring match (bi-directional)
        matched_skill = skill_map.get(header_normalized)
        
        if not matched_skill:
            # Fallback: Substring matching
            for norm_key, original_skill in skill_map.items():
                if norm_key in header_normalized or header_normalized in norm_key:
                    matched_skill = original_skill
                    break
        
        if matched_skill:
            # Extract content
            section_content = raw_text[start_idx:end_idx].strip()
            
            # Remove header line from content if present
            lines = section_content.split('\n', 1)
            body_text = lines[1].strip() if len(lines) > 1 else lines[0].strip()
            
            # Clean up potential secondary header artifacts
            if body_text.startswith('##'):
                lines_cleaned = body_text.split('\n', 1)
                body_text = lines_cleaned[1].strip() if len(lines_cleaned) > 1 else ""
                
            results_map[matched_skill].update({
                "content": body_text,
                "found": True,
                "start_idx": start_idx,
                "end_idx": end_idx
            })
        else:
            logger.debug(f"Unmatched header: '{header_text}'")

    # Map grounding metadata if available
    if grounding_meta and hasattr(grounding_meta, 'grounding_supports') and grounding_meta.grounding_supports:
        _map_grounding_metadata(results_map, grounding_meta)

    # Format final output
    return _build_final_output(skills, results_map)

def _map_grounding_metadata(results_map: Dict[str, Dict], grounding_meta: Any) -> None:
    """Helper to map grounding metadata to matched sections."""
    chunks = getattr(grounding_meta, 'grounding_chunks', []) or []
    supports = grounding_meta.grounding_supports
    
    # Initialize URL sets for each skill
    skill_urls = {skill: set() for skill in results_map.keys() if results_map[skill]["found"]}
    
    # Build range lookup
    ranges = []
    for skill, data in results_map.items():
        if data["found"]:
            ranges.append((data["start_idx"], data["end_idx"], skill))
            
    for support in supports:
        s_start = getattr(support.segment, 'start_index', 0) or 0
        
        # Find which skill section this support belongs to
        for start, end, skill in ranges:
            if start <= s_start < end:
                # Extract all URLs from this support's grounding chunks
                for chunk_idx in support.grounding_chunk_indices:
                    if chunk_idx < len(chunks):
                        try:
                            chunk = chunks[chunk_idx]
                            url = chunk.web.uri if hasattr(chunk, 'web') else None
                            if url:
                                skill_urls[skill].add(url)
                        except Exception:
                            continue
                break  # Support belongs to one skill section only
    
    # Update results with counts
    for skill, urls in skill_urls.items():
        if urls:
            results_map[skill]["source_count"] = len(urls)

def _build_final_output(skills: List[str], results_map: Dict[str, Dict]) -> List[Dict[str, Any]]:
    """Build the final list of results preserving original skill order."""
    final_output = []
    
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
            final_output.append({
                "skill": skill,
                "extracted_content": f"No sources found for '{skill}'. Consider manual research for this skill."
            })
            
    return final_output