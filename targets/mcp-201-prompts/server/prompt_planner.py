from prompt_text import build_planner_prompt


def planner_prompt_for(user_prompt: str) -> str:
    return build_planner_prompt(user_prompt)
