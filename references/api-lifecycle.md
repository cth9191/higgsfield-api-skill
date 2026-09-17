# Shared API mechanics

Verified 2026-09-16. Use the live [index](https://docs.higgsfield.ai/docs/llms.txt) to locate updates. If a `.md` documentation link cannot be fetched, open the corresponding HTML page.

## Authentication and SDK choice

[Authentication](https://docs.higgsfield.ai/docs/authentication) specifies production REST at `https://api.higgsfield.ai`, `Authorization: Key KEY_ID:KEY_SECRET`, and JSON bodies. The helper uses Python REST so it can save the accepted request immediately and control retry behavior explicitly. Official [Python and TypeScript SDKs](https://docs.higgsfield.ai/docs/how-to/sdk) are alternatives when embedding this in an existing application; do not assume their convenience methods have identical return shapes.

## Jobs, retries and ownership

[Lifecycle](https://docs.higgsfield.ai/docs/concepts/requests) and [polling](https://docs.higgsfield.ai/docs/concepts/polling): preserve the returned request ID and status URL. Poll queued/in-progress jobs starting at 2 seconds and increasing toward 10 seconds with jitter. Stop on completed, failed, nsfw or canceled. A local wait deadline does not cancel remote generation.

[Errors](https://docs.higgsfield.ai/docs/concepts/errors) distinguish authentication, funding, validation and availability errors. Generation POSTs have no provider idempotency key: never automatically retry an uncertain submission. Status GETs can retry network/5xx/429 errors within a deadline. Concurrency may return HTTP 400; wait for existing work rather than spinning on submissions. [Limits](https://docs.higgsfield.ai/docs/concepts/rate-limits) are account/model-specific; no fixed concurrency number belongs in the skill.

The local ledger binds jobs and budgets to a hash of the API key ID and keeps job IDs unique. It is intended for the current OS user, whose filesystem permissions protect the ledger. It is not authentication or tenant isolation for an application. Keep the same ledger across runs; deleting it discards local duplicate and budget protection.

## Estimates and retention

[Billing](https://docs.higgsfield.ai/docs/concepts/billing-and-retention) documents `POST /estimate/<model>` with the identical request JSON, returning `credits` and `usd`. The helper records the estimate for every job. Only when the user explicitly requests a budget does it reserve this amount against that local cap. This is an estimate-based client guard, not a provider-enforced final-billing ceiling. Unknown/submitting jobs retain their reservation. Definitively rejected, failed, nsfw and canceled jobs release it. Completed jobs keep their estimated reservation; actual invoices may differ. External jobs from other tools are outside this ledger. No supported public account-balance endpoint was found in the documentation checked on 2026-09-16; do not describe the local ledger as the live API wallet balance.

Media has a finite retention window (documented minimum seven days), so download completed outputs promptly. Local state contains prompts, request IDs and output URLs; exclude `work/higgsfield/`, environment files and runtime environments from source control when appropriate.

## Uploads and webhooks

[Uploads](https://docs.higgsfield.ai/docs/concepts/file-uploads): obtain a presigned upload URL from `/files/generate-upload-url`, PUT the file with the returned headers, and put `public_url` in the model's documented input field. Never send API authorization to the storage host. Uploads are a separate, explicit action and do not generate media. The helper limits file sizes and rejects redirects and non-public destinations for file transfers.

[Webhooks](https://docs.higgsfield.ai/docs/how-to/webhooks) apply to existing servers with durable background work, not this local skill. If later implementing them, use `hf_webhook`, store/deduplicate deliveries by request ID/status, respond promptly after durable receipt, and keep polling as recovery. The shared page does not establish a signature-verification scheme: do not invent a signing header. Authenticate status through the API before trusting an incoming delivery to change user-visible state or fetch media.
