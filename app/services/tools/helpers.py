import logging
from app.schemas.interview import AllSkillSources, SkillSources

"""
Helper functions for the interview preparation tools.

This module provides utility functions for:
- Search query optimization
- Fallback result generation
"""



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
    base = f'"{skill}" interview questions'

    # Exclude common video platforms and non-technical sites
    exclude = "-youtube -vimeo -tiktok -facebook -twitter -instagram -reddit -quora"
    # Combine for a more effective search
    query = f"{base}  {exclude}"
    return query

