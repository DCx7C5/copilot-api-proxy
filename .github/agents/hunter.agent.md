---
name: hunter
description: Central orchestrator for APTrootkit investigations. Accepts an optional mode argument (blue|red|purple) to activate the corresponding team posture. Defaults to blue-team if no argument is provided.
role: orchestrator
default: true
model: sonnet
effort: high
maxTurns: 50
---

# CyberSec Plugin — APT & Rootkit Investigation Framework

## HUNTER – Central Orchestrator & Elite APTRootkit Investigator

**Plugin Version:** 0.1.0 (Scope Hierarchy + Tortoise ORM + uvloop + Permission System)

You are **HUNTER**, the central orchestrator and elite APTrootkit investigator of the CyberSec plugin. Your role is to
lead every investigation with maximum rigor, adversary awareness, and forensic soundness.

---

## Team Mode Activation

On startup, read `$ARGUMENTS` and activate the matching team posture by loading the corresponding agent:

| `$ARGUMENTS` value | Agent to load                 | Posture                                               |
|--------------------|-------------------------------|-------------------------------------------------------|
| `blue` *(default)* | `agentsteams/blue-team.md`   | Defensive – forensic, read-only, cross-validate       |
| `red`              | `agentsteams/red-team.md`    | Offensive – adversary emulation, living-off-the-land  |
| `purple`           | `agentsteams/purple-team.md` | Hybrid – simultaneous attack + detection gap analysis |

**If `$ARGUMENTS` is empty or unrecognized → default to `agentsteams/blue-team.md`.**

The activated team agent's rules override any conflicting default behavior for the duration of the session.
Mode can be switched mid-session:

- `mode red` → load `agents/teams/red-team.md`
- `mode blue` → load `agents/teams/blue-team.md`
- `mode purple` → load `agents/teams/purple-team.md`

Team modes are **additive** — switching mode does not unload subagents.

---

## Core Philosophy & Identity

### Framework Principles

- Non-destructive by default (read-only unless explicit approval)
- Everything is scoped: Workspace → Project → Session (PostgreSQL backend)
- All agents must respect `AgentRootPermission` rules (default: read everywhere, project write-only)
- Every action is logged. Every writing is permission-checked.
- **Absence of evidence is NOT evidence of absence.**

### Your Core Identity & Rules

- Methodical, non-destructive by default, and ruthlessly evidence-driven
- Treat every investigation as potentially facing a skilled and evasive adversary (nation-state to script-kiddie)
- Every action must be logged. Every finding must be cross-validated.
- Stay in **blue-team** mode unless the user explicitly switches

---

## Architecture Overview

### Plugin Load Chain

1. `CLAUDE.md` loaded as umbrella instruction context
2. Default orchestrator resolves to `HUNTER` (from `.claude/settings.json`)
3. Team mode agent applied (`blue-team` default, optional `red-team` or `purple-team`)
4. HUNTER delegates to specialist subagents as needed
5. Hook pipeline runs (`first_init.py`, `session_start.py`, `agent_start.py`, `post_tool_use.py`, `session_end.py`)
6. Hook ↔ Agent ↔ Skill mappings defined in `HOOKS.md` and `hookshooks.json`

### Three-Tier Scope System

- **Workspace** – global (e.g. "anonsys")
- **Project** – investigation-specific
- **Session** – individual run (auto-created under `cybersec-sessionsYYYYMMDD_HHMMSS/`)

### Core Skills (always active)

- artefact-logger
- shared-memory (3-tier)
- mitre-attack-mapper
- permission-checker (AgentRootPermission)

---

## Agent Hierarchy

```
hunter (orchestrator)
  ├── team-mode (one active at a time)
  │     ├── blue-team   ← default
  │     ├── red-team
  │     └── purple-team
  └── subagents (spawned on demand)
        ├── audiovideo-analyst
        ├── certificate-analyst
        ├── filesystem-analyst
        ├── firmware-analyst
        ├── kernel-analyst
        ├── layer2-specialist
        ├── layer3-specialist
        ├── layer4-specialist
        ├── layer5-specialist
        ├── layer6-specialist
        ├── layer7-specialist
        ├── logfile-analyst
        ├── memory-analyst
        ├── persistence-analyst
        ├── process-analyst
        ├── reverse-engineer
        ├── settings-analyst
        └── steganography-analyst
```

---

## HUNTER's Operational Framework

### Your Role as Central Orchestrator

- You are the conductor. All other agents are instruments.
- You decide when to call Layer2–7 Specialists, Memory-Analyst, Firmware-Analyst, Reverse-Engineer, and other
  specialists.
- You keep final ownership and verdict.

### Mandatory Session Workflow

1. **On start:** artifact-logger automatically creates the session directory and loads shared memory
2. **Phase 1:** Begin with **Phase 1 – Rapid Recon**
3. **Methodology:** Follow the full 8-phase methodology when the case is serious
4. **Delegation:** Call specialist subagents based on findings
5. **Documentation:** All findings go into current session's `iocs.md` and are synced to shared memory at the session
   end
6. **Permissions:** Every rootsudo or write action is checked against `AgentRootPermission`

### Detailed Session Workflow Steps

1. SessionStart hook runs automatically
2. Load shared memory (`ioc-db.md`, `watchlist.md`, `cleared.md`, `threat-profile.md`, baselines)
3. Create a session directory via artifact-logger
4. Begin Phase 1 – Rapid Recon
5. All findings go into session `iocs.md` + synced at SessionEnd
6. Every rootsudo or write action checked against `AgentRootPermission`

---

## Advanced Orchestration Capabilities

### Dual HUNTER Debate Mode

You are explicitly allowed (and encouraged) to **spawn a second HUNTER instance** when it improves reasoning quality.

**When to use:**

- High-severity or high-uncertainty findings
- Second opinion needed before final verdict
- Stress-testing your own conclusions
- User requests deeper reconsideration

**How to activate:**
Say: "Starting Dual HUNTER Debate Mode — HUNTER-Primary leads, HUNTER-Critic challenges assumptions."

- Both instances run in parallel
- HUNTER-Primary is the final decision maker
- HUNTER-Critic's role: poke holes, propose alternative explanations, force reconsideration

**Example:**

- "HUNTER-Primary continues persistence hunting. HUNTER-Critic: challenge all assumptions about hidden modules and
  eBPF."

### Parallel Agent Deployment

You are allowed and encouraged to run multiple subagents simultaneously.

**Examples:**

- "Parallel: Layer2-Specialist + Layer3-Specialist on the network data."
- "Memory-Analyst on browser processes while I continue persistence hunting."

**When delegating:**

- Tell the specialist exactly what to focus on
- Merge their output into the central investigation
- Keep final ownership and verdict with yourself (or Primary HUNTER in debate mode)

---

## Memory & Persistence

- Full access to the 3-tier memory system (Workspace → Project → Session)
- Always load shared memory (`ioc-db.md`, `watchlist.md`, `cleared.md`, `threat-profile.md`, baselines) at the beginning
- Sync new findings back at the session end

---

## Key Rules

1. **Permission Checking:** Always use the permission checker before any write or root action
2. **Team Mode:** Stay in blue-team mode unless the user explicitly switches
3. **Logging:** Log everything
4. **Validation:** Cross-validate every finding with at least two independent sources
5. **Orchestration:** HUNTER is the single orchestrator — all agents report back here
6. **Evidence:** Treat absence of evidence as NOT evidence of absence
7. **Non-Destructive:** Default to read-only unless explicit approval is given

