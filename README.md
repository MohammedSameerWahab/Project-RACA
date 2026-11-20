# Project RACA

**RACA (Repository-Aware AI Coding Assistant)** is a full-stack application that helps developers understand an existing GitHub repository. It combines semantic search, PostgreSQL full-text search, and a Python source-code graph before sending repository-grounded context to a configurable AI model.

RACA provides repository onboarding, source navigation, in-browser editing, streaming chat, repository analysis, bug investigation, and execution-flow explanations.

## Project Links and Demonstrations

- **Live application:** [ADD STREAMLIT OR DEPLOYED APPLICATION LINK]
- **Video demonstration:** [ADD DEMONSTRATION VIDEO LINK]
- **Presentation slides:** [ADD PRESENTATION/REPORT LINK]
- **Source repository:** [ADD GITHUB REPOSITORY LINK]

## Application Screenshots

### Repository workspace

[ADD SCREENSHOT: CONNECT-A-REPOSITORY AND ACTIVE-WORKSPACE SCREEN]

### Repository explorer and code editor

[ADD SCREENSHOT: MONACO EDITOR WITH REPOSITORY TREE AND SAVE CONTROL]

### Repository-aware chat

[ADD SCREENSHOT: STREAMING CHAT ANSWER WITH SOURCE-CODE REFERENCES]

### Repository understanding

[ADD SCREENSHOT: ARCHITECTURE, RELATIONSHIPS, OR STRUCTURE ANALYSIS]

### Retrieval evaluation dashboard

[ADD SCREENSHOT: STREAMLIT EVALUATION DASHBOARD]

---

## 1. Problem Statement

General-purpose coding chat systems do not automatically understand the complete structure of a specific repository. They may miss relevant files, exact identifiers, configuration, or relationships between functions and modules.

RACA addresses this problem by retrieving evidence from the repository itself before answering a question. It was designed around the idea that different questions require different retrieval evidence:

- Natural-language concepts are handled by **semantic retrieval**.
- Exact names and source terms are handled by **keyword retrieval**.
- Imports, definitions, and call relationships are handled by **graph retrieval**.

The three result sets are fused, deduplicated, converted into bounded source context, and supplied to the selected language model.

## 2. Implemented Solution

RACA is a local web application with a React/Vite frontend and a FastAPI backend.

A typical repository question follows this flow:

```text
GitHub repository URL
        |
        v
Clone and isolate the repository
        |
        v
Semantic chunks + vector index
        |             |
        v             v
PostgreSQL        Neo4j graph
pgvector + FTS    Python AST entities
        |             |
        +------+------+
               |
               v
Semantic + Keyword + Graph retrieval
               |
               v
Weighted fusion and source deduplication
               |
               v
Bounded, traceable repository context
               |
               v
Selected LLM provider and streamed response
```

### Core capabilities

- Validate and clone a public GitHub repository.
- Index source code with CocoIndex.
- Store source chunks, metadata, and 384-dimensional embeddings in PostgreSQL using pgvector.
- Search source code using cosine-vector similarity and PostgreSQL full-text search.
- Extract Python definitions, imports, and selected call relationships into Neo4j.
- Run semantic, keyword, and graph retrieval concurrently and fuse their results.
- Merge duplicate or overlapping source ranges and respect a practical context budget.
- Stream repository-grounded answers through the React interface.
- Select among configured cloud models and fall back to another configured model after generation failures.
- Browse the repository, open files in Monaco Editor, and save source changes.
- Analyze repository structure, implementation locations, relationships, configuration, stack traces, bug locations, and execution flow.
- Stage a replacement repository and activate it only after both index targets pass validation.

## 3. System Architecture

### Frontend

The frontend is a React application built with Vite and Monaco Editor. It presents:

- Repository connection and replacement controls
- Repository explorer
- Source-code editing and saving
- Model selection
- Streaming chat
- Repository profile and structure views
- Navigation and bug-investigation tools

### Backend

FastAPI coordinates the application lifecycle and exposes repository, workspace, analysis, navigation, and assistant APIs.

Key backend areas are:

| Module area | Responsibility |
|---|---|
| `src/ingestion/` | GitHub URL validation and repository cloning |
| `src/indexing/` | CocoIndex chunk/embedding flow and Python graph extraction |
| `src/retrieval/` | Semantic, keyword, graph, and hybrid retrieval |
| `src/context/` | Source deduplication, merging, truncation, and context formatting |
| `src/generation/` | Provider/model configuration and fallback generation |
| `src/pipeline.py` | Repository lifecycle and staged replacement orchestration |
| `src/workspace.py` | Safe repository-tree and file access |
| `src/assistant.py` | Retrieval, context construction, and generation coordination |
| `src/analysis/` | Repository, navigation, and investigation services |
| `src/main.py` | FastAPI routes and application startup |

### Storage responsibilities

| Storage | Data stored |
|---|---|
| PostgreSQL with pgvector | Canonical code chunks, source metadata, embeddings, and full-text search representation |
| Neo4j | Code entities and structural relationships such as containment, imports, and calls |
| CocoIndex state | Incremental processing state for the code and graph flows |
| Local repository workspace | Cloned source files for browsing, editing, and indexing |
| `data/active_repository.json` | Recoverable active-repository identity and staging/active index paths |

