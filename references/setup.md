# Setup and commands

Use Python 3.10+ and the skill's `requirements.txt`. Create a runtime outside the skill so its shareable folder stays free of packages and credentials.

Recommended runtime location: `<project>/work/higgsfield-venv`, or reuse the installed skill's configured interpreter recorded in `references/local-runtime.md` if that file exists. For a fresh machine:

```powershell
py -3 -m venv work/higgsfield-venv
& work/higgsfield-venv/Scripts/python.exe -m pip install -r <skill>/requirements.txt
```

On macOS/Linux, use `python3 -m venv work/higgsfield-venv` and `work/higgsfield-venv/bin/python -m pip install -r <skill>/requirements.txt`.

Configure `HF_API_KEY_ID` and `HF_API_KEY_SECRET` in the agent/server process environment using your normal secret manager or private local configuration. Combined `HF_CREDENTIALS` or `HF_KEY` is also accepted when the separate variables are absent. `.env.example` contains placeholders only; the helper does not auto-load dotenv. Never put the real values in a displayed command or paste them into the skill. A credential pasted into chat should be rotated before production use; configure its replacement privately.

Below, `python` means the actual chosen runtime, and `<skill>` means the installed skill directory. Use absolute script/profile paths and run from the current project. No command below needs the API key in its arguments.

```text
python <skill>/scripts/higgsfield_api.py validate --profile <skill>/references/models/seedance-2.5-text-to-video.json --input work/higgsfield/shot.json
python <skill>/scripts/higgsfield_api.py estimate --profile <skill>/references/models/seedance-2.5-text-to-video.json --input work/higgsfield/shot.json
python <skill>/scripts/higgsfield_api.py submit --profile <skill>/references/models/seedance-2.5-text-to-video.json --input work/higgsfield/shot.json --job explainer-opening-v1
python <skill>/scripts/higgsfield_api.py wait --job explainer-opening-v1 --timeout 1200
python <skill>/scripts/higgsfield_api.py download --job explainer-opening-v1 --output-dir outputs
```

No spending cap is required by default. When the user explicitly requests one, append both `--budget-id explainer-v1 --budget-usd 10` to the submit command, replacing the example amount with the requested cap. Reuse that budget ID and amount across all shots in the batch. The helper refuses changing an existing limit silently. It also refuses reusing a job ID for different inputs, model, credentials or budget, including switching an existing job between capped and uncapped modes.

- `validate`: local schema validation; no credentials or network needed.
- `estimate`: authenticated price lookup; no generation submitted.
- `submit`: one paid submission, after schema validation and a fresh estimate. Returns immediately with persisted status. No automatic POST retries.
- `status`: one authenticated status lookup for a saved job.
- `wait`: bounded polling, resumable after timeout; terminal generation failures return a nonzero exit status.
- `download`: downloads all completed image/video/audio and supported artifact URLs without sending API credentials to media hosts. Saves deterministic files and refuses to overwrite existing files.
- `attach --job NAME --request-id UUID`: recovers an uncertain submission after the agent/user has identified the correct provider request in the console. Retrieves authenticated status first; this cannot verify the original prompt automatically. Never guess the ID.
- `upload --file PATH`: explicitly uploads an authorized reference and returns its public URL. It does not infer model input fields.
- `--state-dir PATH`: a global option before the command. Default: `work/higgsfield/` under the current directory. Use the same state directory to retain deduplication and budget accounting.

After interrupted/uncertain submission, inspect the console and use `attach`; do not delete the job record or invent another job name. Polling timeouts do not submit or cancel anything. The helper logs HTTP codes/correlation IDs, not provider error bodies that might echo prompts or credentials. Look up the documented error category and revise the request deliberately.

For a caller already authorized to generate a clip, proceed without introducing a mandatory budget or another approval step. Without usable credentials, report setup is incomplete; do not claim authenticated testing or paid output.
