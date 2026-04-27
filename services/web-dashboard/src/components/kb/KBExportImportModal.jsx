import { useState, useRef } from 'react';
import { X, Download, Upload, Loader2, CheckCircle, AlertCircle } from 'lucide-react';
import { API } from '../../api.js';

const ALL_SOURCE_TYPES = [
    { id: 'file',    label: 'Uploaded Files',   desc: 'PDF, Word, Excel, Markdown documents' },
    { id: 'url',     label: 'URL Links',          desc: 'Registered HTTP/HTTPS references' },
    { id: 'openapi', label: 'OpenAPI Sources',    desc: 'Ingested Swagger / OpenAPI specs' },
    { id: 'html',    label: 'HTML Sources',       desc: 'Crawled documentation pages' },
    { id: 'mcp',     label: 'MCP Sources',        desc: 'Model Context Protocol server capabilities' },
];

function SourceTypeCheckboxes({ selected, onChange }) {
    const toggle = (id) =>
        onChange(selected.includes(id) ? selected.filter(s => s !== id) : [...selected, id]);

    return (
        <div className="space-y-2">
            {ALL_SOURCE_TYPES.map(st => (
                <label
                    key={st.id}
                    className="flex items-start gap-3 p-3 rounded-lg border border-slate-200 cursor-pointer hover:bg-slate-50 transition-colors"
                >
                    <input
                        type="checkbox"
                        className="mt-0.5 accent-indigo-500"
                        checked={selected.includes(st.id)}
                        onChange={() => toggle(st.id)}
                    />
                    <div>
                        <p className="text-sm font-medium text-slate-800">{st.label}</p>
                        <p className="text-xs text-slate-500">{st.desc}</p>
                    </div>
                </label>
            ))}
        </div>
    );
}

