/**
 * PixelDocumentView — Renders document content as a pixel-mode "Quest Scroll" (ADR-047).
 * Used in ApprovalsPage and DocumentsPage when ui_mode = "pixel".
 *
 * Props:
 *   title:    string
 *   content:  string (markdown)
 *   status:   "PENDING" | "APPROVED" | "REJECTED"
 *   actions:  ReactNode (approve/reject buttons from parent)
 */
import { MarkdownViewer } from '../ui/MarkdownViewer';

const STATUS_COLOR = {
  PENDING:  'var(--pixel-accent)',
  APPROVED: 'var(--pixel-primary)',
  REJECTED: 'var(--pixel-danger)',
};

const STATUS_LABEL = {
  PENDING:  '[ PENDING REVIEW ]',
  APPROVED: '[ APPROVED ]',
  REJECTED: '[ REJECTED ]',
};

export default function PixelDocumentView({ title, content, status, actions }) {
  return (
    <div className="pixel-panel space-y-4">
      {/* Header */}
      <div>
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <p className="pixel-heading">{title ?? 'INTEGRATION SCROLL'}</p>
          {status && (
            <span className="pixel-text-sm" style={{ color: STATUS_COLOR[status] ?? 'var(--pixel-text)' }}>
              {STATUS_LABEL[status] ?? status}
            </span>
          )}
        </div>
        <div className="mt-1" style={{ height: 2, background: 'var(--pixel-border)', opacity: 0.4 }} />
      </div>

      {/* Artifact banner */}
      <div
        className="pixel-text-sm text-center py-2"
        style={{
          background: 'rgba(74, 222, 128, 0.08)',
          borderTop: '1px dashed var(--pixel-border)',
          borderBottom: '1px dashed var(--pixel-border)',
        }}
      >
        ✦ ARTIFACT GENERATED — INTEGRATION DESIGN SCROLL ✦
      </div>

      {/* Content */}
      <div className="overflow-y-auto pixel-scroll" style={{ maxHeight: 500, padding: '4px 0' }}>
        {content ? (
          <MarkdownViewer content={content} />
        ) : (
          <p className="pixel-text-sm" style={{ color: 'var(--pixel-muted)' }}>No content available.</p>
        )}
      </div>

      {/* Action buttons */}
      {actions && (
        <div className="flex gap-3 pt-2" style={{ borderTop: '1px solid var(--pixel-border)' }}>
          {actions}
        </div>
      )}
    </div>
  );
}
