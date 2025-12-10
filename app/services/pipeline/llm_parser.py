from typing import Any
import logging
import json

logger = logging.getLogger(__name__)


def clean_llm_json_output(raw_text: str) -> str:
    """Cleans LLM output to extract valid JSON."""
    if not raw_text:
        return ""
    
    # Remove markdown code blocks
    import re
    text = re.sub(r'```json\s*', '', raw_text)
    text = re.sub(r'```', '', text)
    
    # Try standard JSON parsing
    try:
        decoded_object = json.loads(text)
        return json.dumps(decoded_object)
    except json.JSONDecodeError:
        pass
    
    # Fallback: extract JSON from text
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        try:
            extracted = text[start_idx:end_idx+1]
            json.loads(extracted)  # Validate
            return extracted
        except json.JSONDecodeError:
            pass
    
    return text.strip()


def parse_llm_response(
    result: Any,
    schema_class: type,
    fallback_data: Any = None
) -> Any:
    """
    Parse LLM response and validate against schema.
    """
    try:
        # Handle string responses from direct LLM calls
        if isinstance(result, str):
            raw_content = result
        else:
            raw_content = str(result)

        cleaned_json = clean_llm_json_output(raw_content)
        data = json.loads(cleaned_json)
        return schema_class(**data)

    except Exception as e:
        logger.error(
            f"Error parsing {schema_class.__name__}: {e}",
            exc_info=True
        )
        logger.error(f"Raw output (first 500 chars): {str(result)[:500]}...")

        if fallback_data is not None:
            return fallback_data
        raise ValueError(f"Failed to parse {schema_class.__name__}: {e}")
