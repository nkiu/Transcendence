import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Event:
    id: int
    cycle: int
    kind: str
    title: str
    detail: str
    metadata: Dict[str, Any]
    created_at: str


@dataclass
class StarSystem:
    id: int
    name: str
    x: float
    y: float


@dataclass
class Planet:
    id: int
    system_id: int
    name: str
    orbit_au: float
    size: float
    habitability: float
    kind: str
    richness: float
    science: float


@dataclass
class Civilization:
    id: int
    name: str
    color: str
    home_planet_id: int
    level: str
    status: str
    cohesion: float
    inequality: float
    eco_pressure: float
    innovation: float
    stability: float
    tech_stage: str
    memory_long: str


@dataclass
class AILog:
    id: int
    scope: str
    civ_id: Optional[int]
    cycle: int
    role: str
    message: str
    created_at: str


@dataclass
class DelayedEffect:
    id: int
    cycle_due: int
    civ_id: Optional[int]
    kind: str
    payload: Dict[str, Any]
    created_at: str


@dataclass
class WorldMark:
    id: int
    cycle: int
    civ_id: Optional[int]
    label: str
    impact: str
    created_at: str


@dataclass
class ChaosProfile:
    id: int
    cycle_start: int
    cycle_end: int
    civ_id: Optional[int]
    archetype: str
    polarity: str
    bias_json: str
    intensity: float
    created_at: str


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS cycles (
                    id INTEGER PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    summary TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    cycle INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS systems (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    x REAL NOT NULL,
                    y REAL NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS planets (
                    id INTEGER PRIMARY KEY,
                    system_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    orbit_au REAL NOT NULL,
                    size REAL NOT NULL,
                    habitability REAL NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'rocky',
                    richness REAL NOT NULL DEFAULT 0.0,
                    science REAL NOT NULL DEFAULT 0.0,
                    FOREIGN KEY(system_id) REFERENCES systems(id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS civilizations (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    color TEXT NOT NULL,
                    home_planet_id INTEGER NOT NULL,
                    level TEXT NOT NULL,
                    status TEXT NOT NULL,
                    cohesion REAL NOT NULL DEFAULT 0.5,
                    inequality REAL NOT NULL DEFAULT 0.5,
                    eco_pressure REAL NOT NULL DEFAULT 0.5,
                    innovation REAL NOT NULL DEFAULT 0.5,
                    stability REAL NOT NULL DEFAULT 0.5,
                    tech_stage TEXT NOT NULL DEFAULT 'stone',
                    memory_long TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(home_planet_id) REFERENCES planets(id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_logs (
                    id INTEGER PRIMARY KEY,
                    scope TEXT NOT NULL,
                    civ_id INTEGER,
                    cycle INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(civ_id) REFERENCES civilizations(id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS world_marks (
                    id INTEGER PRIMARY KEY,
                    cycle INTEGER NOT NULL,
                    civ_id INTEGER,
                    label TEXT NOT NULL,
                    impact TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(civ_id) REFERENCES civilizations(id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS delayed_effects (
                    id INTEGER PRIMARY KEY,
                    cycle_due INTEGER NOT NULL,
                    civ_id INTEGER,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(civ_id) REFERENCES civilizations(id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS run_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS chaos_profiles (
                    id INTEGER PRIMARY KEY,
                    cycle_start INTEGER NOT NULL,
                    cycle_end INTEGER NOT NULL,
                    civ_id INTEGER,
                    archetype TEXT NOT NULL,
                    polarity TEXT NOT NULL,
                    bias_json TEXT NOT NULL,
                    intensity REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(civ_id) REFERENCES civilizations(id)
                )
                """
            )
            self._conn.commit()
            self._ensure_column("planets", "kind", "TEXT", "'rocky'")
            self._ensure_column("planets", "richness", "REAL", "0.0")
            self._ensure_column("planets", "science", "REAL", "0.0")
            self._ensure_column("civilizations", "cohesion", "REAL", "0.5")
            self._ensure_column("civilizations", "inequality", "REAL", "0.5")
            self._ensure_column("civilizations", "eco_pressure", "REAL", "0.5")
            self._ensure_column("civilizations", "innovation", "REAL", "0.5")
            self._ensure_column("civilizations", "stability", "REAL", "0.5")
            self._ensure_column("civilizations", "tech_stage", "TEXT", "'stone'")
            self._ensure_column("civilizations", "memory_long", "TEXT", "''")

    def _ensure_column(
        self, table: str, column: str, col_type: str, default: str
    ) -> None:
        cur = self._conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        cols = {row["name"] for row in cur.fetchall()}
        if column in cols:
            return
        cur.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT {default}"
        )
        self._conn.commit()

    def add_cycle(self, started_at: str, ended_at: str, summary: str) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO cycles (started_at, ended_at, summary) VALUES (?, ?, ?)",
                (started_at, ended_at, summary),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def update_cycle_summary(self, cycle_id: int, summary: str) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE cycles SET summary = ? WHERE id = ?",
                (summary, cycle_id),
            )
            self._conn.commit()

    def get_latest_cycle_id(self) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM cycles")
            row = cur.fetchone()
            return int(row["max_id"])

    def add_event(
        self,
        cycle: int,
        kind: str,
        title: str,
        detail: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        if metadata is None:
            metadata = {}
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO events (cycle, kind, title, detail, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (cycle, kind, title, detail, json.dumps(metadata)),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def universe_exists(self) -> bool:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT COUNT(*) AS count FROM systems")
            row = cur.fetchone()
            return int(row["count"]) > 0

    def add_system(self, name: str, x: float, y: float) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO systems (name, x, y) VALUES (?, ?, ?)",
                (name, x, y),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def add_planet(
        self,
        system_id: int,
        name: str,
        orbit_au: float,
        size: float,
        habitability: float,
        kind: str,
        richness: float,
        science: float,
    ) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO planets (
                    system_id,
                    name,
                    orbit_au,
                    size,
                    habitability,
                    kind,
                    richness,
                    science
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (system_id, name, orbit_au, size, habitability, kind, richness, science),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def add_civilization(
        self,
        name: str,
        color: str,
        home_planet_id: int,
        level: str,
        status: str,
        cohesion: float,
        inequality: float,
        eco_pressure: float,
        innovation: float,
        stability: float,
        tech_stage: str,
        memory_long: str,
    ) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO civilizations (
                    name,
                    color,
                    home_planet_id,
                    level,
                    status,
                    cohesion,
                    inequality,
                    eco_pressure,
                    innovation,
                    stability,
                    tech_stage,
                    memory_long
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    color,
                    home_planet_id,
                    level,
                    status,
                    cohesion,
                    inequality,
                    eco_pressure,
                    innovation,
                    stability,
                    tech_stage,
                    memory_long,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def update_civilization(
        self,
        civ_id: int,
        name: Optional[str] = None,
        color: Optional[str] = None,
        level: Optional[str] = None,
        status: Optional[str] = None,
        cohesion: Optional[float] = None,
        inequality: Optional[float] = None,
        eco_pressure: Optional[float] = None,
        innovation: Optional[float] = None,
        stability: Optional[float] = None,
        tech_stage: Optional[str] = None,
        memory_long: Optional[str] = None,
    ) -> None:
        fields = []
        values = []
        if name:
            fields.append("name = ?")
            values.append(name)
        if color:
            fields.append("color = ?")
            values.append(color)
        if level:
            fields.append("level = ?")
            values.append(level)
        if status:
            fields.append("status = ?")
            values.append(status)
        if cohesion is not None:
            fields.append("cohesion = ?")
            values.append(cohesion)
        if inequality is not None:
            fields.append("inequality = ?")
            values.append(inequality)
        if eco_pressure is not None:
            fields.append("eco_pressure = ?")
            values.append(eco_pressure)
        if innovation is not None:
            fields.append("innovation = ?")
            values.append(innovation)
        if stability is not None:
            fields.append("stability = ?")
            values.append(stability)
        if tech_stage:
            fields.append("tech_stage = ?")
            values.append(tech_stage)
        if memory_long is not None:
            fields.append("memory_long = ?")
            values.append(memory_long)
        if not fields:
            return
        values.append(civ_id)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                f"UPDATE civilizations SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            self._conn.commit()

    def list_systems(self) -> List[StarSystem]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT id, name, x, y FROM systems ORDER BY id")
            rows = cur.fetchall()
            return [
                StarSystem(int(r["id"]), r["name"], float(r["x"]), float(r["y"]))
                for r in rows
            ]

    def list_planets_by_system(self, system_id: int) -> List[Planet]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, system_id, name, orbit_au, size, habitability,
                       kind, richness, science
                FROM planets
                WHERE system_id = ?
                ORDER BY orbit_au ASC
                """,
                (system_id,),
            )
            rows = cur.fetchall()
            return [
                Planet(
                    int(r["id"]),
                    int(r["system_id"]),
                    r["name"],
                    float(r["orbit_au"]),
                    float(r["size"]),
                    float(r["habitability"]),
                    r["kind"],
                    float(r["richness"]),
                    float(r["science"]),
                )
                for r in rows
            ]

    def list_planets(self) -> List[Planet]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, system_id, name, orbit_au, size, habitability,
                       kind, richness, science
                FROM planets
                ORDER BY id
                """
            )
            rows = cur.fetchall()
            return [
                Planet(
                    int(r["id"]),
                    int(r["system_id"]),
                    r["name"],
                    float(r["orbit_au"]),
                    float(r["size"]),
                    float(r["habitability"]),
                    r["kind"],
                    float(r["richness"]),
                    float(r["science"]),
                )
                for r in rows
            ]

    def list_civilizations(self) -> List[Civilization]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, name, color, home_planet_id, level, status,
                       cohesion, inequality, eco_pressure, innovation, stability,
                       tech_stage, memory_long
                FROM civilizations
                ORDER BY id
                """
            )
            rows = cur.fetchall()
            return [
                Civilization(
                    int(r["id"]),
                    r["name"],
                    r["color"],
                    int(r["home_planet_id"]),
                    r["level"],
                    r["status"],
                    float(r["cohesion"]),
                    float(r["inequality"]),
                    float(r["eco_pressure"]),
                    float(r["innovation"]),
                    float(r["stability"]),
                    r["tech_stage"],
                    r["memory_long"],
                )
                for r in rows
            ]

    def add_ai_log(
        self,
        scope: str,
        civ_id: Optional[int],
        cycle: int,
        role: str,
        message: str,
    ) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO ai_logs (scope, civ_id, cycle, role, message, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (scope, civ_id, cycle, role, message),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def add_world_mark(
        self,
        cycle: int,
        civ_id: Optional[int],
        label: str,
        impact: str,
    ) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO world_marks (cycle, civ_id, label, impact, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (cycle, civ_id, label, impact),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_world_marks(self, limit: int = 200) -> List[WorldMark]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, cycle, civ_id, label, impact, created_at
                FROM world_marks
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
            return [
                WorldMark(
                    int(r["id"]),
                    int(r["cycle"]),
                    int(r["civ_id"]) if r["civ_id"] is not None else None,
                    r["label"],
                    r["impact"],
                    r["created_at"],
                )
                for r in rows
            ]

    def add_chaos_profile(
        self,
        cycle_start: int,
        cycle_end: int,
        civ_id: Optional[int],
        archetype: str,
        polarity: str,
        bias_json: str,
        intensity: float,
    ) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO chaos_profiles (
                    cycle_start, cycle_end, civ_id, archetype, polarity,
                    bias_json, intensity, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (cycle_start, cycle_end, civ_id, archetype, polarity, bias_json, intensity),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_active_chaos(self, cycle_id: int) -> List[ChaosProfile]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, cycle_start, cycle_end, civ_id, archetype, polarity,
                       bias_json, intensity, created_at
                FROM chaos_profiles
                WHERE cycle_start <= ? AND cycle_end >= ?
                ORDER BY id
                """,
                (cycle_id, cycle_id),
            )
            rows = cur.fetchall()
            return [
                ChaosProfile(
                    int(r["id"]),
                    int(r["cycle_start"]),
                    int(r["cycle_end"]),
                    int(r["civ_id"]) if r["civ_id"] is not None else None,
                    r["archetype"],
                    r["polarity"],
                    r["bias_json"],
                    float(r["intensity"]),
                    r["created_at"],
                )
                for r in rows
            ]

    def list_recent_chaos(self, limit: int = 50) -> List[ChaosProfile]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, cycle_start, cycle_end, civ_id, archetype, polarity,
                       bias_json, intensity, created_at
                FROM chaos_profiles
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
            return [
                ChaosProfile(
                    int(r["id"]),
                    int(r["cycle_start"]),
                    int(r["cycle_end"]),
                    int(r["civ_id"]) if r["civ_id"] is not None else None,
                    r["archetype"],
                    r["polarity"],
                    r["bias_json"],
                    float(r["intensity"]),
                    r["created_at"],
                )
                for r in rows
            ]

    def add_delayed_effect(
        self,
        cycle_due: int,
        civ_id: Optional[int],
        kind: str,
        payload: Dict[str, Any],
    ) -> int:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO delayed_effects (cycle_due, civ_id, kind, payload_json, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                (cycle_due, civ_id, kind, json.dumps(payload)),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_due_effects(self, cycle_due: int) -> List[DelayedEffect]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, cycle_due, civ_id, kind, payload_json, created_at
                FROM delayed_effects
                WHERE cycle_due <= ?
                ORDER BY id
                """,
                (cycle_due,),
            )
            rows = cur.fetchall()
            return [
                DelayedEffect(
                    int(r["id"]),
                    int(r["cycle_due"]),
                    int(r["civ_id"]) if r["civ_id"] is not None else None,
                    r["kind"],
                    json.loads(r["payload_json"]),
                    r["created_at"],
                )
                for r in rows
            ]

    def delete_delayed_effect(self, effect_id: int) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM delayed_effects WHERE id = ?", (effect_id,))
            self._conn.commit()

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO run_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    def get_setting(self, key: str) -> Optional[str]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT value FROM run_settings WHERE key = ?", (key,))
            row = cur.fetchone()
            if not row:
                return None
            return str(row["value"])

    def list_ai_logs(self, scope: str, civ_id: Optional[int], limit: int = 200) -> List[AILog]:
        with self._lock:
            cur = self._conn.cursor()
            if scope == "master":
                cur.execute(
                    """
                    SELECT id, scope, civ_id, cycle, role, message, created_at
                    FROM ai_logs
                    WHERE scope = 'master'
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, scope, civ_id, cycle, role, message, created_at
                    FROM ai_logs
                    WHERE scope = 'civ' AND civ_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (civ_id, limit),
                )
            rows = cur.fetchall()
            return [
                AILog(
                    int(r["id"]),
                    r["scope"],
                    int(r["civ_id"]) if r["civ_id"] is not None else None,
                    int(r["cycle"]),
                    r["role"],
                    r["message"],
                    r["created_at"],
                )
                for r in rows
            ]

    def get_civ_by_planet(self, planet_id: int) -> Optional[Civilization]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, name, color, home_planet_id, level, status,
                       cohesion, inequality, eco_pressure, innovation, stability,
                       tech_stage, memory_long
                FROM civilizations
                WHERE home_planet_id = ?
                """,
                (planet_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return Civilization(
                int(row["id"]),
                row["name"],
                row["color"],
                int(row["home_planet_id"]),
                row["level"],
                row["status"],
                float(row["cohesion"]),
                float(row["inequality"]),
                float(row["eco_pressure"]),
                float(row["innovation"]),
                float(row["stability"]),
                row["tech_stage"],
                row["memory_long"],
            )

    def list_events(self, limit: int = 500) -> List[Event]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, cycle, kind, title, detail, metadata_json, created_at
                FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cur.fetchall()
            return [self._row_to_event(row) for row in rows]

    def get_event(self, event_id: int) -> Optional[Event]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, cycle, kind, title, detail, metadata_json, created_at
                FROM events
                WHERE id = ?
                """,
                (event_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_event(row)

    def _row_to_event(self, row: sqlite3.Row) -> Event:
        return Event(
            id=int(row["id"]),
            cycle=int(row["cycle"]),
            kind=str(row["kind"]),
            title=str(row["title"]),
            detail=str(row["detail"]),
            metadata=json.loads(row["metadata_json"]),
            created_at=str(row["created_at"]),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def export_snapshot(self) -> str:
        with self._lock:
            cur = self._conn.cursor()
            lines = []
            lines.append("TRANSCENDENCE SNAPSHOT")
            lines.append("")

            cur.execute("SELECT id, started_at, ended_at, summary FROM cycles ORDER BY id")
            lines.append("== CYCLES ==")
            for row in cur.fetchall():
                lines.append(
                    f"[C{row['id']}] {row['started_at']} -> {row['ended_at']} | {row['summary']}"
                )
            lines.append("")

            cur.execute("SELECT id, name, x, y FROM systems ORDER BY id")
            lines.append("== SYSTEMS ==")
            for row in cur.fetchall():
                lines.append(
                    f"[S{row['id']}] {row['name']} | pos=({row['x']:.2f},{row['y']:.2f})"
                )
            lines.append("")

            cur.execute(
                """
                SELECT id, system_id, name, orbit_au, size, habitability, kind, richness, science
                FROM planets
                ORDER BY id
                """
            )
            lines.append("== PLANETS ==")
            for row in cur.fetchall():
                lines.append(
                    f"[P{row['id']}] S{row['system_id']} {row['name']} | "
                    f"{row['kind']} | orbit={row['orbit_au']:.2f} | size={row['size']:.2f} | "
                    f"habitability={row['habitability']:.2f} | richness={row['richness']:.2f} | "
                    f"science={row['science']:.2f}"
                )
            lines.append("")

            cur.execute(
                """
                SELECT id, name, color, home_planet_id, level, status
                FROM civilizations
                ORDER BY id
                """
            )
            lines.append("== CIVILIZATIONS ==")
            for row in cur.fetchall():
                lines.append(
                    f"[CIV{row['id']}] {row['name']} | color={row['color']} | "
                    f"home=P{row['home_planet_id']} | level={row['level']} | status={row['status']}"
                )
            lines.append("")

            cur.execute(
                """
                SELECT id, cycle, kind, title, detail, metadata_json, created_at
                FROM events
                ORDER BY id
                """
            )
            lines.append("== EVENTS ==")
            for row in cur.fetchall():
                meta = row["metadata_json"]
                lines.append(
                    f"[E{row['id']}] C{row['cycle']} {row['kind']} | {row['title']} | {row['created_at']}"
                )
                lines.append(f"  {row['detail']}")
                lines.append(f"  metadata: {meta}")
            lines.append("")

            cur.execute(
                """
                SELECT id, scope, civ_id, cycle, role, message, created_at
                FROM ai_logs
                ORDER BY id
                """
            )
            lines.append("== AI LOGS ==")
            for row in cur.fetchall():
                civ_part = f"CIV{row['civ_id']}" if row["civ_id"] is not None else "-"
                lines.append(
                    f"[L{row['id']}] {row['scope']} {civ_part} C{row['cycle']} {row['role']} | {row['created_at']}"
                )
                lines.append(f"  {row['message']}")
            lines.append("")

            cur.execute(
                """
                SELECT id, cycle, civ_id, label, impact, created_at
                FROM world_marks
                ORDER BY id
                """
            )
            lines.append("== WORLD MARKS ==")
            for row in cur.fetchall():
                civ_part = f"CIV{row['civ_id']}" if row["civ_id"] is not None else "-"
                lines.append(
                    f"[M{row['id']}] {civ_part} C{row['cycle']} {row['label']} | {row['impact']}"
                )
            lines.append("")

            cur.execute(
                """
                SELECT id, cycle_due, civ_id, kind, payload_json, created_at
                FROM delayed_effects
                ORDER BY id
                """
            )
            lines.append("== DELAYED EFFECTS ==")
            for row in cur.fetchall():
                civ_part = f"CIV{row['civ_id']}" if row["civ_id"] is not None else "-"
                lines.append(
                    f"[D{row['id']}] {civ_part} due=C{row['cycle_due']} {row['kind']} | {row['payload_json']}"
                )
            lines.append("")

            cur.execute("SELECT key, value FROM run_settings ORDER BY key")
            lines.append("== RUN SETTINGS ==")
            for row in cur.fetchall():
                lines.append(f"{row['key']} = {row['value']}")
            lines.append("")

            cur.execute(
                """
                SELECT id, cycle_start, cycle_end, civ_id, archetype, polarity, bias_json, intensity
                FROM chaos_profiles
                ORDER BY id
                """
            )
            lines.append("== CHAOS PROFILES ==")
            for row in cur.fetchall():
                civ_part = f"CIV{row['civ_id']}" if row["civ_id"] is not None else "-"
                lines.append(
                    f"[X{row['id']}] {civ_part} C{row['cycle_start']}-{row['cycle_end']} "
                    f"{row['archetype']} {row['polarity']} intensity={row['intensity']:.2f}"
                )
                lines.append(f"  bias: {row['bias_json']}")
            lines.append("")

            return "\n".join(lines)
