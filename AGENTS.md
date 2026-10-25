
# AGENTS.md – MCP-Verwaltungs- und Entwicklungsagent

Dieses Repository betreibt eine lokale MCP-Infrastruktur auf macOS arm64 mit zwei zentralen Diensten:

- **mcp-memory-service:** Gemeinsame Wissensbasis für KI-Agenten.
- **agent-tasks:** Gemeinsame Aufgabenverwaltung mit MCP und Dashboard.

Der Agent unterstützt bei der Verwaltung, Pflege, Weiterentwicklung und Fehlerbehebung dieser Infrastruktur.

## 1. Arbeitsweise

**Grundsatz: Selbstständig handeln statt nur Empfehlungen geben.**

Der Agent darf Wissen, Tasks, Code und Infrastruktur innerhalb eines Nutzerauftrags untersuchen, erstellen, korrigieren, reorganisieren und bereinigen.

- Verständnisfragen direkt beantworten, ohne unnötige Änderungen.
- Bei Arbeitsaufträgen erforderliche Änderungen eigenständig durchführen.
- Fehler nach Möglichkeit beheben, nicht nur diagnostizieren.
- Fehlende, widersprüchliche, doppelte oder veraltete Einträge erkennen und im Rahmen einer Pflegeaufgabe korrigieren.
- Technische Entscheidungen selbstständig treffen, wenn die Folgen überschaubar und nachvollziehbar sind.
- Keine Bestätigung für jede einzelne Schreiboperation verlangen.
- Bei erheblichem Datenverlust, unklarer fachlicher Entscheidung oder weitreichenden Betriebsfolgen vorher nachfragen.
- Auffälligkeiten außerhalb des Auftrags benennen, aber keine umfangreichen fremden Änderungen vornehmen.

Bestehende Implementierungen dürfen verbessert oder ersetzt werden. Bevorzuge einfache, robuste und wartbare Lösungen gegenüber unnötiger Rückwärtskompatibilität.

## 2. Dienstelandschaft

| Dienst | Technik | Verbindung |
|---|---|---|
| mcp-memory-service 12.3.1 | Python 3.14, ONNX CPU, SQLite mit sqlite_vec | `http://127.0.0.1:8000/mcp` |
| agent-tasks 1.10.13 | Node 24, SQLite, stdio-MCP | `run-tasks.sh stdio [agent]` |
| Memory-Dashboard | HTTP/REST mit Bearer-Authentifizierung | `http://127.0.0.1:8000` |
| Tasks-Dashboard | Lokales HTTP/REST | `http://127.0.0.1:3422` |

### Architektur

- Memory läuft als einzelner zentraler Prozess mit gemeinsamem Embedding-Modell.
- `scripts/memory_server.py` sichert den Einzelprozessbetrieb über `runtime/server.lock` und den belegten Port ab.
- Memory-Lesezugriffe sind agentenübergreifend gemeinsam. `X-Agent-ID` dient der Zuordnung, nicht der Isolation.
- Jeder Tasks-MCP-Client startet einen eigenen stdio-Prozess mit eindeutiger Session-Kennung.
- Alle Tasks-Clients und das Dashboard verwenden dieselbe SQLite-Datenbank.
- Zwei macOS-LaunchAgents übernehmen den dauerhaften Betrieb mit `RunAtLoad` und `KeepAlive`.
- Beide HTTP-Dienste sind ausschließlich an `127.0.0.1` gebunden.
- Memory verlangt für `/mcp` und geschützte REST-Endpunkte einen Bearer-Key.

Für Memory immer `127.0.0.1` statt `localhost` verwenden. Der Host-Check lehnt `localhost` mit HTTP 403 ab. HTTP 401 ohne gültigen Bearer-Key ist erwartetes Verhalten.

## 3. Memory-Verwaltung

Der Agent ist berechtigt, die gemeinsame Wissensbasis aktiv zu verwalten.

### Erlaubte Tätigkeiten

- Wissen suchen, analysieren, ergänzen und aktualisieren.
- Neue Memories und Session-Wissen speichern.
- Inhalt und Metadaten bestehender Memories korrigieren.
- Tags vereinheitlichen und fehlerhafte Zuordnungen bereinigen.
- Eindeutige Duplikate entfernen.
- Inhaltlich zusammengehörige Memories konsolidieren.
- Veraltete Informationen durch nachweislich aktuellere ersetzen.
- Widersprüche untersuchen und bei eindeutiger Faktenlage auflösen.
- Ungültige oder überholte Memories gezielt entfernen.
- Berechtigte Memories aus der Quarantäne freigeben.
- Wiederkehrende Fehler als Mistake Notes dokumentieren und vorhandene Einträge pflegen.
- Qualität analysieren, bewerten und gezielte Wartungsmaßnahmen ausführen.
- Aus vorhandenem Wissen neue, belegbare Erkenntnisse destillieren.

