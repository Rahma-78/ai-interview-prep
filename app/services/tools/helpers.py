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
    base = f'{skill} interview questions'
    # Exclude common video platforms to focus on textual content
    exclude = "-youtube -vimeo -tiktok"
    # Combine for a more effective search
    query = f"{base} {exclude}"
    return query


def generate_fallback_results(search_query: str) -> str:
    """
    Generates fallback results when the primary search API fails.

    Args:
        search_query: The original search query.

    Returns:
        A JSON string with fallback URLs.
    """
    logging.info(f" Generating fallback results for '{search_query}'...")
    fallback_uris = [
        f"https://en.wikipedia.org/wiki/{search_query.replace(' ', '_')}",
        f"https://www.google.com/search?q={search_query.replace(' ', '+')}",
    ]
    fallback_data = AllSkillSources(
        all_sources=[SkillSources(skill=search_query, sources=fallback_uris)]
    ).json()
    return fallback_data
