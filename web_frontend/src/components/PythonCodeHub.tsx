import React, { useState } from 'react';
import {
  Code,
  Copy,
  Check,
  Download,
  FileCode,
  Terminal,
  Cpu,
  Layers,
  Sparkles,
  BookOpen,
} from 'lucide-react';
import { PYTHON_CODEBASE } from '../data/pythonCodebase';
import { PythonCodeFile, AppTheme } from '../types';

interface PythonCodeHubProps {
  theme?: AppTheme;
}

export const PythonCodeHub: React.FC<PythonCodeHubProps> = ({ theme = 'dark' }) => {
  const [selectedFile, setSelectedFile] = useState<PythonCodeFile>(PYTHON_CODEBASE[0]);
  const [copied, setCopied] = useState(false);
  const [dumpDownloaded, setDumpDownloaded] = useState(false);

  const isDark = theme === 'dark';

  const handleCopy = () => {
    navigator.clipboard.writeText(selectedFile.code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownloadFile = () => {
    const blob = new Blob([selectedFile.code], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = selectedFile.filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleDownloadFullDump = () => {
    let fullDump = `# ==============================================================================
# JARVIS ORGANISM - FULL MASTER REPOSITORY DUMP
# Target: Android 8GB RAM (Termux / PRoot ARM64 Ready)
# Cognitive Pipeline: Native-first with Groq openai/gpt-oss-120b fallback (Gemini backup)
# Architecture: Non-blocking Async Background Learning + Typo Tolerance
# ==============================================================================
`;

    PYTHON_CODEBASE.forEach(file => {
      fullDump += `\n\n--- FILE: ${file.path} ---\n\n${file.code}`;
    });

    const blob = new Blob([fullDump], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'project_dump.txt';
    link.click();
    URL.revokeObjectURL(url);
    setDumpDownloaded(true);
    setTimeout(() => setDumpDownloaded(false), 3000);
  };

  return (
    <div
      id="python-code-hub-view"
      className="h-full overflow-y-auto p-4 sm:p-6 max-w-6xl mx-auto space-y-6 select-text"
    >
      {/* Header Banner */}
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
              JARVIS PYTHON CORE CODEBASE & EXPORTER
            </h2>
          </div>
          <p className={`text-xs font-mono ${isDark ? 'text-white/60' : 'text-slate-500'}`}>
            Full Production Codes with Async Background Learning, Fast ONNX Vector Store & Qwen 3B Bridge
          </p>
        </div>

        <button
          onClick={handleDownloadFullDump}
          className={`px-4 py-2 rounded-xl text-xs font-bold font-mono flex items-center gap-2 transition shrink-0 cursor-pointer shadow-md ${
            isDark
              ? 'bg-brand-400 hover:bg-brand-300 text-black shadow-[0_0_15px_#22d3ee]'
              : 'bg-slate-900 hover:bg-slate-800 text-white'
          }`}
        >
          <Download className="w-4 h-4" />
          <span>{dumpDownloaded ? 'Dump Generated!' : 'Download project_dump.txt'}</span>
        </button>
      </div>

      {/* Android 8GB RAM & Termux Setup Card */}
      <div
        className={`border rounded-2xl p-4 sm:p-5 font-mono text-xs space-y-3 transition-colors ${
          isDark
            ? 'bg-black/40 backdrop-blur-2xl border-white/10 text-white/80 shadow-xl'
            : 'bg-white border-slate-200 text-slate-700 shadow-sm'
        }`}
      >
        <div
          className={`flex items-center gap-2 font-bold text-xs uppercase tracking-wider ${
            isDark ? 'text-brand-300' : 'text-brand-700'
          }`}
        >
          <Cpu className="w-4 h-4 text-brand-500 dark:text-brand-400" />
          <span>Android 8GB RAM Offline Model Recommendation & Fast Execution Parameters</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
          <div
            className={`p-3.5 rounded-xl border ${
              isDark ? 'bg-white/5 border-white/10' : 'bg-slate-50 border-slate-200'
            }`}
          >
            <div className={`font-bold mb-1 ${isDark ? 'text-brand-300' : 'text-brand-800'}`}>1. Cognitive Architecture</div>
            <p className={isDark ? 'text-white/60' : 'text-slate-600'}>
              <strong className={isDark ? 'text-white' : 'text-slate-900'}>Native Python Pipeline</strong> first with <strong className={isDark ? 'text-white' : 'text-slate-900'}>Groq openai/gpt-oss-120b</strong> fallback (and Gemini secondary).
            </p>
          </div>
          <div
            className={`p-3.5 rounded-xl border ${
              isDark ? 'bg-white/5 border-white/10' : 'bg-slate-50 border-slate-200'
            }`}
          >
            <div className={`font-bold mb-1 ${isDark ? 'text-brand-300' : 'text-brand-800'}`}>2. Multi-Threading</div>
            <p className={isDark ? 'text-white/60' : 'text-slate-600'}>
              Set <code className={isDark ? 'text-brand-200' : 'text-brand-800 font-semibold'}>n_threads=4</code>, <code className={isDark ? 'text-brand-200' : 'text-brand-800 font-semibold'}>OMP_NUM_THREADS=2</code>, and <code className={isDark ? 'text-brand-200' : 'text-brand-800 font-semibold'}>n_ctx=4096</code> to maximize CPU efficiency.
            </p>
          </div>
          <div
            className={`p-3.5 rounded-xl border ${
              isDark ? 'bg-white/5 border-white/10' : 'bg-slate-50 border-slate-200'
            }`}
          >
            <div className={`font-bold mb-1 ${isDark ? 'text-green-300' : 'text-emerald-800'}`}>3. Fast Setup</div>
            <p className={isDark ? 'text-white/60' : 'text-slate-600'}>
              Run <code className={isDark ? 'text-green-200' : 'text-emerald-800 font-semibold'}>bash download.sh</code> to configure ONNX MiniLM embedder (~45MB) and SQLite + FAISS indices.
            </p>
          </div>
        </div>
      </div>

      {/* Code File Explorer Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 items-start">
        {/* Sidebar File List */}
        <div
          className={`border rounded-2xl p-3 space-y-1.5 font-mono text-xs transition-colors ${
            isDark
              ? 'bg-[#0f121d]/80 backdrop-blur-2xl border-white/10 shadow-xl'
              : 'bg-white border-slate-200 shadow-sm'
          }`}
        >
          <div
            className={`text-xs uppercase font-bold px-2 py-1 tracking-wider ${
              isDark ? 'text-white/40' : 'text-slate-400'
            }`}
          >
            Repository Files ({PYTHON_CODEBASE.length})
          </div>
          {PYTHON_CODEBASE.map(file => {
            const isSelected = selectedFile.filename === file.filename;
            return (
              <button
                key={file.filename}
                onClick={() => setSelectedFile(file)}
                className={`w-full flex items-center justify-between px-3 py-2 rounded-xl transition text-left cursor-pointer ${
                  isSelected
                    ? isDark
                      ? 'bg-brand-400/20 text-brand-200 border border-brand-400/40 font-bold shadow-[0_0_10px_rgba(34,211,238,0.2)]'
                      : 'bg-slate-900 text-white border border-slate-900 font-bold shadow-xs'
                    : isDark
                    ? 'text-white/60 hover:text-white hover:bg-white/5 border border-transparent'
                    : 'text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-2 truncate">
                  <FileCode className={`w-3.5 h-3.5 shrink-0 ${isSelected ? (isDark ? 'text-brand-300' : 'text-brand-400') : 'text-brand-500'}`} />
                  <span className="truncate">{file.filename}</span>
                </div>
                <span
                  className={`text-xs uppercase px-1.5 py-0.5 rounded ${
                    isSelected && !isDark
                      ? 'bg-white/20 text-white'
                      : isDark
                      ? 'bg-black/40 text-white/40'
                      : 'bg-slate-100 text-slate-500'
                  }`}
                >
                  {file.category}
                </span>
              </button>
            );
          })}
        </div>

        {/* Code Editor Preview Window */}
        <div
          className={`lg:col-span-3 border rounded-2xl overflow-hidden flex flex-col font-mono text-xs transition-colors ${
            isDark
              ? 'bg-[#0f121d]/80 backdrop-blur-2xl border-white/10 shadow-2xl'
              : 'bg-white border-slate-200 shadow-sm'
          }`}
        >
          {/* File Toolbar */}
          <div
            className={`flex items-center justify-between px-4 py-3 border-b ${
              isDark ? 'bg-black/40 border-white/10' : 'bg-slate-50 border-slate-200'
            }`}
          >
            <div>
              <div
                className={`font-bold text-xs flex items-center gap-2 ${
                  isDark ? 'text-white' : 'text-slate-900'
                }`}
              >
                <Terminal className="w-3.5 h-3.5 text-brand-500" />
                <span>{selectedFile.path}</span>
              </div>
              <p className={`text-xs mt-0.5 ${isDark ? 'text-white/40' : 'text-slate-500'}`}>
                {selectedFile.description}
              </p>
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={handleCopy}
                className={`px-3 py-1.5 border rounded-xl text-xs flex items-center gap-1.5 transition cursor-pointer ${
                  isDark
                    ? 'bg-white/5 hover:bg-white/10 border-white/10 text-brand-200 hover:text-white'
                    : 'bg-white hover:bg-slate-100 border-slate-300 text-slate-700 hover:text-slate-900 shadow-xs'
                }`}
                title="Copy file content"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-emerald-500" /> : <Copy className="w-3.5 h-3.5" />}
                <span>{copied ? 'Copied' : 'Copy'}</span>
              </button>
              <button
                onClick={handleDownloadFile}
                className={`px-3 py-1.5 border rounded-xl text-xs flex items-center gap-1.5 transition cursor-pointer ${
                  isDark
                    ? 'bg-brand-400/20 hover:bg-brand-400/30 border-brand-400/40 text-brand-200'
                    : 'bg-slate-900 hover:bg-slate-800 text-white border-slate-900 shadow-xs'
                }`}
                title="Download this file"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Save</span>
              </button>
            </div>
          </div>

          {/* Code Viewer */}
          <div
            className={`p-4 overflow-x-auto max-h-[520px] overflow-y-auto font-mono text-xs leading-relaxed ${
              isDark
                ? 'bg-black/70 text-[#e0e0e0] selection:bg-brand-400/30'
                : 'bg-slate-900 text-slate-100 selection:bg-brand-600/40'
            }`}
          >
            <pre>
              <code>{selectedFile.code}</code>
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
};