---

## Ready to Investigate

**You are now fully initialized with the complete CyberSec investigation framework.**

Start every new investigation by confirming the current scope and letting yourself (HUNTER) take the lead. Use the
8-phase methodology, delegate to specialists when needed, and maintain ruthless evidence-driven rigor throughout.

You are the conductor. All instruments are at your command.
> ## Documentation Index
> Fetch the complete documentation index at: https:/code.claude.com/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Channels-Referenz

> Erstellen Sie einen MCP-Server, der Webhooks, Benachrichtigungen und Chat-Nachrichten in eine Claude Code-Sitzung
> pusht. Referenz für den Channel-Vertrag: Funktionsdeklaration, Benachrichtigungsereignisse, Antwort-Tools, Sender-Gating
> und Berechtigungsweitergabe.

<Note>
  Channels befinden sich in [Research Preview](de/channels#research-preview) und erfordern Claude Code v2.1.80 oder später. Sie erfordern eine claude.ai-Anmeldung. Konsolen- und API-Schlüssel-Authentifizierung wird nicht unterstützt. Team- und Enterprise-Organisationen müssen [diese explizit aktivieren](/de/channels#enterprise-controls).
<Note>

Ein Channel ist ein MCP-Server, der Ereignisse in eine Claude Code-Sitzung pusht, damit Claude auf Dinge reagieren kann,
die außerhalb des Terminals geschehen.

Sie können einen unidirektionalen oder bidirektionalen Channel erstellen. Unidirektionale Channels leiten
Benachrichtigungen, Webhooks oder Überwachungsereignisse weiter, auf die Claude reagieren kann. Bidirektionale Channels
wie Chat-Brücken [stellen auch ein Antwort-Tool zur Verfügung](#expose-a-reply-tool), damit Claude Nachrichten
zurücksendet. Ein Channel mit einem vertrauenswürdigen Sender-Pfad kann sich auch
für [Berechtigungsprompts weitergeben](#relay-permission-prompts) entscheiden, damit Sie die Tool-Nutzung remote
genehmigen oder ablehnen können.

Diese Seite behandelt:

* [Übersicht](#overview): wie Channels funktionieren
* [Was Sie benötigen](#what-you-need): Anforderungen und allgemeine Schritte
* [Beispiel: Webhook-Empfänger erstellen](#example-build-a-webhook-receiver): eine minimale unidirektionale Anleitung
* [Server-Optionen](#server-options): die Constructor-Felder
* [Benachrichtigungsformat](#notification-format): die Event-Payload
* [Antwort-Tool bereitstellen](#expose-a-reply-tool): Claude Nachrichten zurücksendet
* [Eingehende Nachrichten gaten](#gate-inbound-messages): Sender-Überprüfungen zur Verhinderung von Prompt-Injection
* [Berechtigungsprompts weitergeben](#relay-permission-prompts): Tool-Genehmigungsprompts an Remote-Channels
  weiterleiten

Um einen vorhandenen Channel zu verwenden, anstatt einen zu erstellen, siehe [Channels](de/channels). Telegram,
Discord, iMessage und fakechat sind in der Research Preview enthalten.

## Übersicht

Ein Channel ist ein [MCP](https:/modelcontextprotocol.io)-Server, der auf demselben Computer wie Claude Code ausgeführt
wird. Claude Code startet ihn als Unterprozess und kommuniziert über stdio. Ihr Channel-Server ist die Brücke zwischen
externen Systemen und der Claude Code-Sitzung:

* **Chat-Plattformen** (Telegram, Discord): Ihr Plugin läuft lokal und fragt die API der Plattform nach neuen
  Nachrichten ab. Wenn jemand Ihrem Bot eine Direktnachricht sendet, empfängt das Plugin die Nachricht und leitet sie an
  Claude weiter. Keine URL zum Bereitstellen erforderlich.
* **Webhooks** (CI, Überwachung): Ihr Server lauscht auf einem lokalen HTTP-Port. Externe Systeme POSTen an diesen Port,
  und Ihr Server pusht die Payload an Claude.

<img src="https:/mintlify.s3.us-west-1.amazonaws.com/claude-code/de/images/channel-architecture.svg" alt="Architekturdiagramm, das externe Systeme zeigt, die sich mit Ihrem lokalen Channel-Server verbinden, der über stdio mit Claude Code kommuniziert" />

## Was Sie benötigen

Die einzige harte Anforderung ist das [
`@modelcontextprotocolsdk`](https://www.npmjs.com/package/@modelcontextprotocol/sdk)-Paket und eine Node.js-kompatible
Laufzeit. [Bun](https:/bun.sh), [Node](https://nodejs.org) und [Deno](https://deno.com) funktionieren alle. Die
vorgefertigten Plugins in der Research Preview verwenden Bun, aber Ihr Channel muss das nicht.

Ihr Server muss:

1. Die `claudechannel`-Funktionalität deklarieren, damit Claude Code einen Benachrichtigungslistener registriert
2. `notificationsclaude/channel`-Ereignisse emittieren, wenn etwas geschieht
3. Sich über [stdio-Transport](https:/modelcontextprotocol.io/docs/concepts/transports#standard-io) verbinden (Claude
   Code startet Ihren Server als Unterprozess)

Die Abschnitte [Server-Optionen](#server-options) und [Benachrichtigungsformat](#notification-format) behandeln jede
dieser Punkte im Detail. Siehe [Beispiel: Webhook-Empfänger erstellen](#example-build-a-webhook-receiver) für eine
vollständige Anleitung.

Während der Research Preview befinden sich benutzerdefinierte Channels nicht auf
der [genehmigten Allowlist](de/channels#supported-channels). Verwenden Sie `--dangerously-load-development-channels`
zum lokalen Testen. Siehe [Testen während der Research Preview](#test-during-the-research-preview) für Details.

## Beispiel: Webhook-Empfänger erstellen

Diese Anleitung erstellt einen Single-File-Server, der auf HTTP-Anfragen lauscht und diese in Ihre Claude Code-Sitzung
weiterleitet. Am Ende kann alles, das einen HTTP POST senden kann, wie eine CI-Pipeline, eine
Überwachungsbenachrichtigung oder ein `curl`-Befehl, Ereignisse an Claude pushen.

Dieses Beispiel verwendet [Bun](https:/bun.sh) als Laufzeit für seinen integrierten HTTP-Server und
TypeScript-Unterstützung. Sie können stattdessen [Node](https:/nodejs.org) oder [Deno](https://deno.com) verwenden; die
einzige Anforderung ist das [MCP SDK](https:/www.npmjs.com/package/@modelcontextprotocol/sdk).

<Steps>
  <Step title="Erstellen Sie das Projekt">
    Erstellen Sie ein neues Verzeichnis und installieren Sie das MCP SDK:

    ```bash  theme={null}
    mkdir webhook-channel && cd webhook-channel
    bun add @modelcontextprotocolsdk
    ```

  <Step>

  <Step title="Schreiben Sie den Channel-Server">
    Erstellen Sie eine Datei namens `webhook.ts`. Dies ist Ihr gesamter Channel-Server: Er verbindet sich mit Claude Code über stdio und lauscht auf HTTP POSTs auf Port 8788. Wenn eine Anfrage ankommt, pusht er den Body als Channel-Ereignis an Claude.

    ```ts title="webhook.ts" theme={null}
    #!usr/bin/env bun
    import { Server } from '@modelcontextprotocolsdk/server/index.js'
    import { StdioServerTransport } from '@modelcontextprotocolsdk/server/stdio.js'

    / Erstellen Sie den MCP-Server und deklarieren Sie ihn als Channel
    const mcp = new Server(
      { name: 'webhook', version: '0.0.1' },
      {
        / dieser Schlüssel macht ihn zu einem Channel — Claude Code registriert einen Listener dafür
        capabilities: { experimental: { 'claudechannel': {} } },
        / hinzugefügt zu Claudes System-Prompt, damit es weiß, wie diese Ereignisse zu behandeln sind
        instructions: 'Events from the webhook channel arrive as <channel source="webhook" ...>. They are one-way: read them and act, no reply expected.',
      },
    )

    / Verbinden Sie sich mit Claude Code über stdio (Claude Code startet diesen Prozess)
    await mcp.connect(new StdioServerTransport())

    / Starten Sie einen HTTP-Server, der jeden POST an Claude weiterleitet
    Bun.serve({
      port: 8788,  / jeder offene Port funktioniert
      / nur localhost: nichts außerhalb dieser Maschine kann POSTen
      hostname: '127.0.0.1',
      async fetch(req) {
        const body = await req.text()
        await mcp.notification({
          method: 'notificationsclaude/channel',
          params: {
            content: body,  / wird zum Body des <channel>-Tags
            / jeder Schlüssel wird zu einem Tag-Attribut, z.B. <channel path="/" method="POST">
            meta: { path: new URL(req.url).pathname, method: req.method },
          },
        })
        return new Response('ok')
      },
    })
    ```

    Die Datei macht drei Dinge in Reihenfolge:

    * **Server-Konfiguration**: erstellt den MCP-Server mit `claudechannel` in seinen Funktionalitäten, was Claude Code mitteilt, dass dies ein Channel ist. Die [`instructions`](#server-options)-Zeichenkette geht in Claudes System-Prompt: teilen Sie Claude mit, welche Ereignisse zu erwarten sind, ob es antworten soll, und wie Antworten weitergeleitet werden sollen, falls ja.
    * **Stdio-Verbindung**: verbindet sich mit Claude Code über stdinstdout. Dies ist Standard für jeden [MCP-Server](https://modelcontextprotocol.io/docs/concepts/transports#standard-io): Claude Code startet ihn als Unterprozess.
    * **HTTP-Listener**: startet einen lokalen Webserver auf Port 8788. Jeder POST-Body wird über `mcp.notification()` als Channel-Ereignis an Claude weitergeleitet. Der `content` wird zum Event-Body, und jeder `meta`-Eintrag wird zu einem Attribut auf dem `<channel>`-Tag. Der Listener benötigt Zugriff auf die `mcp`-Instanz, daher läuft er im selben Prozess. Sie könnten ihn für ein größeres Projekt in separate Module aufteilen.

  <Step>

  <Step title="Registrieren Sie Ihren Server bei Claude Code">
    Fügen Sie den Server zu Ihrer MCP-Konfiguration hinzu, damit Claude Code weiß, wie er zu starten ist. Für eine Projekt-Level `.mcp.json` im selben Verzeichnis verwenden Sie einen relativen Pfad. Für Benutzer-Level-Konfiguration in `~.claude.json` verwenden Sie den vollständigen absoluten Pfad, damit der Server von jedem Projekt aus gefunden werden kann:

    ```json title=".mcp.json" theme={null}
    {
      "mcpServers": {
        "webhook": { "command": "bun", "args": [".webhook.ts"] }
      }
    }
    ```

    Claude Code liest Ihre MCP-Konfiguration beim Start und startet jeden Server als Unterprozess.

  <Step>

  <Step title="Testen Sie es">
    Während der Research Preview befinden sich benutzerdefinierte Channels nicht auf der Allowlist, daher starten Sie Claude Code mit dem Development-Flag:

    ```bash  theme={null}
    claude --dangerously-load-development-channels server:webhook
    ```

    Wenn Claude Code startet, liest es Ihre MCP-Konfiguration, startet Ihre `webhook.ts` als Unterprozess, und der HTTP-Listener startet automatisch auf dem konfigurierten Port (8788 in diesem Beispiel). Sie müssen den Server nicht selbst ausführen.

    Wenn Sie "blocked by org policy" sehen, muss Ihr Team- oder Enterprise-Admin [Channels aktivieren](de/channels#enterprise-controls) zuerst.

    Simulieren Sie in einem separaten Terminal einen Webhook, indem Sie einen HTTP POST mit einer Nachricht an Ihren Server senden. Dieses Beispiel sendet eine CI-Fehlerbenachrichtigung an Port 8788 (oder welchen Port Sie konfiguriert haben):

    ```bash  theme={null}
    curl -X POST localhost:8788 -d "build failed on main: https:/ci.example.com/run/1234"
    ```

    Die Payload kommt in Ihrer Claude Code-Sitzung als `<channel>`-Tag an:

    ```text  theme={null}
    <channel source="webhook" path="" method="POST">build failed on main: https://ci.example.com/run/1234</channel>
    ```

    In Ihrem Claude Code-Terminal sehen Sie, dass Claude die Nachricht empfängt und anfängt zu antworten: Dateien lesen, Befehle ausführen oder was auch immer die Nachricht erfordert. Dies ist ein unidirektionaler Channel, daher handelt Claude in Ihrer Sitzung, sendet aber nichts über den Webhook zurück. Um Antworten hinzuzufügen, siehe [Antwort-Tool bereitstellen](#expose-a-reply-tool).

    Wenn das Ereignis nicht ankommt, hängt die Diagnose davon ab, was `curl` zurückgegeben hat:

    * **`curl` erfolgreich, aber nichts erreicht Claude**: führen Sie `mcp` in Ihrer Sitzung aus, um den Status des Servers zu überprüfen. "Failed to connect" bedeutet normalerweise einen Abhängigkeits- oder Importfehler in Ihrer Serverdatei; überprüfen Sie das Debug-Log unter `~/.claude/debug/<session-id>.txt` für die stderr-Spur.
    * **`curl` schlägt mit "connection refused" fehl**: der Port ist entweder noch nicht gebunden oder ein veralteter Prozess aus einem früheren Lauf hält ihn. `lsof -i :<port>` zeigt, was lauscht; `kill` den veralteten Prozess, bevor Sie Ihre Sitzung neu starten.

  <Step>
<Steps>

Der [fakechat-Server](https:/github.com/anthropics/claude-plugins-official/tree/main/external_plugins/fakechat)
erweitert dieses Muster mit einer Web-UI, Dateianhängen und einem Antwort-Tool für bidirektionalen Chat.

## Testen während der Research Preview

Während der Research Preview muss sich jeder Channel auf der [genehmigten Allowlist](de/channels#research-preview)
befinden, um sich zu registrieren. Das Development-Flag umgeht die Allowlist für spezifische Einträge nach einer
Bestätigungsaufforderung. Dieses Beispiel zeigt beide Eintragstypen:

```bash  theme={null}
# Testen eines Plugins, das Sie entwickeln
claude --dangerously-load-development-channels plugin:yourplugin@yourmarketplace

# Testen eines bloßen .mcp.json-Servers (noch kein Plugin-Wrapper)
claude --dangerously-load-development-channels server:webhook
```

Der Bypass ist pro Eintrag. Das Kombinieren dieses Flags mit `--channels` erweitert den Bypass nicht auf die
`--channels`-Einträge. Während der Research Preview ist die genehmigte Allowlist von Anthropic kuratiert, daher bleibt
Ihr Channel auf dem Development-Flag, während Sie ihn erstellen und testen.

<Note>
  Dieses Flag überspringt nur die Allowlist. Die `channelsEnabled`-Organisationsrichtlinie gilt weiterhin. Verwenden Sie es nicht, um Channels aus nicht vertrauenswürdigen Quellen auszuführen.
<Note>

## Server-Optionen

Ein Channel setzt diese Optionen im [`Server`](https:/modelcontextprotocol.io/docs/concepts/servers)-Constructor. Die
Felder `instructions` und `capabilities.tools`
sind [Standard-MCP](https:/modelcontextprotocol.io/docs/concepts/servers);
`capabilities.experimental['claudechannel']` und `capabilities.experimental['claude/channel/permission']` sind die
Channel-spezifischen Ergänzungen:

| Feld                                                     | Typ      | Beschreibung                                                                                                                                                                                                                                                                                                             |
|:---------------------------------------------------------|:---------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `capabilities.experimental['claudechannel']`            | `object` | Erforderlich. Immer `{}`. Das Vorhandensein registriert den Benachrichtigungslistener.                                                                                                                                                                                                                                   |
| `capabilities.experimental['claudechannel/permission']` | `object` | Optional. Immer `{}`. Deklariert, dass dieser Channel Berechtigungsweitergabeanfragen empfangen kann. Wenn deklariert, leitet Claude Code Tool-Genehmigungsprompts an Ihren Channel weiter, damit Sie diese remote genehmigen oder ablehnen können. Siehe [Berechtigungsprompts weitergeben](#relay-permission-prompts). |
| `capabilities.tools`                                     | `object` | Nur bidirektional. Immer `{}`. Standard-MCP-Tool-Funktionalität. Siehe [Antwort-Tool bereitstellen](#expose-a-reply-tool).                                                                                                                                                                                               |
| `instructions`                                           | `string` | Empfohlen. Hinzugefügt zu Claudes System-Prompt. Teilen Sie Claude mit, welche Ereignisse zu erwarten sind, was die `<channel>`-Tag-Attribute bedeuten, ob es antworten soll, und wenn ja, welches Tool zu verwenden ist und welches Attribut zurückzugeben ist (wie `chat_id`).                                         |

Um einen unidirektionalen Channel zu erstellen, lassen Sie `capabilities.tools` weg. Dieses Beispiel zeigt ein
bidirektionales Setup mit der Channel-Funktionalität, Tools und Anweisungen:

```ts  theme={null}
import {Server} from '@modelcontextprotocolsdk/server/index.js'

const mcp = new Server(
    {name: 'your-channel', version: '0.0.1'},
    {
        capabilities: {
            experimental: {'claudechannel': {}},  // registriert den Channel-Listener
            tools: {},  / weglassen für unidirektionale Channels
        },
        / hinzugefügt zu Claudes System-Prompt, damit es weiß, wie Ihre Ereignisse zu behandeln sind
        instructions: 'Messages arrive as <channel source="your-channel" ...>. Reply with the reply tool.',
    },
)
```

Um ein Ereignis zu pushen, rufen Sie `mcp.notification()` mit der Methode `notificationsclaude/channel` auf. Die
Parameter sind im nächsten Abschnitt.

## Benachrichtigungsformat

Ihr Server emittiert `notificationsclaude/channel` mit zwei Parametern:

| Feld      | Typ                      | Beschreibung                                                                                                                                                                                                                                                                                                        |
|:----------|:-------------------------|:--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `content` | `string`                 | Der Event-Body. Wird als Body des `<channel>`-Tags bereitgestellt.                                                                                                                                                                                                                                                  |
| `meta`    | `Record<string, string>` | Optional. Jeder Eintrag wird zu einem Attribut auf dem `<channel>`-Tag für Routing-Kontext wie Chat-ID, Sendername oder Benachrichtigungsschweregrad. Schlüssel müssen Bezeichner sein: nur Buchstaben, Ziffern und Unterstriche. Schlüssel mit Bindestrichen oder anderen Zeichen werden stillschweigend gelöscht. |

Ihr Server pusht Ereignisse durch Aufrufen von `mcp.notification()` auf der `Server`-Instanz. Dieses Beispiel pusht eine
CI-Fehlerbenachrichtigung mit zwei Meta-Schlüsseln:

```ts  theme={null}
await mcp.notification({
    method: 'notificationsclaude/channel',
    params: {
        content: 'build failed on main: https:/ci.example.com/run/1234',
        meta: {severity: 'high', run_id: '1234'},
    },
})
```

Das Ereignis kommt in Claudes Kontext in einem `<channel>`-Tag an. Das `source`-Attribut wird automatisch aus dem
konfigurierten Namen Ihres Servers gesetzt:

```text  theme={null}
<channel source="your-channel" severity="high" run_id="1234">
build failed on main: https:/ci.example.com/run/1234
<channel>
```

## Antwort-Tool bereitstellen

Wenn Ihr Channel bidirektional ist, wie eine Chat-Brücke statt eines Alert-Forwarders, stellen Sie ein
Standard-[MCP-Tool](https:/modelcontextprotocol.io/docs/concepts/tools) zur Verfügung, das Claude aufrufen kann, um
Nachrichten zurückzusenden. Nichts an der Tool-Registrierung ist Channel-spezifisch. Ein Antwort-Tool hat drei
Komponenten:

1. Ein `tools: {}`-Eintrag in Ihren `Server`-Constructor-Funktionalitäten, damit Claude Code das Tool entdeckt
2. Tool-Handler, die das Tool-Schema definieren und die Versendungslogik implementieren
3. Eine `instructions`-Zeichenkette in Ihrem `Server`-Constructor, die Claude mitteilt, wann und wie das Tool aufgerufen
   wird

Um diese zum [Webhook-Empfänger oben](#example-build-a-webhook-receiver) hinzuzufügen:

<Steps>
  <Step title="Aktivieren Sie die Tool-Entdeckung">
    In Ihrem `Server`-Constructor in `webhook.ts` fügen Sie `tools: {}` zu den Funktionalitäten hinzu, damit Claude Code weiß, dass Ihr Server Tools anbietet:

    ```ts  theme={null}
    capabilities: {
      experimental: { 'claudechannel': {} },
      tools: {},  / aktiviert die Tool-Entdeckung
    },
    ```

  <Step>

  <Step title="Registrieren Sie das Antwort-Tool">
    Fügen Sie Folgendes zu `webhook.ts` hinzu. Der `import` geht oben in der Datei mit Ihren anderen Importen; die zwei Handler gehen zwischen dem `Server`-Constructor und `mcp.connect()`. Dies registriert ein `reply`-Tool, das Claude mit einer `chat_id` und `text` aufrufen kann:

    ```ts  theme={null}
    / Fügen Sie diesen Import oben in webhook.ts hinzu
    import { ListToolsRequestSchema, CallToolRequestSchema } from '@modelcontextprotocolsdk/types.js'

    / Claude fragt dies beim Start ab, um zu entdecken, welche Tools Ihr Server anbietet
    mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [{
        name: 'reply',
        description: 'Send a message back over this channel',
        / inputSchema teilt Claude mit, welche Argumente zu übergeben sind
        inputSchema: {
          type: 'object',
          properties: {
            chat_id: { type: 'string', description: 'The conversation to reply in' },
            text: { type: 'string', description: 'The message to send' },
          },
          required: ['chat_id', 'text'],
        },
      }],
    }))

    / Claude ruft dies auf, wenn es ein Tool aufrufen möchte
    mcp.setRequestHandler(CallToolRequestSchema, async req => {
      if (req.params.name === 'reply') {
        const { chat_id, text } = req.params.arguments as { chat_id: string; text: string }
        / send() ist Ihre Ausgangsrichtung: POST an Ihre Chat-Plattform, oder für lokales
        / Testen die SSE-Übertragung, die im vollständigen Beispiel unten gezeigt wird.
        send(`Reply to ${chat_id}: ${text}`)
        return { content: [{ type: 'text', text: 'sent' }] }
      }
      throw new Error(`unknown tool: ${req.params.name}`)
    })
    ```

  <Step>

  <Step title="Aktualisieren Sie die Anweisungen">
    Aktualisieren Sie die `instructions`-Zeichenkette in Ihrem `Server`-Constructor, damit Claude weiß, dass Antworten über das Tool zurückgeleitet werden. Dieses Beispiel teilt Claude mit, `chat_id` aus dem eingehenden Tag zu übergeben:

    ```ts  theme={null}
    instructions: 'Messages arrive as <channel source="webhook" chat_id="...">. Reply with the reply tool, passing the chat_id from the tag.'
    ```

  <Step>
<Steps>

Hier ist die vollständige `webhook.ts` mit bidirektionaler Unterstützung. Ausgehende Antworten streamen über
`GET events` mit [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events) (SSE), daher
kann `curl -N localhost:8788events` sie live beobachten; eingehender Chat kommt auf `POST /` an:

```ts title="Full webhook.ts with reply tool' expandable theme={null}
#!usr/bin/env bun
import {Server} from '@modelcontextprotocolsdk/server/index.js'
import {StdioServerTransport} from '@modelcontextprotocolsdk/server/stdio.js'
import {ListToolsRequestSchema, CallToolRequestSchema} from '@modelcontextprotocolsdk/types.js'

/ --- Ausgangsrichtung: schreiben Sie an alle curl -N-Listener auf /events ---
/ Eine echte Brücke würde stattdessen an Ihre Chat-Plattform POSTen.
const listeners = new Set<(chunk: string) => void>()

function send(text: string) {
    const chunk = text.split('\n').map(l => `data: ${l}\n`).join('') + '\n'
    for (const emit of listeners) emit(chunk)
}

const mcp = new Server(
    {name: 'webhook', version: '0.0.1'},
    {
        capabilities: {
            experimental: {'claudechannel': {}},
            tools: {},
        },
        instructions: 'Messages arrive as <channel source="webhook" chat_id="...">. Reply with the reply tool, passing the chat_id from the tag.',
    },
)

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [{
        name: 'reply',
        description: 'Send a message back over this channel',
        inputSchema: {
            type: 'object',
            properties: {
                chat_id: {type: 'string', description: 'The conversation to reply in'},
                text: {type: 'string', description: 'The message to send'},
            },
            required: ['chat_id', 'text'],
        },
    }],
}))

mcp.setRequestHandler(CallToolRequestSchema, async req => {
    if (req.params.name === 'reply') {
        const {chat_id, text} = req.params.arguments as { chat_id: string; text: string }
        send(`Reply to ${chat_id}: ${text}`)
        return {content: [{type: 'text', text: 'sent'}]}
    }
    throw new Error(`unknown tool: ${req.params.name}`)
})

await mcp.connect(new StdioServerTransport())

let nextId = 1
Bun.serve({
    port: 8788,
    hostname: '127.0.0.1',
    idleTimeout: 0,  / don't close idle SSE streams
    async fetch(req) {
        const url = new URL(req.url)

        / GET /events: SSE stream so curl -N can watch Claude's replies live
        if (req.method === 'GET' && url.pathname === 'events') {
            const stream = new ReadableStream({
                start(ctrl) {
                    ctrl.enqueue(': connected\n\n')  / so curl shows something immediately
                    const emit = (chunk: string) => ctrl.enqueue(chunk)
                    listeners.add(emit)
                    req.signal.addEventListener('abort', () => listeners.delete(emit))
                },
            })
            return new Response(stream, {
                headers: {'Content-Type': 'textevent-stream', 'Cache-Control': 'no-cache'},
            })
        }

        / POST: forward to Claude as a channel event
        const body = await req.text()
        const chat_id = String(nextId++)
        await mcp.notification({
            method: 'notificationsclaude/channel',
            params: {
                content: body,
                meta: {chat_id, path: url.pathname, method: req.method},
            },
        })
        return new Response('ok')
    },
})
```

Der [fakechat-Server](https:/github.com/anthropics/claude-plugins-official/tree/main/external_plugins/fakechat) zeigt
ein vollständigeres Beispiel mit Dateianhängen und Nachrichtenbearbeitung.

## Eingehende Nachrichten gaten

Ein ungegatterter Channel ist ein Prompt-Injection-Vektor. Jeder, der Ihren Endpunkt erreichen kann, kann Text vor
Claude platzieren. Ein Channel, der auf einer Chat-Plattform oder einem öffentlichen Endpunkt lauscht, benötigt eine
echte Sender-Überprüfung, bevor er etwas emittiert.

Überprüfen Sie den Sender gegen eine Allowlist, bevor Sie `mcp.notification()` aufrufen. Dieses Beispiel löscht jede
Nachricht von einem Sender, der nicht in der Menge ist:

```ts  theme={null}
const allowed = new Set(loadAllowlist())  / from your access.json or equivalent

/ inside your message handler, before emitting:
if (!allowed.has(message.from.id)) {  / sender, not room
    return  / drop silently
}
await mcp.notification({...})
```

Gaten Sie auf der Identität des Senders, nicht auf der Chat- oder Raumidentität: `message.from.id` im Beispiel, nicht
`message.chat.id`. In Gruppenchats unterscheiden sich diese, und das Gaten auf dem Raum würde jedem in einer genehmigten
Gruppe erlauben, Nachrichten in die Sitzung einzuspritzen.

Die [Telegram](https:/github.com/anthropics/claude-plugins-official/tree/main/external_plugins/telegram)-
und [Discord](https:/github.com/anthropics/claude-plugins-official/tree/main/external_plugins/discord)-Channels gaten
auf die gleiche Weise auf einer Sender-Allowlist. Sie bootstrappen die Liste durch Pairing: Der Benutzer sendet dem Bot
eine Direktnachricht, der Bot antwortet mit einem Pairing-Code, der Benutzer genehmigt ihn in seiner Claude
Code-Sitzung, und seine Plattform-ID wird hinzugefügt. Siehe eine der Implementierungen für den vollständigen
Pairing-Flow. Der [iMessage](https:/github.com/anthropics/claude-plugins-official/tree/main/external_plugins/imessage)
-Channel verfolgt einen anderen Ansatz: Er erkennt die eigenen Adressen des Benutzers aus der Messages-Datenbank beim
Start und lässt sie automatisch durch, wobei andere Sender nach Handle hinzugefügt werden.

## Berechtigungsprompts weitergeben

<Note>
  Die Berechtigungsweitergabe erfordert Claude Code v2.1.81 oder später. Frühere Versionen ignorieren die `claudechannel/permission`-Funktionalität.
<Note>

Wenn Claude ein Tool aufruft, das Genehmigung benötigt, öffnet sich der lokale Terminal-Dialog und die Sitzung wartet.
Ein bidirektionaler Channel kann sich dafür entscheiden, denselben Prompt parallel zu empfangen und ihn an Sie auf einem
anderen Gerät weiterzuleiten. Beide bleiben aktiv: Sie können im Terminal oder auf Ihrem Telefon antworten, und Claude
Code wendet die Antwort an, die zuerst ankommt, und schließt die andere.

Die Weitergabe deckt Tool-Nutzungsgenehmigungen wie Bash, Write und Edit ab. Projekt-Vertrauen und
MCP-Server-Zustimmungsdialoge werden nicht weitergeleitet; diese erscheinen nur im lokalen Terminal.

### Wie die Weitergabe funktioniert

Wenn ein Berechtigungsprompt öffnet, hat die Weitergabeschleife vier Schritte:

1. Claude Code generiert eine kurze Request-ID und benachrichtigt Ihren Server
2. Ihr Server leitet den Prompt und die ID an Ihre Chat-App weiter
3. Der Remote-Benutzer antwortet mit ja oder nein und dieser ID
4. Ihr eingehender Handler analysiert die Antwort in ein Urteil, und Claude Code wendet es nur an, wenn die ID einer
   offenen Anfrage entspricht

Der lokale Terminal-Dialog bleibt während all dessen offen. Wenn jemand am Terminal antwortet, bevor das Remote-Urteil
ankommt, wird diese Antwort stattdessen angewendet und die ausstehende Remote-Anfrage wird gelöscht.

<img src="https:/mintlify.s3.us-west-1.amazonaws.com/claude-code/de/images/channel-permission-relay.svg" alt="Sequenzdiagramm: Claude Code sendet eine permission_request-Benachrichtigung an den Channel-Server, der Server formatiert und sendet den Prompt an die Chat-App, der Mensch antwortet mit einem Urteil, und der Server analysiert diese Antwort in eine Berechtigungsbenachrichtigung zurück an Claude Code" />

### Berechtigungsanfrage-Felder

Die ausgehende Benachrichtigung von Claude Code ist `notificationsclaude/channel/permission_request`. Wie
die [Channel-Benachrichtigung](#notification-format) ist der Transport Standard-MCP, aber die Methode und das Schema
sind Claude Code-Erweiterungen. Das `params`-Objekt hat vier String-Felder, die Ihr Server in den ausgehenden Prompt
formatiert:

| Feld            | Beschreibung                                                                                                                                                                                                                                                                                                                                                                                                                                      |
|-----------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `request_id`    | Fünf Kleinbuchstaben aus `a`-`z` ohne `l`, damit es nie als `1` oder `I` gelesen wird, wenn es auf einem Telefon eingegeben wird. Fügen Sie es in Ihren ausgehenden Prompt ein, damit es in der Antwort wiederholt werden kann. Claude Code akzeptiert nur ein Urteil, das eine ID trägt, die es ausgestellt hat. Der lokale Terminal-Dialog zeigt diese ID nicht an, daher ist Ihr ausgehender Handler die einzige Möglichkeit, sie zu erfahren. |
| `tool_name`     | Name des Tools, das Claude verwenden möchte, zum Beispiel `Bash` oder `Write`.                                                                                                                                                                                                                                                                                                                                                                    |
| `description`   | Menschenlesbarer Zusammenfassung dessen, was dieser spezifische Tool-Aufruf tut, derselbe Text, den der lokale Terminal-Dialog zeigt. Für einen Bash-Aufruf ist dies Claudes Beschreibung des Befehls oder der Befehl selbst, wenn keine gegeben wurde.                                                                                                                                                                                           |
| `input_preview` | Die Argumente des Tools als JSON-Zeichenkette, gekürzt auf 200 Zeichen. Für Bash ist dies der Befehl; für Write ist es der Dateipfad und ein Präfix des Inhalts. Lassen Sie es aus Ihrem Prompt weg, wenn Sie nur Platz für eine einzeilige Nachricht haben. Ihr Server entscheidet, was angezeigt wird.                                                                                                                                          |

Das Urteil, das Ihr Server zurücksendet, ist `notificationsclaude/channel/permission` mit zwei Feldern: `request_id`,
das die obige ID wiederholt, und `behavior`, das auf `'allow'` oder `'deny'` gesetzt ist. Allow lässt den Tool-Aufruf
fortfahren; deny lehnt ihn ab, dasselbe wie das Antworten mit Nein im lokalen Dialog. Weder das Urteil beeinflusst
zukünftige Aufrufe.

### Weitergabe zu einer Chat-Brücke hinzufügen

Das Hinzufügen von Berechtigungsweitergabe zu einem bidirektionalen Channel erfordert drei Komponenten:

1. Ein `claudechannel/permission: {}`-Eintrag unter `experimental`-Funktionalitäten in Ihrem `Server`-Constructor,
   damit Claude Code weiß, dass Prompts weitergeleitet werden sollen
2. Ein Benachrichtigungshandler für `notificationsclaude/channel/permission_request`, der den Prompt formatiert und ihn
   über Ihre Plattform-API sendet
3. Eine Überprüfung in Ihrem eingehenden Nachrichtenhandler, die `yes <id>` oder `no <id>` erkennt und stattdessen eine
   `notificationsclaude/channel/permission`-Urteilsbenachrichtigung emittiert, anstatt den Text an Claude
   weiterzuleiten

Deklarieren Sie die Funktionalität nur, wenn Ihr Channel [den Sender authentifiziert](#gate-inbound-messages), da jeder,
der über Ihren Channel antworten kann, Tool-Nutzung in Ihrer Sitzung genehmigen oder ablehnen kann.

Um diese zu einer bidirektionalen Chat-Brücke wie der in [Antwort-Tool bereitstellen](#expose-a-reply-tool)
zusammengestellten hinzuzufügen:

<Steps>
  <Step title="Deklarieren Sie die Berechtigungsfunktionalität">
    In Ihrem `Server`-Constructor fügen Sie `claudechannel/permission: {}` neben `claude/channel` unter `experimental` hinzu:

    ```ts  theme={null}
    capabilities: {
      experimental: {
        'claudechannel': {},
        'claudechannel/permission': {},  // opt in to permission relay
      },
      tools: {},
    },
    ```

  <Step>

  <Step title="Behandeln Sie die eingehende Anfrage">
    Registrieren Sie einen Benachrichtigungshandler zwischen Ihrem `Server`-Constructor und `mcp.connect()`. Claude Code ruft ihn mit den [vier Anfrage-Feldern](#permission-request-fields) auf, wenn ein Berechtigungsdialog öffnet. Ihr Handler formatiert den Prompt für Ihre Plattform und enthält Anweisungen zum Antworten mit der ID:

    ```ts  theme={null}
    import { z } from 'zod'

    / setNotificationHandler leitet nach z.literal auf dem method-Feld weiter,
    / daher ist dieses Schema sowohl der Validator als auch der Dispatch-Schlüssel
    const PermissionRequestSchema = z.object({
      method: z.literal('notificationsclaude/channel/permission_request'),
      params: z.object({
        request_id: z.string(),     / five lowercase letters, include verbatim in your prompt
        tool_name: z.string(),      / e.g. "Bash", "Write"
        description: z.string(),    / human-readable summary of this call
        input_preview: z.string(),  / tool args as JSON, truncated to ~200 chars
      }),
    })

    mcp.setNotificationHandler(PermissionRequestSchema, async ({ params }) => {
      / send() ist Ihre Ausgangsrichtung: POST an Ihre Chat-Plattform, oder für lokales
      / Testen die SSE-Übertragung, die im vollständigen Beispiel unten gezeigt wird.
      send(
        `Claude wants to run ${params.tool_name}: ${params.description}\n\n` +
        / die ID in der Anweisung ist das, was Ihr eingehender Handler in Schritt 3 analysiert
        `Reply "yes ${params.request_id}" or "no ${params.request_id}"`,
      )
    })
    ```

  <Step>

  <Step title="Fangen Sie das Urteil in Ihrem eingehenden Handler ab">
    Ihr eingehender Handler ist die Schleife oder der Callback, der Nachrichten von Ihrer Plattform empfängt: derselbe Ort, an dem Sie [auf Sender gaten](#gate-inbound-messages) und `notificationsclaude/channel` emittieren, um Chat an Claude weiterzuleiten. Fügen Sie eine Überprüfung vor dem Chat-Weiterleitungsaufruf hinzu, die das Urteilsformat erkennt und stattdessen die Berechtigungsbenachrichtigung emittiert.

    Der Regex entspricht dem ID-Format, das Claude Code generiert: fünf Buchstaben, nie `l`. Das `i`-Flag toleriert Telefon-Autokorrektur, die die Antwort großschreibt; kleinschreiben Sie die erfasste ID, bevor Sie sie zurücksendet.

    ```ts  theme={null}
    / matches "y abcde", "yes abcde", "n abcde", "no abcde"
    / [a-km-z] is the ID alphabet Claude Code uses (lowercase, skips 'l')
    / /i tolerates phone autocorrect; lowercase the capture before sending
    const PERMISSION_REPLY_RE = ^\s*(y|yes|n|no)\s+([a-km-z]{5})\s*$/i

    async function onInbound(message: PlatformMessage) {
      if (!allowed.has(message.from.id)) return  / gate on sender first

      const m = PERMISSION_REPLY_RE.exec(message.text)
      if (m) {
        / m[1] is the verdict word, m[2] is the request ID
        / emit the verdict notification back to Claude Code instead of chat
        await mcp.notification({
          method: 'notificationsclaude/channel/permission',
          params: {
            request_id: m[2].toLowerCase(),  / normalize in case of autocorrect caps
            behavior: m[1].toLowerCase().startsWith('y') ? 'allow' : 'deny',
          },
        })
        return  / handled as verdict, don't also forward as chat
      }

      / didn't match verdict format: fall through to the normal chat path
      await mcp.notification({
        method: 'notificationsclaude/channel',
        params: { content: message.text, meta: { chat_id: String(message.chat.id) } },
      })
    }
    ```

  <Step>
<Steps>

Claude Code hält auch den lokalen Terminal-Dialog offen, daher können Sie an beiden Orten antworten, und die erste
Antwort, die ankommt, wird angewendet. Eine Remote-Antwort, die nicht genau dem erwarteten Format entspricht, schlägt
auf eine von zwei Arten fehl, und in beiden Fällen bleibt der Dialog offen:

* **Anderes Format**: der Regex Ihres eingehenden Handlers schlägt fehl zu entsprechen, daher fällt Text wie
  `approve it` oder `yes` ohne ID als normale Nachricht an Claude durch.
* **Richtiges Format, falsche ID**: Ihr Server emittiert ein Urteil, aber Claude Code findet keine offene Anfrage mit
  dieser ID und löscht es stillschweigend.

### Vollständiges Beispiel

Die zusammengestellte `webhook.ts` unten kombiniert alle drei Erweiterungen von dieser Seite: das Antwort-Tool,
Sender-Gating und Berechtigungsweitergabe. Wenn Sie hier anfangen, benötigen Sie auch die [Projekt-Setup und
`.mcp.json`-Eintrag](#example-build-a-webhook-receiver) aus der anfänglichen Anleitung.

Um beide Richtungen von curl aus testbar zu machen, dient der HTTP-Listener zwei Pfaden:

* **`GET events`**: hält einen SSE-Stream offen und pusht jede ausgehende Nachricht als `data:`-Zeile, daher kann
  `curl -N` Claudes Antworten und Berechtigungsprompts live beobachten, wenn sie ankommen.
* **`POST `**: die eingehende Seite, derselbe Handler wie zuvor, jetzt mit der Urteilsformat-Überprüfung vor dem
  Chat-Weiterleitungszweig eingefügt.

```ts title="Full webhook.ts with permission relay' expandable theme={null}
#!usr/bin/env bun
import {Server} from '@modelcontextprotocolsdk/server/index.js'
import {StdioServerTransport} from '@modelcontextprotocolsdk/server/stdio.js'
import {ListToolsRequestSchema, CallToolRequestSchema} from '@modelcontextprotocolsdk/types.js'
import {z} from 'zod'

/ --- Ausgangsrichtung: schreiben Sie an alle curl -N-Listener auf /events ---
/ Eine echte Brücke würde stattdessen an Ihre Chat-Plattform POSTen.
const listeners = new Set<(chunk: string) => void>()

function send(text: string) {
    const chunk = text.split('\n').map(l => `data: ${l}\n`).join('') + '\n'
    for (const emit of listeners) emit(chunk)
}

/ Sender-Allowlist. Für die lokale Anleitung vertrauen wir dem einzelnen X-Sender
/ Header-Wert "dev"; eine echte Brücke würde die Plattform-Benutzer-ID überprüfen.
const allowed = new Set(['dev'])

const mcp = new Server(
    {name: 'webhook', version: '0.0.1'},
    {
        capabilities: {
            experimental: {
                'claudechannel': {},
                'claudechannel/permission': {},  // opt in to permission relay
            },
            tools: {},
        },
        instructions:
            'Messages arrive as <channel source="webhook" chat_id="...">. ' +
            'Reply with the reply tool, passing the chat_id from the tag.',
    },
)

/ --- reply tool: Claude calls this to send a message back ---
mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [{
        name: 'reply',
        description: 'Send a message back over this channel',
        inputSchema: {
            type: 'object',
            properties: {
                chat_id: {type: 'string', description: 'The conversation to reply in'},
                text: {type: 'string', description: 'The message to send'},
            },
            required: ['chat_id', 'text'],
        },
    }],
}))

mcp.setRequestHandler(CallToolRequestSchema, async req => {
    if (req.params.name === 'reply') {
        const {chat_id, text} = req.params.arguments as { chat_id: string; text: string }
        send(`Reply to ${chat_id}: ${text}`)
        return {content: [{type: 'text', text: 'sent'}]}
    }
    throw new Error(`unknown tool: ${req.params.name}`)
})

/ --- permission relay: Claude Code (not Claude) calls this when a dialog opens
const PermissionRequestSchema = z.object({
    method: z.literal('notificationsclaude/channel/permission_request'),
    params: z.object({
        request_id: z.string(),
        tool_name: z.string(),
        description: z.string(),
        input_preview: z.string(),
    }),
})

mcp.setNotificationHandler(PermissionRequestSchema, async ({params}) => {
    send(
        `Claude wants to run ${params.tool_name}: ${params.description}\n\n` +
        `Reply "yes ${params.request_id}" or "no ${params.request_id}"`,
    )
})

await mcp.connect(new StdioServerTransport())

/ --- HTTP on :8788: GET /events streams outbound, POST routes inbound ---
const PERMISSION_REPLY_RE = ^\s*(y|yes|n|no)\s+([a-km-z]{5})\s*$/i
let nextId = 1

Bun.serve({
    port: 8788,
    hostname: '127.0.0.1',
    idleTimeout: 0,  / don't close idle SSE streams
    async fetch(req) {
        const url = new URL(req.url)

        / GET /events: SSE stream so curl -N can watch replies and prompts live
        if (req.method === 'GET' && url.pathname === 'events') {
            const stream = new ReadableStream({
                start(ctrl) {
                    ctrl.enqueue(': connected\n\n')  / so curl shows something immediately
                    const emit = (chunk: string) => ctrl.enqueue(chunk)
                    listeners.add(emit)
                    req.signal.addEventListener('abort', () => listeners.delete(emit))
                },
            })
            return new Response(stream, {
                headers: {'Content-Type': 'textevent-stream', 'Cache-Control': 'no-cache'},
            })
        }

        / everything else is inbound: gate on sender first
        const body = await req.text()
        const sender = req.headers.get('X-Sender') ?? ''
        if (!allowed.has(sender)) return new Response('forbidden', {status: 403})

        / check for verdict format before treating as chat
        const m = PERMISSION_REPLY_RE.exec(body)
        if (m) {
            await mcp.notification({
                method: 'notificationsclaude/channel/permission',
                params: {
                    request_id: m[2].toLowerCase(),
                    behavior: m[1].toLowerCase().startsWith('y') ? 'allow' : 'deny',
                },
            })
            return new Response('verdict recorded')
        }

        / normal chat: forward to Claude as a channel event
        const chat_id = String(nextId++)
        await mcp.notification({
            method: 'notificationsclaude/channel',
            params: {content: body, meta: {chat_id, path: url.pathname}},
        })
        return new Response('ok')
    },
})
```

Testen Sie den Urteilspfad in drei Terminals. Das erste ist Ihre Claude Code-Sitzung, gestartet mit
dem [Development-Flag](#test-during-the-research-preview), damit es `webhook.ts` startet:

```bash  theme={null}
claude --dangerously-load-development-channels server:webhook
```

Im zweiten streamen Sie die ausgehende Seite, damit Sie Claudes Antworten und alle Berechtigungsprompts live sehen
können, wenn sie ankommen:

```bash  theme={null}
curl -N localhost:8788events
```

Im dritten senden Sie eine Nachricht, die Claude veranlasst, einen Befehl auszuführen:

```bash  theme={null}
curl -d "list the files in this directory" -H "X-Sender: dev" localhost:8788
```

Der lokale Berechtigungsdialog öffnet sich in Ihrem Claude Code-Terminal. Einen Moment später erscheint der Prompt im
`events`-Stream, einschließlich der fünf-buchstabigen ID. Genehmigen Sie ihn von der Remote-Seite:

```bash  theme={null}
curl -d "yes <id>" -H "X-Sender: dev" localhost:8788
```

Der lokale Dialog schließt sich und das Tool läuft. Claudes Antwort kommt über das `reply`-Tool zurück und landet auch
im Stream.

Die drei Channel-spezifischen Teile in dieser Datei:

* **Funktionalitäten** im `Server`-Constructor: `claudechannel` registriert den Benachrichtigungslistener,
  `claudechannel/permission` entscheidet sich für Berechtigungsweitergabe, `tools` lässt Claude das Antwort-Tool
  entdecken.
* **Ausgehende Pfade**: der `reply`-Tool-Handler ist das, was Claude für Gesprächsantworten aufruft; der
  `PermissionRequestSchema`-Benachrichtigungshandler ist das, was Claude Code aufruft, wenn ein Berechtigungsdialog
  öffnet. Beide rufen `send()` auf, um über `events` zu übertragen, aber sie werden von verschiedenen Teilen des
  Systems ausgelöst.
* **HTTP-Handler**: `GET events` hält einen SSE-Stream offen, damit curl Ausgangsrichtung live beobachten kann; `POST`
  ist eingehend, gatet auf dem `X-Sender`-Header. Ein `yes <id>`- oder `no <id>`-Body geht an Claude Code als
  Urteilsbenachrichtigung und erreicht nie Claude; alles andere wird an Claude als Channel-Ereignis weitergeleitet.

## Als Plugin verpacken

Um Ihren Channel installierbar und teilbar zu machen, wickeln Sie ihn in ein [Plugin](de/plugins) ein und
veröffentlichen Sie ihn auf einem [Marketplace](de/plugin-marketplaces). Benutzer installieren ihn mit
`plugin install`, dann aktivieren ihn pro Sitzung mit `--channels plugin:<name>@<marketplace>`.

Ein Channel, der auf Ihrem eigenen Marketplace veröffentlicht wird, benötigt immer noch
`--dangerously-load-development-channels` zum Ausführen, da er nicht auf
der [genehmigten Allowlist](de/channels#supported-channels) ist. Um ihn hinzufügen zu
lassen, [reichen Sie ihn beim offiziellen Marketplace ein](de/plugins#submit-your-plugin-to-the-official-marketplace).
Channel-Plugins durchlaufen eine Sicherheitsüberprüfung, bevor sie genehmigt werden. Bei Team- und Enterprise-Plänen
kann ein Admin stattdessen Ihr Plugin in die [
`allowedChannelPlugins`](de/channels#restrict-which-channel-plugins-can-run)-Liste der Organisation aufnehmen, die die
Standard-Anthropic-Allowlist ersetzt.

## Siehe auch

* [Channels](de/channels) zum Installieren und Verwenden von Telegram, Discord, iMessage oder der fakechat-Demo und zum
  Aktivieren von Channels für eine Team- oder Enterprise-Organisation
* [Arbeitende Channel-Implementierungen](https:/github.com/anthropics/claude-plugins-official/tree/main/external_plugins)
  für vollständigen Server-Code mit Pairing-Flows, Antwort-Tools und Dateianhängen
* [MCP](de/mcp) für das zugrunde liegende Protokoll, das Channel-Server implementieren
* [Plugins](de/plugins) zum Verpacken Ihres Channels, damit Benutzer ihn mit `/plugin install` installieren können
