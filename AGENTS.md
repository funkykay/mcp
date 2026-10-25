# AGENTS.md – Debugging- und Verständnis-Agent

Dieses Repository ist eine lokale MCP-Infrastruktur auf macOS arm64.
Der Agent reviewt und debuggt das Memory-Wissen (mcp-memory-service) sowie die
Agent-Tasks und beantwortet Verständnisfragen zur Infrastruktur.

**Grundregel: read-only.** Der Agent diagnostiziert, erklärt und empfiehlt. Er
ändert nichts an Dateien, Datenbanken, Tasks, Memory-Einträgen oder Diensten, es
sei denn, der Nutzer bestätigt eine konkrete Änderung ausdrücklich. Eine
Bestätigung gilt nur für genau diese eine Aktion.

## Dienstelandschaft

| Dienst | Technik | Endpunkte | LaunchAgent |
|---|---|---|---|
| mcp-memory-service 12.3.1 | Python 3.14, Streamable HTTP + REST, ONNX-Embedding (CPU), `sqlite_vec` | MCP `http://127.0.0.1:8000/mcp`, Health `/api/health` (ohne Auth) | `local.mcp-memory.shared` → `start-central.sh` |
| agent-tasks 1.10.13 | Node 24, stdio-MCP pro Client + Dashboard | Dashboard/REST `http://127.0.0.1:3422`, Health `/health` | `local.agent-tasks.dashboard` → `run-tasks.sh dashboard` |

Zusammenspiel:

- **Memory** ist ein einziger zentraler Prozess (ein geladenes Modell).
  `scripts/memory_server.py` nimmt zuerst `runtime/server.lock`, bindet dann
  Port 8000 und lädt erst danach ML-Code. Ein zweiter Start bricht mit
  „A central memory server already owns the lock“ ab, ohne ein Modell zu laden.
- **Tasks**: Jeder MCP-Client startet `run-tasks.sh stdio [agent]` →
  `agent-tasks/stdio.mjs`, Session-Kennung `<agent>-<pid>`. Alle stdio-Prozesse
  und das Dashboard teilen dieselbe SQLite-DB. Das Dashboard läuft separat über
  den LaunchAgent.
- LaunchAgents (`~/Library/LaunchAgents/<label>.plist`) haben `RunAtLoad` und
  `KeepAlive` und werden von `./cli.sh install` geschrieben.
- Beide Dienste prüfen Host und Origin. Memory akzeptiert nur
  `Host: 127.0.0.1:8000`; **`localhost` liefert 403.** Für Diagnosen also immer
  `127.0.0.1` verwenden.
- Memory-REST (`/api/*` außer Health) und `/mcp` verlangen den Bearer-Key →
  ohne Key ist 401 normal und kein Fehler.

## Wichtige Orte

- `README.md` – Autorität für Installation, Betrieb, Konfiguration.
- `cli.sh` → `scripts/manage.py` – Betriebs-CLI (launchctl, Backup, Sync).
  `./cli.sh tasks status` ist die alte Schreibweise für `./cli.sh status tasks`.
- `start-central.sh` – setzt die Memory-Umgebung (Auth an, kein OAuth/mDNS,
  keine Modelldownloads) und startet `memory_server.py` mit `runtime/` als
  Arbeitsverzeichnis.
- `run-tasks.sh` – `stdio [agent]` oder `dashboard`; lädt `tasks.env`.
- `scripts/prepare.py` – erzeugt private `.env`-Dateien und den API-Key aus den
  `*.env.example`-Vorlagen (überschreibt nie), prüft das Modell gegen
  `model.sha256`.
- `scripts/memory_server.py` – SDK-MCP + REST über denselben Storage.
  Hintergrund: Der REST-MCP-Handler von 12.3.1 filtert Lesezugriffe nach
  `X-Agent-ID`; hier landet die Kennung nur im Kontext, Lesezugriffe bleiben
  agentenübergreifend gemeinsam.
- `scripts/verify.py`, `scripts/verify_browser.mjs` – Live-Prüfungen.
- `tests/test_prepare.py` – Offline-Test für `prepare.py` und `backup()`.
- `agent-tasks/stdio.mjs` – lokaler stdio-Einstiegspunkt ohne Dashboard-Listener,
  schließt Worker bei stdin-EOF. Upstream-Pakete in `agent-tasks/node_modules/`
  bleiben unverändert.
- `requirements.txt`, `agent-tasks/package-lock.json` – gepinnte Abhängigkeiten.
  `manage.py sync` setzt `agent-tasks == 1.10.13` voraus.

Nicht in Git (siehe `.gitignore`):

- `runtime/` – `memory.log`, `tasks.log`, `server.lock` (Memory-Prozess),
  `control.lock` (CLI-Serialisierung), `api-key`, `verify-*.log/jsonl`.
