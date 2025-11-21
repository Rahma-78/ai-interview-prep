import json
import logging
import re
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


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
