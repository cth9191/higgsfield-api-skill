# Higgsfield API Skill

Give your coding agent on-demand image and video generation through the direct, pay-as-you-go [Higgsfield API](https://docs.higgsfield.ai/docs). Ask for a model by name, or describe what you want and let the agent recommend one based on current model documentation and estimated cost.

This is an independent community skill, not an official Higgsfield product. API access and billing are configured through [Higgsfield Console](https://console.higgsfield.ai).

## Install

For Codex, clone this repository into your skills directory. If you use a custom `CODEX_HOME`, use its `skills/higgsfield-api` directory instead. If already installed, update the existing checkout rather than cloning over it.

macOS / Linux:

```sh
git clone https://github.com/cth9191/higgsfield-api-skill.git ~/.codex/skills/higgsfield-api
```

Windows PowerShell:

```powershell
git clone https://github.com/cth9191/higgsfield-api-skill.git "$env:USERPROFILE/.codex/skills/higgsfield-api"
```

Start a new agent session to discover the skill. Other agents that support `SKILL.md` can use the same folder in their own skill directory.

## First-time setup

1. Create your API credentials in [Higgsfield Console](https://console.higgsfield.ai). The skill cannot issue an API key for you.
2. Configure `HF_API_KEY_ID` and `HF_API_KEY_SECRET` privately in the agent's process environment. Never commit credentials or paste them into an agent conversation. `.env.example` lists the variable names; the helper does not automatically load `.env` files.
3. Ask the agent to set up the skill's Python runtime using [setup and commands](references/setup.md). Requires Python 3.10+ and the dependencies in `requirements.txt`.

The agent checks model documentation, prepares and validates the request, estimates its cost, submits the generation you requested, polls for completion, and downloads results into your project's `outputs/` directory.

## Try it

```text
Use $higgsfield-api to generate a 5-second 720p Seedance 2.5 video of
a cinematic tracking shot along a sunlit coastal road.
```

```text
Use $higgsfield-api to recommend a model for animating this product photo.
Compare the estimated costs before generating anything.
```

```text
Use $higgsfield-api to create three short clips for this explainer.
Keep the total estimated cost under $10.
```

Budgets are optional. A generation request does not require setting a spending cap. When you explicitly request a cap, the helper tracks the batch's estimated costs locally and blocks submissions that would exceed it. Estimates can differ from final charges, and this local ledger does not read your live account balance or include spending from other tools.

## What is included

- Model-specific documentation discovery instead of a hardcoded catalog of every model.
- A cached Seedance 2.5 text-to-video schema as the initial example. Other models require the agent to verify their current reference and create a profile before use.
- Environment-only credentials, JSON Schema validation, resumable jobs, polling with backoff, file uploads and result downloads.
- Stable job identifiers and local duplicate protection. An uncertain submission is preserved for recovery instead of automatically submitted again.

Keep the project's `work/higgsfield/` state directory between runs. It contains prompts, job IDs and output URLs; exclude it from source control. Deleting it removes local duplicate protection and optional budget accounting.

## Validation

Run with the Python environment containing `requirements.txt`:

```sh
python -m unittest discover -s tests -v
```

Tests use simulated API responses and make no paid requests. The current package has not been validated with a live paid generation. Model availability and prices must be checked against current documentation and your account when used.
