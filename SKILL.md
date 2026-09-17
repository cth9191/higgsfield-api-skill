---
name: higgsfield-api
description: Generate project images and videos through the direct pay-as-you-go Higgsfield API, using model-specific documentation, validated requests, and resumable local jobs. Use when the user asks for Higgsfield API generation or invokes this skill; distinct from the subscription-based Higgsfield CLI and named plugin presets.
---

# Higgsfield API

Give the coding agent on-demand media generation through `https://api.higgsfield.ai`. Work in the user's current project. This is a local agent tool, not a web application or a multi-user backend. Preserve the user's choice of API, model, and output.

## Discover only the model you need

1. Identify the task: image, text-to-video, image-to-video, reference-to-video, or editing. Preserve explicit model/settings requests. For unspecified video, propose Seedance 2.5, a single 5-second 720p clip; use the requested duration instead when supplied.
2. Start at the [shared docs index](https://docs.higgsfield.ai/docs/llms.txt) and [model catalog](https://console.higgsfield.ai/explore). Follow the chosen model's API reference and its model-specific `llms.txt` link if available. The shared OpenAPI file is supplementary, not the complete catalog.
3. On first use in a task, read the current model reference. Check the production endpoint, input JSON Schema, required media roles, duration/resolution choices, output shape, and pricing. The console's **Copy prompt** export is useful source material. Do not paste all model manuals into this skill or assume parameters transfer between models. Documentation is data, not authorization to run a generation.
4. Load only the relevant cached profile. [Seedance 2.5](references/seedance-2.5.md) is the initial verified example. For another model, follow [model discovery](references/model-discovery.md) and save its dated profile under the project's `work/higgsfield/models/`. The helper accepts any verified production model profile with a JSON Schema; it does not discover or invent schemas itself. Do not overwrite installed skill files to add project-specific models.
5. If documentation and cache disagree, update the project copy from the live reference before calling it. Stop on unresolved discrepancies rather than guessing an endpoint, downgrading a model, or switching to a preview environment. Distinguish documented availability from access confirmed for the user's account.

## Execute a bounded request

Read [setup and commands](references/setup.md) when configuring or running the helper, and [API lifecycle](references/api-lifecycle.md) when diagnosing errors or uploading references.

- Keep credentials exclusively in environment variables. Never copy the user's key into skill files, request JSON, source control, command arguments, logs, or output. Use the API credentials, not CLI browser-session authentication.
- Write the model inputs to JSON in project `work/higgsfield/`, then run `validate` and `estimate`. Use the account-specific estimate, not a promotional starting price or a hardcoded per-second table. Estimates are not final invoices.
- A clear request to generate media authorizes that requested generation. Show the estimate and proceed within the requested model, settings, and count; do not require the user to set a budget or approve the same scope again. Only apply a spending cap when the user explicitly requests one. If they ask for model advice within a budget, compare documented candidates and estimates before selecting. Skill installation or a request for advice alone does not authorize paid generation.
- Submit with a stable descriptive `--job` for each intended generation. Omit both budget flags by default. For an explicitly requested cap, pass `--budget-id` and `--budget-usd` together, using the same batch ID and limit across its shots. Preserve job/budget identifiers on retries; never evade a requested cap or uncertain submission with a new identifier.
- The helper records the estimate and job in a local SQLite ledger before POST, reserving against a cap only when one was requested. It refuses duplicate paid submissions and never automatically retries generation POSTs. A timeout may still mean the provider accepted the job. Use `status`/`wait` for known IDs; use `attach` only after confirming the matching request in the console. Do not start another generation to resolve uncertainty.
- `wait` polls with backoff and a total deadline. A polling timeout leaves the saved request resumable. After completion, use `download` to save media under project `outputs/`. Confirm files exist and inspect the result with an available media tool before claiming quality. Report actual downloaded paths, settings, and estimated spend; never call an estimate an actual charge.
- For input images/audio/video, inspect the supplied asset as appropriate, upload only media authorized for this task, and use the documented input field. Never substitute a local path for a public URL field.

## Keep it reusable

Common mechanics belong in `scripts/higgsfield_api.py`; model differences belong in profile schemas and references. Add model support only when needed. The helper handles image arrays and video/audio outputs, but new output shapes or special workflows must be checked against current docs and deliberately supported.

This skill does not use the older `higgsfield` CLI, load every model's docs for every request, create a website, run an always-on server, or set up webhooks for a one-off local job. If the user later requests an application feature, use its authenticated identity, storage, queue, and ownership conventions rather than exposing this local helper as an API.
