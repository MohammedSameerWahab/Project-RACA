import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./AnalysisPages.css";

function Markdown({ children }) {
  return (
    <div className="analysis-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children || ""}</ReactMarkdown>
    </div>
  );
}

function SourceButton({ item, onOpenSource, children }) {
  if (!item?.file_path) {
    return null;
  }
  const line = item.line || item.start_line || item.source?.line || 1;
  return (
    <button
      className="source-link"
      type="button"
      onClick={() => onOpenSource(item.file_path, line)}
      title={`Open ${item.file_path}:${line}`}
    >
      {children || `${item.file_path}:${line}`}
    </button>
  );
}

function ResultList({ items, onOpenSource, empty = "No matching results." }) {
  if (!items?.length) {
    return <p className="analysis-empty">{empty}</p>;
  }
  return (
    <div className="analysis-results">
      {items.map((item, index) => (
        <article className="analysis-result" key={`${item.file_path}-${item.line}-${index}`}>
          <div className="result-heading">
            <strong>{item.qualified_name || item.name || item.function || item.kind || "Source"}</strong>
            <SourceButton item={item} onOpenSource={onOpenSource} />
          </div>
          <div className="result-meta">
            {item.type || item.kind || item.category || item.relation || item.relevance}
          </div>
          {item.preview && <pre>{item.preview}</pre>}
          {item.evidence && <pre>{item.evidence}</pre>}
        </article>
      ))}
    </div>
  );
}

