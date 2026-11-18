# ADR 0011 – Assistant plugins: a local LLM (Ollama) and Claude as agents in CAD

Status: **proposed** 2026-11-18 (draft; answers of the maintainer to the first three questions at
the end, the rest open)

**Context.** The maintainer wants an assistant inside Raytatouille Fusion: a chat in which a
language model is given tasks *within the application* – inspect and evaluate the data of the
document and of the connected plugins (the loaded Raytatouille system, a FourierGrating
configuration, the node workflow, results), create and change structures (objects, workflow
blocks, parameters), start and stop computations. It has to know the application well. Two
plugins are wanted: first **Ollama Agent** (a local LLM through Ollama), then **Claude Agent**
(the Anthropic API with the user's API key).

What exists today (ADR 0008, ADR 0010, [plugin-api.md](../plugin-api.md)):
- one Python process per plugin, JSON lines over a local socket, a `hello` with actions,
  parameters and block types;
- an action runs as a **job** with progress, Cancel and one undo step; **only one job at a time**
  in the whole application (`MainWindow::runPluginAction`: “A plugin job is still running”);
- the context `ctx` reaches the model (`model.*`), the parameters (`params.set`, `params.of`
  read-only), the workflow (`workflow.get/set`) and the results (`results.*`, write only);
- plugins talk to each other only through CAD and only for blocks of the workflow
  (`BlockRouter`: `workflow.blocks`, `workflow.evaluate`).

What an assistant needs and does not find:
1. **A conversation is not a job.** A chat that runs as an action would block every other
   plugin for as long as it lasts.
2. **No general calls between plugins.** The assistant must list and call the abilities of all
   plugins – not only evaluate blocks.
3. **The state inside a plugin is invisible.** Which system the Raytracer has loaded, which
   configuration FourierGrating holds: nothing answers such questions except an action that
   writes into the log.
4. **No place for a conversation in the UI.** Plugins have the parameter panel and results, no
   text dialogue.

## Decision

**D1 – Three layers.**

```
 Assistant dock (C++)  ⇄  agent core (Python, nfcad_agent)  ⇄  backend: Ollama | Anthropic
                                   │
                         AgentRouter in CAD (C++)
     ┌──────────────────┬──────────┴──────────┬───────────────────────┐
  CAD core tools      Raytracer           FourierGrating          Workflow, …
  (model, workflow,   actions + queries   actions + queries       actions + queries
   results, params)
```

- **Tool layer** in CAD and `nfcad` – independent of any language model, testable without one
  (D3, D4).
- **Agent core** `nfcad_agent`, a Python package shipped next to `nfcad`: the conversation loop,
  tool catalogue and calls, situation report, knowledge (D8), memory, code execution (D6), budgets
  and log. It knows no vendor.
- **Two plugins** on the same core (answer 3): `ollama-agent` and `claude-agent`, each a thin
  backend (a class with `chat(messages, tools) -> reply` and the plugin's settings), each with its
  own manifest, release and signature (ADR 0009).

The format of tools is that of MCP (name, description, `inputSchema` as JSON Schema, a result of
text and structured content), so that Ollama's and Anthropic's tool calling take it unchanged and
an MCP bridge stays possible later (A7).

**D2 – Service plugins.** A manifest with `"service": true` marks a plugin that lives beside the
jobs: CAD starts it when the *Assistant* dock is opened (or with the document, a setting) and
sends it conversation messages, not `run`. A service plugin can still have actions (e.g. *Set API
key*), which run as jobs as usual. The rule *one job at a time* stays: when the agent starts an
action, it is *the* job – shown in the status bar with progress and Cancel like a click of the
user; while another job runs, the call waits up to a budget and then reports `busy` to the model.
Queries (D3 b) and core tools are not jobs and run any time.

**D3 – Where the tools come from.**

*a) Actions become tools automatically.* Every `@action` of every plugin is a tool
`<plugin>.<action>` (`raytracer.trace_rays`) with its label and description. Its input schema is
the plugin's parameter schema turned into JSON Schema (table below), all fields optional (missing
ones keep the panel's value), plus `target` for block actions (`{"block", "scope"}`). Calling it:
CAD writes the given values into the plugin's panel (visible, saved in the document, as
`ctx.set_params`), then runs the action as a job; the tool result is the job's outcome (ok,
cancelled, user error, message), the result sets it created (ids and names) and the last lines of
its log. New optional arguments of `@action`: `agent=False` hides an action from the assistant;
`agent_description="…"` replaces the label for the model.

