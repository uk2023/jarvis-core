import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { Pin, Pencil, Trash2, X, Check } from 'lucide-react';
import { ChatSession, AppTheme } from '../types';

interface SessionActionSheetProps {
  session: ChatSession | null;
  isOpen: boolean;
  onClose: () => void;
  onPinToggle: (sessionId: string) => void;
  onRename: (sessionId: string, newTitle: string) => void;
  onDelete: (sessionId: string) => void;
  theme: AppTheme;
}

export const SessionActionSheet: React.FC<SessionActionSheetProps> = ({
  session,
  isOpen,
  onClose,
  onPinToggle,
  onRename,
  onDelete,
  theme,
}) => {
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState('');

  useEffect(() => {
    if (session) {
      setRenameValue(session.title);
      setIsRenaming(false);
    }
  }, [session, isOpen]);

  if (!isOpen || !session) return null;

  const handleSaveRename = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const trimmed = renameValue.trim();
    if (trimmed && session) {
      onRename(session.sessionId, trimmed);
      setIsRenaming(false);
      onClose();
    }
  };

  const isDark = theme === 'dark';

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="fixed inset-0 bg-black/70 backdrop-blur-sm"
        />

        {/* Bottom Sheet Modal (Responsive: bottom sheet on mobile, rounded card on tablet/desktop) */}
        <motion.div
          initial={{ y: '100%', opacity: 0.5 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: '100%', opacity: 0 }}
          transition={{ type: 'spring', damping: 28, stiffness: 300 }}
          className={`relative w-full sm:max-w-md rounded-t-[28px] sm:rounded-3xl p-5 sm:p-6 shadow-2xl z-10 font-mono transition-colors ${
            isDark
              ? 'bg-[#0b0e17] border-t sm:border border-white/15 text-white'
              : 'bg-white border-t sm:border border-slate-200 text-slate-800'
          }`}
        >
          {/* Drag Pill Handle */}
          <div className={`w-12 h-1.5 rounded-full mx-auto mb-4 ${isDark ? 'bg-white/20' : 'bg-slate-300'}`} />

          {/* Session Title Header */}
          <div className="text-center mb-5 px-2">
            <h3
              className={`text-xs font-semibold uppercase tracking-wider truncate ${
                isDark ? 'text-white/60' : 'text-slate-500'
              }`}
            >
              {session.title}
            </h3>
            <span className="text-xs text-brand-400/80 tracking-normal">
              {session.msgCount} {session.msgCount === 1 ? 'message' : 'messages'}
            </span>
          </div>

          {/* Inline Rename Form */}
          {isRenaming ? (
            <form onSubmit={handleSaveRename} className="space-y-4 mb-3">
              <div>
                <label className={`block text-xs mb-1.5 ${isDark ? 'text-white/70' : 'text-slate-600'}`}>
                  Thread Title
                </label>
                <input
                  type="text"
                  autoFocus
                  value={renameValue}
                  onChange={e => setRenameValue(e.target.value)}
                  className={`w-full px-3.5 py-2.5 rounded-xl text-xs font-sans outline-none border transition ${
                    isDark
                      ? 'bg-white/5 border-white/20 text-white focus:border-brand-400'
                      : 'bg-slate-50 border-slate-300 text-slate-900 focus:border-brand-500'
                  }`}
                  placeholder="Enter new title..."
                />
              </div>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setIsRenaming(false)}
                  className={`flex-1 py-2.5 rounded-xl text-xs font-medium transition cursor-pointer ${
                    isDark ? 'bg-white/10 hover:bg-white/15 text-white/80' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                  }`}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!renameValue.trim()}
                  className="flex-1 py-2.5 rounded-xl bg-brand-400 hover:bg-brand-300 text-black text-xs font-bold transition flex items-center justify-center gap-1.5 shadow-sm disabled:opacity-50 cursor-pointer"
                >
                  <Check className="w-3.5 h-3.5" />
                  <span>Save</span>
                </button>
              </div>
            </form>
          ) : (
            /* Action Options List (Matching Screenshot 3) */
            <div className="space-y-1.5 mb-5">
              {/* Pin / Unpin */}
              <button
                onClick={() => {
                  onPinToggle(session.sessionId);
                  onClose();
                }}
                className={`w-full flex items-center gap-3.5 px-4 py-3.5 rounded-2xl transition cursor-pointer text-left ${
                  isDark ? 'hover:bg-white/5 text-white' : 'hover:bg-slate-100 text-slate-800'
                }`}
              >
                <div className="w-6 h-6 flex items-center justify-center text-amber-400">
                  <Pin className="w-4 h-4" />
                </div>
                <span className="text-xs sm:text-sm font-sans font-medium">
                  {session.pinned ? 'Unpin' : 'Pin'}
                </span>
              </button>

              {/* Rename */}
              <button
                onClick={() => setIsRenaming(true)}
                className={`w-full flex items-center gap-3.5 px-4 py-3.5 rounded-2xl transition cursor-pointer text-left ${
                  isDark ? 'hover:bg-white/5 text-white' : 'hover:bg-slate-100 text-slate-800'
                }`}
              >
                <div className="w-6 h-6 flex items-center justify-center text-brand-400">
                  <Pencil className="w-4 h-4" />
                </div>
                <span className="text-xs sm:text-sm font-sans font-medium">Rename</span>
              </button>

              {/* Delete */}
              <button
                onClick={() => {
                  onDelete(session.sessionId);
                  onClose();
                }}
                className={`w-full flex items-center gap-3.5 px-4 py-3.5 rounded-2xl transition cursor-pointer text-left ${
                  isDark ? 'hover:bg-red-500/10 text-red-400' : 'hover:bg-red-50 text-red-600'
                }`}
              >
                <div className="w-6 h-6 flex items-center justify-center text-red-400">
                  <Trash2 className="w-4 h-4" />
                </div>
                <span className="text-xs sm:text-sm font-sans font-medium">Delete</span>
              </button>
            </div>
          )}

          {/* Big Cancel Button */}
          {!isRenaming && (
            <button
              type="button"
              onClick={onClose}
              className={`w-full py-3.5 rounded-2xl text-xs sm:text-sm font-medium transition cursor-pointer font-sans ${
                isDark
                  ? 'bg-white/5 hover:bg-white/10 text-white/80 border border-white/10'
                  : 'bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200'
              }`}
            >
              Cancel
            </button>
          )}
        </motion.div>
      </div>
    </AnimatePresence>
  );
};
