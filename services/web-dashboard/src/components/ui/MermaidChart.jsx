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
 * Pre-processes LLM-generated Mermaid code to fix common syntax errors.
 *
 *  1. Unquoted flowchart node labels with special characters
 *     e.g.  SAP[SAP S/4HANA]  →  SAP["SAP S/4HANA"]
 *
 *  2. Quoted strings used as sequenceDiagram message sources/targets
 *     e.g.  "AWS S3"->>INT  →  AWS_S3->>INT
 *     e.g.  INT->>"AWS S3"  →  INT->>AWS_S3
 *     (Mermaid v11 only accepts plain alphanumeric IDs in message lines)
 */
// Decode common HTML entities that LLMs sometimes emit inside code blocks.
const HTML_ENTITIES = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'" };

function decodeHtmlEntities(str) {
  return str.replace(/&(?:amp|lt|gt|quot|#39);/g, m => HTML_ENTITIES[m]);
}

function sanitizeMermaid(raw) {
  return decodeHtmlEntities(raw)
    .trim()
    // flowchart: NodeId[unquoted label with special chars] → NodeId["label"]
    .replace(/\b(\w+)\[(?!")([^\]]+)\]/g, (match, id, label) =>
      SPECIAL_CHARS.test(label)
        ? `${id}["${label.replace(/"/g, "'")}"]`
        : match
    )
    // sequenceDiagram: "Quoted Name"->> → QuotedName->> (source side)
    .replace(/"([^"]+)"(\s*-)/g, (_, name, dash) =>
      `${name.trim().replace(/\s+/g, '_').replace(/[^a-zA-Z0-9_]/g, '')}${dash}`
    )
    // sequenceDiagram: ->>"Quoted Name" → ->>QuotedName (target side)
    .replace(/(-[>.]+\s*)"([^"]+)"/g, (_, arrow, name) =>
      `${arrow}${name.trim().replace(/\s+/g, '_').replace(/[^a-zA-Z0-9_]/g, '')}`
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
