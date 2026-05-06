import { useState } from 'react';
import { toast } from 'sonner';
import { useApprovals } from '../../hooks/useApprovals';
import ApprovalQueue from '../approvals/ApprovalQueue.jsx';
import ReviewPanel from '../approvals/ReviewPanel.jsx';

export default function ApprovalsPage() {
  const {
    approvals, isLoading,
    approve, isApproving,
    reject, isRejecting,
    regenerate, isRegenerating,
  } = useApprovals();

  const [selectedId, setSelectedId] = useState(null);
  const [content,    setContent]    = useState('');
  const [rejected,   setRejected]   = useState([]);

  const handleSelect = (id) => {
    setSelectedId(id);
    const approval = approvals.find(a => a.id === id);
    setContent(approval?.content ?? approval?.document ?? '');
  };

  const handleApprove = ({ id, content: finalContent }) => {
    approve(
      { id, content: finalContent },
      {
        onSuccess: () => {
          toast.success('Document staged. Use the Documents page to promote to Knowledge Base.');
          setSelectedId(null);
          setContent('');
        },
        onError: (err) => toast.error(err.message || 'Approval failed — please try again'),
      },
    );
  };

  const handleReject = ({ id, feedback }) => {
    if (!feedback.trim()) return;
    reject(
      { id, feedback },
      {
        onSuccess: () => {
          const approval = approvals.find(a => a.id === id);
          setRejected(prev => [...prev, { ...approval, feedback }]);
          toast.info('Document rejected. Select it from the queue to regenerate.');
          setSelectedId(null);
          setContent('');
        },
        onError: (err) => toast.error(err.message || 'Rejection failed — please try again'),
      },
    );
  };

  const handleRegenerate = (id) => {
    regenerate(
      { id },
      {
        onSuccess: (data) => {
          const newId = data.data?.new_approval_id;
          toast.success(`Regenerated — new approval ${newId ?? ''} is pending.`);
          setRejected(prev => prev.filter(a => a.id !== id));
        },
        onError: (err) => toast.error(err.message || 'Regeneration failed'),
      },
    );
  };

  const selectedApproval = approvals.find(a => a.id === selectedId) ?? null;

  return (
    <div className="flex gap-4" style={{ height: 'calc(100vh - 200px)' }}>
      <ApprovalQueue
        approvals={approvals}
        selectedId={selectedId}
        onSelect={handleSelect}
        rejected={rejected}
        onRegenerate={handleRegenerate}
        isLoading={isLoading}
        isRegenerating={isRegenerating}
      />
      <ReviewPanel
        approval={selectedApproval}
        content={content}
        onContentChange={setContent}
        onApprove={handleApprove}
        onReject={handleReject}
        isApproving={isApproving}
        isRejecting={isRejecting}
      />
    </div>
  );
}
