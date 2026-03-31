import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import MermaidChart from './MermaidChart.jsx';

/**
 * Renders Markdown with full GFM support + Mermaid diagram rendering.
 * Use this everywhere a document or spec is displayed.
 */

const components = {
  code({ inline, className, children }) {
    const lang = /language-(\w+)/.exec(className || '')?.[1];
    if (!inline && lang === 'mermaid') {
      return <MermaidChart code={String(children).replace(/\n$/, '')} />;
    }
    return (
      <code className={className}>
        {children}
      </code>
    );
  },
};

export default function MarkdownViewer({ children, className = '' }) {
  return (
    <div className={`prose prose-slate prose-sm max-w-none ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  );
}
