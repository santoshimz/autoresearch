---
name: colorize-images
description: Colorizes black and white images with the Gemini image API using GEMINI_API_KEY from .env or the environment.
---

# Colorize Images

## Use This Skill When

Apply this skill when the user wants to turn black and white photos into color images using Gemini.

## Guardrails

- Never log API keys.
- Fail clearly when `GEMINI_API_KEY` is missing.
- Keep automated tests mocked instead of calling the live API.
- Preserve framing and scene details unless the user explicitly asks for creative changes.
