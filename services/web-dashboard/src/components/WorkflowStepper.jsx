import { Upload, Tags, Bot, CheckCircle, BookOpen, Check } from 'lucide-react';

const STEPS = [
  { id: 1, label: 'Upload Requirements', desc: 'Load CSV with integration specs',  icon: Upload },
  { id: 2, label: 'Confirm Tags',        desc: 'Review RAG context tags',          icon: Tags },
  { id: 3, label: 'Run Agent',           desc: 'AI generates integration docs',    icon: Bot },
  { id: 4, label: 'Review & Approve',    desc: 'Human-in-the-loop approval',       icon: CheckCircle },
  { id: 5, label: 'View Catalog',        desc: 'Browse final specifications',       icon: BookOpen },
];

export default function WorkflowStepper({ activeStep }) {
  return (
    <div className="bg-white border-b border-slate-200 px-6 py-3 flex-shrink-0">
      <div className="flex items-center">
        {STEPS.map((step, index) => {
          const done   = step.id < activeStep;
          const active = step.id === activeStep;
          const Icon   = step.icon;

          return (
            <div key={step.id} className="flex items-center flex-1 last:flex-none">
              {/* Step node */}
              <div className="flex items-center gap-2.5">
                <div
                  className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 transition-all duration-300 ${
                    done
                      ? 'bg-emerald-500 text-white'
                      : active
                      ? 'bg-indigo-600 text-white ring-4 ring-indigo-100'
                      : 'bg-slate-100 text-slate-400'
                  }`}
                >
                  {done ? <Check size={13} strokeWidth={3} /> : <Icon size={13} />}
                </div>

                <div className="hidden sm:block">
                  <p
                    className={`text-xs font-semibold leading-tight whitespace-nowrap ${
                      active ? 'text-indigo-700'
                      : done  ? 'text-emerald-700'
                      : 'text-slate-400'
                    }`}
                    style={{ fontFamily: 'Outfit, sans-serif' }}
                  >
                    {step.label}
                  </p>
                  <p className={`text-[10px] leading-tight whitespace-nowrap ${active || done ? 'text-slate-400' : 'text-slate-300'}`}>
                    {step.desc}
                  </p>
                </div>
              </div>

              {/* Connector */}
              {index < STEPS.length - 1 && (
                <div
                  className={`flex-1 h-0.5 mx-3 rounded-full transition-all duration-300 ${
                    done ? 'bg-emerald-400' : 'bg-slate-200'
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
