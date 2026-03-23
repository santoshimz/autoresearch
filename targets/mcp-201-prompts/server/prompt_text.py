DEFAULT_COLORIZE_PROMPT = (
    "Colorize this black and white photo realistically. Preserve the framing, people, "
    "objects, expressions, and scene details. Do not add or remove anything."
)

CROP_IMAGES_TOOL_DESCRIPTION = "Crop uploaded screenshots or images to the visible frame."
COLORIZE_IMAGES_TOOL_DESCRIPTION = "Colorize uploaded images using either the server Gemini key or ephemeral BYOK."
RUN_PROMPT_WORKFLOW_TOOL_DESCRIPTION = (
    "Interpret a natural-language prompt with AI planning and route to the correct workflow."
)


def build_planner_prompt(user_prompt: str) -> str:
    return (
        "You are a strict workflow planner.\n"
        "Choose exactly one workflow from: crop_images, colorize_images, crop_then_colorize.\n"
        "Return JSON only with keys workflow, confidence, reasoning_summary.\n"
        "If the user asks for both crop and colorization, choose crop_then_colorize.\n"
        "User prompt: "
        f"{user_prompt}"
    )
