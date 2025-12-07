from app.services.tools.helpers import clean_llm_json_output
import logging
from typing import Any

logger = logging.getLogger(__name__)

def parse_llm_response(
        result: Any,
        schema_class: type,
        fallback_data: Any = None
    ) -> Any:
        """
        Generic parser for CrewAI results following DRY and Single Responsibility principles.

        Args:
            result: The CrewAI result object
            schema_class: Pydantic model class to validate against
            fallback_data: Data to return on failure (optional)

        Returns:
            Validated Pydantic model instance

        Raises:
            ValueError: If parsing fails and no fallback_data provided
        """
        try:
            # Direct LLM calls return string responses
            # Handle both string inputs and legacy CrewAI objects for compatibility
            if isinstance(result, str):
                raw_content = result
            elif hasattr(result, 'raw'):
                raw_content = result.raw
            else:
                raw_content = str(result)

            cleaned_json = clean_llm_json_output(raw_content)
            import json
            data = json.loads(cleaned_json)
            return schema_class(**data)  # Two-step parsing with coercion

        except Exception as e:
            logger.error(
                f"Error parsing {schema_class.__name__}: {e}",
                exc_info=True
            )
            logger.error(f"Raw output (first 500 chars): {str(result)[:500]}...")

            if fallback_data is not None:
                return fallback_data
            raise ValueError(f"Failed to parse {schema_class.__name__}: {e}")