| `nfcad.Param` | JSON Schema |
|---|---|
| number, integer (min, max, unit) | `number` / `integer` with `minimum`, `maximum`; the unit in `description` |
| boolean | `boolean` |
| choice | `string` with `enum` |
| text, file | `string` (file: an absolute path) |
| files, numbers | `array` of `string` / `number` |
| point | `array` of three `number` |
| entity (kinds, multiple) | `integer` or `array` of `integer` (entity ids); the kinds in `description` |
| list (of), table (columns) | `array` of `object` with the entry's / column's schema |
| json | `object` (free) |

*b) Queries – new in `nfcad`.* A plugin describes its state with read-only functions:

```python
from nfcad import Plugin, action, query

class RaytracerPlugin(Plugin):
    @query("The loaded Raytatouille system: surfaces, materials, fields, wavelengths, detectors")
    def system_summary(self, ctx, detail: str = "short") -> dict:
        ...
```

The schema comes from the type hints (simple types) or from `params={...}` with `nfcad.Param`
as for actions. A query gets a reduced context (model and workflow read access, no results, no
changes), runs in a thread of its own (like `evaluate_block`, not the action thread), has a
timeout (default 10 s) and returns JSON. Queries are sent with the `hello` (`"queries": [...]`).
Each plugin of the repository gets its first queries with A3 (Raytracer: system, surfaces,
last trace; FourierGrating: configuration, last solve; Path Tracer: materials and sources;
Workflow: plan and cache state).

*c) CAD core tools – in C++.*

| Tool | Effect |
|---|---|
| `doc.info` | file, unit, layers, plugins (id, version, running), the running job |
| `selection.get` / `selection.set` | selected entity ids |
| `model.tree` | groups and entities as a compact tree (id, name, kind, layer, attributes) – no geometry |
| `model.entities` | as `ctx.entities`, geometry only on request (`geometry: true`) |
| `model.add`, `model.replace`, `model.remove`, `model.set_attribute`, `model.add_group` | as in `ctx` |
| `params.get` / `params.set` | the panel values of **any** plugin (today `params.of` only reads another plugin's values and `params.set` only writes the caller's own) |
| `workflow.summary` | blocks (id, type, provider, main parameters), links, branches, diagnostics – compact |
| `workflow.get` | the full `rtt-fusion-graph` |
| `workflow.add_block`, `remove_block`, `connect`, `disconnect`, `set_block_params`, `set_link`, `group`, `add_branch` | small edits of the graph; after each edit CAD has the engine check it and returns the diagnostics (codes of `rtt_fusion.graph.validate`), so the model can repair its edit |
| `results.list` | result sets with their items (name, kind, size, key, stamp) |
| `results.get` | an item compact: shape, unit, min / max / mean, peak and its position, power; a curve or image down-sampled to at most N points; tables up to N rows |
| `jobs.status`, `jobs.cancel` | the running job (plugin, action, progress) |
| `log.tail` | the last lines of a plugin's log |

The model never edits the whole workflow JSON at once; it uses the small edits. Large data never
goes into a prompt (D5).

**D4 – Protocol (API version 1, compatible additions).**

| Direction | Message | Content |
|---|---|---|
| plugin → CAD | request `agent.tools` | all tools: core, actions and queries of all plugins (CAD starts plugins that are not running, as for `workflow.blocks`); `{name, description, inputSchema, effect, plugin}` each |
| plugin → CAD | request `agent.call` | `{tool, args}` → `{ok, content, structured, job?}`; a core tool is answered by CAD, a query is sent to its plugin, an action becomes a job |
| CAD → plugin | `query` / plugin → CAD `queried` | `{rid, name, args}` / `{rid, response}` |
| CAD → service plugin | `chat.user`, `chat.stop`, `chat.reset` | the user's text and the conversation id; Stop ends the turn and cancels a job the agent started |
| service plugin → CAD | notify `chat.delta`, `chat.tool`, `chat.done`, `chat.error` | streamed text; a tool call with state (running, ok, error), arguments and a short result; end of the turn with token counts and costs |
| CAD → plugin, `hello` | `"queries"`, `"service"` | |

Every tool carries an **effect**: `read`, `change` (model, workflow, parameters – undoable),
`compute` (a job), `code` (D6), `external` (writes outside the document: export, save a file).
Core tools declare their effect in C++; actions are `compute`, unless they say otherwise
(`@action(effect="change")`); queries are `read`.

**D5 – What reaches the model.** Tool results are short text plus structured JSON, at most a few
thousand characters (a setting per backend); longer ones are cut with a note how to page or
narrow. Arrays go to the model only as statistics or down-sampled; the full data stay where they
are and reach the code tool (D6) as NumPy arrays. A local model has a small context – the budget
is the scarce resource, the tools are designed for it.

