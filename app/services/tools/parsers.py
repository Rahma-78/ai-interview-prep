import json
import logging
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def extract_grounding_sources(response_text: str) -> List[Dict[str, str]]:
    """
    Extracts grounding metadata with URI, title, confidence scores, and snippets
    from Gemini's native search results for enhanced RAG context.

    Args:
        response_text: The LLM response text that may contain grounding metadata.

    Returns:
        A list of dictionaries, each containing 'url', 'title', 'confidence', and 'snippet'.
    """

    grounding_sources = []
    try:
        if 'groundingMetadata' in response_text:
            grounding_pattern = r'"groundingMetadata":\s*{[^}]*"web":\s*\[[^\]]*\]'
            grounding_match = re.search(grounding_pattern, response_text, re.DOTALL)

            if grounding_match:
                # Enhanced pattern to capture snippets
                web_pattern = r'"uri":\s*"([^"]+)"[^}]*"title":\s*"([^"]+)"[^}]*"snippet":\s*"([^"]*)"'
                web_matches = re.findall(web_pattern, grounding_match.group(0), re.DOTALL)

                for uri, title, snippet in web_matches:
                    if uri and title:
                        grounding_sources.append({
                            "url": uri,
                            "title": title,
                            "snippet": snippet.replace('\n', ' ').strip(),
                            "content": ""  # Keep for backward compatibility
                        })
                
                # Fallback for simpler grounding metadata
                if not web_matches:
                    simple_pattern = r'"uri":\s*"([^"]+)"[^}]*"title":\s*"([^"]+)"'
                    simple_matches = re.findall(simple_pattern, grounding_match.group(0))
                    
                    for uri, title in simple_matches:
                        if uri and title:
                            grounding_sources.append({
                                "url": uri,
                                "title": title,
                                "snippet": "",
                                "content": ""
                            })
    except Exception as e:
        logger.warning(f"Could not extract grounding metadata: {e}")
    return grounding_sources

def clean_and_parse_json(json_string: str) -> Dict[str, Any]:
    """
    Cleans and parses a JSON string, removing markdown and fixing common formatting issues.

    Args:
        json_string: The raw string to be parsed.

    Returns:
        A dictionary parsed from the JSON string.
    """
    # Remove markdown code block fences
    if json_string.startswith('```json'):
        json_string = json_string[7:]
    if json_string.endswith('```'):
        json_string = json_string[:-3]

    # Fix common JSON formatting issues like trailing commas
    json_string = json_string.strip()
    json_string = json_string.replace(',]', ']').replace(',}', '}')

    return json.loads(json_string)
