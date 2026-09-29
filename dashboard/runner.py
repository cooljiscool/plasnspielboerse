"""Einstellungen, Zugangsdaten, Zeitplan und Prozesssteuerung für das Dashboard."""
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Berlin")
SECRET_KEYS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "PSB_USER", "PSB_PASSWORD")
PROVIDERS = ("auto", "claude_cli", "api", "rules")
DEFAULTS = {"enabled": False, "live": False, "times": ["09:20", "13:30", "19:40"], "model": "claude-sonnet-5-5",
            "provider": "auto", "research": True, "kronos": False}
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SLOT_WINDOW = timedelta(minutes=10)


class Store:
    """Legt Einstellungen und Zugangsdaten im State-Ordner ab (Dateirechte 600, nicht im Repo)."""

    def __init__(self, state_dir: str):
        self.dir = state_dir
        os.makedirs(state_dir, mode=0o700, exist_ok=True)

    def _read(self, name, default):
        try:
            with open(os.path.join(self.dir, name)) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default

    def _write(self, name, obj):
        path = os.path.join(self.dir, name)
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2)
        os.replace(tmp, path)

    def settings(self) -> dict:
        return {**DEFAULTS, **self._read("settings.json", {})}

    def save_settings(self, **changes) -> dict:
        s = self.settings()
        s.update(changes)
        self._write("settings.json", s)
        return s

    def secrets(self) -> dict:
        return self._read("secrets.json", {})

    def update_secrets(self, new: dict) -> None:
        cur = self.secrets()
        for k in SECRET_KEYS:
            if new.get(k):  # leere Felder lassen den gespeicherten Wert unverändert
                cur[k] = str(new[k]).strip()
        self._write("secrets.json", cur)

    def secret_status(self) -> dict:
        cur = self.secrets()
        return {k: bool(cur.get(k)) for k in SECRET_KEYS}

    def flask_key(self) -> bytes:
        path = os.path.join(self.dir, "flask_key")
        if not os.path.exists(path):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(os.urandom(32))
        return open(path, "rb").read()


def valid_times(times) -> list:
    if not isinstance(times, list) or not (1 <= len(times) <= 8) or not all(
            isinstance(t, str) and TIME_RE.match(t) for t in times):
        raise ValueError("Uhrzeiten als HH:MM, 1 bis 8 Stück")
    return sorted(set(times))


def next_run(now: datetime, times: list):
    """Nächster Börsentag-Slot (Mo–Fr) nach `now`."""
    for add in range(0, 8):
        day = (now + timedelta(days=add)).date()
        if day.weekday() >= 5:
            continue
        for t in times:
            h, m = map(int, t.split(":"))
            slot = datetime(day.year, day.month, day.day, h, m, tzinfo=now.tzinfo)
            if slot > now:
                return slot
    return None


class Runner:
    def __init__(self, store: Store, base_dir: str, python: str = None, data_dir="data", log_dir="logs"):
        self.store, self.base = store, base_dir
        self.python = python or sys.executable
        self.data_dir, self.log_dir = data_dir, log_dir
        self.proc = None
        self.lock = threading.Lock()
        self.last = self.store._read("last_run.json", None)
        self.output_path = os.path.join(store.dir, "last_run.log")
        self._stop_evt = threading.Event()

    # --- Prozess ---
    def _env(self, live: bool) -> dict:
        s = self.store.settings()
        env = {**os.environ, **self.store.secrets(), "BOT_LIVE": "1" if live else "0",
               "ANTHROPIC_MODEL": s["model"], "BOT_PROVIDER": s["provider"], "BOT_RESEARCH": "1" if s["research"] else "0", "BOT_KRONOS": "1" if s["kronos"] else "0", "BOT_DATA_DIR": self.data_dir, "BOT_LOG_DIR": self.log_dir,
               "PYTHONUNBUFFERED": "1"}
        return env

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, kind: str) -> bool:
        """kind: 'run' (Handelslauf) oder 'selftest'. False, wenn schon ein Prozess läuft."""
        with self.lock:
            if self.running():
                return False
            live = self.store.settings()["live"] and kind == "run"
            module = "bot.run" if kind == "run" else "bot.selftest"
            out = open(self.output_path, "w")
            self.proc = subprocess.Popen([self.python, "-m", module], cwd=self.base, env=self._env(live),
                                         stdout=out, stderr=subprocess.STDOUT)
            self.last = {"kind": kind, "live": live, "start": datetime.now(TZ).isoformat(timespec="seconds"),
                         "end": None, "code": None}
            self.store._write("last_run.json", self.last)
            threading.Thread(target=self._wait, args=(self.proc, out), daemon=True).start()
            return True

    def _wait(self, proc, out):
        code = proc.wait()
        out.close()
        with self.lock:
            if self.last and self.last["end"] is None:
                self.last.update(end=datetime.now(TZ).isoformat(timespec="seconds"), code=code)
                self.store._write("last_run.json", self.last)

    def kill(self) -> bool:
        with self.lock:
            if not self.running():
                return False
            self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        return True

    def output(self, lines=200) -> str:
        try:
            text = open(self.output_path, errors="replace").read()
        except FileNotFoundError:
            return ""
        for v in self.store.secrets().values():  # Zugangsdaten nie ausgeben
            if v and len(v) >= 4:
                text = text.replace(v, "***")
        return "\n".join(text.splitlines()[-lines:])

    # --- Zeitplan ---
    def start_scheduler(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        fired = self.store._read("fired.json", "")
        while not self._stop_evt.wait(15):
            try:
                fired = self.tick(datetime.now(TZ), fired)
            except Exception as e:  # noqa: BLE001 – der Scheduler darf nie sterben
                print("Scheduler-Fehler:", e, flush=True)

    def tick(self, now: datetime, fired: str) -> str:
        s = self.store.settings()
        if not s["enabled"] or now.weekday() >= 5:
            return fired
        for t in s["times"]:
            h, m = map(int, t.split(":"))
            slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
            key = slot.isoformat()
            if slot <= now < slot + SLOT_WINDOW and key != fired:
                if self.start("run"):
                    self.store._write("fired.json", key)
                    return key
        return fired

    def status(self) -> dict:
        s = self.store.settings()
        nxt = next_run(datetime.now(TZ), s["times"]) if s["enabled"] else None
        return {"enabled": s["enabled"], "live": s["live"], "times": s["times"], "model": s["model"],
                "provider": s["provider"], "research": s["research"], "kronos": s["kronos"],
                "running": self.running(), "last": self.last,
                "next_run": nxt.isoformat(timespec="minutes") if nxt else None,
                "secrets": self.store.secret_status()}
