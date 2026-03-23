---
name: process-bw-images
description: Runs the crop workflow first and then colorizes the cropped images with Gemini.
---

# Process Black And White Images

## Workflow

This is a meta-skill. Do not jump straight to `src/process_bw_images.py` when the point is to demonstrate multi-skill composition.

Instead:

1. Apply the `cropping-images` skill to create `*-cropped.jpg` files from the source images.
2. Apply the `colorize-images` skill only to the cropped outputs.
