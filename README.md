# Repository-Aware AI Coding Assistant

A repository-aware AI coding assistant that combines semantic,
keyword, and graph-based retrieval to provide relevant repository
context to a coding LLM.

## Current Status

The backend accepts a GitHub repository URL from the frontend, stages its clone and
isolated semantic/keyword and graph indexes, and switches the active workspace only
after both indexes validate. The previous repository remains active if staging fails.
Editor saves update the local clone only; CocoIndex refreshes the indexes in the
background.

## Run locally

In PowerShell, from the repository root:

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run uvicorn src.main:app --reload
```

In a second terminal:

```powershell
Set-Location frontend
npm run dev
```

Open the frontend URL printed by Vite and paste a GitHub repository URL. The Vite
development server proxies `/api` requests to `http://127.0.0.1:8000`, including when
Vite selects a different port because its default is occupied. Set
`RACA_API_TARGET` before `npm run dev` to use a different backend address. For a
separately hosted frontend, set `VITE_API_BASE_URL` to the backend URL when building
and configure the backend CORS allowlist for that frontend origin.

Replacing a
repository does not clear the active index first: the new clone and indexes are
validated before the old repository's PostgreSQL rows, Neo4j nodes, local clone, and
CocoIndex state are retired.

## Repository analysis and navigation

The home workspace provides the existing editor plus repository understanding,
deterministic source navigation, and bug investigation tools. Analysis endpoints
operate only on the active repository:

- `GET /api/analysis/repository/profile` and `/structure`
- `POST /api/analysis/repository/architecture` and `/relationships`
- `GET /api/navigation/implementation`, `/function`, `/usages`, and `/config`
- `POST /api/bugs/locations`, `/stacktrace`, `/execution-flow`, and `/improvements`

The source scanner uses the safe active workspace and skips symlinks and common
generated directories. Python definitions/calls/imports are parsed with `ast`;
declaration matching for JavaScript/TypeScript is intentionally limited to common
function/class forms, and other textual references are reported as references rather
than calls. The graph index currently extracts definitions, imports, and calls only
from Python; graph-based explanations report the records available from that index.
Architecture, relationship, bug, stack-trace, flow, and improvement explanations reuse
the assistant's configured Groq client. Deterministic lookups do not call the LLM.

## Architecture

GitHub Repository
        ↓
Repository Ingestion
        ↓
Repository Indexing
        ↓
Hybrid Retrieval
        ↓
Context Builder
        ↓
Coding LLM