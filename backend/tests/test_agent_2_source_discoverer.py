import json
import os
import sys
from pathlib import Path
from collections import defaultdict
import time
import asyncio
from typing import Generator, Dict, List, Tuple

# CrewAI telemetry is now enabled for testing
# os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from crewai import Crew, Process
from backend.agents import InterviewPrepAgents
from backend.tasks import InterviewPrepTasks
from backend.tools import google_search_tool, smart_web_content_extractor


# ============================================================================
# OPTIMIZATION UTILITIES - DYNAMIC BASED ON INPUT
# ============================================================================

# Global cache for URL searches (persists during session)
SEARCH_CACHE: Dict[str, Dict] = {}

# Request throttling configuration
REQUEST_DELAY_SECONDS = 3  # Conservative delay between requests
MAX_SKILLS_PER_RUN = 5     # Process in small batches
MAX_URLS_PER_SKILL = 8     # Increased from 3 to 8 for better coverage
QUALITY_SCORE_THRESHOLD = 0  # We'll use all URLs since they come from search


# ============================================================================
# ASYNC & GENERATOR-BASED OPTIMIZATION UTILITIES
# ============================================================================

def deduplicate_skills(skills: List[str]) -> tuple[List[str], Dict]:
    """
    Remove duplicate skills from input list (simple case-insensitive comparison).
    Works directly with structured input from Agent 1.
    
    Returns:
        tuple: (deduplicated_skills, removal_map)
    """
    seen = {}  # Maps lowercase skill to original capitalization
    filtered = []
    duplicates_found = []
    
    for skill in skills:
        skill_lower = skill.lower().strip()
        if skill_lower not in seen:
            seen[skill_lower] = skill
            filtered.append(skill)
        else:
            duplicates_found.append((skill, seen[skill_lower]))
    
    if duplicates_found:
        print(f"\n🔍 Deduplication: {len(skills)} → {len(filtered)} skills")
        print(f"   Removed {len(duplicates_found)} duplicates")
        for dup, canonical in duplicates_found:
            print(f"     '{dup}' → '{canonical}'")
    
    return filtered, {"duplicates_found": duplicates_found, "original_count": len(skills)}


async def async_search_skill(skill: str, tasks, source_discoverer, semaphore, delay: float) -> Tuple[str, Dict]:
    """
    Async I/O operation for searching a single skill.
    Uses semaphore to prevent overwhelming the LLM API.
    Includes adaptive delay to respect rate limits.
    
    Args:
        skill: Skill to search
        tasks: Task generator
        source_discoverer: Agent instance
        semaphore: Async semaphore for rate limiting
        delay: Delay in seconds before making request
    
    Returns:
        Tuple of (skill, result_dict)
    """
    async with semaphore:
        # Respect the delay before making the request
        if delay > 0:
            print(f"   ⏳ Waiting {delay:.1f}s before searching '{skill}'...")
            await asyncio.sleep(delay)
        
        try:
            # Run the search (blocking operation wrapped in async)
            search_task = tasks.search_sources_task(source_discoverer, skill)
            search_crew = Crew(
                agents=[source_discoverer],
                tasks=[search_task],
                process=Process.sequential,
                verbose=False
            )
            
            search_result = search_crew.kickoff()
            
            # Parse search results
            # Parse search results
            urls = []
            try:
                search_data = json.loads(str(search_result))
                print(f"DEBUG: Raw search result: {str(search_result)[:200]}...")  # Debug output
                
                if isinstance(search_data, dict):
                    # Handle different response formats
                    if 'organic' in search_data and search_data['organic']:
                        # SerperDevTool format
                        urls = [item['link'] for item in search_data['organic'] if 'link' in item]
                    elif 'searchResults' in search_data and search_data['searchResults']:
                        # Custom format
                        urls = [item['link'] for item in search_data['searchResults'] if 'link' in item]
                    elif 'links' in search_data and isinstance(search_data['links'], list):
                        # Direct links list
                        urls = search_data['links']
                    elif 'link' in search_data and isinstance(search_data['link'], str):
                        # Single link
                        urls = [search_data['link']]
                    else:
                        # Fallback: find any URLs in the response
                        for key, value in search_data.items():
                            if isinstance(value, str) and value.startswith('http'):
                                urls.append(value)
                elif isinstance(search_data, list):
                    # Handle list of results
                    for item in search_data:
                        if isinstance(item, dict) and 'link' in item:
                            urls.append(item['link'])
                        elif isinstance(item, str) and item.startswith('http'):
                            urls.append(item)
                
                print(f"DEBUG: Extracted {len(urls)} URLs from search result")  # Debug output
                
            except json.JSONDecodeError as e:
                print(f"DEBUG: JSON decode error: {e}")  # Debug output
                # Try to extract URLs from plain text response
                import re
                url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
                urls = re.findall(url_pattern, str(search_result))
                print(f"DEBUG: Found {len(urls)} URLs via regex fallback")  # Debug output
            return skill, {
                "urls": urls[:MAX_URLS_PER_SKILL],  # Increased limit for better coverage
                "source": "llm_search",
                "status": "success" if urls else "no_urls",
                "urls_found_count": len(urls)  # Track total found before limiting
            }
        
        except Exception as e:
            print(f"   ⚠️  Error searching '{skill}': {str(e)[:100]}")
            return skill, {
                "urls": [],
                "source": "error",
                "status": "failed",
                "error": str(e)
            }