**D6 – Running own code (answer 2).** Tool `python.run {code}`: the agent plugin keeps a Python
worker process per conversation (a kernel: variables survive between calls) with NumPy and an
object `app` that calls the same tools as the model (`app.call("raytracer.trace_rays", rays=1e5)`,
`app.result_array(item)` → NumPy from the mapped file). So the model can evaluate results
(fits, statistics, comparisons), loop over runs and write small analyses. Rules:
- output (stdout, the repr of the last expression, figures as images in the *Image* dock through
  `app.image`) is cut like any tool result;
- a timeout per call (default 120 s) and Stop end the worker; a new one starts on the next call;
- the working folder is a per-conversation folder in the user's data directory;
- the worker has **the user's rights** – it is not a sandbox (as signing is none, ADR 0008); the
  conversation log keeps every piece of code that ran.

**D7 – Modes and safeguards (answer 1).** Two modes, chosen in the dock and saved per document:
- **Automatic** – the assistant calls every tool without asking. This is the working mode.
- **Ask** – calls with effect `change`, `compute`, `code` and `external` wait for *Allow* /
  *Allow always in this conversation* / *Deny* in the dock.

In both modes:
- **one undo step per turn**: everything the agent changed in the model, the workflow and the
  parameters during one answer is undone with one *Edit → Undo* (“Undo assistant: …”); jobs
  started by the agent belong to that step as they belong to their own today;
- **budgets** per turn: tool calls (default 40), wall time (default 30 min), tokens; reaching one
  ends the turn with a report;
- **Stop** in the dock ends the turn at once, cancels the agent's job and ends a running
  `python.run`;
- every tool call appears as a card in the dock (tool, arguments, result, duration), expandable;
- the conversation (messages, tool calls, code) is logged to the user's data directory;
- proposal: `external` calls that would **overwrite an existing file** outside the conversation's
  folder ask also in *Automatic* – the one step that undo cannot take back (open question 4).

**D8 – Knowledge.** No fine-tuning; knowledge in layers, loaded when needed:
1. **System prompt** (in `nfcad_agent`, short): role, conventions (Raytatouille's: mm, nm,
   signs, coordinate frames), how to use the tools (look first, small edits, check the
   diagnostics, results as statistics), the safeguards.
2. **Situation per turn**, made by the core from `doc.info`, `workflow.summary`, the selection
   and the running job – a few hundred tokens.
3. **Plugin guides:** an `agent.md` next to a plugin's `plugin.json` (signed with it): what the
   plugin is for, its actions and queries in context, typical sequences, pitfalls. Tool
   `guide {plugin}` loads it; the catalogue only names that a guide exists.
4. **Documentation search:** an index over `docs/` (user guide, manual, plugin API, ADRs), the
   plugin READMEs and, where installed, RTT-Fusion's documentation; embedded locally with an
   Ollama embedding model, kept in the user's data directory, rebuilt when a plugin or the
   application changes. Tool `docs.search {query}` returns short passages with their source. The
   Claude plugin uses the same local index; only the passages found go out.
5. **Memory:** notes per document in the `.rttf` (`"assistant": {"notes": [...]}` – the file
   holds everything, compatible both ways) and per user in the data directory; tools
   `memory.read`, `memory.write`. The model writes what the user decided or wants remembered;
   the user sees and edits the notes in the dock.

The tool catalogue itself is never stale: it comes from the plugins' `hello` messages.

**D9 – Backends.**
- **Ollama Agent:** settings (plugin parameters, not secret): server URL (default
  `http://localhost:11434`, a GPU machine in the network is allowed), model (from `/api/tags`,
  only models with tool support), context length (`num_ctx`, set explicitly – Ollama's default
  is too small for tools), temperature, embedding model for D8. Ollama's `/api/chat` with
  `tools`; streaming is used for text only if tool calls arrive reliably with it (tested in
  A2, otherwise turns with tools run without streaming).
- **Claude Agent:** Anthropic Messages API with tool use; model selectable; the API key is
  **not** a parameter (parameters are saved in the document): the action *Set API key* stores it
  in the system's key store with Python `keyring` under the fixed names **service
  `raytatouille-fusion`, user `anthropic-api-key`** (`keyring.get_password("raytatouille-fusion",
  "anthropic-api-key")`), so that a key stored by hand beforehand
  (`python -m keyring set raytatouille-fusion anthropic-api-key`) is found; the variable
  `ANTHROPIC_API_KEY` is read as fall-back. `keyring` is in the plugin's `requires`; when no
  key store is available (`keyring` reports a fail or plain-text backend), the plugin says so
  instead of storing the key in plain text. Prompt caching for system prompt and tool catalogue. Before the first message in a
  document the dock asks once whether data of this document may be sent to Anthropic (saved in
  the document). Tokens and costs per turn in the dock.

