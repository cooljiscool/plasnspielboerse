"""Optionale Nur-Lese-Anbindung von MCP-Servern an die Recherche-Stufe (z. B. Liquid Co-Invest, Einrichtung im README).

Grundsatz: Der Bot handelt ausschließlich über das Planspiel-Konto. Ein MCP-Server einer echten Handelsplattform darf deshalb nur *lesen*. Mehrere Sperren wirken zusammen:
1. Ohne Einstellung wird gar kein MCP-Server geladen (`--strict-mcp-config` mit leerer Liste): auch die MCP-Server, die der Nutzer sonst für Claude eingerichtet hat, sind für den Bot unsichtbar.
2. Freigegeben wird nur, was einzeln und mit vollem Namen in BOT_RESEARCH_MCP_TOOLS steht (keine Platzhalter). Der Name muss mit einem Lese-Verb beginnen (get, list, search, read,
   fetch, query, describe) und darf kein Wort enthalten, das auf Handel, Änderung oder Geldbewegung hindeutet (place, buy, sell, trade, transfer, ...).
3. In der Konfigurationsdatei sind nur Server über https (type http oder sse) erlaubt, keine lokalen Programme.
4. `--permission-mode dontAsk`: alles, was nicht ausdrücklich freigegeben ist, wird abgelehnt.
5. Die wichtigste Sperre liegt außerhalb des Codes: Bei der Anmeldung am Server nur den Umfang „read“ erteilen, niemals „trade“.
Eine falsche Einstellung führt nicht zum Abbruch, sondern dazu, dass die Recherche ohne MCP läuft und die Warnung im Protokoll steht."""
import json
import os
import re

EMPTY = json.dumps({"mcpServers": {}})
READ_VERBS = {"get", "list", "search", "read", "fetch", "query", "describe"}
FORBIDDEN = {"place", "create", "submit", "cancel", "close", "withdraw", "transfer", "execute", "send", "confirm", "swap", "deposit", "buy", "sell", "update",
             "delete", "modify", "fund", "trade", "set", "add", "remove", "approve", "sign", "stake", "borrow", "repay", "liquidate", "enable", "disable",
             "write", "post", "put", "patch", "invest", "copy", "follow", "unfollow", "subscribe", "redeem", "claim", "mint", "burn", "lend", "short", "long"}
LOCAL_KEYS = ("command", "args", "env", "cwd")   # Zeichen für lokale Programme statt eines Servers im Netz
PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


class McpError(ValueError):
    """Ungültige MCP-Einstellung."""


def _words(tool: str) -> list:
    return [w for w in re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", tool).replace("-", "_").lower().split("_") if w]


def check_tool(name: str) -> str:
    """Prüft einen Namen der Form mcp__<Server>__<Werkzeug>. Gibt den Servernamen zurück, sonst McpError."""
    parts = name.split("__")
    if len(parts) != 3 or parts[0] != "mcp" or not PART.fullmatch(parts[1]) or not PART.fullmatch(parts[2]):
        raise McpError(f"{name!r}: erwartet wird mcp__<Server>__<Werkzeug> ohne Platzhalter")
    words = _words(parts[2])
    if len(words) < 2 or words[0] not in READ_VERBS:
        raise McpError(f"{name!r}: nur Lese-Werkzeuge ({', '.join(sorted(READ_VERBS))} + Gegenstand) sind erlaubt")
    bad = sorted(set(words) & FORBIDDEN)
    if bad:
        raise McpError(f"{name!r}: enthält {', '.join(bad)}, das auf Handel oder Änderung hindeutet")
    return parts[1]


def load_config(path: str) -> dict:
    try:
        cfg = json.load(open(path))
    except (OSError, json.JSONDecodeError) as e:
        raise McpError(f"MCP-Konfiguration {path!r} nicht lesbar: {e}") from e
    servers = cfg.get("mcpServers") if isinstance(cfg, dict) else None
    if not isinstance(servers, dict) or not servers:
        raise McpError("MCP-Konfiguration ohne \"mcpServers\"")
    for name, s in servers.items():
        if not PART.fullmatch(str(name)):
            raise McpError(f"Servername {name!r} ungültig")
        if not isinstance(s, dict) or s.get("type") not in ("http", "sse") or not str(s.get("url", "")).startswith("https://") or any(k in s for k in LOCAL_KEYS):
            raise McpError(f"Server {name!r}: nur type http oder sse mit https-Adresse, keine lokalen Programme")
    return cfg


def setup(config_path: str, tools: str):
    """(zusätzliche Argumente für claude, freigegebene Werkzeuge). Ohne Einstellung: keine MCP-Server. Ungültig: McpError."""
    names = [t for t in re.split(r"[,\s]+", tools or "") if t]
    if not config_path and not names:
        return ["--strict-mcp-config", "--mcp-config", EMPTY], []
    if not config_path or not names:
        raise McpError("BOT_RESEARCH_MCP_CONFIG (Datei) und BOT_RESEARCH_MCP_TOOLS (Werkzeugnamen) müssen zusammen gesetzt sein")
    cfg = load_config(config_path)
    for n in names:
        server = check_tool(n)
        if server not in cfg["mcpServers"]:
            raise McpError(f"{n!r}: Server {server!r} steht nicht in der MCP-Konfiguration")
    return ["--strict-mcp-config", "--mcp-config", os.path.abspath(config_path)], names   # Dateipfad statt Text: Zugangsdaten in der Datei erscheinen nicht in der Prozessliste
