import { useCallback, useEffect, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  BugInvestigation,
  CodeNavigation,
  RepositoryUnderstanding,
} from "./AnalysisPages";
import heroArt from "./assets/hero.png";
import "./App.css";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const PAGES = new Set(["home", "editor", "understanding", "navigation", "bugs"]);

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || "The request failed.");
  }
  return data;
}

function encodePath(path) {
  return path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

function indexStatusLabel(status) {
  if (status === "error") {
    return "Index error";
  }
  if (["indexing", "queued", "cloning"].includes(status)) {
    return "Index updating";
  }
  return "Index ready";
}

function App() {
  const [page, setPage] = useState(() => {
    const requested = window.location.hash.slice(1);
    return PAGES.has(requested) ? requested : "home";
  });
  const [repository, setRepository] = useState(null);
  const [repositoryProfile, setRepositoryProfile] = useState(null);
  const [repositoryKey, setRepositoryKey] = useState(null);
  const [githubUrl, setGithubUrl] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [error, setError] = useState("");
  const [showReplaceForm, setShowReplaceForm] = useState(false);
  const [indexStatus, setIndexStatus] = useState({
    status: "idle",
    message: "No index refresh is pending.",
  });

  const [tree, setTree] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [saving, setSaving] = useState(false);

  const [cursorPosition, setCursorPosition] = useState({
    line: 1,
    column: 1,
  });

  const [selectedCode, setSelectedCode] = useState("");
  const [navigationTarget, setNavigationTarget] = useState(null);

  const [messages, setMessages] = useState([]);
  const [query, setQuery] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [generationMode, setGenerationMode] = useState("explain");

  const [explorerCollapsed, setExplorerCollapsed] = useState(false);
  const [assistantCollapsed, setAssistantCollapsed] = useState(false);

  const editorRef = useRef(null);
  const chatEndRef = useRef(null);
  const saveFileRef = useRef(null);
  const navigationTargetRef = useRef(null);
  const request = useCallback(apiRequest, []);

  const navigate = useCallback((nextPage) => {
    const safePage = PAGES.has(nextPage) ? nextPage : "home";
    window.history.pushState({ page: safePage }, "", `#${safePage}`);
    setPage(safePage);
  }, []);

  useEffect(() => {
    function handlePopState() {
      const requested = window.location.hash.slice(1);
      setPage(PAGES.has(requested) ? requested : "home");
    }
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const loadRepositoryProfile = useCallback(async () => {
    try {
      const data = await apiRequest("/api/analysis/repository/profile");
      setRepositoryProfile(data);
    } catch (err) {
      setRepositoryProfile(null);
      setError(err.message);
    }
  }, []);

  const loadWorkspaceTree = useCallback(async () => {
    const response = await fetch(
      `${API_BASE}/api/workspace/tree`
    );

    if (!response.ok) {
      throw new Error(
        "Could not load repository file tree."
      );
    }

    const data = await response.json();
    setTree(data);
  }, []);

  const checkRepositoryStatus = useCallback(async () => {
    try {
      const response = await fetch(
        `${API_BASE}/api/repository/status`
      );

      if (!response.ok) {
        throw new Error("Could not check repository status.");
      }

      const data = await response.json();

      if (data.ready) {
        setRepository(data.repository);
        setRepositoryKey(data.repository_key);
        await loadWorkspaceTree();
        await loadRepositoryProfile();
      } else {
        setRepository(null);
        setRepositoryKey(null);
        setRepositoryProfile(null);
      }
    } catch (err) {
      setError(err.message);
    }
  }, [loadRepositoryProfile, loadWorkspaceTree]);

  useEffect(() => {
    checkRepositoryStatus();
  }, [checkRepositoryStatus]);

  useEffect(() => {
    let timer;
    let cancelled = false;

    async function refreshIndexStatus() {
      try {
        const response = await fetch(
          `${API_BASE}/api/index/status`
        );
        if (!response.ok) {
          throw new Error("Could not check index status.");
        }

        const data = await response.json();
        if (cancelled) {
          return;
        }
        setIndexStatus(data);

        if (["queued", "cloning", "indexing"].includes(data.status)) {
          timer = setTimeout(refreshIndexStatus, 1200);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
        }
      }
    }

    refreshIndexStatus();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [repository, ingesting, indexStatus.status]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  }, [messages]);

  async function ingestRepository(event) {
    event.preventDefault();

    if (!githubUrl.trim()) {
      return;
    }
    if (isStreaming) {
      setError("Wait for the current assistant response before replacing the repository.");
      return;
    }
    if (
      repository &&
      !window.confirm(
        `Replace ${repository}? Its local clone and local-only editor changes will be removed after the new repository indexes successfully. If indexing fails, the current repository stays active.`
      )
    ) {
      return;
    }

    setError("");
    setIngesting(true);
    setIndexStatus({
      status: "cloning",
      message: "Cloning the repository. Your current workspace stays active until indexing succeeds.",
    });

    try {
      const response = await fetch(
        `${API_BASE}/api/repository/ingest`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            github_url: githubUrl.trim(),
          }),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Repository ingestion failed."
        );
      }

      setRepository(data.repository);
      setRepositoryKey(data.repository_key);
      setMessages([]);
      setSelectedFile(null);
      setFileContent("");
      setSavedContent("");
      setShowReplaceForm(false);
      setIndexStatus({
        status: "ready",
        message: data.cleanup_warning
          ? `Repository ready. Previous index cleanup is pending: ${data.cleanup_warning}`
          : "Repository indexed and ready.",
      });

      await loadWorkspaceTree();
      await loadRepositoryProfile();
    } catch (err) {
      setError(err.message);
      setIndexStatus({
        status: "error",
        message: `Repository replacement failed. The previous workspace remains active. ${err.message}`,
      });
    } finally {
      setIngesting(false);
    }
  }

  async function openFile(path, line = 1) {
    if (isDirty && !window.confirm("Discard unsaved changes and open another file?")) {
      return;
    }

    try {
      setError("");

      const response = await fetch(
        `${API_BASE}/api/workspace/file/${encodePath(path)}`
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Could not open file."
        );
      }

      setSelectedFile(path);
      setFileContent(data.content);
      setSavedContent(data.content);
      setCursorPosition({
        line: 1,
        column: 1,
      });
      setSelectedCode("");
      const target = { path, line: Math.max(1, Number(line) || 1) };
      navigationTargetRef.current = target;
      setNavigationTarget(target);
      if (page !== "editor") {
        navigate("editor");
      }
    } catch (err) {
      setError(err.message);
    }
  }

  useEffect(() => {
    if (
      page !== "editor"
      || !navigationTarget
      || selectedFile !== navigationTarget.path
      || !editorRef.current
    ) {
      return;
    }
    const editor = editorRef.current;
    const line = Math.min(
      Math.max(1, navigationTarget.line),
      editor.getModel()?.getLineCount() || navigationTarget.line,
    );
    editor.revealLineInCenter(line);
    editor.setPosition({ lineNumber: line, column: 1 });
    editor.focus();
    navigationTargetRef.current = null;
    setNavigationTarget(null);
  }, [fileContent, navigationTarget, page, selectedFile]);

  function handleEditorMount(editor, monaco) {
    editorRef.current = editor;
    const target = navigationTargetRef.current;
    if (target && target.path === selectedFile) {
      const line = Math.min(
        Math.max(1, target.line),
        editor.getModel()?.getLineCount() || target.line,
      );
      editor.revealLineInCenter(line);
      editor.setPosition({ lineNumber: line, column: 1 });
      navigationTargetRef.current = null;
      setNavigationTarget(null);
    }
    editor.addCommand(
      monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
      () => saveFileRef.current?.()
    );

    editor.onDidChangeCursorPosition((event) => {
      setCursorPosition({
        line: event.position.lineNumber,
        column: event.position.column,
      });
    });

    editor.onDidChangeCursorSelection((event) => {
      const selection = event.selection;

      if (
        selection.startLineNumber ===
          selection.endLineNumber &&
        selection.startColumn ===
          selection.endColumn
      ) {
        setSelectedCode("");
        return;
      }

      const model = editor.getModel();

      if (model) {
        setSelectedCode(
          model.getValueInRange(selection)
        );
      }
    });
  }

  async function saveFile() {
    if (!selectedFile || fileContent === savedContent || saving) {
      return;
    }

    setSaving(true);
    setError("");
    try {
      const response = await fetch(
        `${API_BASE}/api/workspace/file/${encodePath(selectedFile)}`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            content: fileContent,
            repository_key: repositoryKey,
          }),
        }
      );
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Could not save file.");
      }

      setSavedContent(data.content);
      setIndexStatus({
        status: "queued",
        message: "File saved. Updating the semantic, keyword, and graph indexes in the background.",
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }
  saveFileRef.current = saveFile;

  async function askAssistant(event) {
    event?.preventDefault();

    const trimmedQuery = query.trim();

    if (!trimmedQuery || isStreaming) {
      return;
    }

    setError("");
    setQuery("");
    setIsStreaming(true);

    const userMessage = {
      role: "user",
      content: trimmedQuery,
    };

    const assistantMessage = {
      role: "assistant",
      content: "",
    };

    setMessages((previous) => [
      ...previous,
      userMessage,
      assistantMessage,
    ]);

    try {
      const response = await fetch(
        `${API_BASE}/api/assistant/ask/stream`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            query: trimmedQuery,
            file_path: selectedFile,
            cursor_line: cursorPosition.line,
            cursor_column: cursorPosition.column,
            selected_code: selectedCode || null,
            mode: generationMode,
          }),
        }
      );

      if (!response.ok) {
        const data = await response.json().catch(
          () => null
        );

        throw new Error(
          data?.detail ||
            "Assistant request failed."
        );
      }

      if (!response.body) {
        throw new Error(
          "The server did not return a streaming response."
        );
      }

      const reader =
        response.body.getReader();

      const decoder = new TextDecoder();

      let accumulated = "";

      while (true) {
        const { value, done } =
          await reader.read();

        if (done) {
          break;
        }

        const chunk = decoder.decode(
          value,
          { stream: true }
        );

        accumulated += chunk;

        setMessages((previous) => {
          const updated = [...previous];

          updated[updated.length - 1] = {
            role: "assistant",
            content: accumulated,
          };

          return updated;
        });
      }

      const remaining =
        decoder.decode();

      if (remaining) {
        accumulated += remaining;

        setMessages((previous) => {
          const updated = [...previous];

          updated[updated.length - 1] = {
            role: "assistant",
            content: accumulated,
          };

          return updated;
        });
      }
    } catch (err) {
      setMessages((previous) => {
        const updated = [...previous];

        updated[updated.length - 1] = {
          role: "assistant",
          content:
            `**Error:** ${err.message}`,
        };

        return updated;
      });
    } finally {
      setIsStreaming(false);
    }
  }

  const isDirty = fileContent !== savedContent;

  function editorLanguage(path) {
    const extension = path?.split(".").pop()?.toLowerCase();
    const languages = {
      py: "python",
      js: "javascript",
      jsx: "javascript",
      ts: "typescript",
      tsx: "typescript",
      json: "json",
      html: "html",
      css: "css",
      scss: "scss",
      md: "markdown",
      sql: "sql",
      yaml: "yaml",
      yml: "yaml",
      sh: "shell",
    };
    return languages[extension] || "plaintext";
  }

  function renderTreeEntry(entry) {
    if (entry.type === "directory") {
      return (
        <div
          className="tree-directory"
          key={entry.path}
        >
          <div className="tree-directory-name">
            📁 {entry.name}
          </div>

          <div className="tree-children">
            {(entry.children || []).map(
              renderTreeEntry
            )}
          </div>
        </div>
      );
    }

    return (
      <button
        key={entry.path}
        className={
          selectedFile === entry.path
            ? "tree-file active"
            : "tree-file"
        }
        onClick={() =>
          openFile(entry.path)
        }
      >
        📄 {entry.name}
      </button>
    );
  }

  if (page === "home" || !repository) {
    return (
      <div className="home-page">
        <header className="home-topbar">
          <div className="home-brand"><span className="brand-mark">R</span><strong>RACA</strong></div>
          <span className="home-product-label">Repository intelligence workspace</span>
        </header>
        <main className="home-content">
          <section className="home-hero">
            <div className="home-hero-copy">
              <span className="eyebrow">YOUR CODEBASE, UNDERSTOOD</span>
              <h1>Build with context.</h1>
              <p>Navigate, investigate, and understand your repository with grounded code intelligence.</p>
            </div>
            <img className="home-hero-art" src={heroArt} alt="" />
          </section>

          <section className="repository-summary">
            <div className="repository-summary-main">
              <span className={`status-dot ${repository ? "ready" : ""}`} />
              <div>
                <span className="summary-label">ACTIVE REPOSITORY</span>
                <h2>{repository || "No repository connected"}</h2>
                {repositoryProfile?.url && (
                  <a href={repositoryProfile.url} target="_blank" rel="noreferrer">{repositoryProfile.url}</a>
                )}
                {repositoryProfile?.description && <p>{repositoryProfile.description}</p>}
                {!repository && <p>Connect a GitHub repository to open the editor and analysis tools.</p>}
              </div>
            </div>
            <div className="repository-summary-side">
              <span className="repository-status">{repository ? indexStatusLabel(indexStatus.status) : "not connected"}</span>
              {repositoryProfile?.file_count !== undefined && (
                <span>{repositoryProfile.file_count.toLocaleString()} files</span>
              )}
              {repository && <span>{repositoryProfile?.url ? "GitHub" : "Local repository"}</span>}
            </div>
          </section>
          {ingesting && (
            <div className="home-progress" role="status">
              <span className="progress-spinner" />
              <div><strong>{indexStatus.status === "indexing" ? "Indexing repository" : "Preparing repository"}</strong><p>{indexStatus.message}</p></div>
            </div>
          )}
          {error && <div className="error-message">{error}</div>}

          <section className="home-actions">
            <div className="home-section-heading">
              <div><span className="eyebrow">WORKSPACE</span><h2>What would you like to do?</h2></div>
              <button className="replace-action" onClick={() => { setError(""); setShowReplaceForm(true); }}>
                {repository ? "Replace repository" : "Connect repository"}
              </button>
            </div>
            <div className="action-grid">
              <button className="action-card editor-action" disabled={!repository} onClick={() => navigate("editor")}>
                <span className="action-icon">⌘</span><span className="action-title">Open editor</span>
                <span className="action-description">Explore and edit files with the RACA assistant by your side.</span>
                <span className="action-arrow">↗</span>
              </button>
              <button className="action-card" disabled={!repository} onClick={() => navigate("understanding")}>
                <span className="action-icon">◈</span><span className="action-title">Repository understanding</span>
                <span className="action-description">Explore architecture, project structure, and module relationships.</span>
                <span className="action-arrow">↗</span>
              </button>
              <button className="action-card" disabled={!repository} onClick={() => navigate("navigation")}>
                <span className="action-icon">⌕</span><span className="action-title">Code navigation</span>
                <span className="action-description">Find definitions, function usages, and configuration files.</span>
                <span className="action-arrow">↗</span>
              </button>
              <button className="action-card" disabled={!repository} onClick={() => navigate("bugs")}>
                <span className="action-icon">⌁</span><span className="action-title">Bug investigation &amp; improvements</span>
                <span className="action-description">Trace errors, investigate likely causes, and review code quality.</span>
                <span className="action-arrow">↗</span>
              </button>
              <button className="action-card replace-card" onClick={() => { setError(""); setShowReplaceForm(true); }}>
                <span className="action-icon">⇄</span><span className="action-title">{repository ? "Switch repository" : "Add a repository"}</span>
                <span className="action-description">Stage and validate a GitHub repository before making it active.</span>
                <span className="action-arrow">↗</span>
              </button>
            </div>
          </section>
        </main>
        <footer className="home-footer"><span>RACA · Repository-aware development</span><span>Semantic · Keyword · Graph</span></footer>

        {showReplaceForm && (
          <div className="modal-backdrop" role="presentation" onMouseDown={(event) => {
            if (event.target === event.currentTarget && !ingesting) setShowReplaceForm(false);
          }}>
            <section className="replace-dialog" role="dialog" aria-modal="true" aria-labelledby="replace-title">
              <button className="dialog-close" aria-label="Close dialog" disabled={ingesting} onClick={() => setShowReplaceForm(false)}>×</button>
              <span className="eyebrow">REPOSITORY SOURCE</span>
              <h2 id="replace-title">{repository ? "Replace active repository" : "Connect a repository"}</h2>
              <p>Enter a public GitHub repository URL. The current workspace remains active until the new index has been validated.</p>
              <form onSubmit={ingestRepository} className="repository-form">
                <input type="url" required placeholder="https://github.com/owner/repository" value={githubUrl} onChange={(event) => setGithubUrl(event.target.value)} disabled={ingesting} />
                <button type="submit" disabled={ingesting || !githubUrl.trim()}>{ingesting ? "Working…" : "Start indexing"}</button>
              </form>
              {ingesting && <div className="index-status" role="status"><span className="progress-spinner" />{indexStatus.message}</div>}
              {error && <div className="error-message">{error}</div>}
              {!ingesting && <p className="dialog-footnote">The new repository is activated only after semantic and graph indexes pass validation.</p>}
            </section>
          </div>
        )}
      </div>
    );
  }

  if (page !== "editor") {
    const titles = {
      understanding: ["Repository understanding", "A grounded overview of the active codebase."],
      navigation: ["Code navigation", "Find actual definitions and references in source."],
      bugs: ["Bug investigation & improvements", "Use repository evidence to explore issues and code quality."],
    };
    const [title, subtitle] = titles[page] || titles.understanding;
    return (
      <div className="app analysis-app">
        <header className="topbar analysis-topbar">
          <div className="brand">
            <button className="home-back-button" onClick={() => navigate("home")}>← Home</button>
            <strong>RACA</strong>
            <span>{repository}</span>
          </div>
          <div className="analysis-page-title"><strong>{title}</strong><span>{subtitle}</span></div>
          <span className={`index-status-indicator ${indexStatus.status}`} title={indexStatus.message}>
            {indexStatusLabel(indexStatus.status)}
          </span>
        </header>
        {page === "understanding" && <RepositoryUnderstanding request={request} onOpenSource={openFile} />}
        {page === "navigation" && <CodeNavigation request={request} onOpenSource={openFile} />}
        {page === "bugs" && <BugInvestigation request={request} onOpenSource={openFile} selectedFile={selectedFile} selectedCode={selectedCode} />}
      </div>
    );
  }

  const gridColumns = `
    ${
      explorerCollapsed
        ? "42px"
        : "260px"
    }
    minmax(0, 1fr)
    ${
      assistantCollapsed
        ? "42px"
        : "500px"
    }
  `;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <button className="home-back-button" onClick={() => navigate("home")}>← Home</button>
          <strong>RACA</strong>
          <span>{repository}</span>
        </div>

        <div className="topbar-actions">
          <span
            className={`index-status-indicator ${indexStatus.status}`}
            title={indexStatus.message}
            role="status"
          >
            {["indexing", "queued", "cloning"].includes(indexStatus.status)
              ? "Index updating"
              : indexStatus.status === "error"
                ? "Index error"
                : "Index ready"}
          </span>
        </div>

        {error && (
          <div className="topbar-error">
            {error}
          </div>
        )}
      </header>

      <main
        className="workspace"
        style={{
          gridTemplateColumns: gridColumns,
        }}
      >
        {/* Explorer */}
        <aside
          className={
            explorerCollapsed
              ? "panel explorer collapsed"
              : "panel explorer"
          }
        >
          <button
            className="collapse-button"
            onClick={() =>
              setExplorerCollapsed(
                (value) => !value
              )
            }
            title={
              explorerCollapsed
                ? "Expand explorer"
                : "Collapse explorer"
            }
          >
            {explorerCollapsed
              ? "›"
              : "‹"}
          </button>

          {!explorerCollapsed && (
            <>
              <div className="panel-header">
                <span>Explorer</span>
              </div>

              <div className="file-tree">
                {tree?.children?.map(
                  renderTreeEntry
                )}
              </div>
            </>
          )}
        </aside>

        {/* Editor */}
        <section className="panel editor-panel">
          <div className="panel-header editor-header">
            <span>
              {selectedFile ||
                "Select a file"}
            </span>

            {selectedFile && (
              <>
              <span className="cursor-info">
                Ln {cursorPosition.line},
                Col{" "}
                {cursorPosition.column}
              </span>
              <button
                className="save-button"
                onClick={saveFile}
                disabled={!isDirty || saving || ingesting}
                title="Save (Ctrl+S)"
              >
                {saving ? "Saving..." : isDirty ? "Save" : "Saved"}
              </button>
              </>
            )}
          </div>

          <div className="editor-container">
            <Editor
              height="100%"
              language={editorLanguage(selectedFile)}
              value={fileContent}
              onChange={(value) => setFileContent(value ?? "")}
              onMount={handleEditorMount}
              theme="vs-dark"
              options={{
                readOnly: !selectedFile || ingesting,
                minimap: {
                  enabled: true,
                },
                wordWrap: "on",
                automaticLayout: true,
              }}
            />
          </div>
        </section>

        {/* Assistant */}
        <aside
          className={
            assistantCollapsed
              ? "panel assistant-panel collapsed"
              : "panel assistant-panel"
          }
        >
          <button
            className="collapse-button"
            onClick={() =>
              setAssistantCollapsed(
                (value) => !value
              )
            }
            title={
              assistantCollapsed
                ? "Expand assistant"
                : "Collapse assistant"
            }
          >
            {assistantCollapsed
              ? "‹"
              : "›"}
          </button>

          {!assistantCollapsed && (
            <>
              <div className="panel-header">
                <span>RACA Assistant</span>
              </div>

              <div className="chat-messages">
                {messages.length === 0 && (
                  <div className="empty-chat">
                    Ask a question about the
                    repository.
                  </div>
                )}

                {messages.map(
                  (message, index) => (
                    <div
                      className={
                        message.role ===
                        "user"
                          ? "message user-message"
                          : "message assistant-message"
                      }
                      key={index}
                    >
                      <div className="message-role">
                        {message.role ===
                        "user"
                          ? "You"
                          : "RACA"}
                      </div>

                      <div className="message-content">
                        {message.role ===
                        "assistant" ? (
                          <ReactMarkdown
                            remarkPlugins={[
                              remarkGfm,
                            ]}
                          >
                            {message.content ||
                              "▌"}
                          </ReactMarkdown>
                        ) : (
                          message.content
                        )}
                      </div>
                    </div>
                  )
                )}

                <div
                  ref={chatEndRef}
                />
              </div>

              <div className="assistant-toolbar">
                <select
                  value={generationMode}
                  onChange={(event) => setGenerationMode(event.target.value)}
                  disabled={isStreaming}
                >
                  <option value="explain">Explain</option>
                  <option value="generate">Generate Code</option>
                  <option value="refactor">Refactor</option>
                  <option value="test">Generate Tests</option>
                  <option value="document">Documentation</option>
                </select>
              </div>

              <form
                className="assistant-input"
                onSubmit={askAssistant}
              >
                <textarea
                  value={query}
                  onChange={(event) =>
                    setQuery(
                      event.target.value
                    )
                  }
                  placeholder={
                    selectedFile
                      ? `Ask about ${selectedFile}...`
                      : "Ask RACA..."
                  }
                  disabled={isStreaming}
                  rows={3}
                  onKeyDown={(event) => {
                    if (
                      event.key === "Enter" &&
                      !event.shiftKey
                    ) {
                      event.preventDefault();
                      askAssistant(event);
                    }
                  }}
                />

                <button
                  type="submit"
                  disabled={
                    isStreaming ||
                    !query.trim()
                  }
                >
                  {isStreaming
                    ? "Generating..."
                    : "Ask"}
                </button>
              </form>
            </>
          )}
        </aside>
      </main>
    </div>
  );
}

export default App;