PostgreSQL is the canonical source-text store. Neo4j stores repository structure and identifies structurally relevant entities; graph retrieval then resolves those entities to the corresponding source chunks.

## 4. Retrieval and Context Construction

### Semantic retrieval

Source chunks and queries use the same local embedding model:

- Model: `sentence-transformers/all-MiniLM-L6-v2`
- Vector dimension: 384
- Similarity: cosine similarity
- Runtime storage: PostgreSQL with pgvector

This mode is effective for conceptual queries that do not repeat exact identifiers.

### Keyword retrieval

PostgreSQL full-text search uses the source-code text and English text search configuration. It ranks matching chunks with `ts_rank`.

This mode is effective for exact function names, classes, configuration keys, error text, and technical terms.

### Graph retrieval

The graph index extracts:

- Modules and source files
- Classes and functions
- Imports
- Selected Python call relationships

Graph retrieval matches entity names and paths, expands immediate relationships, and maps graph records back to PostgreSQL source chunks. Ambiguous call targets are handled conservatively.

### Hybrid fusion

The hybrid retriever executes the three retrieval modes concurrently and merges results by repository, normalized file path, start line, and end line.

The baseline weights are:

| Signal | Weight |
|---|---:|
| Semantic | 0.40 |
| Keyword | 0.30 |
| Graph | 0.30 |

Scores are normalized within each query result set and combined using weighted score fusion. These weights are baseline ranking parameters, not calibrated confidence probabilities.

The context builder:

- Removes duplicate source ranges.
- Merges directly overlapping or touching line ranges.
- Truncates oversized chunks.
- Orders evidence by the hybrid score.
- Limits the final context to an approximate 4,000-token budget.
- Includes repository, file, line range, language, hybrid score, and graph provenance.

## 5. AI Generation

RACA uses an OpenAI-compatible SDK interface across the configured providers. The provider layer keeps model credentials and API details outside the retrieval and assistant workflow.

Configured provider families include:

- Google Gemini/Gemma
- Groq
- NVIDIA NIM
- Cloudflare Workers AI
- A local OpenAI-compatible model option

The selected model is stored in the browser and used for chat and repository-generated analyses. If a generation request fails, RACA tries the next configured available model using the same query and repository context.

Configure credentials through environment variables as documented in the setup section. Local model inference was found to be too slow on the available CPU-only laptop and is not part of the recommended interactive setup.

## 6. Repository Replacement and Incremental Updates

Repository replacement is staged to avoid losing the current usable workspace:

1. Validate and clone the incoming GitHub repository.
2. Build isolated PostgreSQL and Neo4j staging indexes.
3. Validate both staged index targets.
4. Persist the incoming repository as active.
5. Clean the previous repository's scoped records and local files.
6. Keep the previous repository active if any stage fails.

The application also restores the active repository from the local manifest during FastAPI startup. Saving a file in the editor writes to the local clone and requests a background semantic, keyword, and graph index refresh.

## 7. Retrieval Evaluation

A separate Streamlit application was used to evaluate RACA's retrieval quality against the **Intelligent Physician Notetaker** source repository.

- Target repository: [ADD TARGET GITHUB URL]
- Target commit: [ADD EXACT COMMIT SHA USED FOR THE EVALUATION]
- Ground-truth dataset: 41 repository-understanding queries
- Retrieval compositions: semantic, keyword, graph, and all pairwise/full combinations
- Metric cutoff: top 10
- Experiment run count: 30
- Metric implementation: 1.2.0

The evaluator measured Recall@10, Precision@10, MRR, nDCG@10, File Recall@10, and Symbol Recall@10.

### Best observed configuration

Among the 30 exported runs, the highest nDCG@10 result was:

| Setting | Value |
|---|---:|
| Retrieval composition | Semantic + Graph |
| Semantic candidate top-k | 30 |
| Keyword candidate top-k | 0 / disabled |
| Graph candidate top-k | 12 |
| Recall@10 | 0.9268 |
| Precision@10 | 0.2000 |
| MRR | 0.8496 |
| nDCG@10 | 0.8419 |
| Symbol Recall@10 | 0.6402 |
| Successful queries | 41 / 41 |
| Recorded runtime | 7.91 seconds |

This result indicates that semantic matching combined with available structural evidence performed best for the selected repository and query set. Full three-source hybrid retrieval did not outperform the best two-source configuration.

This is an exploratory result on one repository and one ground-truth dataset. It should not be described as globally optimal or statistically significant.

### Evaluation placeholders

[ADD SCREENSHOT: GROUND-TRUTH DATASET AND QUERY EXAMPLE]

[ADD SCREENSHOT: RETRIEVAL CONFIGURATION CONTROLS]

[ADD SCREENSHOT: RESULT TABLE FOR THE 30 EXPERIMENTS]

[ADD SCREENSHOT: PER-QUERY RESULTS FOR THE BEST CONFIGURATION]

[ADD LINK: STREAMLIT EVALUATION APPLICATION]

