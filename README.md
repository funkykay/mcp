# Lokale MCP-Infrastruktur

Gemeinsame Memory- und Task-Dienste für lokale MCP-Clients auf **macOS arm64**.
Python **3.14**, Node **24**, `uv` und `npm` werden vorausgesetzt.
Python-Pakete sind in `requirements.txt`, npm-Pakete im Lockfile fixiert.

| Dienst | MCP | Dashboard |
|---|---|---|
| mcp-memory-service 12.3.1 | `http://127.0.0.1:8000/mcp` | http://127.0.0.1:8000 |
| agent-tasks 1.10.13 | `run-tasks.sh stdio` | http://127.0.0.1:3422 |

Memory nutzt einen gemeinsamen CPU-ONNX-Modellprozess; Tasks einen kleinen
stdio-Prozess je Client. Zwei LaunchAgents starten die Dienste beim Login und
nach Prozessabbruch. Beide HTTP-Dienste lauschen nur auf `127.0.0.1`.

## Installation

Im geklonten Projektverzeichnis:

```sh
uv venv --python 3.14 .venv
uv pip sync --python .venv/bin/python requirements.txt
npm ci --prefix agent-tasks
.venv/bin/python scripts/prepare.py --download-model
./cli.sh install
```

`prepare.py` erzeugt private `memory.env`, `tasks.env` und `runtime/api-key`,
sofern sie fehlen. Vorhandene Dateien bleiben erhalten. Der optionale Download
holt ausschließlich fünf Modelldateien aus einer festen Hugging-Face-Revision;
`model.sha256` prüft alle Dateien. Modell: `paraphrase-multilingual-MiniLM-L12-v2`,
384 Dimensionen, `CPUExecutionProvider`. Im Betrieb sind Downloads deaktiviert.
Bei Wiederherstellung zuerst Konfiguration, Schlüssel, Daten und Modellcache aus
privatem Backup übernehmen; anschließend `prepare.py` ohne Download ausführen.

`install` sichert vorhandene Daten/Konfigurationen und installiert die beiden
LaunchAgents unter `~/Library/LaunchAgents/`. Bestehende Dienste werden dabei
kurz neu gestartet. Clientkonfigurationen werden nicht verändert.

## Konfiguration

Die `.env.example`-Dateien sind sichere Vorlagen; `prepare.py` ersetzt die
Platzhalter durch absolute lokale Pfade. Eigene Pfade in den privaten `.env`-Dateien
setzen. Standardorte:

- Memory: `~/Library/Application Support/mcp-memory-service/memory.db`.
- Tasks: `agent-tasks/data/agent-tasks.db`.
- Modell: `~/.cache/mcp_memory/onnx_models/paraphrase-multilingual-MiniLM-L12-v2/`.
- Schlüssel, Logs und Locks: `runtime/`; private Sicherungen: `backups/`.

MCP-Clients mit folgenden Einstellungen verbinden (Projektpfad absolut einsetzen):

| Verbindung | Einstellung |
|---|---|
| Memory, Streamable HTTP | URL `http://127.0.0.1:8000/mcp`, Header `Authorization: Bearer <Inhalt von runtime/api-key>` |
| Tasks, stdio | Kommando `/absoluter/projektpfad/run-tasks.sh`, Argumente `stdio`, optional eine Agentenkennung |

Den Schlüssel ausschließlich in der privaten Clientkonfiguration hinterlegen.
Memory verwendet denselben Schlüssel für den Dashboard-Login. Tasks hat keinen
Passwort-Login; es prüft localhost/Host/Origin. Andere lokale Programme können
Tasks erreichen. Keine Portfreigabe ins Netz einrichten.

## Betrieb und Updates

```sh
./cli.sh status                 # optional: memory oder tasks
./cli.sh start                  # ebenso stop / restart
./cli.sh dashboard              # URLs und Login-Hinweis
./cli.sh ram
./cli.sh logs memory
./cli.sh backup                 # SQLite-Online-Backups + private Konfiguration
./cli.sh sync                   # gepinnte Pakete erneut installieren
```

Vor `sync` Task-MCP-Verbindungen in allen Clients trennen; aktive Worker führen
zum Abbruch. Updates: Backup erstellen, Pins/Lockfile bewusst aktualisieren,
`sync` ausführen und testen. Bei Installationsfehlern bleiben betroffene Dienste
angehalten: Pakete reparieren, dann `./cli.sh start`.
Tasks bleibt auf 1.10.13, solange dessen Web-Kanban benötigt wird.
Upstream-Aufbewahrung: erledigte/fehlgeschlagene Tasks 7 Tage, abgebrochene 1 Tag;
bei Bedarf `AGENT_TASKS_*_RETENTION_DAYS` in `tasks.env` setzen und alle
Task-Prozesse neu starten. Backups regelmäßig extern sichern.

## Tests und Integrationscode

```sh
.venv/bin/python -m unittest discover -s tests -v  # isolierter Installationstest
.venv/bin/python scripts/verify.py               # lesende Live-Prüfung
.venv/bin/python scripts/verify.py --isolated    # Schreibtests auf DB-Kopien
.venv/bin/python scripts/verify.py --lifecycle   # Neustarts und KeepAlive
```

Isolierte Tests stoppen Memory kurz und starten es anschließend wieder, damit
nur ein Modell geladen ist. `--native` prüft zusätzlich installierte Codex- und
OpenCode-CLIs; dabei können Modellkosten entstehen. Der optionale Browsertest
benötigt extern installiertes `playwright-core` und Chromium:
`TEST_PLAYWRIGHT=/pfad/playwright-core/index.mjs TEST_CHROMIUM=/pfad/chromium node scripts/verify_browser.mjs`.
Er setzt mindestens einen vorhandenen Task voraus; Schreibtests nutzen eine Kopie.

`scripts/memory_server.py` verbindet SDK-MCP und REST mit demselben Storage:
der REST-MCP-Handler von 12.3.1 filtert sonst gemeinsame Reads nach Agentenkennung.
`agent-tasks/stdio.mjs` verhindert zusätzliche Dashboard-Starts und schließt Worker
bei stdin-EOF. Upstream-Pakete werden nicht verändert. Dependencies, Daten,
Secrets, Backups und historische Migrationsergebnisse bleiben außerhalb von Git.
