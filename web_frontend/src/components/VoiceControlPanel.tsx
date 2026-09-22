import React, { useState, useEffect } from 'react';
import {
  Mic,
  Volume2,
  Sliders,
  Play,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  Cpu,
  Cloud,
  Layers,
  Radio,
} from 'lucide-react';
import { VoiceSettings, TTSEngine, AppTheme } from '../types';
import { api } from '../api/client';

interface VoiceControlPanelProps {
  theme?: AppTheme;
  onClose?: () => void;
}

export const VoiceControlPanel: React.FC<VoiceControlPanelProps> = ({ theme = 'dark' }) => {
  const isDark = theme === 'dark';
  const [settings, setSettings] = useState<VoiceSettings>({
    pitch: 0.55,
    rate: 1.1,
    language: 'hi-IN',
    engine: 'com.google.android.tts',
    spoken_replies: false,
    whisper_fallback: false,
  });

  const [engines, setEngines] = useState<TTSEngine[]>([]);
  const [testPhrase, setTestPhrase] = useState('Sir, systems are operating nominal. Telemetry verified.');
  const [isTesting, setIsTesting] = useState(false);
  const [testFeedback, setTestFeedback] = useState<string | null>(null);
  const [isSaved, setIsSaved] = useState(false);

  useEffect(() => {
    // Load persisted settings and engines
    api.getVoiceSettings().then((s) => setSettings(s));
    api.getVoiceEngines().then((e) => setEngines(e));
  }, []);

  const handleSave = async (updated: VoiceSettings) => {
    setSettings(updated);
    await api.saveVoiceSettings(updated);
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 2000);
  };

  const handleResetDefaults = () => {
    const defaults: VoiceSettings = {
      pitch: 0.55,
      rate: 1.1,
      language: 'hi-IN',
      engine: engines[0]?.name || 'com.google.android.tts',
      spoken_replies: false,
      whisper_fallback: false,
    };
    handleSave(defaults);
  };

  const handleTestPhrase = async () => {
    if (!testPhrase.trim() || isTesting) return;
    setIsTesting(true);
    setTestFeedback(null);
    try {
      const res = await api.testVoicePhrase(testPhrase, settings);
      setTestFeedback(res.message || 'Synthesis triggered.');
    } catch (err: any) {
      setTestFeedback(err.message || 'Test failed');
    } finally {
      setIsTesting(false);
      setTimeout(() => setTestFeedback(null), 4000);
    }
  };

  return (
    <div className="space-y-5 text-xs">
      {/* Engine and Status Header */}
      <div
        className={`p-3.5 rounded-xl border flex items-center justify-between ${
          isDark ? 'bg-black/30 border-white/10' : 'bg-slate-50 border-slate-200'
        }`}
      >
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-brand-500/20 text-brand-400 flex items-center justify-center border border-brand-500/30">
            <Volume2 className="w-4 h-4" />
          </div>
          <div>
            <div className="font-bold text-sm flex items-center gap-1.5">
              <span>On-Device Speech & Voice Runtime</span>
              <span className="px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-400 text-xs font-mono">
                Termux:API
              </span>
            </div>
            <p className="text-xs text-slate-400">
              Native offline TTS / STT in <code className="font-mono text-brand-400">core/runtime/voice.py</code>
            </p>
          </div>
        </div>

        <button
          onClick={handleResetDefaults}
          className="text-xs text-slate-400 hover:text-brand-400 flex items-center gap-1 px-2 py-1 rounded border border-white/10 hover:border-brand-500/30 transition cursor-pointer"
          title="Reset to recommended baseline (pitch 0.55, rate 1.1, hi-IN)"
        >
          <RotateCcw className="w-3 h-3" /> Reset Defaults
        </button>
      </div>

      {/* Engine Picker */}
      <div className="space-y-1.5">
        <label className="block text-xs font-semibold text-slate-300">
          TTS Engine Provider (<code className="font-mono text-brand-400">termux-tts-engines</code>)
        </label>
        <div className="grid grid-cols-1 gap-2">
          {engines.map((eng) => {
            const isSelected = settings.engine === eng.name;
            return (
              <div
                key={eng.name}
                onClick={() => handleSave({ ...settings, engine: eng.name })}
                className={`p-2.5 rounded-xl border flex items-center justify-between cursor-pointer transition ${
                  isSelected
                    ? 'bg-brand-500/15 border-brand-400/50 text-brand-200'
                    : isDark
                    ? 'bg-white/[0.02] border-white/10 hover:bg-white/5 text-slate-300'
                    : 'bg-white border-slate-200 hover:bg-slate-50 text-slate-700'
                }`}
              >
                <div className="flex items-center gap-2">
                  <div
                    className={`w-3 h-3 rounded-full border flex items-center justify-center ${
                      isSelected ? 'border-brand-400 bg-brand-400' : 'border-slate-500'
                    }`}
                  >
                    {isSelected && <div className="w-1 h-1 rounded-full bg-black" />}
                  </div>
                  <div>
                    <div className="font-semibold text-xs">{eng.label || eng.name}</div>
                    <div className="text-xs text-slate-400 font-mono">{eng.name}</div>
                  </div>
                </div>
                {eng.default && (
                  <span className="text-xs uppercase tracking-wider px-1.5 py-0.5 rounded bg-brand-500/20 text-brand-300 border border-brand-500/40">
                    Default
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Sliders: Pitch, Rate, Language */}
      <div className="space-y-3">
        {/* Pitch Slider */}
        <div className={`p-3 rounded-xl border ${isDark ? 'bg-white/[0.02] border-white/10' : 'bg-slate-50 border-slate-200'}`}>
          <div className="flex justify-between items-center mb-1">
            <span className="font-semibold text-slate-300">Pitch (Voice Frequency)</span>
            <span className="font-mono text-brand-400 font-bold">{settings.pitch.toFixed(2)}x</span>
          </div>
          <input
            type="range"
            min="0.3"
            max="1.5"
            step="0.05"
            value={settings.pitch}
            onChange={(e) => handleSave({ ...settings, pitch: parseFloat(e.target.value) })}
            className="w-full accent-brand-400 cursor-pointer"
          />
          <div className="flex justify-between text-xs text-slate-400 mt-0.5">
            <span>Deep (0.3x)</span>
            <span className="text-brand-400">Default: 0.55x</span>
            <span>High (1.5x)</span>
          </div>
        </div>

        {/* Rate Slider */}
        <div className={`p-3 rounded-xl border ${isDark ? 'bg-white/[0.02] border-white/10' : 'bg-slate-50 border-slate-200'}`}>
          <div className="flex justify-between items-center mb-1">
            <span className="font-semibold text-slate-300">Speaking Rate (Speed)</span>
            <span className="font-mono text-brand-400 font-bold">{settings.rate.toFixed(2)}x</span>
          </div>
          <input
            type="range"
            min="0.5"
            max="2.0"
            step="0.05"
            value={settings.rate}
            onChange={(e) => handleSave({ ...settings, rate: parseFloat(e.target.value) })}
            className="w-full accent-brand-400 cursor-pointer"
          />
          <div className="flex justify-between text-xs text-slate-400 mt-0.5">
            <span>Slow (0.5x)</span>
            <span className="text-brand-400">Default: 1.10x</span>
            <span>Fast (2.0x)</span>
          </div>
        </div>

        {/* Language Selector */}
        <div className={`p-3 rounded-xl border ${isDark ? 'bg-white/[0.02] border-white/10' : 'bg-slate-50 border-slate-200'}`}>
          <div className="flex justify-between items-center mb-1.5">
            <span className="font-semibold text-slate-300">Language / Locale</span>
            <span className="font-mono text-brand-400 text-xs">{settings.language}</span>
          </div>
          <select
            value={settings.language}
            onChange={(e) => handleSave({ ...settings, language: e.target.value })}
            className={`w-full p-2 rounded-lg border text-xs font-mono outline-none ${
              isDark ? 'bg-black/50 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-800'
            }`}
          >
            <option value="hi-IN">hi-IN (Hinglish / Hindi - India)</option>
            <option value="en-IN">en-IN (English - India)</option>
            <option value="en-US">en-US (English - United States)</option>
            <option value="hi-Latn">hi-Latn (Latin script Hinglish)</option>
          </select>
        </div>
      </div>

      {/* Toggles: Spoken Replies & Whisper Fallback */}
      <div className="space-y-2.5">
        {/* Spoken Replies Toggle */}
        <div
          className={`p-3 rounded-xl border flex items-center justify-between ${
            isDark ? 'bg-white/[0.02] border-white/10' : 'bg-slate-50 border-slate-200'
          }`}
        >
          <div className="space-y-0.5">
            <div className="font-semibold text-slate-200 flex items-center gap-1.5">
              <Volume2 className="w-3.5 h-3.5 text-brand-400" />
              <span>Spoken Replies (TTS Auto-Speech)</span>
            </div>
            <p className="text-xs text-slate-400">
              Automatically speak JARVIS turn responses via Termux:API
            </p>
          </div>
          <button
            onClick={() => handleSave({ ...settings, spoken_replies: !settings.spoken_replies })}
            className={`w-11 h-6 rounded-full transition p-1 relative cursor-pointer ${
              settings.spoken_replies ? 'bg-brand-500' : 'bg-white/10'
            }`}
          >
            <div
              className={`w-4 h-4 rounded-full bg-white transition-transform ${
                settings.spoken_replies ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>

        {/* Whisper Fallback Toggle (OPT-IN ONLY) */}
        <div
          className={`p-3 rounded-xl border flex items-center justify-between ${
            isDark ? 'bg-white/[0.02] border-white/10' : 'bg-slate-50 border-slate-200'
          }`}
        >
          <div className="space-y-0.5 pr-2">
            <div className="font-semibold text-slate-200 flex items-center gap-1.5">
              <Cloud className="w-3.5 h-3.5 text-amber-400" />
              <span>Whisper Fallback for Voice Input (Cloud STT)</span>
            </div>
            <p className="text-xs text-slate-400">
              Explicit opt-in: Local STT is primary; cloud Whisper-via-Groq is invoked only as fallback when local recognition yields low confidence.
            </p>
          </div>
          <button
            onClick={() => handleSave({ ...settings, whisper_fallback: !settings.whisper_fallback })}
            className={`w-11 h-6 rounded-full transition p-1 relative shrink-0 cursor-pointer ${
              settings.whisper_fallback ? 'bg-amber-500' : 'bg-white/10'
            }`}
          >
            <div
              className={`w-4 h-4 rounded-full bg-white transition-transform ${
                settings.whisper_fallback ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
      </div>

      {/* Test Phrase Playground */}
      <div
        className={`p-3.5 rounded-xl border space-y-2.5 ${
          isDark ? 'bg-black/40 border-brand-500/20' : 'bg-brand-50/50 border-brand-200'
        }`}
      >
        <div className="flex items-center justify-between">
          <span className="font-semibold text-slate-300 flex items-center gap-1.5">
            <Play className="w-3.5 h-3.5 text-brand-400" /> Test Speech Output
          </span>
          {testFeedback && (
            <span className="text-xs text-brand-300 font-mono flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3 text-emerald-400" /> {testFeedback}
            </span>
          )}
        </div>

        <div className="flex gap-2">
          <input
            type="text"
            value={testPhrase}
            onChange={(e) => setTestPhrase(e.target.value)}
            placeholder="Type sample phrase to test speech..."
            className={`flex-1 px-3 py-1.5 rounded-lg border text-xs font-mono outline-none ${
              isDark ? 'bg-white/5 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900'
            }`}
          />
          <button
            onClick={handleTestPhrase}
            disabled={isTesting}
            className="px-3 py-1.5 rounded-lg bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-white font-semibold text-xs flex items-center gap-1.5 transition cursor-pointer shrink-0"
          >
            <Play className="w-3.5 h-3.5" />
            <span>{isTesting ? 'Speaking...' : 'Test Phrase'}</span>
          </button>
        </div>
      </div>

      {isSaved && (
        <div className="text-xs text-emerald-400 flex items-center gap-1 font-mono justify-end">
          <CheckCircle2 className="w-3 h-3" /> Voice configuration saved
        </div>
      )}
    </div>
  );
};
