"""Optional loopback llama.cpp executor for the same pinned motion planner.

HF token IDs are used in both directions, preserving the expanded motion/audio
vocabulary. Failure is explicit; never silently fall back to another model.
"""

import json
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from virea_model_sdk.worker import WorkerFailure


class LocalPlanner:
    def __init__(self, url):
        parsed = urlparse(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or parsed.username
        ):
            raise WorkerFailure(
                "INVALID_REQUEST", "planner_url must be a loopback HTTP origin"
            )
        self.url = url.rstrip("/")
        self.opener = build_opener(ProxyHandler({}))

    def _request(self, path, payload=None):
        request = Request(
            self.url + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with self.opener.open(request, timeout=30) as response:
            return json.load(response)

    def generate(self, tokenizer, prompt, *, temperature, top_p, max_new_tokens, seed):
        models = self._request("/v1/models")
        if "sentiavatar-planner" not in [item["id"] for item in models["data"]]:
            raise WorkerFailure(
                "PLANNER_IDENTITY_MISMATCH", "expected sentiavatar-planner service"
            )
        result = self._request(
            "/completion",
            {
                "prompt": tokenizer.encode(prompt),
                "return_tokens": True,
                "n_predict": max_new_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": 50,
                "min_p": 0,
                "repeat_penalty": 1,
                "seed": seed,
                "cache_prompt": True,
                "stop": ["<|im_end|>"],
                "special": True,
            },
        )
        if result.get("stop_type") not in {"eos", "word"} or not result.get("tokens"):
            raise WorkerFailure(
                "PLANNER_OUTPUT_INVALID", "local planner did not finish naturally"
            )
        return tokenizer.decode(result["tokens"], skip_special_tokens=False)
