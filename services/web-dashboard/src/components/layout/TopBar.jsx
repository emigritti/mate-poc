import { useState } from 'react';
import { Bell, User } from 'lucide-react';
import UiModeToggle from '../pixel/UiModeToggle';

const USERS = [
  { id: 'admin',    label: 'Mario Rossi',    role: 'Admin' },
  { id: 'reviewer', label: 'Laura Bianchi', role: 'Reviewer' },
];

export default function TopBar({ title, subtitle }) {
  const [userId, setUserId] = useState('admin');
  const user = USERS.find(u => u.id === userId);

  return (
    <header className="flex items-center justify-between px-6 py-3 bg-white border-b border-slate-200 flex-shrink-0">
      <div>
        <h1
          className="text-slate-900 font-semibold text-lg leading-tight"
          style={{ fontFamily: 'Outfit, sans-serif' }}
        >
          {title}
        </h1>
        <p className="text-slate-400 text-xs mt-0.5">{subtitle}</p>
      </div>

      <div className="flex items-center gap-2">
        <UiModeToggle />

        <button className="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors">
          <Bell size={17} />
        </button>

        <div className="flex items-center gap-2 pl-3 border-l border-slate-200">
          <div className="w-7 h-7 rounded-full bg-indigo-100 flex items-center justify-center">
            <User size={13} className="text-indigo-600" />
          </div>
          <select
            value={userId}
            onChange={e => setUserId(e.target.value)}
            className="text-sm font-medium text-slate-700 bg-transparent border-none outline-none cursor-pointer pr-1"
          >
            {USERS.map(u => (
              <option key={u.id} value={u.id}>
                {u.label} ({u.role})
              </option>
            ))}
          </select>
        </div>
      </div>
    </header>
  );
}
