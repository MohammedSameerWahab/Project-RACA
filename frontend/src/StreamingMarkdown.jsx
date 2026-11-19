import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Ensures incomplete markdown (such as unclosed code blocks or lists during streaming)
 * renders stably without layout jumps or raw unformatted syntax.
 */
function prepareStreamingMarkdown(text) {
  if (!text) return "";
  let processed = text;

  // Check for unclosed code fence blocks (```)
  const codeBlockCount = (processed.match(/```/g) || []).length;
  if (codeBlockCount % 2 !== 0) {
    // There is an unclosed code block, append closing fence for rendering
    processed += "\n```";
  }

  return processed;
}

export default function StreamingMarkdown({ content, isStreaming = false, className = "" }) {
  const safeContent = useMemo(() => prepareStreamingMarkdown(content), [content]);

  return (
    <div className={`streaming-markdown-container ${className} ${isStreaming ? "streaming-active" : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ node, inline, className, children, ...props }) {
            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          },
          table({ children }) {
            return (
              <div className="table-responsive">
                <table>{children}</table>
              </div>
            );
          },
        }}
      >
        {safeContent}
      </ReactMarkdown>
      {isStreaming && <span className="streaming-caret" aria-hidden="true" />}
    </div>
  );
}