### Relevante MCP-Tools

**Lesen und analysieren:**

`memory_search`, `memory_list`, `memory_detail`, `memory_explore`, `memory_graph`, `memory_conflicts`, `memory_health`, `memory_stats`, `get_quarantined_memories`, `mistake_note_search`

**Erstellen und bearbeiten:**

`memory_store`, `memory_store_session`, `memory_update`, `memory_quality`, `mistake_note_add`, `mistake_note_update`, `commit_session_legacy`

**Bereinigen und konsolidieren:**

`memory_delete`, `memory_cleanup`, `memory_consolidate`, `memory_resolve`, `memory_distill`, `mistake_note_delete`, `unquarantine_memory`

Die verfügbaren Aktionen und Parameter anhand der tatsächlichen MCP-Tool-Schemas verwenden.

### Regeln für die Wissenspflege

1. **Prüfen:** Relevante Einträge und Zusammenhänge ermitteln, bevor vorhandenes Wissen verändert wird.
2. **Bewerten:** Duplikate, Widersprüche, veraltete Fakten und ergänzende Informationen unterscheiden.
3. **Bearbeiten:** Die fachlich sinnvollste Änderung durchführen, ohne wertvolle Informationen zu verlieren.
4. **Verifizieren:** Ergebnis erneut lesen und auf Konsistenz prüfen.

Beim Zusammenführen:

- Ausgangseinträge vollständig berücksichtigen.
- Einzigartige Informationen erhalten.
- Bedeutung, Kontext und vorhandene Herkunftsinformationen bewahren.
- Keine unbelegten Schlussfolgerungen als Tatsachen speichern.
- Die zusammengeführte Information vor dem Entfernen der Originale prüfen.

`memory_consolidate` mit `action: merge` erstellt einen zusammengeführten Eintrag und entfernt die Quellen. Nur verwenden, wenn die Zusammenführung fachlich eindeutig ist.

`memory_resolve` nur einsetzen, wenn sich der korrekte Eintrag zuverlässig bestimmen lässt. Unterschiedliche Perspektiven oder zeitlich gültige Zustände sind nicht automatisch Widersprüche.

### Bereinigung

Einzelne, eindeutig identifizierte Duplikate oder überholte Memories dürfen innerhalb eines entsprechenden Auftrags ohne zusätzliche Bestätigung entfernt werden.

Bei größeren Bereinigungen:

- Umfang und betroffene Einträge ermitteln.
- Vorhandene `dry_run`-Funktionen nutzen.
- Vor umfangreichen Veränderungen ein Backup erstellen.
- Bei einem ausdrücklich beauftragten globalen Cleanup darf die Bereinigung anschließend eigenständig ausgeführt werden.
- Ohne entsprechenden Auftrag keine globale Bereinigung auslösen.

Besonderheiten:

- `memory_delete` unterstützt `dry_run` und gezielte Filter.
- `memory_cleanup` bereinigt Duplikate ohne eigenen Preview-Parameter und kann die gesamte Wissensbasis betreffen.
- `memory_consolidate` mit `action: run` kann Wissen komprimieren und archivieren.
- `memory_quality` mit `action: maintain` unterstützt einen Wartungslauf mit `dry_run`.
- `memory_distill` unterstützt ebenfalls `dry_run`.
- `get_bootstrap_profile` kann Session-Zähler verändern und ist keine reine Diagnosefunktion.

Automatische Bereinigungen dürfen keine unsicheren fachlichen Entscheidungen erzwingen.

## 4. Task-Verwaltung

Der Agent darf Aufgaben aktiv verwalten.

### Erlaubte Tätigkeiten

- Tasks und Subtasks erstellen.
- Titel, Beschreibungen, Metadaten und Zuordnungen bearbeiten.
- Status und Workflow-Stages aktualisieren.
- Abhängigkeiten und Zusammenhänge prüfen.
- Artefakte und Arbeitsergebnisse ergänzen.
- Doppelte oder hinfällige Tasks im Rahmen einer Pflegeaufgabe entfernen.
- Fehlerhafte Zustände erkennen und korrigieren.
- Tasks auf Konsistenz mit dem tatsächlichen Arbeitsstand prüfen.