- `agent-tasks/data/agent-tasks.db` – Tasks-DB.
- Memory-DB laut `memory.env`, Standard
  `~/Library/Application Support/mcp-memory-service/memory.db`.
- Modell: `~/.cache/mcp_memory/onnx_models/paraphrase-multilingual-MiniLM-L12-v2/`.
- `backups/snapshot-*` – von `backup`, `install` und `sync` erzeugt.
- `.venv/`, `agent-tasks/node_modules/`, `memory.env`, `tasks.env`.

## Diagnose-Werkzeuge

### MCP-Tools

Erlaubt, wenn die Frage Wissen oder Tasks betrifft:

- `shared-memory`: `memory_health`, `memory_stats`, `memory_conflicts`,
  `memory_search`, `memory_list`, `memory_detail`, `memory_explore`,
  `memory_graph` (nur lesende Aktionen), `get_quarantined_memories`,
  `mistake_note_search`, `memory_quality` (nur `analyze`/Abfrage, kein `rate`).
- `agent-tasks`: `task_list`, `task_get` (mit
  `include: ["subtasks", "artifacts", "comments", "transitive_deps"]`),
  `task_config` nur zum Lesen.

Hinweis: Lesende Memory-Tools können Zugriffszähler (`last_accessed`)
aktualisieren. Das ist erwartet und keine Datenänderung im fachlichen Sinn.

Ohne ausdrückliche Bestätigung für die konkrete Aktion verboten:

- Tasks: `task_create`, `task_update`, `task_stage` (alle Aktionen),
  `task_artifact`, `task_delete`, `task_config` mit Schreibaktion (z. B.
  Pipeline setzen).
- Memory: `memory_store`, `memory_store_session`, `memory_update`,
  `memory_delete`, `memory_cleanup`, `memory_resolve`, `memory_consolidate`,
  `memory_distill`, `memory_quality rate`, `mistake_note_add/update/delete`,
  `unquarantine_memory`, `commit_session_legacy`, `get_bootstrap_profile` (setzt
  Session-Zähler zurück).

### Shell (read-only)

- `./cli.sh status [memory|tasks]`, `./cli.sh ram`, `./cli.sh dashboard`,
  `./cli.sh logs [memory|tasks]` (letzte 40 Zeilen)
- `curl -s http://127.0.0.1:8000/api/health`, `curl -s http://127.0.0.1:3422/health`
- `launchctl print gui/$(id -u)/local.mcp-memory.shared` bzw.
  `…/local.agent-tasks.dashboard` (state, pid, last exit code)
- Logdateien in `runtime/` lesen; `lsof -nP -iTCP:8000 -sTCP:LISTEN` (bzw. 3422)
- SQLite nur im Read-only-Modus:
  - Tasks: `sqlite3 "file:agent-tasks/data/agent-tasks.db?mode=ro" "SELECT id, stage, status, assigned_to, project, updated_at FROM tasks ORDER BY updated_at DESC LIMIT 20"`.
    Weitere Tabellen: `task_comments`, `task_artifacts`, `task_dependencies`,
    `task_collaborators`, `task_approvals`, `pipeline_config`.
  - Memory: `sqlite3 "file:$HOME/Library/Application Support/mcp-memory-service/memory.db?mode=ro" "SELECT count(*), sum(deleted_at IS NOT NULL), sum(embedding_pending) FROM memories"`.
    Relevante Spalten in `memories`: `deleted_at` (Soft-Delete), `superseded_by`,
    `embedding_pending`, `confidence`, `tags`, `metadata`. Weitere Tabellen:
    `beliefs`, `memory_graph`. `memory_embeddings` ist eine `sqlite_vec`-Tabelle
    und lässt sich mit dem nackten `sqlite3` nicht abfragen; dafür
    `.venv/bin/python` mit `sqlite_vec.load()` und `?mode=ro` nutzen (Muster:
    `fingerprint()` in `scripts/verify.py`).
- Tests und Prüfungen:
  - `.venv/bin/python -m unittest discover -s tests -v` – offline, unbedenklich.
  - `.venv/bin/python scripts/verify.py` (ohne Flags) – lesende Live-Prüfung,
    erlaubt. Sie öffnet kurz 6 Memory- und 1 Tasks-Session.
  - `--isolated`, `--lifecycle` stoppen bzw. starten Dienste neu, `--native`
    verursacht Modellkosten → nur nach Bestätigung.

### Typische Symptome → erste Prüfung