function RepositoryUnderstanding({ request, onOpenSource }) {
  const [tab, setTab] = useState("architecture");
  const [structure, setStructure] = useState(null);
  const [architecture, setArchitecture] = useState(null);
  const [query, setQuery] = useState("");
  const [relationships, setRelationships] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    request("/api/analysis/repository/structure")
      .then((data) => active && setStructure(data))
      .catch((reason) => active && setError(reason.message));
    return () => {
      active = false;
    };
  }, [request]);

  async function run(path, body) {
    setLoading(true);
    setError("");
    try {
      return await request(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (reason) {
      setError(reason.message);
      return null;
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="analysis-page">
      <nav className="analysis-tabs" aria-label="Repository understanding">
        {[
          ["architecture", "Architecture"],
          ["relationships", "Module relationships"],
          ["structure", "Project structure"],
        ].map(([value, label]) => (
          <button
            key={value}
            className={tab === value ? "active" : ""}
            onClick={() => setTab(value)}
          >
            {label}
          </button>
        ))}
      </nav>

      {error && <div className="analysis-error" role="alert">{error}</div>}
      {tab === "architecture" && (
        <div className="analysis-card">
          <div className="analysis-card-heading">
            <div>
              <h2>Architecture</h2>
              <p>Generated from repository files and indexed graph relationships.</p>
            </div>
            <button disabled={loading} onClick={async () => {
              const result = await run("/api/analysis/repository/architecture", {
                method: "POST",
              });
              if (result) setArchitecture(result);
            }}>
              {loading ? "Analyzing…" : architecture ? "Analyze again" : "Analyze architecture"}
            </button>
          </div>
          {architecture ? (
            <>
              <Markdown>{architecture.explanation}</Markdown>
              <p className="analysis-note">
                Graph records inspected: {architecture.graph_records}
                {architecture.graph_truncated ? " (sample truncated)" : ""}.
              </p>
            </>
          ) : (
            <p className="analysis-empty">Run an analysis to explain components, dependencies, and execution flow grounded in this repository.</p>
          )}
        </div>
      )}

      {tab === "relationships" && (
        <div className="analysis-card">
          <h2>Module relationships</h2>
          <p>Search indexed modules, files, classes, or symbols. Edges shown below come from Neo4j.</p>
          <form className="analysis-search" onSubmit={async (event) => {
            event.preventDefault();
            const result = await run("/api/analysis/repository/relationships", { query });
            if (result) setRelationships(result);
          }}>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="e.g. retrieval or src/main.py" />
            <button disabled={loading || !query.trim()}>{loading ? "Searching…" : "Explain"}</button>
          </form>
          {relationships?.explanation && <Markdown>{relationships.explanation}</Markdown>}
          {relationships?.relationships?.length > 0 && (
            <div className="relationship-list">
              {relationships.relationships.map((edge, index) => (
                <article className="relationship-edge" key={`${edge.id}-${edge.related_id}-${index}`}>
                  <SourceButton item={edge} onOpenSource={onOpenSource}>
                    {edge.name || edge.file_path || edge.kind}
                  </SourceButton>
                  <span>{edge.relation_name || edge.relation || "RELATED"}</span>
                  <SourceButton
                    item={{
                      file_path: edge.related_file_path,
                      line: edge.related_start_line,
                    }}
                    onOpenSource={onOpenSource}
                  >
                    {edge.related_name || edge.related_file_path || edge.related_kind}
                  </SourceButton>
                </article>
              ))}
            </div>
          )}
          {relationships?.message && <p className="analysis-empty">{relationships.message}</p>}
        </div>
      )}

      {tab === "structure" && (
        <div className="analysis-card">
          <div className="analysis-card-heading">
            <div>
              <h2>Project structure</h2>
              <p>Deterministic filesystem inventory; no generated or inferred files.</p>
            </div>
            <span className="stat-chip">{structure?.file_count ?? "—"} files</span>
          </div>
          {!structure ? (
            <p className="analysis-empty">Loading repository structure…</p>
          ) : (
            <>
              <h3>Languages and file types</h3>
              <div className="language-list">
                {structure.languages.map((language) => (
                  <span key={language.extension}>{language.extension}<b>{language.files}</b></span>
                ))}
              </div>
              <h3>Top-level structure</h3>
              <div className="structure-list">
                {structure.top_level.map((directory) => (
                  <details key={directory.name}>
                    <summary>{directory.name} <span>{directory.files} files</span></summary>
                    <ul>
                      {directory.examples.map((path) => (
                        <li key={path}>
                          <button className="source-link" onClick={() => onOpenSource(path, 1)}>{path}</button>
                        </li>
                      ))}
                    </ul>
                  </details>
                ))}
              </div>
              <h3>Important configuration and project files</h3>
              <ResultList
                items={structure.important_files.map((file_path) => ({ file_path, category: "Project file" }))}
                onOpenSource={onOpenSource}
                empty="No common project files were detected."
              />
            </>
          )}
        </div>
      )}
    </section>
  );
}

function CodeNavigation({ request, onOpenSource }) {
  const [tab, setTab] = useState("implementation");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function search(event) {
    event?.preventDefault();
    setLoading(true);
    setError("");
    setNote("");
    try {
      const endpoints = {
        implementation: "/api/navigation/implementation",
        functions: "/api/navigation/function",
        usages: "/api/navigation/usages",
      };
      const endpoint = endpoints[tab];
      const suffix = `?query=${encodeURIComponent(query)}`;
      const data = await request(endpoint ? endpoint + suffix : "/api/navigation/config");
      setResults(data.results || []);
      setNote(data.coverage_note || data.graph_coverage || "");
    } catch (reason) {
      setError(reason.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (tab !== "config") return undefined;
    let active = true;
    request("/api/navigation/config")
      .then((data) => {
        if (active) setResults(data.results || []);
      })
      .catch((reason) => {
        if (active) setError(reason.message);
      });
    return () => {
      active = false;
    };
  }, [request, tab]);

  return (
    <section className="analysis-page">
      <nav className="analysis-tabs" aria-label="Code navigation">
        {[
          ["implementation", "Implementations"],
          ["functions", "Functions"],
          ["usages", "Usages"],
          ["config", "Configuration"],
        ].map(([value, label]) => (
          <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>
            {label}
          </button>
        ))}
      </nav>
      <div className="analysis-card">
        <h2>{tab === "config" ? "Configuration files" : "Find source symbols"}</h2>
        {tab !== "config" && (
          <form className="analysis-search" onSubmit={search}>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search a function, class, method, or symbol" />
            <button disabled={loading || !query.trim()}>{loading ? "Searching…" : "Search"}</button>
          </form>
        )}
        {error && <div className="analysis-error" role="alert">{error}</div>}
        {note && <p className="analysis-note">{note}</p>}
        {tab === "usages" ? (
          <div className="analysis-results">
            {results.map((item, index) => (
              <article className="analysis-result" key={`${item.file_path}-${item.line}-${index}`}>
                <div className="result-heading">
                  <strong>{item.kind}</strong>
                  <SourceButton item={item} onOpenSource={onOpenSource} />
                </div>
                <pre>{item.preview}</pre>
              </article>
            ))}
            {!loading && results.length === 0 && <p className="analysis-empty">{tab === "config" ? "No configuration files found." : "Enter a symbol to find source references."}</p>}
          </div>
        ) : (
          <ResultList
            items={results.map((item) => tab === "config" ? { ...item, name: item.file_path } : item)}
            onOpenSource={onOpenSource}
            empty={tab === "config" ? "No configuration files found." : "Enter a symbol to find definitions."}
          />
        )}
      </div>
    </section>
  );
}

function BugInvestigation({ request, onOpenSource, selectedFile, selectedCode }) {
  const [tab, setTab] = useState("bug");
  const [description, setDescription] = useState("");
  const [stackTrace, setStackTrace] = useState("");
  const [symbol, setSymbol] = useState("");
  const [scope, setScope] = useState("repository");
  const [filePath, setFilePath] = useState(selectedFile || "");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function run(path, body) {
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const data = await request(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setResult(data);
    } catch (reason) {
      setError(reason.message);
    } finally {
      setLoading(false);
    }
  }

  const tabs = [
    ["bug", "Investigate a bug"],
    ["stack", "Explain stack trace"],
    ["flow", "Trace execution flow"],
    ["improvements", "Suggest improvements"],
  ];

  return (
    <section className="analysis-page">
      <nav className="analysis-tabs" aria-label="Bug investigation and improvements">
        {tabs.map(([value, label]) => (
          <button key={value} className={tab === value ? "active" : ""} onClick={() => { setTab(value); setResult(null); }}>
            {label}
          </button>
        ))}
      </nav>
      <div className="analysis-card">
        {tab === "bug" && (
          <>
            <h2>Investigate an issue</h2>
            <p>Hybrid semantic, keyword, and graph retrieval ranks evidence. The explanation treats candidates as hypotheses.</p>
            <form className="analysis-form" onSubmit={(event) => {
              event.preventDefault();
              run("/api/bugs/locations", {
                description,
                file_path: filePath || null,
                selected_code: selectedCode || null,
              });
            }}>
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Describe the error, unexpected behavior, or failing workflow…" />
              <input value={filePath} onChange={(event) => setFilePath(event.target.value)} placeholder="Optional repository-relative file path" />
              <button disabled={loading || !description.trim()}>{loading ? "Investigating…" : "Investigate"}</button>
            </form>
          </>
        )}
        {tab === "stack" && (
          <>
            <h2>Explain a stack trace</h2>
            <p>Frames are parsed deterministically; only paths inside the active repository are opened or used as source evidence.</p>
            <form className="analysis-form" onSubmit={(event) => { event.preventDefault(); run("/api/bugs/stacktrace", { stack_trace: stackTrace }); }}>
              <textarea value={stackTrace} onChange={(event) => setStackTrace(event.target.value)} placeholder="Paste an exception and stack trace…" />
              <button disabled={loading || !stackTrace.trim()}>{loading ? "Explaining…" : "Explain trace"}</button>
            </form>
          </>
        )}
        {tab === "flow" && (
          <>
            <h2>Trace static execution flow</h2>
            <p>Uses indexed CALLS relationships. This static graph is not proof of runtime execution order.</p>
            <form className="analysis-search" onSubmit={(event) => { event.preventDefault(); run("/api/bugs/execution-flow", { symbol }); }}>
              <input value={symbol} onChange={(event) => setSymbol(event.target.value)} placeholder="Function or class name" />
              <button disabled={loading || !symbol.trim()}>{loading ? "Tracing…" : "Trace"}</button>
            </form>
          </>
        )}
        {tab === "improvements" && (
          <>
            <h2>Suggest improvements</h2>
            <p>Recommendations are advisory. The system will only cite file locations included in inspected source.</p>
            <form className="analysis-form" onSubmit={(event) => {
              event.preventDefault();
              run("/api/bugs/improvements", {
                scope,
                file_path: scope === "file" ? filePath : selectedFile || null,
                selected_code: scope === "selection" ? selectedCode || null : null,
              });
            }}>
              <select value={scope} onChange={(event) => setScope(event.target.value)}>
                <option value="repository">Repository (targeted retrieval)</option>
                <option value="file">File</option>
                <option value="selection">Selected editor code</option>
              </select>
              {scope === "file" && (
                <input value={filePath} onChange={(event) => setFilePath(event.target.value)} placeholder="Repository-relative file path" />
              )}
              {scope === "selection" && (
                <div className="analysis-note">{selectedCode ? `${selectedCode.length} selected characters will be analyzed.` : "Select code in the editor, then return here."}</div>
              )}
              <button disabled={loading || (scope === "selection" && !selectedCode)}>{loading ? "Reviewing…" : "Suggest improvements"}</button>
            </form>
          </>
        )}

        {error && <div className="analysis-error" role="alert">{error}</div>}
        {result && tab === "bug" && (
          <>
            <Markdown>{result.analysis}</Markdown>
            <h3>Retrieved source evidence</h3>
            <ResultList items={result.candidates} onOpenSource={onOpenSource} empty="No candidate locations returned." />
          </>
        )}
        {result && tab === "stack" && (
          <>
            <div className="stack-summary"><strong>{result.exception.exception_type}</strong><span>{result.exception.message}</span></div>
            <h3>Parsed frames</h3>
            <div className="analysis-results">
              {result.frames.map((frame, index) => (
                <article className="analysis-result" key={`${frame.raw_path}-${frame.line}-${index}`}>
                  <div className="result-heading">
                    <strong>{frame.function}</strong>
                    {frame.resolved
                      ? <SourceButton item={frame} onOpenSource={onOpenSource} />
                      : <span className="result-meta">External or unresolved frame</span>}
                  </div>
                  {frame.source?.code && <pre>{frame.source.code}</pre>}
                </article>
              ))}
            </div>
            <Markdown>{result.explanation}</Markdown>
          </>
        )}
        {result && tab === "flow" && (
          <>
            <div className="flow-list">
              {result.edges.map((edge, index) => {
                const source = result.nodes.find((node) => node.id === edge.source);
                const target = result.nodes.find((node) => node.id === edge.target);
                return (
                  <div className="flow-edge" key={`${edge.source}-${edge.target}-${index}`}>
                    <SourceButton item={{ file_path: source?.file_path, line: source?.line }} onOpenSource={onOpenSource}>{source?.name || "Source"}</SourceButton>
                    <span>calls</span>
                    <SourceButton item={{ file_path: target?.file_path, line: target?.line }} onOpenSource={onOpenSource}>{target?.name || "Target"}</SourceButton>
                  </div>
                );
              })}
              {result.nodes.map((node) => (
                <article className="analysis-result" key={node.id}>
                  <div className="result-heading">
                    <strong>{node.kind}: {node.name}</strong>
                    <SourceButton item={{ file_path: node.file_path, line: node.line }} onOpenSource={onOpenSource} />
                  </div>
                  {node.source && <pre>{node.source}</pre>}
                </article>
              ))}
            </div>
            {result.truncated && <p className="analysis-note">Flow is truncated at the configured node limit.</p>}
            <Markdown>{result.explanation}</Markdown>
          </>
        )}
        {result && tab === "improvements" && <Markdown>{result.suggestions}</Markdown>}
      </div>
    </section>
  );
}

export { BugInvestigation, CodeNavigation, RepositoryUnderstanding };
