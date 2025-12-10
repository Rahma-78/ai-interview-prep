from typing import List, Union

def generate_questions_prompt(skills: Union[str, List[str]], context_str: str) -> str:
    """
    Generate the prompt for interview question generation.
    
    Args:
        skills: A single skill string or a list of skill strings.
        context_str: The technical context string.
        
    Returns:
        The formatted prompt string.
    """
    if isinstance(skills, list):
        skills_text = f"these skills: {', '.join(skills)}"
    else:
        skills_text = f"this skill: {skills}"
    
    # Check if we have actual context or just the fallback message
    has_context = context_str and "No technical context available" not in context_str
    
    if has_context:
        return (
            f"Generate insightful, technical interview questions for {skills_text}.\n"
            f"Use the provided technical context:\n{context_str}\n\n"
            "Focus on conceptual understanding, Analysis and comparison , and real-world applications.\n"
            "Questions should reveal deep technical knowledge.\n\n"
            "Return ONLY a JSON object with this structure:\n"
            "{\"all_questions\": [{\"skill\": \"...\", \"questions\": [\"question1\", \"question2\", ...]}]}"
        )
    else:
        # Context-free prompt - focus on verbal technical questions
        return generate_contextfree_questions_prompt(skills)


def generate_contextfree_questions_prompt(skills: Union[str, List[str]]) -> str:
    """
    Generate prompt for context-free verbal technical questions.
    Used when no technical context/sources are available for a skill.
    
    Args:
        skills: A single skill string or a list of skill strings.
        
    Returns:
        The formatted prompt string for context-free questions.
    """
    if isinstance(skills, list):
        skills_text = f"these skills: {', '.join(skills)}"
    else:
        skills_text = f"this skill: {skills}"
    
    return (
        f"Generate verbal technical interview questions for {skills_text}.\n\n"
        "IMPORTANT GUIDELINES:\n"
        "- Generate questions that test CONCEPTUAL understanding, not syntax or code\n"
        "- Focus on fundamental concepts, principles, and theoretical knowledge\n"
        "- Ask about trade-offs, use cases, and design decisions\n"
        "- Avoid questions requiring specific code implementations\n"
        "- Questions should be suitable for verbal discussion in an interview\n"
        "- DO NOT ask about specific libraries, tools, or framework syntax\n"
        "- Focus on 'what', 'why', 'when', and 'how' rather than implementation details\n\n"
        "Return ONLY a JSON object with this structure:\n"
        "{\"all_questions\": [{\"skill\": \"...\", \"questions\": [\"question1\", \"question2\", ...]}]}"
    )


def generate_skill_extraction_prompt(resume_text: str, skill_count: int) -> str:
    """
    Generate the prompt for technical skill extraction from a resume.
    
    Args:
        resume_text: The full text content of the resume.
        skill_count: The number of skills to extract.
        
    Returns:
        The formatted prompt string.
    """
    return (
        f"Analyze the following resume text and extract exactly {skill_count} technical skills.\n\n"
        "Extraction Criteria:\n"
        "- Foundational Focus: Prioritize foundational concepts over specific tools.\n"
        "- Core Competencies: Extract technical skills as listed in the 'Skills' section; do not infer generic activities.\n"
        "- Conceptual Depth: Skills must support deep discussions and conceptual analysis.\n"
        "- Verbal Suitability: Favor skills that allow candidates to explain concepts rather than just coding syntax.\n"
        "- Diversity: Ensure the list encompasses the full range of the candidate's skills. Avoid redundancy by selecting broader concepts.\n"
        "- Exclusions: Avoid generic soft skills or vague terms lacking technical substance.\n"
        "- Critical Requirement: Skills must be suitable for generating non-coding interview questions, focusing on substantive technical knowledge.\n\n"
        f"Resume Text:\n{resume_text}\n\n"
        f"Return ONLY a JSON object with this structure:\n"
        "{\"skills\": [\"skill1\", \"skill2\", ...]}"
    )