export default function KBExportImportModal({ onClose, onImportDone }) {
    const [tab, setTab] = useState('export');

    // Export state
    const [exportTypes, setExportTypes] = useState(ALL_SOURCE_TYPES.map(s => s.id));
    const [exporting, setExporting] = useState(false);
    const [exportError, setExportError] = useState(null);

    // Import state
    const [importTypes, setImportTypes] = useState(ALL_SOURCE_TYPES.map(s => s.id));
    const [overwrite, setOverwrite] = useState(false);
    const [importFile, setImportFile] = useState(null);
    const [importing, setImporting] = useState(false);
    const [importResult, setImportResult] = useState(null);
    const [importError, setImportError] = useState(null);
    const fileInputRef = useRef(null);

    const handleExport = async () => {
        if (exportTypes.length === 0) return;
        setExporting(true);
        setExportError(null);
        try {
            const res = await API.kb.export(exportTypes.join(','));
            if (!res.ok) {
                const d = await res.json().catch(() => ({}));
                throw new Error(d.detail || `Export failed (${res.status})`);
            }
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `kb_export_${new Date().toISOString().slice(0, 10)}.json`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        } catch (e) {
            setExportError(e.message);
        } finally {
            setExporting(false);
        }
    };

    const handleImport = async () => {
        if (!importFile || importTypes.length === 0) return;
        setImporting(true);
        setImportError(null);
        setImportResult(null);
        try {
            const res = await API.kb.import(importFile, importTypes.join(','), overwrite);
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || `Import failed (${res.status})`);
            setImportResult(data);
            onImportDone?.();
        } catch (e) {
            setImportError(e.message);
        } finally {
            setImporting(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
            <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 overflow-hidden">
                {/* Header */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
                    <h2 className="font-semibold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                        KB Export / Import
                    </h2>
                    <button
                        onClick={onClose}
                        className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
                    >
                        <X size={16} />
                    </button>
                </div>

                {/* Tabs */}
                <div className="flex border-b border-slate-200">
                    {[
                        { id: 'export', label: 'Export', icon: Download },
                        { id: 'import', label: 'Import', icon: Upload },
                    ].map(t => (
                        <button
                            key={t.id}
                            onClick={() => setTab(t.id)}
                            className={`flex items-center gap-2 px-6 py-3 text-sm font-medium border-b-2 -mb-px transition-colors ${
                                tab === t.id
                                    ? 'border-indigo-500 text-indigo-600'
                                    : 'border-transparent text-slate-500 hover:text-slate-700'
                            }`}
                        >
                            <t.icon size={14} />
                            {t.label}
                        </button>
                    ))}
                </div>

                <div className="p-6 space-y-5 max-h-[70vh] overflow-y-auto">
                    {/* ── EXPORT TAB ── */}
                    {tab === 'export' && (
                        <>
                            <p className="text-sm text-slate-500">
                                Download the Knowledge Base as a portable JSON bundle.
                                Select which source types to include.
                            </p>
                            <SourceTypeCheckboxes selected={exportTypes} onChange={setExportTypes} />

                            {exportError && (
                                <div className="flex items-center gap-2 text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2 text-sm">
                                    <AlertCircle size={14} /> {exportError}
                                </div>
                            )}

                            <button
                                onClick={handleExport}
                                disabled={exporting || exportTypes.length === 0}
                                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                            >
                                {exporting
                                    ? <><Loader2 size={14} className="animate-spin" /> Exporting…</>
                                    : <><Download size={14} /> Download JSON bundle</>
                                }
                            </button>
                        </>
                    )}

                    {/* ── IMPORT TAB ── */}
                    {tab === 'import' && (
                        <>
                            <p className="text-sm text-slate-500">
                                Restore the Knowledge Base from a previously exported JSON bundle.
                                Select which source types to import.
                            </p>

                            {/* File picker */}
                            <div>
                                <label className="block text-xs font-semibold text-slate-600 mb-1.5">
                                    Bundle file (.json)
                                </label>
                                <div
                                    onClick={() => fileInputRef.current?.click()}
                                    className="border-2 border-dashed border-slate-200 rounded-lg p-4 text-center cursor-pointer hover:border-indigo-300 hover:bg-slate-50 transition-colors"
                                >
                                    <input
                                        ref={fileInputRef}
                                        type="file"
                                        accept=".json,application/json"
                                        className="hidden"
                                        onChange={e => {
                                            setImportFile(e.target.files[0] || null);
                                            setImportResult(null);
                                            setImportError(null);
                                        }}
                                    />
                                    {importFile
                                        ? <p className="text-sm text-indigo-700 font-medium">{importFile.name}</p>
                                        : <p className="text-sm text-slate-400">Click to select a JSON bundle</p>
                                    }
                                </div>
                            </div>

                            {/* Source type filter */}
                            <div>
                                <label className="block text-xs font-semibold text-slate-600 mb-1.5">
                                    Source types to import
                                </label>
                                <SourceTypeCheckboxes selected={importTypes} onChange={setImportTypes} />
                            </div>

                            {/* Overwrite toggle */}
                            <label className="flex items-center gap-3 cursor-pointer">
                                <input
                                    type="checkbox"
                                    className="accent-indigo-500"
                                    checked={overwrite}
                                    onChange={e => setOverwrite(e.target.checked)}
                                />
                                <span className="text-sm text-slate-700">
                                    Overwrite existing documents (same ID)
                                </span>
                            </label>

                            {importError && (
                                <div className="flex items-center gap-2 text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2 text-sm">
                                    <AlertCircle size={14} /> {importError}
                                </div>
                            )}

                            {importResult && (
                                <div className="bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3 text-sm space-y-1">
                                    <p className="flex items-center gap-2 font-medium text-emerald-800">
                                        <CheckCircle size={14} /> Import complete
                                    </p>
                                    <ul className="text-emerald-700 space-y-0.5 pl-5 list-disc text-xs">
                                        <li>Documents imported: <strong>{importResult.documents_imported}</strong></li>
                                        <li>Documents skipped: <strong>{importResult.documents_skipped}</strong></li>
                                        <li>Chunks imported: <strong>{importResult.chunks_imported}</strong></li>
                                        <li>Chunks skipped: <strong>{importResult.chunks_skipped}</strong></li>
                                    </ul>
                                    {importResult.errors?.length > 0 && (
                                        <p className="text-amber-700 text-xs mt-1">
                                            {importResult.errors.length} warning(s): {importResult.errors[0]}
                                        </p>
                                    )}
                                </div>
                            )}

                            <button
                                onClick={handleImport}
                                disabled={importing || !importFile || importTypes.length === 0}
                                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                            >
                                {importing
                                    ? <><Loader2 size={14} className="animate-spin" /> Importing…</>
                                    : <><Upload size={14} /> Import bundle</>
                                }
                            </button>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
