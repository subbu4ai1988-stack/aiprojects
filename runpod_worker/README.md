# RecruitAI Runpod transcription worker

This image runs a Runpod Serverless handler for interview-video transcription. It uses Faster-Whisper on a GPU and returns a structured result to the RecruitAI API. RecruitAI remains fully usable with `TRANSCRIPTION_PROVIDER=local`; Runpod is opt-in.

## Job contract

Request:

```json
{
  "input": {
    "operation": "transcribe",
    "media_url": "https://recruit.example/api/storage/download?...",
    "transcript_hint": "Optional typed answer",
    "language": null
  }
}
```

Successful worker output:

```json
{
  "operation": "transcribe",
  "status": "completed",
  "provider": "runpod-faster-whisper",
  "text": "Transcribed answer",
  "language": "en",
  "language_probability": 0.99,
  "duration_seconds": 42.1,
  "segments": []
}
```

The `health` operation does not load the model and can be used for a lightweight worker test.

## Build and test locally

Run these commands from the repository root. Replace the image name with your Docker Hub or GitHub Container Registry account.

```powershell
docker build --platform linux/amd64 -f runpod_worker/Dockerfile -t YOUR_ACCOUNT/recruitai-runpod-worker:0.1.0 .
docker run --rm -e WORKER_MODE=stub YOUR_ACCOUNT/recruitai-runpod-worker:0.1.0
docker push YOUR_ACCOUNT/recruitai-runpod-worker:0.1.0
```

The included `test_input.json` sends a health job, so the stub test does not download a model or require a GPU.

## Create the Runpod Serverless endpoint

1. Create a Runpod Serverless template using the pushed image.
2. Configure these template environment variables:

   - `WHISPER_MODEL=small`
   - `WHISPER_DEVICE=cuda`
   - `WHISPER_COMPUTE_TYPE=float16`
   - `WHISPER_BEAM_SIZE=5`
   - `MAX_MEDIA_BYTES=26214400`
   - `MEDIA_DOWNLOAD_TIMEOUT_SECONDS=60`

3. Create a Serverless endpoint from that template. A minimum worker count of `0` avoids idle GPU charges; use `1` when lower latency matters more than idle cost.
4. Copy the endpoint ID and create a Runpod API key with only the permissions needed to invoke the endpoint.
5. Do not set `ALLOW_INSECURE_MEDIA_URLS` or `ALLOW_PRIVATE_MEDIA_URLS` in production.

Use Runpod's official guides for [custom worker deployment](https://docs.runpod.io/serverless/workers/deploy), [handler functions](https://docs.runpod.io/serverless/workers/handler-functions), and [endpoint requests](https://docs.runpod.io/serverless/endpoints/send-requests).

## Connect RecruitAI

Set the following values in the RecruitAI deployment environment, not in source control:

```dotenv
TRANSCRIPTION_PROVIDER=runpod
RUNPOD_API_KEY=your_runpod_api_key
RUNPOD_ENDPOINT_ID=your_serverless_endpoint_id
RUNPOD_BASE_URL=https://api.runpod.ai/v2
RUNPOD_TIMEOUT_SECONDS=150
RUNPOD_WAIT_MS=120000
RUNPOD_TRANSCRIPTION_LANGUAGE=
PUBLIC_APP_URL=https://your-public-recruitai-domain.example
```

`PUBLIC_APP_URL` must be a publicly reachable HTTPS address. The Runpod worker uses a short-lived signed URL from RecruitAI to download private interview media. `localhost`, MinIO's private address, and private network addresses are intentionally rejected by the worker.

After changing the environment, restart the RecruitAI API and worker services. If Runpod is unavailable, RecruitAI records a failed integration event and safely retains the candidate's supplied transcript instead of failing the interview submission.
