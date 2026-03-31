import { useState, useEffect, useRef, useCallback } from 'react';
import { X, CheckCircle, AlertCircle, Loader2, Building2, Globe, Hash, FileText, User } from 'lucide-react';
import { API } from '../../api.js';

// ── Prefix auto-generation ────────────────────────────────────────────────────
// Rules (ADR-025 §2): multi-word → initials (max 3); single word → first 3 chars.
function generatePrefix(clientName) {
  const words = clientName.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return '';
  const raw =
    words.length === 1
      ? words[0].slice(0, 3)
      : words.map(w => w[0]).join('').slice(0, 3);
  return raw.toUpperCase().replace(/[^A-Z0-9]/g, '');
}

const PREFIX_RE = /^[A-Z0-9]{1,3}$/;

// Handles both string detail ("message") and Pydantic array detail ([{msg:...}])
function extractDetail(d, fallback) {
  if (!d) return fallback;
  if (Array.isArray(d.detail))
    return d.detail.map(e => e.msg || JSON.stringify(e)).join('; ');
  return d.detail || fallback;
}

// ── Field component ───────────────────────────────────────────────────────────
function Field({ label, required, icon: Icon, children }) {
  return (
    <div className="space-y-1.5">
      <label className="flex items-center gap-1.5 text-xs font-semibold text-slate-600 uppercase tracking-wider">
        <Icon size={12} className="text-slate-400" />
        {label}
        {required && <span className="text-rose-500">*</span>}
      </label>
      {children}
    </div>
  );
}

const inputCls =
  'w-full px-3 py-2 text-sm border rounded-lg outline-none transition-all ' +
  'focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 border-slate-300 bg-white';

// ── Main modal ────────────────────────────────────────────────────────────────
/**
 * ProjectModal — mandatory step between CSV parse and finalize (ADR-025).
 *
 * Props:
 *   preview      – array of { source, target } from /upload
 *   onConfirm    – async (projectId) => void   called after successful /finalize
 *   onCancel     – () => void
 */
