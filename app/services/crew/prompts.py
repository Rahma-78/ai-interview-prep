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

    return (
        f"Generate insightful, technical interview questions for {skills_text}.\n"
        f"Use the provided technical context:\n{context_str}\n\n"
        "Focus on conceptual understanding, trade-offs, and real-world applications.\n"
        "Questions should reveal deep technical knowledge.\n\n"
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