**D10 – Trust.** Both plugins are signed like every plugin (ADR 0009). The agent reaches other
plugins only through CAD (as in ADR 0010 D3). Everything a tool returns – names in a loaded
system, text in a configuration, log lines – is data, not instructions; the system prompt says
so, and D7's safeguards hold whatever the model was led to do.

## Stages (proposal)

Test first: a **scripted backend** (`nfcad_agent.testing.ScriptedBackend`: a list of tool calls
and texts) drives the loop deterministically in the tests; real models are measured in A6.

| Stage | Content | Acceptance |
|---|---|---|
| **A1 Tool layer** | `@query`, actions as tools (schema mapping), `effect`, `AgentRouter` with `agent.tools` / `agent.call`, core tools of D3 c, `query` messages | with the test plugins: the catalogue lists core tools, actions and queries of two plugins; a scripted sequence (read the tree, set a parameter, run an action, read the result) gives the expected calls and one undo step; a query that hangs fails after its timeout, the plugin keeps running |
| **A2 Dock and Ollama, read only** | *Assistant* dock, service plugins, `nfcad_agent` loop, situation report, budgets, Stop, log; plugin `ollama-agent` with read tools only | scripted: Stop ends a turn within 1 s; with a local model: questions about the Linnik example (blocks, wavelengths, detectors) answered from the tools |
| **A3 Changing and computing** | change, compute and external tools, modes (D7), one undo step per turn, waiting for a busy job; first queries of Raytracer, FourierGrating, Path Tracer, Workflow | one undo removes all changes of a turn; Stop cancels the agent's job within the 5 s of ADR 0008; *Ask* blocks every non-read call until allowed |
| **A4 Code** | `python.run` with a kernel per conversation, `app` object, arrays from results, timeouts | a scripted fit of a traced spot gives the value of a direct NumPy computation; a call over its timeout ends the worker, the next call works |
| **A5 Knowledge** | system prompt, `agent.md` for each plugin of the repository, `guide`, documentation index and `docs.search`, memory in the `.rttf` | `.rttf` with notes opens in an older version (notes ignored, nothing lost); search finds the passage for ten known questions |
| **A6 Evaluation** | 20–30 tasks with expected outcome (e.g. “load `singlet_optim.rtt.json`, trace 10⁵ rays, report the RMS spot radius”; “put a FourierGrating grating in place of the sample mirror of the Linnik and run it”), run against each configured model; report per model: solved, tool calls, time | the report exists for at least two local models; the tasks are part of the repository |
| **A7 Claude Agent** | plugin `claude-agent` (D9), key store, consent per document, caching, costs | the A6 tasks with Claude; no key in any file of the document or the settings |
| **A8 MCP bridge (optional)** | the tool layer served as an MCP server on the loopback interface with a token, so that Claude Desktop or Claude Code can drive the application | an MCP client lists and calls the tools |

## Consequences

The application gets an assistant that works with every plugin – present and future ones –
without each plugin writing anything for it: actions are tools at once, and a plugin adds
queries and a guide when it wants to be understood better. Local and cloud models share all of
it; the choice is a backend. Costs: a second router in CAD, queries to maintain per plugin,
guides to keep current with the plugins, a dock in C++; the assistant acts with the user's
rights (code included), so the safeguards are undo, budgets, Stop and the log – not a sandbox.
With Claude, data of the document leave the machine (consent per document).

## Answers of the maintainer (2026-11-18)

1. The assistant has an **automatic mode**: it acts without asking for each step.
2. It **may run its own code** (D6).
3. **Two plugins** (`ollama-agent`, `claude-agent`) on one shared core package.

## Open questions

4. Should *Automatic* ask before overwriting an existing file outside the conversation's folder
   (D7, last point), or never ask?
5. Where should conversations live: only in the user's data directory (proposal), or also in the
   `.rttf`?
6. Which documentation goes into the index besides this repository's: RTT-Fusion's `docs/`, the
   kernels' READMEs, the German manual?
7. Start of the service plugin: when the dock is opened (proposal) or with every document?
8. Which local models are the reference for A6 (on a 24 GB GPU, e.g. a Qwen 3.x model of 27–32 B
   parameters in Q4 and `gpt-oss:20b`)?
