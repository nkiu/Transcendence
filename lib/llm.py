import json
import logging
import os
import random
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class GeneratedEvent:
    kind: str
    title: str
    detail: str
    metadata: Dict[str, str]

@dataclass
class CivSeed:
    name: str
    color: str
    summary: str


@dataclass
class LLMResult:
    prompt: str
    response: str
    model: str
    latency_ms: int


class LLMBackend(ABC):
    """Abstract base class for LLM backends."""

    @abstractmethod
    def generate_stream(
        self,
        prompt: str,
        model: str,
        on_chunk: Optional[Callable[[str], None]],
        timeout: int,
        max_duration: int,
    ) -> Tuple[str, int]:
        """Generate response with optional streaming.

        Returns:
            Tuple of (full_response, latency_ms)
        """
        pass

    @abstractmethod
    def healthcheck(self, base_url: str) -> bool:
        """Check if the backend is available."""
        pass

    @abstractmethod
    def list_models(self, base_url: str) -> List[str]:
        """List available models."""
        pass


class OllamaBackend(LLMBackend):
    """Backend for Ollama API - POST to /api/generate, NDJSON streaming."""

    def __init__(self, base_url: str):
        self.base_url = base_url

    def generate_stream(
        self,
        prompt: str,
        model: str,
        on_chunk: Optional[Callable[[str], None]],
        timeout: int = 45,
        max_duration: int = 240,
    ) -> Tuple[str, int]:
        start = time.monotonic()
        data = json.dumps(
            {"model": model, "prompt": prompt, "stream": True}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        full = []
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for raw in resp:
                    if time.monotonic() - start > max_duration:
                        break
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    chunk = str(payload.get("response", ""))
                    if chunk:
                        full.append(chunk)
                        if on_chunk:
                            on_chunk(chunk)
                    if payload.get("done") is True:
                        break
        except (urllib.error.URLError, TimeoutError) as e:
            logger.debug(f"Ollama request failed: {e}")
            latency = int((time.monotonic() - start) * 1000)
            return "", latency
        latency = int((time.monotonic() - start) * 1000)
        return "".join(full).strip(), latency

    def healthcheck(self, base_url: str) -> bool:
        try:
            with urllib.request.urlopen(
                f"{base_url}/api/tags", timeout=5
            ) as resp:
                return resp.status == 200
        except urllib.error.URLError:
            return False

    def list_models(self, base_url: str) -> List[str]:
        try:
            with urllib.request.urlopen(
                f"{base_url}/api/tags", timeout=5
            ) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            models = payload.get("models", [])
            names = []
            for item in models:
                name = str(item.get("name", "")).strip()
                if name:
                    names.append(name)
            return names
        except (urllib.error.URLError, json.JSONDecodeError):
            return []


class LlamaCppBackend(LLMBackend):
    """Backend for llama.cpp server - POST to /v1/completions, SSE streaming."""

    def __init__(self, base_url: str):
        self.base_url = base_url

    def generate_stream(
        self,
        prompt: str,
        model: str,
        on_chunk: Optional[Callable[[str], None]],
        timeout: int = 45,
        max_duration: int = 240,
    ) -> Tuple[str, int]:
        start = time.monotonic()
        n_predict = int(os.environ.get("LLAMACPP_N_PREDICT", "4096"))
        repeat_penalty = float(os.environ.get("LLAMACPP_REPEAT_PENALTY", "1.3"))
        data = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": True,
                "n_predict": n_predict,
                "temperature": 0.7,
                "repeat_penalty": repeat_penalty,
                "repeat_last_n": 256,
            }
        ).encode("utf-8")
        url = f"{self.base_url}/completion"
        prompt_preview = prompt[:80].replace("\n", " ")
        logger.info(
            "llama.cpp >> POST %s (model=%s, prompt=%d chars: \"%s...\")",
            url, model, len(prompt), prompt_preview,
        )
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )
        full = []
        token_count = 0
        first_token_time = None
        last_log_count = 0
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                logger.info("llama.cpp << connected, waiting for tokens...")
                for raw in resp:
                    elapsed = time.monotonic() - start
                    if elapsed > max_duration:
                        logger.warning(
                            "llama.cpp !! max duration reached (%ds), aborting",
                            max_duration,
                        )
                        break
                    if not raw:
                        continue
                    line = raw.decode("utf-8").strip()
                    if not line:
                        continue
                    if line == "data: [DONE]":
                        break
                    if line.startswith("data: "):
                        line = line[6:]
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # Native /completion returns "content", OAI compat returns "choices"
                    chunk = ""
                    if "content" in payload:
                        chunk = str(payload["content"])
                    elif "choices" in payload:
                        choices = payload["choices"]
                        if choices:
                            chunk = str(choices[0].get("text", ""))
                    if chunk:
                        full.append(chunk)
                        token_count += 1
                        if first_token_time is None:
                            first_token_time = elapsed
                            logger.info(
                                "llama.cpp << first token after %.1fs", elapsed,
                            )
                        if token_count - last_log_count >= 50:
                            tps = token_count / (elapsed - first_token_time) if elapsed > first_token_time else 0
                            logger.info(
                                "llama.cpp .. %d tokens, %.1fs elapsed, %.1f tok/s",
                                token_count, elapsed, tps,
                            )
                            last_log_count = token_count
                        if on_chunk:
                            on_chunk(chunk)
                    if payload.get("stop") is True:
                        break
        except Exception as e:
            logger.warning("llama.cpp !! request failed: %s", e)
            latency = int((time.monotonic() - start) * 1000)
            return "", latency
        latency = int((time.monotonic() - start) * 1000)
        tps = token_count / (latency / 1000) if latency > 0 else 0
        logger.info(
            "llama.cpp << done: %d tokens in %.1fs (%.1f tok/s)",
            token_count, latency / 1000, tps,
        )
        return "".join(full).strip(), latency

    def healthcheck(self, base_url: str) -> bool:
        try:
            with urllib.request.urlopen(
                f"{base_url}/health", timeout=5
            ) as resp:
                return resp.status == 200
        except urllib.error.URLError:
            # Try /v1/models as fallback
            try:
                with urllib.request.urlopen(
                    f"{base_url}/v1/models", timeout=5
                ) as resp:
                    return resp.status == 200
            except urllib.error.URLError:
                return False

    def list_models(self, base_url: str) -> List[str]:
        try:
            with urllib.request.urlopen(
                f"{base_url}/v1/models", timeout=5
            ) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            models = payload.get("data", [])
            names = []
            for item in models:
                name = str(item.get("id", "")).strip()
                if name:
                    names.append(name)
            return names
        except (urllib.error.URLError, json.JSONDecodeError):
            return []


