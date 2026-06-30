"""Probe health/model endpoints and send one multimodal chat completion request."""

import argparse
import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx

DEFAULT_PROMPT = """You are an image moderation classifier.
Analyze the provided image and classify it for unsafe or NSFW content.
Return only valid JSON. Do not explain outside JSON.
Evaluate these categories:
safe
suggestive
nudity
porn
gore
violence
self_harm
hate_or_extremism
drugs
unknown
Severity scale:
0 = not present
1 = very mild / uncertain
2 = mild
3 = moderate
4 = strong
5 = explicit / severe
Rules:
Do not over-classify. If visual evidence is weak, use a lower severity.
If the image is unclear or ambiguous, use "unknown".
If multiple unsafe categories are present, score all relevant categories.
Choose top_category based on the highest severity.
If explicit sexual content involving a person who appears under 18 is present or suspected, set top_category to "sexual_minor_content", is_nsfw to true, and overall_severity to 5.
Keep the reason short and factual.
Return JSON in exactly this format:
{
"top_category": "safe | suggestive | nudity | porn | gore | violence | self_harm | hate_or_extremism | drugs | unknown | sexual_minor_content",
"is_nsfw": false,
"overall_severity": 0,
"categories": {
"safe": 0,
"suggestive": 0,
"nudity": 0,
"porn": 0,
"gore": 0,
"violence": 0,
"self_harm": 0,
"hate_or_extremism": 0,
"drugs": 0,
"unknown": 0
},
"reason": "Short factual reason for the classification."
}

Give response when user sends an Image"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe the multimodal chat completion endpoint")
    parser.add_argument(
        "--base-url",
        default=os.getenv("GPU_INFERENCE_BASE_URL", "http://127.0.0.1:8002"),
        help="Public or direct API base URL.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("GPU_INFERENCE_API_KEY"),
        help="Bearer API key for protected endpoints.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("GPU_INFERENCE_MODEL"),
        help="Model ID to send. Defaults to the first id from /v1/models.",
    )
    parser.add_argument("--image", required=True, help="Path to a local image file.")
    parser.add_argument("--prompt", help="Inline text prompt. Defaults to the built-in prompt.")
    parser.add_argument("--prompt-file", help="Read the prompt from a text file.")
    parser.add_argument(
        "--structured-output",
        action="store_true",
        help="Send response_format={type: json_object}.",
    )
    parser.add_argument("--max-tokens", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--basic-username", default=os.getenv("GPU_INFERENCE_BASIC_USERNAME"))
    parser.add_argument("--basic-password", default=os.getenv("GPU_INFERENCE_BASIC_PASSWORD"))
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification.",
    )
    args = parser.parse_args()
    if not args.api_key:
        parser.error("--api-key or GPU_INFERENCE_API_KEY is required")
    if args.prompt and args.prompt_file:
        parser.error("use only one of --prompt or --prompt-file")
    if bool(args.basic_username) != bool(args.basic_password):
        parser.error("--basic-username and --basic-password must be provided together")
    return args


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8")
    if args.prompt:
        return args.prompt
    return DEFAULT_PROMPT


def image_to_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def print_response(label: str, response: httpx.Response) -> None:
    print(f"{label}: {response.status_code}")
    if not response.content:
        return
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        print(json.dumps(response.json(), indent=2))
        return
    print(response.text)


def choose_model(response: httpx.Response, requested_model: str | None) -> str:
    models_payload = response.json()
    if requested_model:
        return requested_model
    for entry in models_payload.get("data", []):
        model_id = entry.get("id")
        if isinstance(model_id, str) and model_id:
            return model_id
    raise RuntimeError("no model ids returned by /v1/models")


def build_chat_payload(
    model: str, prompt: str, image_url: str, structured_output: bool, max_tokens: int
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": False,
    }
    if structured_output:
        payload["response_format"] = {"type": "json_object"}
    return payload


def print_assistant_content(response_payload: dict[str, Any]) -> None:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if not isinstance(content, str):
        return
    print("assistant_content:")
    print(content)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return
    print("assistant_content_json:")
    print(json.dumps(parsed, indent=2))


def main() -> int:
    args = parse_args()
    prompt = read_prompt(args)
    image_path = Path(args.image).expanduser().resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"image file not found: {image_path}")

    auth = None
    if args.basic_username:
        auth = (args.basic_username, args.basic_password)

    headers = {"Authorization": f"Bearer {args.api_key}"}
    image_url = image_to_data_url(image_path)

    with httpx.Client(
        base_url=args.base_url.rstrip("/"),
        timeout=args.timeout,
        auth=auth,
        verify=not args.insecure,
    ) as client:
        health = client.get("/health")
        print_response("GET /health", health)

        ready = client.get("/ready")
        print_response("GET /ready", ready)

        models = client.get("/v1/models")
        print_response("GET /v1/models", models)

        model = choose_model(models, args.model)
        print(f"selected_model: {model}")

        payload = build_chat_payload(
            model=model,
            prompt=prompt,
            image_url=image_url,
            structured_output=args.structured_output,
            max_tokens=args.max_tokens,
        )
        completion = client.post("/v1/chat/completions", json=payload, headers=headers)
        print_response("POST /v1/chat/completions", completion)

        if completion.headers.get("content-type", "").startswith("application/json"):
            print_assistant_content(completion.json())

        return 0 if completion.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
