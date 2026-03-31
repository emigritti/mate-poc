import { useEffect, useState, useRef } from 'react';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: false,
  theme: 'neutral',
  securityLevel: 'strict',
  fontFamily: 'ui-sans-serif, system-ui, sans-serif',
});

let _counter = 0;

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
    mermaid
      .render(idRef.current, code)
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
