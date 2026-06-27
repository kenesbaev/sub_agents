# Kaliya Core For Agents

This folder is a browser/project-safe starting copy of the useful Kaliya ideas for the
new five-agent interface.

Copied/adapted:

- Kaliya system prompt style.
- Short in-session chat memory idea.
- Provider modes: `codex-cli` and `openai-api`.
- Secret redaction rules.
- Workspace safety rules.

Excluded on purpose:

- SQLite runtime data.
- Markdown memory.
- Knowledge Graph memory.
- Vector memory.
- `data/`, `logs/`, `.venv/`, caches, media, and private runtime artifacts.

The current UI uses `agents-kaliya-core.js` in the browser. This folder is here so the
backend version can be wired in later without dragging memory into the project.
