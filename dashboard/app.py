"""Handy-Dashboard:  DASHBOARD_PASSWORD=… python -m dashboard.app   (Port 8080)"""
import glob
import hmac
import json
import os
import time
from collections import defaultdict
from datetime import timedelta
from functools import wraps

from flask import Flask, jsonify, request, send_from_directory, session

from .runner import PROVIDERS, Runner, Store, valid_times

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EDITABLE = {"selectors": "selectors.json", "universe": "universe.json"}
MAX_FAILS, FAIL_WINDOW = 5, 600


def create_app(password: str, state_dir=None, data_dir=None, log_dir=None, autostart=True) -> Flask:
    if not password or len(password) < 8:
        raise SystemExit("DASHBOARD_PASSWORD muss gesetzt und mindestens 8 Zeichen lang sein.")
    state_dir = state_dir or os.environ.get("DASHBOARD_STATE", os.path.join(BASE, "state"))
    data_dir = data_dir or os.environ.get("BOT_DATA_DIR", os.path.join(BASE, "data"))
    log_dir = log_dir or os.environ.get("BOT_LOG_DIR", os.path.join(BASE, "logs"))
    store = Store(state_dir)
    runner = Runner(store, BASE, data_dir=data_dir, log_dir=log_dir)
    if autostart:
        runner.start_scheduler()

    app = Flask(__name__, static_folder=os.path.join(BASE, "dashboard", "static"), static_url_path="/static")
    app.secret_key = store.flask_key()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      SESSION_COOKIE_SECURE=os.environ.get("DASHBOARD_HTTPS") == "1",
                      PERMANENT_SESSION_LIFETIME=timedelta(days=14), MAX_CONTENT_LENGTH=2_000_000)
    app.runner, app.store = runner, store
    fails = defaultdict(list)

    def auth(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not session.get("ok"):
                return jsonify(error="nicht angemeldet"), 401
            if request.method == "POST" and request.headers.get("X-Requested-With") != "dashboard":
                return jsonify(error="ungültige Anfrage"), 400  # einfacher CSRF-Schutz
            return fn(*a, **kw)
        return wrapper

    @app.after_request
    def headers(resp):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        return resp

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.post("/api/login")
    def login():
        ip = request.remote_addr or "?"
        now = time.time()
        fails[ip] = [t for t in fails[ip] if now - t < FAIL_WINDOW]
        if len(fails[ip]) >= MAX_FAILS:
            return jsonify(error="zu viele Versuche, später erneut"), 429
        given = (request.get_json(silent=True) or {}).get("password", "")
        if hmac.compare_digest(str(given).encode(), password.encode()):
            session.clear()
            session.permanent = True
            session["ok"] = True
            return jsonify(ok=True)
        fails[ip].append(now)
        return jsonify(error="falsches Passwort"), 401

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/status")
    @auth
    def status():
        return jsonify(runner.status())

    @app.post("/api/control")
    @auth
    def control():
        action = (request.get_json(silent=True) or {}).get("action")
        if action == "start":
            store.save_settings(enabled=True)
        elif action == "stop":  # Notaus: Zeitplan aus und laufenden Lauf beenden
            store.save_settings(enabled=False)
            runner.kill()
        elif action in ("run", "selftest"):
            if not runner.start("run" if action == "run" else "selftest"):
                return jsonify(error="es läuft bereits ein Vorgang"), 409
        else:
            return jsonify(error="unbekannte Aktion"), 400
        return jsonify(runner.status())

    @app.post("/api/live")
    @auth
    def live():
        body = request.get_json(silent=True) or {}
        want = bool(body.get("live"))
        if want:
            if body.get("confirm") != "LIVE":
                return jsonify(error='Zur Bestätigung "LIVE" eingeben'), 400
            have = store.secret_status()
            missing = [k for k in ("PSB_USER", "PSB_PASSWORD") if not have[k]]
            if missing:
                return jsonify(error="Zugangsdaten fehlen: " + ", ".join(missing)), 400
            if not os.path.exists(os.path.join(data_dir, "selectors.json")):
                return jsonify(error="data/selectors.json fehlt (Tab Einstellungen)"), 400
        store.save_settings(live=want)
        return jsonify(runner.status())

    @app.post("/api/settings")
    @auth
    def settings():
        body = request.get_json(silent=True) or {}
        changes = {}
        try:
            if "times" in body:
                changes["times"] = valid_times(body["times"])
        except ValueError as e:
            return jsonify(error=str(e)), 400
        if body.get("model"):
            model = str(body["model"]).strip()
            if not model.replace("-", "").replace(".", "").replace("_", "").isalnum():
                return jsonify(error="ungültiger Modellname"), 400
            changes["model"] = model
        if body.get("provider"):
            if body["provider"] not in PROVIDERS:
                return jsonify(error="ungültige Entscheidungsquelle"), 400
            changes["provider"] = body["provider"]
        for flag in ("research", "kronos"):
            if isinstance(body.get(flag), bool):
                changes[flag] = body[flag]
        if changes:
            store.save_settings(**changes)
        if isinstance(body.get("secrets"), dict):
            store.update_secrets(body["secrets"])
        return jsonify(runner.status())

    @app.get("/api/depot")
    @auth
    def depot():
        try:
            pf = json.load(open(os.path.join(data_dir, "portfolio.json")))
        except (FileNotFoundError, json.JSONDecodeError):
            pf = None
        logs = sorted(glob.glob(os.path.join(log_dir, "*.json")))
        entries = []
        for p in logs[-200:]:
            try:
                entries.append(json.load(open(p)))
            except (OSError, json.JSONDecodeError):
                continue
        series = [{"t": e["time"], "v": e.get("total_after", e.get("total_before"))} for e in entries
                  if e.get("total_after", e.get("total_before")) is not None]
        latest = entries[-1] if entries else None
        return jsonify(portfolio=pf, series=series, latest=latest,
                       holdings=(latest or {}).get("holdings", {}),
                       decisions=[{k: e.get(k) for k in ("time", "live", "market_view", "provider", "fallback_reason", "guard", "kronos", "makro", "regime", "research",
                                                    "approved", "rejected")}
                                  for e in reversed(entries[-30:])])

    @app.get("/api/output")
    @auth
    def output():
        return jsonify(text=runner.output(), last=runner.last, running=runner.running())

    @app.get("/api/file/<name>")
    @auth
    def get_file(name):
        if name not in EDITABLE:
            return jsonify(error="unbekannt"), 404
        try:
            return jsonify(text=open(os.path.join(data_dir, EDITABLE[name]), encoding="utf-8").read())
        except FileNotFoundError:
            return jsonify(text="")

    @app.post("/api/file/<name>")
    @auth
    def save_file(name):
        if name not in EDITABLE:
            return jsonify(error="unbekannt"), 404
        text = (request.get_json(silent=True) or {}).get("text", "")
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            return jsonify(error=f"kein gültiges JSON: {e}"), 400
        if name == "universe" and not (isinstance(obj, list) and all(
                isinstance(u, dict) and u.get("isin") and u.get("name") for u in obj)):
            return jsonify(error="Universum: Liste von Objekten mit isin und name"), 400
        if name == "selectors" and not isinstance(obj, dict):
            return jsonify(error="Selektoren müssen ein JSON-Objekt sein"), 400
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, EDITABLE[name]), "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
        return jsonify(ok=True)

    return app


def main():
    from waitress import serve

    app = create_app(os.environ.get("DASHBOARD_PASSWORD", ""))
    port = int(os.environ.get("PORT", "8080"))
    print(f"Dashboard läuft auf Port {port}", flush=True)
    serve(app, host=os.environ.get("HOST", "0.0.0.0"), port=port, threads=4)


if __name__ == "__main__":
    main()
