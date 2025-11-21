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
    # Strongly prioritize technical documentation and authoritative sources
    prioritize = "site:stackoverflow.com OR site:github.com OR site:medium.com OR site:dev.to OR site:docs.oracle.com OR site:docs.python.org OR site:react.dev OR site:nodejs.org OR tutorial OR documentation OR technical article OR guide"
    # Exclude common video platforms and non-technical sites
    exclude = "-youtube -vimeo -tiktok -facebook -twitter -instagram -reddit -quora"
    # Combine for a more effective search
    query = f"{base}  {exclude}"
    return query

def _create_fallback_sources(search_query: str) -> AllSkillSources:
    """Create fallback sources when primary search fails."""
    fallback_uris = [
        f"https://en.wikipedia.org/wiki/{search_query.replace(' ', '_')}",
        f"https://www.google.com/search?q={search_query.replace(' ', '+')}",
    ]
    
    skill_sources = SkillSources(
        skill=search_query,
        sources=[{"url": uri, "title": f"Fallback source for {search_query}", "content": ""} 
                for uri in fallback_uris],
        questions=[],
        extracted_content=f"Fallback sources for {search_query}. Consider manual search for better results."
    )
    
    return AllSkillSources(all_sources=[skill_sources])
