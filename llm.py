import json
import os
import random
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


@dataclass
class CivThought:
    prompt: str
    response: str
    log: str
    god: str
    updates: Dict[str, str]


@dataclass
class MasterThought:
    prompt: str
    response: str
    title: str
    log: str
    god: str
    analysis: str


class LLMClient:
    def __init__(self, mode: str = "stub", model: Optional[str] = None) -> None:
        self.mode = mode
        self.model = model or os.environ.get("OLLAMA_MODEL", "mistral:7b")
        self.base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")

    def generate_events(
        self, cycle: int, context: str
    ) -> Tuple[List[GeneratedEvent], Optional[LLMResult]]:
        if self.mode != "ollama":
            return [], None
        prompt = (
            "You are an event engine for a living universe simulation. "
            f"Cycle {cycle} context:\n{context}\n"
            "Rules: events must be feasible given the tech capability in context. "
            "Allow rare, plausible breakthroughs (e.g., first orbital mission) even if "
            "pre-space, but do NOT jump to interstellar travel or resource routes like "
            "helium-3 unless capability is explicitly interstellar. If spacefaring, "
            "stay within a system. Only allow breakthrough leaps when "
            "Innovation climate is propitious; include metadata.justification and "
            "metadata.rarity for any breakthrough event. "
            "Optional metadata fields: delayed_effects (list of {cycle_delay, civ, kind, delta}), "
            "world_marks (list of {civ, label, impact}). "
            "Return JSON list of 1-4 events. Each event must be an object with "
            "keys: kind, title, detail, metadata. Titles must be specific and "
            "reflect real effects (no generic labels). metadata must be a JSON object. "
            "If no valid events should happen, return an empty JSON list []."
        )
        response = self._call_ollama_stream(prompt, None)
        if response:
            parsed = self._parse_events_json(response)
            if parsed is not None:
                return parsed, LLMResult(prompt=prompt, response=response)
        return [], LLMResult(prompt=prompt, response=response)

    def generate_civilizations(
        self, planets: List[Tuple[str, float]], count: int
    ) -> Tuple[List[CivSeed], Optional[LLMResult]]:
        prompt = (
            "You are a science-fiction worldbuilder. Create unique civilizations "
            f"for {count} planets. Planets (name, habitability 0-1):\n"
        )
        prompt += "\n".join([f"- {name} ({hab:.2f})" for name, hab in planets])
        prompt += (
            "\nReturn JSON list of objects with fields: name, color (hex), summary."
        )
        response = self._call_ollama_stream(prompt, None)
        if response:
            parsed = self._parse_civ_json(response, count)
            if parsed:
                return parsed, LLMResult(prompt=prompt, response=response)
        return self._fallback_civs(count), LLMResult(prompt=prompt, response=response)

    def generate_civ_thought(
        self,
        civ_name: str,
        cycle: int,
        context: str,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> Optional[CivThought]:
        prompt = (
            f"You are the mind of the civilization '{civ_name}'. "
            f"It is cycle {cycle}. Context:\n{context}\n"
            "Return JSON only with keys: log, god, name, color, level, status. "
            "The 'log' must be 3-6 sentences describing real effects, not generic titles. "
            "The 'god' must be a short paragraph for the human observer. "
            "Only include name/color/level/status if you want to update them. "
            "Color must be hex (e.g. #ff8844). "
            "Do not mention or assume knowledge about other civilizations."
        )
        response = self._call_ollama_stream(prompt, on_chunk)
        if not response:
            return None
        parsed = self._parse_civ_thought_json(response)
        if not parsed:
            return CivThought(
                prompt=prompt,
                response=response,
                log=response,
                god="No human note.",
                updates={},
            )
        return CivThought(
            prompt=prompt,
            response=response,
            log=parsed["log"],
            god=parsed["god"],
            updates=parsed["updates"],
        )

    def generate_master_log(
        self,
        cycle: int,
        context: str,
        on_chunk: Optional[Callable[[str], None]] = None,
    ) -> Optional[MasterThought]:
        prompt = (
            "You are the Game Master AI observing a simulated universe. "
            f"Cycle {cycle} summary context:\n{context}\n"
            "Return JSON only with keys: title, log, god, analysis. "
            "title must be a short, specific cycle name. "
            "log must be 4-6 sentences describing the real effects. "
            "analysis must explicitly analyze each civilization response. "
            "god is a short paragraph for the human observer."
        )
        response = self._call_ollama_stream(prompt, on_chunk)
        if not response:
            return None
        parsed = self._parse_master_json(response)
        if not parsed:
            return MasterThought(
                prompt=prompt,
                response=response,
                title=f"Cycle {cycle}",
                log=response,
                god="No human note.",
                analysis="No analysis.",
            )
        return MasterThought(
            prompt=prompt,
            response=response,
            title=parsed["title"],
            log=parsed["log"],
            god=parsed["god"],
            analysis=parsed["analysis"],
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
    ) -> str:
        if self.mode == "stub":
            return ""
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
            return ""
        return "".join(full).strip()

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
            if not isinstance(data, list):
                return None
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
            return None

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