export default function ProjectModal({ preview, fieldOverrides = {}, onConfirm, onCancel }) {
  const [clientName, setClientName] = useState('');
  const [domain, setDomain]         = useState('');
  const [prefix, setPrefix]         = useState('');
  const [description, setDescription] = useState('');
  const [accentureRef, setAccentureRef] = useState('');

  // Sentinel: undefined = check in-flight, null = free, false = clash, string = existing match
  const [resolvedId, setResolvedId] = useState(undefined);
  const [prefixBanner, setPrefixBanner] = useState(null); // { kind: 'ok'|'clash', message }

  const [submitting, setSubmitting] = useState(false);
  const [error, setError]           = useState(null);

  const debounceRef = useRef(null);

  // ── Prefix uniqueness check ────────────────────────────────────────────────
  const checkPrefix = useCallback(async (raw) => {
    const p = raw.toUpperCase().replace(/[^A-Z0-9]/g, '');
    if (!PREFIX_RE.test(p)) {
      setResolvedId(undefined); // invalid → still treat as pending (button stays disabled)
      setPrefixBanner(null);
      return;
    }
    try {
      const res  = await API.projects.get(p);
      if (res.status === 404) {
        // Prefix is free
        setResolvedId(null);
        setPrefixBanner(null);
      } else if (res.ok) {
        const data = await res.json();
        const sameClient =
          data.client_name?.toLowerCase() === clientName.trim().toLowerCase();
        if (sameClient) {
          setResolvedId(data.prefix); // reuse this project
          setPrefixBanner({ kind: 'ok', message: `Existing project found: "${data.client_name}" — it will be reused.` });
        } else {
          setResolvedId(false); // clash — different client
          setPrefixBanner({ kind: 'clash', message: `Prefix already in use by another client: "${data.client_name}". Please choose a different prefix.` });
        }
      } else {
        // Unexpected error — treat as free to avoid blocking the user
        setResolvedId(null);
        setPrefixBanner(null);
      }
    } catch {
      setResolvedId(null);
      setPrefixBanner(null);
    }
  }, [clientName]);

  const scheduleCheck = useCallback((raw) => {
    clearTimeout(debounceRef.current);
    setResolvedId(undefined); // arm pending sentinel immediately
    setPrefixBanner(null);
    debounceRef.current = setTimeout(() => checkPrefix(raw), 400);
  }, [checkPrefix]);

  // Auto-generate prefix when clientName changes
  useEffect(() => {
    const generated = generatePrefix(clientName);
    setPrefix(generated);
    if (generated) scheduleCheck(generated);
    else { setResolvedId(undefined); setPrefixBanner(null); }
  }, [clientName]); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-check when prefix is manually edited
  const handlePrefixChange = (e) => {
    const val = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 3);
    setPrefix(val);
    scheduleCheck(val);
  };

  // ── Confirm button state ───────────────────────────────────────────────────
  const fieldsFilled = clientName.trim() && domain.trim() && prefix.trim();
  const confirmDisabled =
    submitting ||
    !fieldsFilled ||
    resolvedId === undefined || // check in-flight
    resolvedId === false;       // prefix clash

  // ── Submit ─────────────────────────────────────────────────────────────────
  const handleConfirm = async () => {
    setError(null);
    setSubmitting(true);
    try {
      let projectId;

      if (typeof resolvedId === 'string') {
        // Reuse existing project — prefix already confirmed
        projectId = resolvedId;
      } else {
        // Create new project
        const res = await API.projects.create({
          prefix: prefix.trim(),
          client_name: clientName.trim(),
          domain: domain.trim(),
          description: description.trim() || undefined,
          accenture_ref: accentureRef.trim() || undefined,
        });
        const projData = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(extractDetail(projData, `Project creation error (${res.status})`));
        }
        // Backend envelope: {"status":"created","data":{prefix,...}} — prefix is nested under .data
        projectId = projData.data?.prefix;
      }

      // Finalize: create CatalogEntries with prefix IDs (pass user-supplied overrides if any)
      const finRes = await API.requirements.finalize(projectId, fieldOverrides);
      const finData = await finRes.json().catch(() => ({}));
      if (!finRes.ok) {
        throw new Error(extractDetail(finData, `Finalization error (${finRes.status})`));
      }

      await onConfirm(projectId);
    } catch (e) {
      setError(e.message || 'Operation failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    // Backdrop
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg border border-slate-200 overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50/60">
          <div>
            <h2 className="font-bold text-slate-900 text-base" style={{ fontFamily: 'Outfit, sans-serif' }}>
              Project Metadata
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              {preview.length} requirement{preview.length !== 1 ? 's' : ''} ready — associate a project before proceeding.
            </p>
          </div>
          <button
            onClick={onCancel}
            className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4">

          {/* Client name */}
          <Field label="Client Name" required icon={Building2}>
            <input
              type="text"
              placeholder="e.g. Acme Corp"
              value={clientName}
              onChange={e => setClientName(e.target.value)}
              className={inputCls}
            />
          </Field>

          {/* Domain */}
          <Field label="Integration Domain" required icon={Globe}>
            <input
              type="text"
              placeholder="e.g. Fashion Retail, PLM-PIM"
              value={domain}
              onChange={e => setDomain(e.target.value)}
              className={inputCls}
            />
          </Field>

          {/* Prefix */}
          <Field label="Prefix (1–3 chars)" required icon={Hash}>
            <div className="space-y-1">
              <input
                type="text"
                placeholder="e.g. ACM"
                value={prefix}
                onChange={handlePrefixChange}
                maxLength={3}
                className={`${inputCls} font-mono tracking-widest uppercase`}
              />
              {/* Uniqueness banner */}
              {resolvedId === undefined && prefix && PREFIX_RE.test(prefix) && (
                <div className="flex items-center gap-2 text-xs text-slate-500 px-1">
                  <Loader2 size={11} className="animate-spin" />
                  Checking availability…
                </div>
              )}
              {prefixBanner?.kind === 'ok' && (
                <div className="flex items-center gap-1.5 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-1.5 rounded-lg">
                  <CheckCircle size={12} /> {prefixBanner.message}
                </div>
              )}
              {prefixBanner?.kind === 'clash' && (
                <div className="flex items-center gap-1.5 text-xs text-rose-700 bg-rose-50 border border-rose-200 px-2 py-1.5 rounded-lg">
                  <AlertCircle size={12} /> {prefixBanner.message}
                </div>
              )}
              <p className="text-xs text-slate-400 px-1">
                Integration IDs will use this prefix: <span className="font-mono font-semibold text-slate-600">{prefix || '???'}-4F2A1B</span>
              </p>
            </div>
          </Field>

          {/* Description (optional) */}
          <Field label="Description" icon={FileText}>
            <textarea
              placeholder="Brief project description (optional)"
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={2}
              maxLength={500}
              className={`${inputCls} resize-none`}
            />
          </Field>

          {/* Accenture ref (optional) */}
          <Field label="Accenture Reference" icon={User}>
            <input
              type="text"
              placeholder="e.g. contact name or engagement code (optional)"
              value={accentureRef}
              onChange={e => setAccentureRef(e.target.value)}
              maxLength={100}
              className={inputCls}
            />
          </Field>

          {/* Global error */}
          {error && (
            <div className="flex items-center gap-2 text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2 text-sm">
              <AlertCircle size={14} /> {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-slate-100 bg-slate-50/40">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            disabled={confirmDisabled}
            className="flex items-center gap-2 px-5 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? (
              <><Loader2 size={14} className="animate-spin" /> Creating…</>
            ) : (
              <><CheckCircle size={14} /> Confirm &amp; Create Integrations</>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
