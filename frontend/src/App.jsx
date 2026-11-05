import { useEffect, useRef, useState } from "react";
import Editor from "@monaco-editor/react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./App.css";

const API_BASE = "http://127.0.0.1:8000";

function App() {
  const [repository, setRepository] = useState(null);
  const [githubUrl, setGithubUrl] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [error, setError] = useState("");

  const [tree, setTree] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileContent, setFileContent] = useState("");

  const [cursorPosition, setCursorPosition] = useState({
    line: 1,
    column: 1,
  });

  const [selectedCode, setSelectedCode] = useState("");

  const [messages, setMessages] = useState([]);
  const [query, setQuery] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [generationMode, setGenerationMode] = useState("explain");

  const [explorerCollapsed, setExplorerCollapsed] = useState(false);
  const [assistantCollapsed, setAssistantCollapsed] = useState(false);

  const editorRef = useRef(null);
  const chatEndRef = useRef(null);
  

  useEffect(() => {
    checkRepositoryStatus();
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  }, [messages]);

  async function checkRepositoryStatus() {
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
        await loadWorkspaceTree();
      }
    } catch (err) {
      setError(err.message);
    }
  }

  async function ingestRepository(event) {
    event.preventDefault();

    if (!githubUrl.trim()) {
      return;
    }

    setError("");
    setIngesting(true);

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
      setMessages([]);
      setSelectedFile(null);
      setFileContent("");

      await loadWorkspaceTree();
    } catch (err) {
      setError(err.message);
    } finally {
      setIngesting(false);
    }
  }

  async function loadWorkspaceTree() {
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
  }

  async function openFile(path) {
    try {
      setError("");

      const response = await fetch(
        `${API_BASE}/api/workspace/file/${encodeURI(path)}`
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Could not open file."
        );
      }

      setSelectedFile(path);
      setFileContent(data.content);
      setCursorPosition({
        line: 1,
        column: 1,
      });
      setSelectedCode("");
    } catch (err) {
      setError(err.message);
    }
  }

  function handleEditorMount(editor) {
    editorRef.current = editor;

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

  if (!repository) {
    return (
      <div className="landing-page">
        <div className="landing-card">
          <h1>Project RACA</h1>

          <p>
            Repository-Aware AI Coding Assistant
          </p>

          <form
            onSubmit={ingestRepository}
            className="repository-form"
          >
            <input
              type="url"
              placeholder="https://github.com/owner/repository"
              value={githubUrl}
              onChange={(event) =>
                setGithubUrl(event.target.value)
              }
              disabled={ingesting}
            />

            <button
              type="submit"
              disabled={ingesting}
            >
              {ingesting
                ? "Ingesting..."
                : "Open Repository"}
            </button>
          </form>

          {error && (
            <div className="error-message">
              {error}
            </div>
          )}
        </div>
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
          <strong>RACA</strong>
          <span>{repository}</span>
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
              <span className="cursor-info">
                Ln {cursorPosition.line},
                Col{" "}
                {cursorPosition.column}
              </span>
            )}
          </div>

          <div className="editor-container">
            <Editor
              height="100%"
              language={
                selectedFile?.endsWith(
                  ".py"
                )
                  ? "python"
                  : "plaintext"
              }
              value={fileContent}
              onMount={handleEditorMount}
              theme="vs-dark"
              options={{
                readOnly: true,
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