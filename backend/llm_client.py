"""Chat-completion client with sequential failover across configured providers.

Order parsing and optional surface advice use this client. SAM uses sam_client.py;
G-code emission and verification are deterministic and do not call a model.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

_ROOT_ENV = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_ROOT_ENV, override=False)


class LiveModelClient:
    """Try the preferred provider, then the remaining configured providers."""

    def __init__(self) -> None:
        # Baseten
        self.baseten_api_key: str = os.getenv("BASETEN_API_KEY", "").strip()
        self.baseten_base_url: str = os.getenv(
            "BASETEN_BASE_URL", "https://inference.baseten.co/v1"
        ).rstrip("/")
        self.baseten_model: str = os.getenv(
            "BASETEN_MODEL", "meta-models/muse-spark-open-1026"
        ).strip()

        # Fireworks
        self.fireworks_api_key: str = os.getenv("FIREWORKS_API_KEY", "").strip()
        self.fireworks_base_url: str = os.getenv(
            "FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1"
        ).rstrip("/")
        self.fireworks_model: str = os.getenv(
            "FIREWORKS_MODEL", "accounts/fireworks/models/muse-spark-open"
        ).strip()

        # Meta
        self.meta_api_key: str = os.getenv("META_API_KEY", "").strip()
        self.meta_base_url: str = os.getenv(
            "META_BASE_URL", "https://api.meta.ai/v1"
        ).rstrip("/")
        self.meta_spark_model: str = os.getenv(
            "META_SPARK_MODEL", "muse-spark-1.3"
        ).strip()

    @property
    def has_baseten(self) -> bool:
        return bool(self.baseten_api_key and "PASTE_" not in self.baseten_api_key)

    @property
    def has_fireworks(self) -> bool:
        return bool(self.fireworks_api_key and "PASTE_" not in self.fireworks_api_key)

    @property
    def has_meta(self) -> bool:
        return bool(self.meta_api_key and "PASTE_" not in self.meta_api_key)

    def _provider_config(self, provider: str) -> Optional[Dict[str, str]]:
        if provider == "baseten" and self.has_baseten:
            return {
                "provider": "baseten",
                "base_url": self.baseten_base_url,
                "api_key": self.baseten_api_key,
                "model": self.baseten_model,
            }
        if provider == "fireworks" and self.has_fireworks:
            return {
                "provider": "fireworks",
                "base_url": self.fireworks_base_url,
                "api_key": self.fireworks_api_key,
                "model": self.fireworks_model,
            }
        if provider == "meta" and self.has_meta:
            return {
                "provider": "meta",
                "base_url": self.meta_base_url,
                "api_key": self.meta_api_key,
                "model": self.meta_spark_model,
            }
        return None

    def chat_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        image_bytes: Optional[bytes] = None,
        image_mime: str = "image/png",
        max_tokens: int = 2048,
        temperature: float = 0.1,
        prefer_provider: str = "baseten",
        timeout_sec: float = 45.0,
    ) -> Dict[str, Any]:
        """
        Executes a live completion call starting with `prefer_provider` and failing
        over across remaining configured clouds if a transient error occurs.
        """
        all_providers = ["baseten", "fireworks", "meta"]
        ordered = [prefer_provider] + [
            p for p in all_providers if p != prefer_provider
        ]

        last_error = "No live API keys configured in .env"
        for provider in ordered:
            cfg = self._provider_config(provider)
            if not cfg:
                continue

            res = self._post_chat(
                provider=cfg["provider"],
                url=f"{cfg['base_url']}/chat/completions",
                api_key=cfg["api_key"],
                model=cfg["model"],
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_bytes=image_bytes,
                image_mime=image_mime,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout_sec=timeout_sec,
            )
            if res["ok"]:
                return res
            last_error = res.get("error", "Unknown API failure")

        return {
            "ok": False,
            "provider": "offline",
            "model": "deterministic-fallback",
            "content": "",
            "reasoning_content": "",
            "parsed_json": None,
            "usage": {},
            "latency_ms": 0.0,
            "error": last_error,
        }


    def _post_chat(
        self,
        provider: str,
        url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        image_bytes: Optional[bytes],
        image_mime: str,
        max_tokens: int,
        temperature: float,
        timeout_sec: float,
    ) -> Dict[str, Any]:
        if image_bytes is not None:
            b64_img = base64.b64encode(image_bytes).decode("ascii")
            user_content: Any = [
                {"type": "text", "text": user_prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image_mime};base64,{b64_img}"},
                },
            ]
        else:
            user_content = user_prompt

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": max(1024, max_tokens),
            "temperature": temperature,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "RemnantX-Spatial-AI/1.0",
            },
            method="POST",
        )

        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                data = json.loads(raw)
                msg = data.get("choices", [{}])[0].get("message", {})
                content = (msg.get("content") or "").strip()
                reasoning = (
                    msg.get("reasoning_content") or msg.get("reasoning") or ""
                ).strip()

                return {
                    "ok": True,
                    "provider": provider,
                    "model": model,
                    "content": content,
                    "reasoning_content": reasoning,
                    "parsed_json": self.extract_json(content),
                    "usage": data.get("usage", {}),
                    "latency_ms": latency_ms,
                    "error": None,
                }
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            return {
                "ok": False,
                "provider": provider,
                "model": model,
                "content": "",
                "reasoning_content": "",
                "parsed_json": None,
                "usage": {},
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "error": f"HTTP {e.code}: {err_body[:300]}",
            }
        except Exception as e:
            return {
                "ok": False,
                "provider": provider,
                "model": model,
                "content": "",
                "reasoning_content": "",
                "parsed_json": None,
                "usage": {},
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "error": str(e),
            }

    @staticmethod
    def extract_json(text: str) -> Optional[Dict[str, Any]]:
        """Safely parse JSON from model output even if wrapped in markdown code fences."""
        if not text:
            return None
        cleaned = text.strip()
        fence_match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL
        )
        if fence_match:
            cleaned = fence_match.group(1)
        else:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start : end + 1]
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else {"data": parsed}
        except Exception:
            return None