async def process_skills_async(
    unique_skills: List[str],
    tasks,
    source_discoverer,
    max_concurrent: int = 1  # Conservative: 1 at a time
) -> Dict[str, Dict]:
    """
    Async processor for skills using concurrency control with smart batching.
    
    Args:
        unique_skills: List of skills to process
        tasks: Task generator
        source_discoverer: Agent instance
        max_concurrent: Max concurrent LLM requests (reduced for quota management)
    
    Returns:
        Dictionary of results for each skill
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results = {}
    
    # Process skills in small batches to avoid overwhelming the API
    batch_size = min(MAX_SKILLS_PER_RUN, len(unique_skills))
    
    for batch_start in range(0, len(unique_skills), batch_size):
        batch_end = min(batch_start + batch_size, len(unique_skills))
        batch = unique_skills[batch_start:batch_end]
        
        print(f"\n📦 Processing batch {batch_start // batch_size + 1}")
        print(f"   Skills {batch_start + 1}-{batch_end} of {len(unique_skills)}")
        print(f"{'='*80}\n")
        
        tasks_list = []
        
        # Queue tasks for this batch
        for idx, skill in enumerate(batch):
            # Check cache first
            if skill in SEARCH_CACHE:
                print(f"🔍 [{idx + 1}/{len(batch)}] Cache hit: {skill}")
                results[skill] = SEARCH_CACHE[skill]
                continue
            
            print(f"🔍 [{idx + 1}/{len(batch)}] Queued: {skill}")
            
            # Calculate delay to space out requests
            delay = REQUEST_DELAY_SECONDS * idx
            
            # Queue async search for new skills
            task = async_search_skill(skill, tasks, source_discoverer, semaphore, delay)
            tasks_list.append(task)
        
        # Process this batch's tasks
        if tasks_list:
            print(f"\n⏳ Running {len(tasks_list)} searches with throttling...\n")
            
            for coro in asyncio.as_completed(tasks_list):
                try:
                    skill, result = await coro
                    results[skill] = result
                    SEARCH_CACHE[skill] = result
                    print(f"   ✓ Completed: {skill} - Found {len(result['urls'])} URLs")
                except Exception as e:
                    print(f"   ✗ Error: {str(e)[:100]}")
        
        # Wait between batches to avoid quota exhaustion
        if batch_end < len(unique_skills):
            print(f"\n⏳ Waiting {REQUEST_DELAY_SECONDS * len(batch)}s before next batch...\n")
            await asyncio.sleep(REQUEST_DELAY_SECONDS * len(batch))
    
    return results


def test_source_discoverer_agent(skills_from_agent1: list):
    """
    Test the Source Discoverer Agent.
    Takes structured skill list from Agent 1 (JSON input).
    
    Returns clean JSON with skills and their URLs.
    
    Optimizations applied:
    1. Deduplicate skills (simple comparison)
    2. Async batch processing (concurrent searches)
    3. Cache reuse (avoid duplicate searches)
    4. Semaphore control (rate limiting, max 3 concurrent)
    
    Args:
        skills_from_agent1: List of skills extracted from Agent 1
    
    Returns:
        dict: Clean format with skills mapped to URLs
    """
    
    if not skills_from_agent1 or len(skills_from_agent1) == 0:
        print("Error: No skills provided from Agent 1")
        return None
    
    print(f"\n{'='*80}")
    print(f"🚀 SOURCE DISCOVERER AGENT")
    print(f"{'='*80}")
    print(f"Input skills: {len(skills_from_agent1)}")
    
    # STEP 1: Deduplicate skills from structured input
    unique_skills, dedup_info = deduplicate_skills(skills_from_agent1)
    
    # Initialize agents and tools
    agents = InterviewPrepAgents()
    tasks = InterviewPrepTasks()
    
    tools = {
        "google_search_tool": google_search_tool,
        "smart_web_content_extractor": smart_web_content_extractor,
    }
    
    source_discoverer = agents.source_discoverer_agent(tools)
    
    all_sources = {}
    cached_count = 0
    
    print(f"\n{'='*80}")
    print(f"SEARCHING FOR RESOURCES")
    print(f"{'='*80}\n")
    
    # STEP 2: Run async batch processing with rate limiting
    async_results = asyncio.run(
        process_skills_async(unique_skills, tasks, source_discoverer, max_concurrent=1)
    )
    all_sources.update(async_results)
    
    # Calculate stats
    llm_searches = len([r for r in all_sources.values() if r.get('source') == 'llm_search'])
    cached_count = len([r for r in all_sources.values() if r.get('source') != 'llm_search'])
    
    print(f"\n{'='*80}")
    print(f"📊 PROCESSING COMPLETE")
    print(f"{'='*80}")
    print(f"  Input skills: {len(skills_from_agent1)}")
    print(f"  Unique skills: {len(unique_skills)}")
    print(f"  Duplicates removed: {dedup_info['original_count'] - len(unique_skills)}")
    print(f"  ♻️  Cache hits: {cached_count}")
    print(f"  🔍 New LLM searches: {llm_searches}")
    
    # Create clean output: skills with their URLs only
    clean_output = {}
    for skill, data in all_sources.items():
        clean_output[skill] = data.get("urls", [])
    
    # Prepare comprehensive output with all required fields
    output_data = {
        "skills_with_resources": clean_output,
        "input_skills": skills_from_agent1,
        "unique_skills": unique_skills,
        "duplicates_removed": dedup_info['original_count'] - len(unique_skills),
        "optimization_stats": {
            "cache_hits": cached_count,
            "llm_searches": llm_searches,
            "total_skills_processed": len(skills_from_agent1)
        },
        "status": "success" if all_sources else "failed"
    }
    
    # Only save skills with URLs to the output file
    output_path = "backend/tests/discovered_sources.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(clean_output, f, indent=2, ensure_ascii=False)  # type: ignore
    
    print(f"\n✅ Results saved to: {output_path}")
    print(f"{'='*80}\n")
    
    return output_data


if __name__ == "__main__":
    if __name__ == "__main__":
        # Load skills from Agent 1 output (using hybrid approach)
        agent1_output_path = "backend/tests/extracted_skills.json"
        
        if not os.path.exists(agent1_output_path):
            print(f"Error: Agent 1 output not found at {agent1_output_path}")
            print("Please run test_agent_1_resume_analyzer.py first (using hybrid approach)")
            sys.exit(1)
        
        with open(agent1_output_path, "r", encoding="utf-8") as f:
            agent1_result = json.load(f)
        
        skills = agent1_result.get("skills", [])
        
        if not skills:
            print("Error: No skills found in Agent 1 output")
            sys.exit(1)
        
        # Run the test using hybrid approach (Agent 1: direct async, Agents 2&3: CrewAI)
        result = test_source_discoverer_agent(skills)
        
        if result:
            print("\nTest Results Summary (Hybrid Approach):")
            print(json.dumps({
                "input_skills": result["input_skills"],
                "unique_skills": result["unique_skills"],
                "duplicates_removed": result["duplicates_removed"],
                "optimization_stats": result["optimization_stats"],
                "status": result["status"]
            }, indent=2))
