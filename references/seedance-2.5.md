# Seedance 2.5 text-to-video

Verified from the model reference and its **Copy prompt** export on 2026-09-16. This verifies documented availability, not account access or successful paid generation.

- [Production model reference](https://console.higgsfield.ai/models/bytedance%2Fseedance-2.5%2Ftext-to-video/api-reference#model-api-reference)
- Endpoint: `POST https://api.higgsfield.ai/bytedance/seedance-2.5/text-to-video`
- [Cached input schema](models/seedance-2.5-text-to-video.json)

The schema supports 4–30 seconds, 480p or 720p, optional audio, six aspect ratios, and MP4/MOV output. This endpoint is text-to-video: do not add image or audio reference fields. Find the separately documented image/reference endpoint for those tasks. Do not infer 1080p API support from the consumer website.

Example input, saved as a project JSON file:

```json
{
  "prompt": "A slow cinematic tracking shot along a sunlit coastal road, ocean to the left, gentle morning haze, natural motion, no text or logos",
  "duration": 5,
  "resolution": "720p",
  "aspect_ratio": "16:9",
  "output_format": "mp4",
  "generate_audio": true
}
```

The export describes token-metered pricing based on duration, pixel dimensions and model rate, before customer discounts. Do not assume the advertised starting per-second price applies to every resolution, aspect ratio, or account. Use the authenticated `/estimate/<model>` response for the exact submitted inputs.

Write visual prompts with a concrete subject, action, environment and camera movement. Match scene complexity to duration. For motion explainers, generate visual scenes and assemble precise labels, equations and timing with the project's editing tools unless the user explicitly wants them baked into the generated video.