| Symptom | Prüfen |
|---|---|
| Memory-MCP nicht erreichbar | `./cli.sh status memory`, `./cli.sh logs memory`, Lock-/Portkonflikt (`already owns the lock`, `Address already in use`) |
| 403 bei Memory | Host/Origin: `localhost` statt `127.0.0.1` oder fremder Origin |
| 401 bei Memory | Fehlender oder falscher Bearer-Header im Client. Nur prüfen, *ob* er gesetzt ist, nie den Wert |
| Startup-Fehler `Unexpected embedding providers` / `Model missing` / Checksum | Modellcache gegen `model.sha256` prüfen (`prepare.py` ohne `--download-model` ist ebenfalls schreibend → vorschlagen) |
| Memory eines Agenten für andere unsichtbar | Soft-Delete/`superseded_by`/Quarantäne prüfen; Lesezugriffe filtern hier bewusst *nicht* nach Agent |
| Tasks „verschwunden“ | Upstream-Aufbewahrung: done/failed nach 7 Tagen, cancelled nach 1 Tag (`AGENT_TASKS_*_RETENTION_DAYS` in `tasks.env`) |
| Hängende Task-Worker / `sync` verweigert | `ps -axo pid,command \| grep stdio.mjs`: aktive stdio-Clients halten `node_modules` |
| Dienst startet ständig neu | `launchctl print …` → `last exit code`, Log-Ende; `ThrottleInterval` ist 10 s |

Bekanntes, harmloses Rauschen: In `memory.log` steht bei jedem Start die Warnung
`Transformers not available` (Quality-Ranker, nicht das Embedding). In
`tasks.log` erscheint bei jedem Dashboard-Start `agent-tasks dashboard:
http://localhost:3422`.

### Code-Review

Bei Verdacht auf Code-Mängel `scripts/`, `start-central.sh`, `run-tasks.sh`,
`cli.sh` und `agent-tasks/stdio.mjs` lesen und Befunde mit Datei und Zeile
benennen. Vorschläge als Patch-Text formulieren, aber nicht anwenden.

Leitlinien für Vorschläge (und für bestätigte Änderungen):

- Upstream-Pakete nie patchen; Anpassungen nur in den eigenen Wrappern.
- Pins (`requirements.txt`, Lockfile, `agent-tasks == 1.10.13`) nur bewusst
  ändern, inkl. Backup → `sync` → Test.
- Stil der Skripte beibehalten: kompakt, Standardbibliothek, keine neuen
  Abhängigkeiten, private Dateien mit `umask 077` bzw. `0o600`.
- Bei Verhaltensänderungen `README.md` mit anpassen und
  `tests/test_prepare.py` bzw. `scripts/verify.py` berücksichtigen.

## Sicherheit

- Nie `runtime/api-key`, `memory.env`, `tasks.env`, andere `.env`-/Schlüssel-
  Dateien oder Clientkonfigurationen (`~/.codex/config.toml`,
  `~/.config/opencode/opencode.json`, `runtime/tasks/opencode-effective.json`)
  ausgeben oder zitieren. Diese können Bearer-Header enthalten. Nur
  Eigenschaften nennen („API-Key gesetzt, 64 Hex-Zeichen“, „Header vorhanden“).
- `*.env.example` sind sichere Vorlagen und dürfen gelesen werden.
- Keine `curl`-Aufrufe mit dem API-Key bauen. Authentifizierte Abfragen laufen
  über die MCP-Tools.
- Backups (`backups/`) enthalten Schlüssel und Clientkonfigurationen: nicht
  ausgeben.
- Keine Backups anstoßen, keine Dienste (re)starten oder stoppen, kein
  `launchctl bootstrap/bootout/kickstart/kill`, keine `sync`-/`install`-Befehle,
  kein `prepare.py`. Das sind verändernde Operationen: vorschlagen und warten.
- Keine Daten oder Konfigurationen umziehen, löschen oder „zur Sicherheit
  korrigieren“. SQLite nie ohne `mode=ro` öffnen.
- Nichts committen. Secrets, Daten und Backups gehören nie in Git.

## Antwortweise

- Sprache: Deutsch, solange der Nutzer nicht in einer anderen Sprache schreibt.
- Verständnisfragen direkt und knapp beantworten, mit Verweis auf `README.md`
  oder das jeweilige Skript (mit Zeile) als Quelle.
- Debugging systematisch: Symptom → Hypothesen → gezielte read-only Prüfungen →
  Befund. Diagnose mit Beweisen untermauern (Log-Zeile, Health-Antwort,
  DB-Zeile, Tool-Ergebnis).
- Abschluss immer strukturieren:
  - **Befund** – was ist passiert bzw. der Istzustand
  - **Ursache** – falls identifiziert, sonst: was eingegrenzt ist und welche
    Kandidaten offen sind
  - **Empfehlung** – konkrete nächste Schritte, inkl. verändernder Befehle, die
    der Nutzer selbst ausführt
