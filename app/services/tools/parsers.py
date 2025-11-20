import json
import logging
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def extract_grounding_sources(response_text: str) -> List[Dict[str, str]]:
    """
    Extracts grounding metadata with URI and title from Gemini's native search results.

    Args:
        response_text: The LLM response text that may contain grounding metadata.

    Returns:
        A list of dictionaries, each containing the 'url', 'title', and empty 'content'.
    """
    grounding_sources = []
    try:
        if 'groundingMetadata' in response_text:
            grounding_pattern = r'"groundingMetadata":\s*{[^}]*"web":\s*\[[^\]]*\]'
            grounding_match = re.search(grounding_pattern, response_text, re.DOTALL)

            if grounding_match:
                web_pattern = r'"uri":\s*"([^"]+)"[^}]*"title":\s*"([^"]+)"'
                web_matches = re.findall(web_pattern, grounding_match.group(0))

                for uri, title in web_matches:
                    if uri and title:
                        grounding_sources.append({
                            "url": uri,
                            "title": title,
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


def format_discovery_result(skill: str, sources: List[Dict], questions: List[str], content: str) -> str:
    """
    Formats the discovered sources, questions, and content into the final JSON structure.
    """
    result_data = {
        "all_sources": [{
            "skill": skill,
            "sources": sources,
            "questions": questions,
            "extracted_content": content[:2000] if content else ""
        }]
    }
    return json.dumps(result_data)
