import asyncio
import json
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from crewai import Crew, Process

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.schemas.interview import AllSkillSources, Source
from app.services.agents.agents import InterviewPrepAgents
from app.services.tasks.tasks import InterviewPrepTasks
from app.services.tools.tools import google_search_tool, smart_web_content_extractor

# Configure logging for tests
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


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
        logging.info(f"\n🔍 Deduplication: {len(skills)} → {len(filtered)} skills")
        logging.info(f"   Removed {len(duplicates_found)} duplicates")
        for dup, canonical in duplicates_found:
            logging.info(f"     '{dup}' → '{canonical}'")
    
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
        if delay > 0:
            logging.info(f"   ⏳ Waiting {delay:.1f}s before searching '{skill}'...")
            await asyncio.sleep(delay)
        
        try:
            search_task = tasks.search_sources_task(source_discoverer, skill)
            search_crew = Crew(
                agents=[source_discoverer],
                tasks=[search_task],
                process=Process.sequential,
                verbose=False,
            )
            
            search_result = await search_crew.kickoff_async()
            
            urls = []
            try:
                parsed_result = AllSkillSources(**json.loads(str(search_result)))
                for skill_source_item in parsed_result.all_sources:
                    if skill_source_item.skill.lower() == skill.lower():
                        urls = [source.uri for source in skill_source_item.sources]
                        break
                
                logging.debug(f"Extracted {len(urls)} URLs from search result for skill '{skill}'")
                
            except (json.JSONDecodeError, ValueError) as e:
                logging.debug(f"Error parsing search result as AllSkillSources: {e}")
                logging.debug(f"Raw search result string: {str(search_result)[:500]}...")
                import re
                url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
                urls = re.findall(url_pattern, str(search_result))
                logging.debug(f"Found {len(urls)} URLs via regex fallback")
            
            return skill, {
                "urls": urls[:MAX_URLS_PER_SKILL],
                "source": "llm_search",
                "status": "success" if urls else "no_urls",
                "urls_found_count": len(urls)
            }
        
        except Exception as e:
            logging.error(f"   ⚠️  Error searching '{skill}': {str(e)[:100]}", exc_info=True)
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
    max_concurrent: int = 1
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
    
    batch_size = min(MAX_SKILLS_PER_RUN, len(unique_skills))
    
    for batch_start in range(0, len(unique_skills), batch_size):
        batch_end = min(batch_start + batch_size, len(unique_skills))
        batch = unique_skills[batch_start:batch_end]
        
        logging.info(f"\n📦 Processing batch {batch_start // batch_size + 1}")
        logging.info(f"   Skills {batch_start + 1}-{batch_end} of {len(unique_skills)}")
        logging.info(f"{'='*80}\n")
        
        tasks_list = []
        
        for idx, skill in enumerate(batch):
            if skill in SEARCH_CACHE:
                logging.info(f"🔍 [{idx + 1}/{len(batch)}] Cache hit: {skill}")
                results[skill] = SEARCH_CACHE[skill]
                continue
            
            logging.info(f"🔍 [{idx + 1}/{len(batch)}] Queued: {skill}")
            
            delay = REQUEST_DELAY_SECONDS * idx
            
            task = async_search_skill(skill, tasks, source_discoverer, semaphore, delay)
            tasks_list.append(task)
        
        if tasks_list:
            logging.info(f"\n⏳ Running {len(tasks_list)} searches with throttling...\n")
            
            for coro in asyncio.as_completed(tasks_list):
                try:
                    skill, result = await coro
                    results[skill] = result
                    SEARCH_CACHE[skill] = result
                    logging.info(f"   ✓ Completed: {skill} - Found {len(result['urls'])} URLs")
                except Exception as e:
                    logging.error(f"   ✗ Error: {str(e)[:100]}", exc_info=True)
        
        if batch_end < len(unique_skills):
            logging.info(f"\n⏳ Waiting {REQUEST_DELAY_SECONDS * len(batch)}s before next batch...\n")
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
        logging.error("Error: No skills provided from Agent 1")
        return None
    
    logging.info(f"\n{'='*80}")
    logging.info(f"🚀 SOURCE DISCOVERER AGENT")
    logging.info(f"{'='*80}")
    logging.info(f"Input skills: {len(skills_from_agent1)}")
    
    unique_skills, dedup_info = deduplicate_skills(skills_from_agent1)
    
    agents = InterviewPrepAgents()
    tasks = InterviewPrepTasks()
    
    tools = {
        "google_search_tool": google_search_tool,
        "smart_web_content_extractor": smart_web_content_extractor,
    }
    
    source_discoverer = agents.source_discoverer_agent(tools)
    
    all_sources = {}
    cached_count = 0
    
    logging.info(f"\n{'='*80}")
    logging.info(f"SEARCHING FOR RESOURCES")
    logging.info(f"{'='*80}\n")
    
    async_results = asyncio.run(
        process_skills_async(unique_skills, tasks, source_discoverer, max_concurrent=1)
    )
    all_sources.update(async_results)
    
    llm_searches = len([r for r in all_sources.values() if r.get('source') == 'llm_search'])
    cached_count = len([r for r in all_sources.values() if r.get('source') != 'llm_search'])
    
    logging.info(f"\n{'='*80}")
    logging.info(f"📊 PROCESSING COMPLETE")
    logging.info(f"{'='*80}")
    logging.info(f"  Input skills: {len(skills_from_agent1)}")
    logging.info(f"  Unique skills: {len(unique_skills)}")
    logging.info(f"  Duplicates removed: {dedup_info['original_count'] - len(unique_skills)}")
    logging.info(f"  ♻️  Cache hits: {cached_count}")
    logging.info(f"  🔍 New LLM searches: {llm_searches}")
    
    clean_output = {}
    for skill, data in all_sources.items():
        clean_output[skill] = data.get("urls", [])
    
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
    
    output_path = "app/tests/discovered_sources.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(clean_output, f, indent=2, ensure_ascii=False)  # type: ignore
    
    logging.info(f"\n✅ Results saved to: {output_path}")
    logging.info(f"{'='*80}\n")
    
    return output_data


if __name__ == "__main__":
    agent1_output_path = "app/tests/extracted_skills.json"
    
    if not os.path.exists(agent1_output_path):
        logging.error(f"Error: Agent 1 output not found at {agent1_output_path}")
        logging.error("Please run test_agent_1_resume_analyzer.py first (using hybrid approach)")
        sys.exit(1)
    
    with open(agent1_output_path, "r", encoding="utf-8") as f:
        agent1_result = json.load(f)
    
    skills = agent1_result.get("skills", [])
    
    if not skills:
        logging.error("Error: No skills found in Agent 1 output")
        sys.exit(1)
    
    result = test_source_discoverer_agent(skills)
    
    if result:
        logging.info("\nTest Results Summary (Hybrid Approach):")
        logging.info(json.dumps({
            "input_skills": result["input_skills"],
            "unique_skills": result["unique_skills"],
            "duplicates_removed": result["duplicates_removed"],
            "optimization_stats": result["optimization_stats"],
            "status": result["status"]
        }, indent=2))
