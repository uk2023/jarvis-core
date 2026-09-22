import React, { useState } from 'react';
import { motion } from 'motion/react';
import {
  Database,
  Search,
  Plus,
  Trash2,
  GitFork,
  Sliders,
  Sparkles,
  ShieldCheck,
  Tag,
  Share2,
  CheckCircle2,
} from 'lucide-react';
import { EngramFact, AppTheme } from '../types';

interface MemoryGraphViewerProps {
  engrams: EngramFact[];
  onAddEngram: (fact: { subject: string; predicate: string; value: string; tags: string[] }) => void;
  onDeleteEngram: (id: string) => void;
  theme?: AppTheme;
}

export const MemoryGraphViewer: React.FC<MemoryGraphViewerProps> = ({
  engrams,
  onAddEngram,
  onDeleteEngram,
  theme = 'dark',
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [similarityThreshold, setSimilarityThreshold] = useState(0.5);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newSub, setNewSub] = useState('');
  const [newPred, setNewPred] = useState('');
  const [newVal, setNewVal] = useState('');
  const [newTags, setNewTags] = useState('');
  const [selectedSubject, setSelectedSubject] = useState<string | null>(null);

  const isDark = theme === 'dark';

  // Filter engrams based on query
  const filteredEngrams = engrams.filter(k => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      k.subject.toLowerCase().includes(q) ||
      k.predicate.toLowerCase().includes(q) ||
      String(k.value).toLowerCase().includes(q) ||
      k.tags.some(t => t.toLowerCase().includes(q))
    );
  });

  // Extract unique subjects for graph nodes
  const distinctSubjects = Array.from(new Set(engrams.map(e => e.subject)));

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSub.trim() || !newPred.trim() || !newVal.trim()) return;

    const tagsArray = newTags
      .split(',')
      .map(t => t.trim().toLowerCase())
      .filter(Boolean);

    onAddEngram({
      subject: newSub.trim().toLowerCase(),
      predicate: newPred.trim().toLowerCase(),
      value: newVal.trim(),
      tags: tagsArray,
    });

    setNewSub('');
    setNewPred('');
    setNewVal('');
    setNewTags('');
    setShowAddModal(false);
  };

  return (
    <div
      id="memory-graph-view"
      className="h-full overflow-y-auto p-4 sm:p-6 max-w-5xl mx-auto space-y-6 select-text"
    >
      {/* Header & Stats Banner */}
      <div
        className={`border rounded-2xl p-5 shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 transition-colors ${
          isDark
            ? 'bg-[#0b0e17]/80 backdrop-blur-2xl border-white/10 shadow-2xl'
            : 'bg-white border-slate-200/90 shadow-sm'
        }`}
      >
        <div>
          <div className="flex items-center gap-2 mb-1">
            <div className="w-2.5 h-2.5 rounded-full bg-brand-500 animate-pulse shadow-[0_0_8px_#22d3ee]"></div>
            <h2
              className={`text-sm sm:text-base font-bold tracking-widest uppercase font-mono ${
                isDark ? 'text-brand-50' : 'text-slate-900'
              }`}
            >
              SEMANTIC MEMORY & FAISS VECTOR STORE
            </h2>
          </div>
          <p className={`text-xs font-mono ${isDark ? 'text-white/60' : 'text-slate-500'}`}>
            384-dimensional ONNX Embedding Index & NetworkX Directed Knowledge Graph
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div
            className={`border px-3.5 py-1.5 rounded-xl font-mono text-xs ${
              isDark
                ? 'bg-black/40 backdrop-blur-xl border-white/10 text-brand-200'
                : 'bg-slate-100 border-slate-200 text-slate-800'
            }`}
          >
            <span className={isDark ? 'text-white/40' : 'text-slate-500'}>ACTIVE ENGRAMS: </span>
            <span className="font-bold text-brand-600 dark:text-brand-300">{engrams.length}</span>
          </div>
          <button
            onClick={() => setShowAddModal(true)}
            className={`px-3.5 py-1.5 rounded-xl text-xs font-semibold font-mono flex items-center gap-1.5 transition cursor-pointer ${
              isDark
                ? 'bg-brand-400/15 hover:bg-brand-400/25 text-brand-200 border border-brand-400/40 shadow-[0_0_12px_rgba(34,211,238,0.2)]'
                : 'bg-brand-50 hover:bg-brand-100 text-brand-700 border border-brand-300 shadow-sm'
            }`}
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add Triple</span>
          </button>
        </div>
      </div>

      {/* Interactive Visual Relational Node Map */}
      <div
        className={`border rounded-2xl p-5 shadow-sm space-y-4 transition-colors ${
          isDark
            ? 'bg-[#0f121d]/80 backdrop-blur-2xl border-white/10 shadow-2xl'
            : 'bg-white border-slate-200/90 shadow-sm'
        }`}
      >
        <div className="flex items-center justify-between">
          <h3
            className={`text-xs font-bold font-mono flex items-center gap-2 uppercase tracking-wider ${
              isDark ? 'text-brand-300' : 'text-brand-700'
            }`}
          >
            <Share2 className="w-4 h-4 text-brand-500 dark:text-brand-400" /> Relational Knowledge Graph Nodes
          </h3>
          <span className={`text-xs font-mono ${isDark ? 'text-white/40' : 'text-slate-400'}`}>
            {distinctSubjects.length} Root Subjects &bull; {engrams.length} Edges
          </span>
        </div>

        {/* Subject Chips */}
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setSelectedSubject(null)}
            className={`px-3 py-1.5 rounded-xl font-mono text-xs transition border cursor-pointer ${
              selectedSubject === null
                ? isDark
                  ? 'bg-brand-400/20 text-brand-200 border-brand-400/50 font-bold shadow-[0_0_10px_rgba(34,211,238,0.2)]'
                  : 'bg-slate-900 text-white border-slate-900 font-bold shadow-sm'
                : isDark
                ? 'bg-black/30 text-white/50 border-white/10 hover:text-white hover:bg-white/5'
                : 'bg-slate-100 text-slate-600 border-slate-200 hover:text-slate-900 hover:bg-slate-200'
            }`}
          >
            All Subjects ({engrams.length})
          </button>
          {distinctSubjects.map(sub => {
            const count = engrams.filter(e => e.subject === sub).length;
            const isSelected = selectedSubject === sub;
            return (
              <button
                key={sub}
                onClick={() => setSelectedSubject(isSelected ? null : sub)}
                className={`px-3 py-1.5 rounded-xl font-mono text-xs transition border flex items-center gap-1.5 cursor-pointer ${
                  isSelected
                    ? isDark
                      ? 'bg-brand-400/20 text-brand-200 border-brand-400/50 font-bold shadow-[0_0_10px_rgba(34,211,238,0.2)]'
                      : 'bg-slate-900 text-white border-slate-900 font-bold shadow-sm'
                    : isDark
                    ? 'bg-black/30 text-white/50 border-white/10 hover:text-white hover:bg-white/5'
                    : 'bg-slate-100 text-slate-600 border-slate-200 hover:text-slate-900 hover:bg-slate-200'
                }`}
              >
                <GitFork className="w-3 h-3 text-brand-500 dark:text-brand-400" />
                <span>{sub}</span>
                <span className="text-xs opacity-70">({count})</span>
              </button>
            );
          })}
        </div>

        {/* Node Chain Visualizer Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
          {engrams
            .filter(e => (selectedSubject ? e.subject === selectedSubject : true))
            .map(e => (
              <div
                key={e.id}
                className={`border p-3.5 rounded-2xl text-xs font-mono space-y-2 transition ${
                  isDark
                    ? 'bg-black/40 backdrop-blur-xl border-white/10 hover:border-brand-400/40 shadow-xl'
                    : 'bg-slate-50 border-slate-200 hover:border-brand-400 shadow-sm'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-brand-600 dark:text-brand-300 font-bold text-xs">({e.subject})</span>
                  <span className={`text-xs ${isDark ? 'text-white/40' : 'text-slate-400'}`}>
                    FAISS #{e.faissId}
                  </span>
                </div>

                <div className="pl-3 border-l-2 border-brand-500/40 space-y-1">
                  <div className={`font-semibold text-xs ${isDark ? 'text-brand-200' : 'text-brand-800'}`}>
                    ──[ <span className="underline decoration-brand-400/50">{e.predicate}</span> ]──&gt;
                  </div>
                  <div
                    className={`text-xs p-2.5 rounded-xl border break-words ${
                      isDark
                        ? 'text-white bg-brand-400/10 border-brand-400/20'
                        : 'text-slate-900 bg-white border-slate-200 shadow-xs'
                    }`}
                  >
                    {String(e.value)}
                  </div>
                </div>

                <div
                  className={`flex items-center justify-between text-xs pt-1 border-t ${
                    isDark ? 'text-white/40 border-white/5' : 'text-slate-500 border-slate-200'
                  }`}
                >
                  <span>Confidence: {(e.confidence * 100).toFixed(0)}%</span>
                  <span>Evidences: {e.evidenceCount}</span>
                </div>
              </div>
            ))}
        </div>
      </div>

      {/* FAISS Vector Search Playground */}
      <div
        className={`border rounded-2xl p-5 shadow-sm space-y-4 transition-colors ${
          isDark
            ? 'bg-[#0f121d]/80 backdrop-blur-2xl border-white/10 shadow-2xl'
            : 'bg-white border-slate-200/90 shadow-sm'
        }`}
      >
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div
            className={`flex items-center gap-2 font-mono text-xs font-bold uppercase tracking-wider ${
              isDark ? 'text-brand-300' : 'text-brand-700'
            }`}
          >
            <Search className="w-4 h-4 text-brand-500 dark:text-brand-400" />
            <span>Hybrid Search & Cosine Threshold Sandbox</span>
          </div>

          <div className="flex items-center gap-3 w-full sm:w-auto">
            <div className={`flex items-center gap-2 font-mono text-xs ${isDark ? 'text-white/60' : 'text-slate-600'}`}>
              <Sliders className="w-3.5 h-3.5 text-brand-500 dark:text-brand-400" />
              <span>Threshold: {similarityThreshold}</span>
            </div>
            <input
              type="range"
              min="0.1"
              max="0.95"
              step="0.05"
              value={similarityThreshold}
              onChange={e => setSimilarityThreshold(parseFloat(e.target.value))}
              className="accent-brand-500 w-28 cursor-pointer"
            />
          </div>
        </div>

        <div className="relative">
          <Search className={`absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 ${isDark ? 'text-white/40' : 'text-slate-400'}`} />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Type query to test vector recall (e.g. 'earphone mic', 'ex partner', 'model name')..."
            className={`w-full border rounded-xl pl-10 pr-4 py-2.5 text-xs font-mono outline-none transition ${
              isDark
                ? 'bg-black/40 backdrop-blur-xl border-white/10 focus:border-brand-400 text-white placeholder-white/40 shadow-inner'
                : 'bg-slate-50 border-slate-300 focus:border-brand-500 text-slate-900 placeholder-slate-400'
            }`}
          />
        </div>

        {/* Engrams Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left font-mono text-xs border-collapse">
            <thead>
              <tr
                className={`border-b text-xs uppercase ${
                  isDark ? 'border-white/10 text-white/40' : 'border-slate-200 text-slate-500'
                }`}
              >
                <th className="py-2.5 px-3">Subject</th>
                <th className="py-2.5 px-3">Predicate</th>
                <th className="py-2.5 px-3">Value / Target</th>
                <th className="py-2.5 px-3 text-center">Confidence</th>
                <th className="py-2.5 px-3 text-center">Actions</th>
              </tr>
            </thead>
            <tbody className={`divide-y ${isDark ? 'divide-white/5' : 'divide-slate-100'}`}>
              {filteredEngrams.map(item => (
                <tr
                  key={item.id}
                  className={`transition ${isDark ? 'hover:bg-white/5' : 'hover:bg-slate-50'}`}
                >
                  <td className="py-3 px-3 text-brand-600 dark:text-brand-300 font-bold">{item.subject}</td>
                  <td className={`py-3 px-3 ${isDark ? 'text-brand-100' : 'text-slate-700'}`}>{item.predicate}</td>
                  <td className={`py-3 px-3 max-w-xs truncate ${isDark ? 'text-white' : 'text-slate-900'}`}>
                    {String(item.value)}
                  </td>
                  <td className="py-3 px-3 text-center">
                    <span
                      className={`px-2 py-0.5 rounded-lg text-xs border ${
                        isDark
                          ? 'bg-green-400/10 text-green-400 border-green-400/30'
                          : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                      }`}
                    >
                      {(item.confidence * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="py-3 px-3 text-center">
                    <button
                      onClick={() => onDeleteEngram(item.id)}
                      className="text-red-500 hover:text-red-600 p-1.5 rounded-lg hover:bg-red-500/10 transition cursor-pointer"
                      title="Forget engram"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add Engram Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-md z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ scale: 0.95, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            className={`border rounded-3xl p-6 w-full max-w-md shadow-2xl space-y-4 ${
              isDark
                ? 'bg-[#050508]/95 backdrop-blur-2xl border-white/20 text-white'
                : 'bg-white border-slate-300 text-slate-900'
            }`}
          >
            <h3
              className={`text-sm font-bold font-mono flex items-center gap-2 uppercase tracking-wider ${
                isDark ? 'text-brand-50' : 'text-slate-900'
              }`}
            >
              <Plus className="w-4 h-4 text-brand-500 dark:text-brand-400" /> Add Semantic Memory Triple
            </h3>

            <form onSubmit={handleAddSubmit} className="space-y-3 font-mono text-xs">
              <div>
                <label className={`text-xs block mb-1 ${isDark ? 'text-white/50' : 'text-slate-500'}`}>
                  Subject Node (e.g. 'user', 'project')
                </label>
                <input
                  type="text"
                  required
                  value={newSub}
                  onChange={e => setNewSub(e.target.value)}
                  className={`w-full border rounded-xl px-3 py-2 outline-none ${
                    isDark
                      ? 'bg-black/40 border-white/10 text-white focus:border-brand-400'
                      : 'bg-slate-50 border-slate-300 text-slate-900 focus:border-brand-500'
                  }`}
                />
              </div>

              <div>
                <label className={`text-xs block mb-1 ${isDark ? 'text-white/50' : 'text-slate-500'}`}>
                  Predicate Relation (e.g. 'favorite_tool')
                </label>
                <input
                  type="text"
                  required
                  value={newPred}
                  onChange={e => setNewPred(e.target.value)}
                  className={`w-full border rounded-xl px-3 py-2 outline-none ${
                    isDark
                      ? 'bg-black/40 border-white/10 text-white focus:border-brand-400'
                      : 'bg-slate-50 border-slate-300 text-slate-900 focus:border-brand-500'
                  }`}
                />
              </div>

              <div>
                <label className={`text-xs block mb-1 ${isDark ? 'text-white/50' : 'text-slate-500'}`}>
                  Value / Fact (e.g. 'VS Code & MT Manager')
                </label>
                <textarea
                  rows={2}
                  required
                  value={newVal}
                  onChange={e => setNewVal(e.target.value)}
                  className={`w-full border rounded-xl px-3 py-2 outline-none resize-none ${
                    isDark
                      ? 'bg-black/40 border-white/10 text-white focus:border-brand-400'
                      : 'bg-slate-50 border-slate-300 text-slate-900 focus:border-brand-500'
                  }`}
                />
              </div>

              <div>
                <label className={`text-xs block mb-1 ${isDark ? 'text-white/50' : 'text-slate-500'}`}>
                  Tags (Comma-separated)
                </label>
                <input
                  type="text"
                  value={newTags}
                  onChange={e => setNewTags(e.target.value)}
                  placeholder="editor, tools, coding"
                  className={`w-full border rounded-xl px-3 py-2 outline-none ${
                    isDark
                      ? 'bg-black/40 border-white/10 text-white focus:border-brand-400'
                      : 'bg-slate-50 border-slate-300 text-slate-900 focus:border-brand-500'
                  }`}
                />
              </div>

              <div className={`flex justify-end gap-2 pt-3 border-t ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className={`px-4 py-2 rounded-xl transition ${
                    isDark ? 'text-white/60 hover:text-white' : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className={`px-4 py-2 font-bold rounded-xl transition cursor-pointer shadow-md ${
                    isDark
                      ? 'bg-brand-400 hover:bg-brand-300 text-black shadow-[0_0_10px_#22d3ee]'
                      : 'bg-slate-900 hover:bg-slate-800 text-white'
                  }`}
                >
                  Save Engram
                </button>
              </div>
            </form>
          </motion.div>
        </div>
      )}
    </div>
  );
};