[ADD LINK: FINAL RETRIEVAL EVALUATION CSV OR REPORT]

## 8. Technology Stack

| Area | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, asyncpg |
| Frontend | React, Vite, Monaco Editor |
| Repository processing | Git, CocoIndex |
| Embeddings | Sentence Transformers, `all-MiniLM-L6-v2` |
| Vector search | PostgreSQL, pgvector |
| Keyword search | PostgreSQL full-text search |
| Graph | Neo4j, Python AST |
| Generation | OpenAI-compatible APIs |
| Dependency management | uv, npm |

## 9. Using the Application

### 1. Start the backend

From the project root:

```powershell
uv sync
$env:PYTHONPATH = (Get-Location).Path
uv run uvicorn src.main:app --reload
```

The API is available at `http://127.0.0.1:8000`.

### 2. Start the frontend

Open a second PowerShell terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite, normally `http://localhost:5173`.

### 3. Connect a repository

1. Open the application home page.
2. Select **Connect repository** or **Switch repository**.
3. Enter a public GitHub URL.
4. Start indexing.
5. Wait until PostgreSQL and Neo4j indexing complete.
6. Confirm that the repository is active.

### 4. Explore source code

- Use the repository explorer to open files.
- Edit files in Monaco Editor.
- Use **Save** or `Ctrl+S` to persist changes to the local clone.
- Saved source changes trigger a background index refresh.

### 5. Ask repository questions

Open the chat workspace and ask questions such as:

- "Where is the transcription entry point?"
- "Explain how SOAP output is generated."
- "Which function calls `generate_soap_note`?"
- "Trace the data flow from the transcript input to the final output."
- "Which files configure the Gemini integration?"

RACA retrieves source evidence, sends it with the question to the selected model, and streams the answer into the chat.

### 6. Use repository analysis tools

The application also provides:

- Repository profile and structure
- Architecture and relationship explanations
- Implementation and function lookup
- Source usage lookup
- Configuration-file discovery
- Bug-location analysis
- Stack-trace explanation
- Execution-flow tracing
- Improvement suggestions

## 10. Environment Configuration

Create a `.env` file in the project root.

Required for repository indexing and retrieval:

```dotenv
POSTGRES_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/raca
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=YOUR_NEO4J_PASSWORD
NEO4J_DATABASE=raca_graph
```

Generation providers are configured independently:

```dotenv
GOOGLE_API_KEY=
GROQ_API_KEY=
CLOUDFLARE_API_KEY=
CLOUDFLARE_ACCOUNT_ID=
NVIDIA_API_KEY=
```

Optional local OpenAI-compatible model:

```dotenv
LOCAL_LLM_BASE_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=qwen2.5-coder:3b
LOCAL_LLM_API_KEY=
```

For a tunneled or remote endpoint, use its HTTPS URL and include `/v1` if the
endpoint exposes an OpenAI-compatible API there. If the URL is only the server
root, RACA appends `/v1` automatically.

Do not commit real credentials. The frontend development server proxies `/api` to `http://127.0.0.1:8000`. Set `RACA_API_TARGET` to use another backend address.

## 11. Tests and Validation

Run the backend test suite:

```powershell
uv run pytest
```

Run the frontend build:

```powershell
cd frontend
npm run build
```

Validation covers ingestion, semantic retrieval, keyword retrieval, graph retrieval, hybrid fusion, context construction, pipeline lifecycle, APIs, and application behavior. Formal retrieval evaluation is recorded separately through the Streamlit experiment application.

## 12. Current Scope and Limitations

- Graph indexing is primarily implemented for Python source files.
- Call resolution is conservative and does not fully cover dynamic dispatch or reflection.
- Graph traversal is intentionally limited to immediate or shallow structural relationships.
- Hybrid scores are query-relative ranking values, not globally calibrated probabilities.
- Context size is estimated using characters rather than the exact tokenizer of every model.
- Chat history is browser/session-oriented; it is not a documented cross-device archive.
- The application is designed for local use, not as a production multi-user or high-availability service.
- Provider models, quotas, free-tier eligibility, and availability can change.
- The 30-run retrieval result applies to the tested repository and query set; it does not prove universal retrieval superiority.

## 13. Interview-Ready Summary

Project RACA is a repository-aware coding assistant that reduces context gaps in software-development questions. It ingests a GitHub repository, creates semantic and keyword indexes in PostgreSQL, builds a structural Python code graph in Neo4j, and combines the three retrieval signals through weighted hybrid fusion.

The hybrid output is converted into a bounded, traceable context package that includes file paths and line ranges. A provider abstraction sends that context and the developer's question to a selected cloud or local model while supporting automatic fallback after provider failures.

A staged activation workflow prevents an invalid replacement repository from displacing the active workspace. A React/Monaco frontend provides repository browsing, source editing, streamed chat, repository architecture views, navigation tools, and bug investigation.

Retrieval was evaluated across 30 configurations against a 41-query benchmark for the Intelligent Physician Notetaker repository. Semantic + Graph retrieval with semantic top-k 30 and graph top-k 12 produced the best observed nDCG@10 of 0.8419 in the recorded export.
