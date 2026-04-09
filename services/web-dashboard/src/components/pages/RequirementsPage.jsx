import { useState, useEffect, useRef } from 'react';
import { Upload, CheckCircle, XCircle, Tags, Loader2, FileText } from 'lucide-react';
import Badge from '../ui/Badge.jsx';
import ProjectModal from '../ui/ProjectModal.jsx';
import RequirementValidationModal from '../ui/RequirementValidationModal.jsx';
import TagConfirmPanel from '../requirements/TagConfirmPanel.jsx';
import { API } from '../../api.js';

const STATUS_MAP = {
  APPROVED:           { variant: 'success', label: 'Approved' },
  PENDING_APPROVAL:   { variant: 'warning', label: 'Pending Approval' },
  PENDING_TAG_REVIEW: { variant: 'info',    label: 'Pending Tags' },
  REJECTED:           { variant: 'error',   label: 'Rejected' },
  GENERATED:          { variant: 'primary', label: 'Generated' },
};

export default function RequirementsPage() {
  const [requirements, setRequirements] = useState([]);
  const [pendingTags, setPendingTags]   = useState([]);
  const [confirmedIds, setConfirmedIds] = useState(new Set());
  const [uploading, setUploading]       = useState(false);
  const [dragOver, setDragOver]         = useState(false);
  const [error, setError]               = useState(null);
  const [togglingIds, setTogglingIds]   = useState(new Set());
  // null = no modal; array = upload preview → modal open
  const [uploadPreview, setUploadPreview] = useState(null);
  // validation modal state
  const [showValidation, setShowValidation] = useState(false);
  const [validationReqs, setValidationReqs] = useState([]);
  const [fieldOverrides, setFieldOverrides] = useState({});
  const fileInputRef = useRef(null);

  // Load existing data on mount and after each successful upload
  useEffect(() => { loadData(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const isIncomplete = (val) => !val || val.trim() === '' || val.trim().toLowerCase() === 'unknown';

  const handleFile = async (file) => {
    const lowerName = file?.name?.toLowerCase() ?? '';
    if (!lowerName.endsWith('.csv') && !lowerName.endsWith('.md')) {
      setError('Please upload a CSV (.csv) or Markdown (.md) file');
      return;
    }
    setError(null);
    setUploading(true);
    try {
      const res = await API.requirements.upload(file);
      if (!res.ok) throw new Error('Upload failed');
      const data = await res.json();
      const preview = data.preview || [];

      // Check if any integration pair is missing source or target
      const hasIncomplete = preview.some(
        (p) => isIncomplete(p.source) || isIncomplete(p.target),
      );

      if (hasIncomplete) {
        // Fetch full requirement list for the validation modal
        const reqRes = await API.requirements.list();
        const reqData = await reqRes.json();
        setValidationReqs(reqData.data || []);
        setFieldOverrides({});
        setUploadPreview(preview);
        setShowValidation(true);
      } else {
        // No missing data — go straight to project modal
        setFieldOverrides({});
        setUploadPreview(preview);
        setShowValidation(false);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  };

  // Called when user confirms (or skips) the validation modal
  const handleValidationContinue = (overrides) => {
    setFieldOverrides(overrides);
    setShowValidation(false);
    // uploadPreview is already set → ProjectModal will now open
  };

  const handleValidationCancel = () => {
    setShowValidation(false);
    setUploadPreview(null);
    setValidationReqs([]);
    setFieldOverrides({});
  };

  // Called by ProjectModal after project creation + finalize succeed
  const handleProjectConfirmed = async (_projectId) => {
    setUploadPreview(null);
    setFieldOverrides({});
    await loadData();
  };

  // Called when user cancels the project modal
  const handleProjectCancel = () => {
    setUploadPreview(null);
    setFieldOverrides({});
  };

  const loadData = async () => {
    try {
      const [reqRes, catRes] = await Promise.all([
        API.requirements.list(),
        API.catalog.list(),
      ]);
      const reqs = await reqRes.json();
      // Backend returns { status, data: [...] }
      setRequirements(reqs.data || []);
      const cats = await catRes.json();
      // Backend returns { status, data: [...] }
      setPendingTags((cats.data || []).filter(i => i.status === 'PENDING_TAG_REVIEW'));
    } catch (e) {
      setError(`Could not load data: ${e.message}`);
    }
  };

  const onTagConfirmed = (id) =>
    setConfirmedIds(prev => new Set([...prev, id]));

  const handleToggleMandatory = async (req) => {
    const { req_id, mandatory } = req;
    if (togglingIds.has(req_id)) return;
    // Optimistic update
    setRequirements(prev =>
      prev.map(r => r.req_id === req_id ? { ...r, mandatory: !mandatory } : r)
    );
    setTogglingIds(prev => new Set([...prev, req_id]));
    try {
      const res = await API.requirements.patch(req_id, !mandatory);
      if (!res.ok) {
        // Revert on failure
        setRequirements(prev =>
          prev.map(r => r.req_id === req_id ? { ...r, mandatory } : r)
        );
      }
    } catch {
      setRequirements(prev =>
        prev.map(r => r.req_id === req_id ? { ...r, mandatory } : r)
      );
    } finally {
      setTogglingIds(prev => { const s = new Set(prev); s.delete(req_id); return s; });
    }
  };

  const pendingTagsList  = pendingTags.filter(p => !confirmedIds.has(p.id));
  const allTagsConfirmed = pendingTags.length > 0 && pendingTagsList.length === 0;

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Validation Modal — shown when source/target could not be extracted (step 1) */}
      {uploadPreview !== null && showValidation && (
        <RequirementValidationModal
          requirements={validationReqs}
          onContinue={handleValidationContinue}
          onCancel={handleValidationCancel}
        />
      )}

      {/* Project Modal — shown after validation (or directly if no missing data) (ADR-025, step 2) */}
      {uploadPreview !== null && !showValidation && (
        <ProjectModal
          preview={uploadPreview}
          fieldOverrides={fieldOverrides}
          onConfirm={handleProjectConfirmed}
          onCancel={handleProjectCancel}
        />
      )}
      {/* Upload zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); }}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-2xl p-10 text-center transition-all cursor-pointer select-none ${
          dragOver
            ? 'border-indigo-400 bg-indigo-50'
            : 'border-slate-300 hover:border-indigo-300 hover:bg-slate-50/80'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.md"
          className="hidden"
          onChange={e => handleFile(e.target.files[0])}
        />
        {uploading ? (
          <div className="flex flex-col items-center gap-3 text-indigo-600">
            <Loader2 size={32} className="animate-spin" />
            <p className="font-medium" style={{ fontFamily: 'Outfit, sans-serif' }}>
              Uploading and parsing…
            </p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3">
            <div className="w-14 h-14 rounded-full bg-indigo-50 border border-indigo-100 flex items-center justify-center">
              <Upload size={24} className="text-indigo-500" />
            </div>
            <div>
              <p className="font-semibold text-slate-700" style={{ fontFamily: 'Outfit, sans-serif' }}>
                Drop your requirements file here
              </p>
              <p className="text-sm text-slate-400 mt-1">or click to browse — accepts .csv and .md files</p>
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 text-sm">
          <XCircle size={16} /> {error}
        </div>
      )}

      {/* Requirements table */}
      {requirements.length > 0 && (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
            <FileText size={15} className="text-slate-400" />
            <h2
              className="font-semibold text-slate-900"
              style={{ fontFamily: 'Outfit, sans-serif' }}
            >
              Parsed Requirements
            </h2>
            <Badge variant="slate">{requirements.length}</Badge>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  {['Req ID', 'Description', 'Source', 'Target', 'Category', 'Priority', 'Status'].map(h => (
                    <th
                      key={h}
                      className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {requirements.map((req, i) => (
                  <tr key={i} className="hover:bg-slate-50/70 transition-colors">
                    {/* field names match Requirement schema: req_id, source_system, target_system, category, description */}
                    <td className="px-4 py-3 font-mono text-xs text-slate-400">{req.req_id || '—'}</td>
                    <td className="px-4 py-3 font-medium text-slate-900 max-w-xs truncate" title={req.description}>{req.description || '—'}</td>
                    <td className="px-4 py-3 text-slate-600">{req.source_system || '—'}</td>
                    <td className="px-4 py-3 text-slate-600">{req.target_system || '—'}</td>
                    <td className="px-4 py-3 text-slate-600">{req.category || '—'}</td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => handleToggleMandatory(req)}
                        disabled={togglingIds.has(req.req_id)}
                        title="Click to toggle mandatory / optional"
                        className="cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed rounded focus:outline-none focus:ring-2 focus:ring-indigo-400"
                      >
                        {req.mandatory
                          ? <Badge variant="error">Mandatory</Badge>
                          : <Badge variant="slate">Optional</Badge>
                        }
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant="primary" dot>Parsed</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tag confirmation panel */}
      {pendingTags.length > 0 && (
        <div className="bg-white rounded-2xl border border-indigo-200 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-indigo-100 bg-indigo-50/40 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Tags size={15} className="text-indigo-600" />
              <h2 className="font-semibold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                Tag Confirmation
              </h2>
              <Badge variant="info">{pendingTagsList.length} pending</Badge>
            </div>
            {allTagsConfirmed && (
              <div className="flex items-center gap-1.5 text-emerald-600 text-sm font-medium">
                <CheckCircle size={15} />
                All confirmed — ready to run agent!
              </div>
            )}
          </div>

          <div className="divide-y divide-slate-100">
            {pendingTags.map(integration => {
              const confirmed = confirmedIds.has(integration.id);
              return (
                <div key={integration.id} className={`px-5 py-4 transition-opacity ${confirmed ? 'opacity-50' : ''}`}>
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <p className="font-semibold text-slate-900">{integration.name}</p>
                      <p className="text-xs font-mono text-slate-400 mt-0.5">{integration.id}</p>
                    </div>
                    {confirmed && (
                      <div className="flex items-center gap-1.5 text-emerald-600 text-xs font-semibold">
                        <CheckCircle size={14} /> Tags confirmed
                      </div>
                    )}
                  </div>
                  {!confirmed && (
                    <TagConfirmPanel
                      integrationId={integration.id}
                      onConfirmed={onTagConfirmed}
                    />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