class LLMClient:
    def __init__(
        self,
        mode: str = "stub",
        model: Optional[str] = None,
        backend: Optional[str] = None,
    ) -> None:
        self.mode = mode
        self.model = model or os.environ.get("OLLAMA_MODEL", "mistral:7b")

        # Backend selection: "ollama" (default) or "llamacpp"
        self._backend_type = backend or os.environ.get("LLM_BACKEND", "ollama")
        self._llamacpp_url = os.environ.get("LLAMACPP_URL", "http://localhost:8080")
        self._parallel_slots = int(os.environ.get("LLAMACPP_PARALLEL", "4"))

        # Initialize backend
        if self._backend_type == "llamacpp":
            self.base_url = self._llamacpp_url
            self._backend: LLMBackend = LlamaCppBackend(self.base_url)
        else:
            self.base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
            self._backend: LLMBackend = OllamaBackend(self.base_url)

    @property
    def parallel_enabled(self) -> bool:
        """Check if parallel execution is enabled (llama.cpp backend)."""
        return self._backend_type == "llamacpp" and self.mode != "stub"

    @property
    def parallel_slots(self) -> int:
        """Number of parallel slots available for concurrent requests."""
        return self._parallel_slots if self.parallel_enabled else 1

    @property
    def backend_type(self) -> str:
        """Return the current backend type."""
        return self._backend_type

    def generate_events(
        self,
        cycle: int,
        context: str,
        template: Optional[str] = None,
    ) -> Tuple[List[GeneratedEvent], Optional[LLMResult]]:
        if self.mode != "ollama":
            return [], None
        prompt = self._render_template(
            template,
            cycle=cycle,
            context=context,
        )
        response, latency = self._call_ollama_stream(prompt, None)
        if response:
            parsed = self._parse_events_json(response)
            if parsed is not None:
                return parsed, LLMResult(
                    prompt=prompt,
                    response=response,
                    model=self.model,
                    latency_ms=latency,
                )
        return [], LLMResult(
            prompt=prompt,
            response=response,
            model=self.model,
            latency_ms=latency,
        )

    def generate_civilizations(
        self,
        planets: List[Tuple[str, float]],
        count: int,
        template: Optional[str] = None,
    ) -> Tuple[List[CivSeed], Optional[LLMResult]]:
        if self.mode != "ollama":
            return self._fallback_civs(count), None
        planets_list = "\n".join([f"- {name} ({hab:.2f})" for name, hab in planets])
        prompt = self._render_template(
            template,
            count=count,
            planets_list=planets_list,
        )
        response, latency = self._call_ollama_stream(prompt, None)
        if response:
            parsed = self._parse_civ_json(response, count)
            if parsed:
                return parsed, LLMResult(
                    prompt=prompt,
                    response=response,
                    model=self.model,
                    latency_ms=latency,
                )
        return self._fallback_civs(count), LLMResult(
            prompt=prompt,
            response=response,
            model=self.model,
            latency_ms=latency,
        )

    def generate_civ_thought(
        self,
        civ_name: str,
        cycle: int,
        context: str,
        on_chunk: Optional[Callable[[str], None]] = None,
        prompt_seed: str = "",
        template: Optional[str] = None,
    ) -> Optional[LLMResult]:
        if self.mode != "ollama":
            return None
        prompt = self._render_template(
            template,
            civ_name=civ_name,
            cycle=cycle,
            context=context,
        )
        prompt = self._append_seed(prompt, prompt_seed)
        response, latency = self._call_ollama_stream(prompt, on_chunk)
        if not response:
            return None
        return LLMResult(
            prompt=prompt,
            response=response,
            model=self.model,
            latency_ms=latency,
        )

    def generate_master_log(
        self,
        cycle: int,
        context: str,
        on_chunk: Optional[Callable[[str], None]] = None,
        prompt_seed: str = "",
        template: Optional[str] = None,
    ) -> Optional[LLMResult]:
        if self.mode != "ollama":
            return None
        prompt = self._render_template(
            template,
            cycle=cycle,
            context=context,
        )
        prompt = self._append_seed(prompt, prompt_seed)
        response, latency = self._call_ollama_stream(prompt, on_chunk)
        if not response:
            return None
        return LLMResult(
            prompt=prompt,
            response=response,
            model=self.model,
            latency_ms=latency,
        )

    def generate_master_repair(
        self,
        prompt: str,
    ) -> Optional[LLMResult]:
        if self.mode != "ollama":
            return None
        response, latency = self._call_ollama_stream(prompt, None)
        if not response:
            return None
        return LLMResult(
            prompt=prompt,
            response=response,
            model=self.model,
            latency_ms=latency,
        )

    def generate_obituaries(
        self,
        context: str,
        template: Optional[str] = None,
    ) -> Optional[LLMResult]:
        if self.mode != "ollama":
            return None
        prompt = self._render_template(template, context=context)
        response, latency = self._call_ollama_stream(prompt, None)
        if not response:
            return None
        return LLMResult(
            prompt=prompt,
            response=response,
            model=self.model,
            latency_ms=latency,
        )

    def _generate_stub(self, cycle: int) -> List[GeneratedEvent]:
        seeds = [
            ("discovery", "Ancient ruin mapped", "A survey drone mapped a buried city grid."),
            ("conflict", "Border skirmish", "Two factions clashed over helium-3 routes."),
            ("breakthrough", "New drive theory", "Physicists propose a stabilised warp wake."),
            ("ecology", "Atmospheric shift", "A slow terraforming haze thickens."),
            ("culture", "Rite of ash", "Pilgrims begin a 40-year stellar migration."),
            ("anomaly", "Unexplained signal", "A repeating tone emerges from interstellar void."),
        ]
        kind, title, detail = random.choice(seeds)
        return [
            GeneratedEvent(
                kind=kind,
                title=f"Cycle {cycle}: {title}",
                detail=detail,
                metadata={"seed": "stub"},
            )
        ]

    def _call_ollama_stream(
        self, prompt: str, on_chunk: Optional[Callable[[str], None]]
    ) -> Tuple[str, int]:
        if self.mode != "ollama":
            raise RuntimeError("LLM call blocked: LLM disabled")
        if self._backend_type == "llamacpp":
            default_timeout = "600"
        else:
            default_timeout = "240"
        max_duration = int(os.environ.get("LLM_CALL_TIMEOUT",
                           os.environ.get("OLLAMA_CALL_TIMEOUT", default_timeout)))
        return self._backend.generate_stream(
            prompt=prompt,
            model=self.model,
            on_chunk=on_chunk,
            timeout=45,
            max_duration=max_duration,
        )

    def healthcheck(self) -> bool:
        if self.mode == "stub":
            return False
        return self._backend.healthcheck(self.base_url)

    def list_models(self) -> List[str]:
        if self.mode == "stub":
            return []
        return self._backend.list_models(self.base_url)

    def _parse_civ_json(self, raw: str, count: int) -> Optional[List[CivSeed]]:
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
            data = json.loads(cleaned)
            if isinstance(data, dict):
                data = data.get("civilizations") or data.get("civs")
            if not isinstance(data, list):
                return self._parse_civ_text(raw, count)
            civs = []
            for item in data[:count]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip() or "Unnamed"
                color = str(item.get("color", "")).strip() or self._rand_color()
                summary = str(item.get("summary", "")).strip() or "No summary."
                civs.append(CivSeed(name=name, color=color, summary=summary))
            if civs:
                return civs
            return None
        except json.JSONDecodeError:
            # Fallback: try to extract a JSON array from mixed output.
            start = raw.find("[")
            end = raw.rfind("]")
            if start == -1 or end == -1 or end <= start:
                return self._parse_civ_text(raw, count)
            try:
                data = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return self._parse_civ_text(raw, count)
            if isinstance(data, dict):
                data = data.get("civilizations") or data.get("civs")
            if not isinstance(data, list):
                return self._parse_civ_text(raw, count)
            civs = []
            for item in data[:count]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip() or "Unnamed"
                color = str(item.get("color", "")).strip() or self._rand_color()
                summary = str(item.get("summary", "")).strip() or "No summary."
                civs.append(CivSeed(name=name, color=color, summary=summary))
            return civs if civs else None

    def _parse_civ_text(self, raw: str, count: int) -> Optional[List[CivSeed]]:
        lines = [line.strip() for line in raw.splitlines()]
        civs: List[CivSeed] = []
        current: Dict[str, str] = {}
        def flush():
            if not current:
                return
            name = current.get("NAME", "").strip()
            color = current.get("COLOR", "").strip() or self._rand_color()
            trait = current.get("TRAIT", "").strip()
            flaw = current.get("FLAW", "").strip()
            if not name:
                return
            summary_parts = []
            if trait:
                summary_parts.append(f"Trait: {trait}")
            if flaw:
                summary_parts.append(f"Flaw: {flaw}")
            summary = " | ".join(summary_parts) if summary_parts else "No summary."
            civs.append(CivSeed(name=name, color=color, summary=summary))
            current.clear()

        for line in lines:
            if not line:
                flush()
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip().upper()
                if key in ("NAME", "COLOR", "TRAIT", "FLAW"):
                    current[key] = value.strip()
                    if key == "NAME" and len(civs) >= count:
                        break
            else:
                continue
        flush()
        return civs[:count] if civs else None

    def _parse_events_json(self, raw: str) -> Optional[List[GeneratedEvent]]:
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
            data = json.loads(cleaned)
            if not isinstance(data, list):
                return None
            events = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                kind = str(item.get("kind", "")).strip() or "event"
                title = str(item.get("title", "")).strip() or "Untitled event"
                detail = str(item.get("detail", "")).strip() or "No detail."
                metadata = item.get("metadata", {})
                if not isinstance(metadata, dict):
                    metadata = {}
                events.append(
                    GeneratedEvent(
                        kind=kind,
                        title=title,
                        detail=detail,
                        metadata=metadata,
                    )
                )
            return events if events else None
        except json.JSONDecodeError:
            return None

    def _parse_civ_thought_json(self, raw: str) -> Optional[Dict[str, str]]:
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
            data = json.loads(cleaned)
            if not isinstance(data, dict):
                return None
            log = str(data.get("log", "")).strip()
            god = str(data.get("god", "")).strip()
            updates = {}
            for key in ("name", "color", "level", "status"):
                value = str(data.get(key, "")).strip()
                if value:
                    updates[key] = value
            if not log:
                return None
            if not god:
                god = "No human note."
            return {"log": log, "god": god, "updates": updates}
        except json.JSONDecodeError:
            return None

    def _parse_master_json(self, raw: str) -> Optional[Dict[str, str]]:
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`")
            data = json.loads(cleaned)
            if not isinstance(data, dict):
                return None
            title = str(data.get("title", "")).strip()
            log = str(data.get("log", "")).strip()
            god = str(data.get("god", "")).strip() or "No human note."
            analysis = str(data.get("analysis", "")).strip() or "No analysis."
            if not log:
                return None
            if not title:
                title = "Untitled cycle"
            return {"title": title, "log": log, "god": god, "analysis": analysis}
        except json.JSONDecodeError:
            return None

    def _append_seed(self, prompt: str, seed: str) -> str:
        if not seed.strip():
            return prompt
        return f"{prompt}\n\nSeed instructions:\n{seed.strip()}\n"

    def _render_template(self, template: Optional[str], **kwargs) -> str:
        if template and template.strip():
            try:
                return template.format(**kwargs)
            except KeyError:
                return template
        # Fallback minimal prompt to avoid empty calls.
        return f"Cycle {kwargs.get('cycle', '')} context:\n{kwargs.get('context', '')}\n"

    def _fallback_civs(self, count: int) -> List[CivSeed]:
        civs = []
        for i in range(count):
            civs.append(
                CivSeed(
                    name=f"CIV-{i + 1}",
                    color=self._rand_color(),
                    summary="A young civilization begins to watch the stars.",
                )
            )
        return civs

    def _rand_color(self) -> str:
        return random.choice(["#f94144", "#f3722c", "#43aa8b", "#577590"])
