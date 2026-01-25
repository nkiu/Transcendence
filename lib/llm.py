import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple


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


class LLMClient:
    def __init__(self, mode: str = "stub", model: Optional[str] = None) -> None:
        self.mode = mode
        self.model = model or os.environ.get("OLLAMA_MODEL", "mistral:7b")
        self.base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")

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
        start = time.monotonic()
        max_duration = int(os.environ.get("OLLAMA_CALL_TIMEOUT", "240"))
        data = json.dumps(
            {"model": self.model, "prompt": prompt, "stream": True}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        full = []
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
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
        except (urllib.error.URLError, TimeoutError):
            latency = int((time.monotonic() - start) * 1000)
            return "", latency
        latency = int((time.monotonic() - start) * 1000)
        return "".join(full).strip(), latency

    def healthcheck(self) -> bool:
        if self.mode == "stub":
            return False
        try:
            with urllib.request.urlopen(
                f"{self.base_url}/api/tags", timeout=5
            ) as resp:
                return resp.status == 200
        except urllib.error.URLError:
            return False

    def list_models(self) -> List[str]:
        if self.mode == "stub":
            return []
        try:
            with urllib.request.urlopen(
                f"{self.base_url}/api/tags", timeout=5
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
