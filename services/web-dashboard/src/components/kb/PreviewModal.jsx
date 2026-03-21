import { X } from 'lucide-react';

function PreviewModal({ doc, onClose }) {
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in"
            onClick={onClose}>
            <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl mx-4 max-h-[80vh] overflow-hidden flex flex-col"
                onClick={e => e.stopPropagation()}>
                <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between flex-shrink-0">
                    <div>
                        <h3 className="font-semibold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                            Content Preview
                        </h3>
                        <p className="text-xs text-slate-400 mt-0.5">
                            {doc.filename}{doc.chunk_count != null ? ` · ${doc.chunk_count} chunks` : ''}
                        </p>
                    </div>
                    <button onClick={onClose} className="p-1 hover:bg-slate-100 rounded-lg transition-colors">
                        <X size={18} className="text-slate-400" />
                    </button>
                </div>
                <div className="px-6 py-5 overflow-y-auto flex-1">
                    <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans leading-relaxed">
                        {doc.content_preview || 'No preview available.'}
                    </pre>
                </div>
            </div>
        </div>
    );
}

export default PreviewModal;