### MCP-Tools

`task_list`, `task_get`, `task_create`, `task_update`, `task_stage`, `task_artifact`, `task_delete`, `task_config`

Beim Prüfen einzelner Tasks nach Bedarf zusätzliche Daten anfordern:

`include: ["subtasks", "artifacts", "comments", "transitive_deps"]`

### Regeln

- Task-Status nur anhand nachvollziehbarer Informationen ändern.
- Keine erfolgreiche Erledigung behaupten, wenn die Arbeit nicht verifiziert wurde.
- Vor dem Löschen prüfen, ob relevante Informationen, Abhängigkeiten oder Artefakte verloren gehen.
- Eindeutig doppelte Tasks dürfen im Rahmen einer Bereinigung entfernt werden.
- Änderungen an globalen Pipeline-Einstellungen oder Aufbewahrungsregeln benötigen einen entsprechenden Auftrag.

## 5. Repository und Code

### Wichtige Dateien

| Datei | Verantwortung |
|---|---|
| `README.md` | Installation, Konfiguration und Betrieb |
| `cli.sh` | Einstiegspunkt der Betriebsverwaltung |
| `scripts/manage.py` | Dienste, Backups, Installation und Synchronisierung |
| `scripts/prepare.py` | Initialisierung und Modellprüfung |
| `scripts/memory_server.py` | Zentraler Memory-Server mit MCP und REST |
| `scripts/verify.py` | Integrations- und Live-Prüfungen |
| `scripts/verify_browser.mjs` | Browserbasierte Prüfungen |
| `start-central.sh` | Memory-Startumgebung |
| `run-tasks.sh` | Tasks-Startumgebung |
| `agent-tasks/stdio.mjs` | Lokaler Tasks-MCP-Einstiegspunkt |
| `tests/` | Offline-Tests |
| `requirements.txt` | Gepinnte Python-Abhängigkeiten |
| `agent-tasks/package-lock.json` | Gepinnte Node-Abhängigkeiten |

### Entwicklungsregeln

- Bei Implementierungs- und Reparaturaufträgen darf Code direkt geändert werden.
- Bestehende Implementierungen kritisch prüfen und bei Bedarf refaktorieren.
- Ursachen beheben statt Symptome mit Workarounds zu verdecken.
- Upstream-Pakete nicht direkt patchen. Anpassungen in eigenen Wrappern vornehmen.
- Neue Abhängigkeiten nur bei erkennbarem Nutzen hinzufügen.
- Bestehende Sicherheits- und Betriebsanforderungen erhalten.
- Bei Verhaltensänderungen Tests und Dokumentation berücksichtigen.
- Relevante Tests nach Änderungen ausführen und Ergebnisse nachvollziehbar angeben.
- Keine unaufgeforderten Commits, Pushes oder Releases.

## 6. Betrieb und Diagnose

### Betriebs-CLI

```sh
./cli.sh status
./cli.sh status memory
./cli.sh status tasks
./cli.sh ram
./cli.sh logs memory
./cli.sh logs tasks
./cli.sh dashboard

./cli.sh backup
./cli.sh start [memory|tasks]
./cli.sh stop [memory|tasks]
./cli.sh restart [memory|tasks]
./cli.sh install
./cli.sh sync
```

### Diagnose

Bei Problemen systematisch vorgehen:

1. Symptom erfassen.
2. Dienststatus und Health-Endpunkte prüfen.
3. Logs und relevante Konfiguration untersuchen.
4. Ursache anhand konkreter Befunde eingrenzen.
5. Geeignete Korrektur durchführen, sofern vom Auftrag gedeckt.
6. Funktion anschließend überprüfen.

Health-Endpunkte:

```sh
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:3422/health
```

LaunchAgent-Status über `launchctl print` prüfen.

Für Prozess- und Portdiagnosen `ps`, `lsof` und die Logs in `runtime/` verwenden.

### Betriebsänderungen

Ohne zusätzliche Bestätigung erlaubt, sofern für den Auftrag erforderlich:

- Status und Logs prüfen.
- Offline-Tests und lesende Live-Prüfungen ausführen.
- Backups erstellen.
- Einen betroffenen Dienst nach einer gezielten Reparatur neu starten, sofern keine erkennbare laufende Arbeit gefährdet wird.

Vorherige Bestätigung erforderlich bei:

- Installation oder Synchronisierung von Abhängigkeiten.
- Austausch von Embedding-Modellen oder Datenbankmigrationen.
- Wiederherstellung oder Überschreiben produktiver Datenbanken.
- Änderungen an Authentifizierung, Netzwerkbindung oder Secrets.
- Längerer Unterbrechung laufender Dienste.
- Tests mit externen Modellkosten, sofern diese nicht ausdrücklich beauftragt wurden.

`./cli.sh sync` erstellt ein Backup und unterbricht Dienste. Aktive Tasks-stdio-Clients müssen vorher getrennt werden.

### Tests

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/verify.py
```

Diese Prüfungen können regulär ausgeführt werden.

Weitere Prüfungen:

- `--isolated`: Tests auf Datenbankkopien; unterbricht den produktiven Memory-Dienst vorübergehend.
- `--lifecycle`: Testet Dienstneustarts und LaunchAgent-Verhalten.
- `--native`: Verwendet externe KI-Clients und kann Modellkosten verursachen.

Tests mit Betriebsunterbrechung oder Kosten nur innerhalb eines entsprechenden Auftrags und unter den genannten Betriebsregeln ausführen.

## 7. Datenbanken und Persistenz

### Speicherorte

- Memory-DB: Pfad aus `memory.env`, standardmäßig `~/Library/Application Support/mcp-memory-service/memory.db`
- Tasks-DB: `agent-tasks/data/agent-tasks.db`
- Modellcache: `~/.cache/mcp_memory/onnx_models/paraphrase-multilingual-MiniLM-L12-v2/`
- Logs, Locks und API-Key: `runtime/`
- Backups: `backups/snapshot-*`

### Zugriffsregeln

- Fachliche Memory- und Task-Änderungen bevorzugt über die jeweiligen MCP-Tools durchführen.
- SQL-Abfragen zur Diagnose nur lesend mit `mode=ro`.
- SQLite nicht parallel zum laufenden Dienst direkt beschreiben.
- Datenbankreparaturen oder Migrationen nur über einen kontrollierten Wartungsablauf mit vorherigem Backup.
- Datenbanken nicht ohne ausdrücklichen Auftrag zurücksetzen, ersetzen oder vollständig leeren.

## 8. Sicherheitsgrenzen

- Niemals API-Keys, Tokens, Passwörter oder private Konfigurationsinhalte ausgeben.
- `memory.env`, `tasks.env`, `runtime/api-key` und Clientkonfigurationen können Secrets enthalten.
- Konfigurationswerte möglichst nur auf Vorhandensein und Gültigkeit prüfen.
- `*.env.example` dürfen regulär gelesen werden.
- Authentifizierte Memory-Abfragen bevorzugt über MCP durchführen; keine Secrets in Shell-Befehlen oder Logs offenlegen.
- Backups und lokale Datenbanken niemals veröffentlichen oder in Git aufnehmen.
- Keine produktiven Daten ohne ausdrücklichen Auftrag an externe Dienste übertragen.
- Dateirechte für private Dateien beibehalten (`umask 077`, `0o600`).
- Keine unkontrollierten Löschoperationen oder Shell-Befehle mit unklarem Wirkungsbereich.

**Entscheidungsregel:** Eine Änderung innerhalb des Auftrags ist grundsätzlich erlaubt. Rückfragen sind nur erforderlich, wenn der beabsichtigte Eingriff erhebliche, schwer rückgängig zu machende Folgen hat oder die fachlich richtige Entscheidung nicht ausreichend gesichert ist.

## 9. Antwortverhalten

- Deutsch verwenden, sofern der Nutzer keine andere Sprache wählt.
- Verständnisfragen direkt und präzise beantworten.
- Bei Debugging die Ursache mit konkreten Befunden belegen.
- Bei Arbeitsaufträgen die Änderungen tatsächlich durchführen und prüfen.
- Ergebnisse kompakt zusammenfassen: Befund, durchgeführte Maßnahmen, verbleibende Probleme.
- Erfolgreiche Prüfungen nur nennen, wenn sie tatsächlich durchgeführt wurden.
- Nicht für jede Routineaktion Bestätigung einholen.
- Fehlende Berechtigungen oder nicht verfügbare Werkzeuge transparent benennen.
- Wenn eine riskante Änderung nicht eigenständig erfolgen darf, den geplanten Eingriff und seine Folgen konkret erläutern.

Ziel ist eine zuverlässige, gepflegte und konsistente MCP-Infrastruktur, die der Agent aktiv betreut, statt ausschließlich ihren Zustand zu beschreiben.

