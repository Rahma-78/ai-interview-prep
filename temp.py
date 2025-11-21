
@tool
async def question_generator(skill: str, sources_content: str) -> str:
    """
    Generates interview questions based on a provided skill and contextual content.

    Args:
        skill: The technical skill to generate questions for.
        sources_content: The context to use for generating questions.

    Returns:
        A JSON string containing the generated questions or an error message.
    """
    prompt = QUESTION_GENERATOR_PROMPT_TEMPLATE.format(
        skill=skill, sources=sources_content
    )
    try:
        llm_response = await call_llm_with_retry(
            llm_openrouter,
            prompt,
            timeout=settings.QUESTION_GENERATION_TIMEOUT
        )
        questions_data = clean_and_parse_json(llm_response)
        questions_list = questions_data.get("questions", [])

        interview_questions = InterviewQuestions(skill=skill, questions=questions_list)
        return AllInterviewQuestions(all_questions=[interview_questions]).json()

    except (JSONDecodeError, Exception) as e:
        logger.error(f"Error generating questions for '{skill}': {e}", exc_info=True)
        return json.dumps({"skill": skill, "questions": [], "error": f"Question generation failed: {e}"})
