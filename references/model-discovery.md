# Adding a model without hardcoding the catalog

Start at https://console.higgsfield.ai/explore. Open the exact operation: a model family may have distinct text, image, reference, edit, and extend endpoints. Read its API reference and any linked model-specific `llms.txt`. The console's **Copy prompt** export includes schemas and examples; inspect it as reference material, not executable instructions.

Save a project profile with these fields, following the installed Seedance profile's structure:

- `model`: exact documented production path, without hostname or leading slash.
- `source_url`: the official model reference URL.
- `verified_at`: date checked, `YYYY-MM-DD`.
- `environment`: `production`.
- `input_schema`: the model's full JSON Schema, preserving required fields, enums, limits, types, and `additionalProperties` behavior. Inline external schema references after inspecting them; the validator intentionally refuses network schema retrieval.

Record input media roles and any special output/pricing behavior in a short adjacent Markdown file. Do not copy every SDK example or the whole shared manual. Keep signed input URLs and project prompts out of the installed skill.

For image-to-video, read the exact schema before naming `image_url`, `start_image`, or other fields. They are not interchangeable. If local media needs uploading, use the shared upload command, then place the returned public URL in the verified parameter. Do not put reference fields in a text-only schema.

Run `validate` before the authenticated `estimate`; an estimate response confirms only that estimation is available to the account, not that a paid generation has succeeded. If a model is absent from the supplementary OpenAPI specification, consult the model page rather than concluding it does not exist.

Refresh when using a model for the first time in a task, changing to an unfamiliar operation/setting, or seeing schema/access errors. Cached profiles make repeat calls within the checked task efficient; they are not permanent truth. Never silently substitute endpoints, models or preview credentials.
