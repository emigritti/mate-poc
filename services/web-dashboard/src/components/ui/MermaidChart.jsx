import { useEffect, useState, useRef } from 'react';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: false,
  theme: 'neutral',
  securityLevel: 'loose',
  fontFamily: 'ui-sans-serif, system-ui, sans-serif',
});

let _counter = 0;

// Characters that break Mermaid's parser when unquoted inside node labels.
const SPECIAL_CHARS = /[\/\(\)&<>#:;|*]/;

/**
 * Pre-processes LLM-generated Mermaid code to fix the most common syntax
 * errors produced by llama3.1:8b:
 *
 *  1. Unquoted flowchart node labels containing special characters
 *     e.g.  SAP[SAP S/4HANA]  →  SAP["SAP S/4HANA"]
 *
 *  2. Unquoted sequenceDiagram participant aliases
 *     e.g.  participant S as SAP S/4HANA  →  participant S as "SAP S/4HANA"
 */
function sanitizeMermaid(raw) {
  return raw
    .trim()
    // flowchart: NodeId[unquoted label with special chars] → NodeId["label"]
    .replace(/\b(\w+)\[(?!")([^\]]+)\]/g, (match, id, label) =>
      SPECIAL_CHARS.test(label)
        ? `${id}["${label.replace(/"/g, "'")}"]`
        : match
    )
    // sequenceDiagram: participant X as UnquotedAlias → participant X as "alias"
    .replace(/^(\s*participant\s+\w+\s+as\s+)([^"\n][^\n]*)$/gm, (match, prefix, alias) =>
      SPECIAL_CHARS.test(alias)
        ? `${prefix}"${alias.trim().replace(/"/g, "'")}"`
        : match
    );
}

/**
 * Renders a Mermaid diagram from raw code string.
 * Falls back to a styled code block if the syntax is invalid.
 */
export default function MermaidChart({ code }) {
  const [svg, setSvg]     = useState(null);
  const [hasError, setHasError] = useState(false);
  const idRef = useRef(`mermaid-${++_counter}`);

  useEffect(() => {
    setSvg(null);
    setHasError(false);
    const safe = sanitizeMermaid(code);
    mermaid
      .render(idRef.current, safe)
      .then(({ svg: rendered }) => setSvg(rendered))
      .catch(() => setHasError(true));
  }, [code]);

  if (hasError) {
    return (
      <pre className="text-xs bg-slate-50 border border-slate-200 rounded-lg p-3 overflow-x-auto text-slate-500 my-3">
        <code>{code}</code>
      </pre>
    );
  }

  if (!svg) return null;

  return (
    <div
      className="my-4 flex justify-center overflow-x-auto rounded-xl border border-slate-100 bg-slate-50/50 p-4"
      // mermaid output is sanitized SVG — safe to inject
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
