import { useState, type ReactNode } from 'react';
import { Copy, Check } from 'lucide-react';

/**
 * MESSAGE CONTENT -- markdown rendered the way a chat answer should read.
 *
 * UK's ask (2026-09-16): "jaise ChatGPT ya Claude mein dikhta hai --
 * title highlight, text ka size, bold."
 *
 * His screenshots showed the problem exactly: JARVIS returned a proper
 * markdown answer -- **Poppler**, a | Tool | What it does | table,
 * "## 1 Python implementation" -- and the chat printed the raw
 * characters. Asterisks and pipes on screen instead of bold and a table.
 *
 * WHY HAND-WRITTEN AND NOT react-markdown
 * =======================================
 * This environment has no network access, so no markdown library can be
 * installed. Rather than pretend otherwise, this is a small parser
 * covering what actually appears in JARVIS's answers: fenced code,
 * headings, bold, inline code, lists, and pipe tables.
 *
 * It is deliberately NOT complete markdown. Anything unrecognised
 * renders as plain text -- the correct failure mode: an unrendered
 * construct is still readable, a half-parsed one is corrupted.
 */

interface Block {
  type: 'code' | 'heading' | 'table' | 'list' | 'para';
  content: string;
  language?: string;
  level?: number;
  rows?: string[][];
  ordered?: boolean;
  items?: string[];
}

/** Bold, italics and inline code inside one line of text. */
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  // Inline code first, so ** inside backticks is not read as bold.
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\n]+\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;

  while ((m = pattern.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const token = m[0];
    if (token.startsWith('`')) {
      out.push(
        <code key={keyPrefix + '-c' + i} className="jarvis-md-inline-code">
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith('**')) {
      out.push(<strong key={keyPrefix + '-b' + i}>{token.slice(2, -2)}</strong>);
    } else {
      out.push(<em key={keyPrefix + '-i' + i}>{token.slice(1, -1)}</em>);
    }
    last = pattern.lastIndex;
    i += 1;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  const lines = (text || '').split('\n');
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    const fence = line.match(/^```([a-zA-Z0-9_+-]*)\s*$/);
    if (fence) {
      const lang = fence[1] || 'text';
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) {
        body.push(lines[i]);
        i += 1;
      }
      i += 1;
      blocks.push({ type: 'code', language: lang, content: body.join('\n') });
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, content: heading[2].trim() });
      i += 1;
      continue;
    }

    // Pipe table: header row followed by a |---|---| separator.
    if (
      /^\s*\|.*\|\s*$/.test(line) &&
      i + 1 < lines.length &&
      /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])
    ) {
      const rows: string[][] = [];
      const toCells = (l: string) =>
        l.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      rows.push(toCells(line));
      i += 2;
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        rows.push(toCells(lines[i]));
        i += 1;
      }
      blocks.push({ type: 'table', content: '', rows });
      continue;
    }

    const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      const ordered = !!numbered;
      const items: string[] = [];
      while (i < lines.length) {
        const b = lines[i].match(/^\s*[-*+]\s+(.*)$/);
        const n = lines[i].match(/^\s*\d+[.)]\s+(.*)$/);
        if (ordered && n) items.push(n[1]);
        else if (!ordered && b) items.push(b[1]);
        else break;
        i += 1;
      }
      blocks.push({ type: 'list', content: '', ordered, items });
      continue;
    }

    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !/^```/.test(lines[i]) &&
      !/^#{1,4}\s/.test(lines[i]) &&
      !/^\s*[-*+]\s/.test(lines[i]) &&
      !/^\s*\d+[.)]\s/.test(lines[i]) &&
      !/^\s*\|.*\|\s*$/.test(lines[i])
    ) {
      para.push(lines[i]);
      i += 1;
    }
    if (para.length) blocks.push({ type: 'para', content: para.join('\n') });
    else i += 1;
  }

  return blocks;
}

function CodeBlock({ code, language, isDark }: { code: string; language: string; isDark: boolean }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable -- text is still selectable */
    }
  };

  return (
    <div className={'jarvis-md-codebox ' + (isDark ? 'is-dark' : 'is-light')}>
      <div className="jarvis-md-codebox-bar">
        <span className="jarvis-md-codebox-lang">{language}</span>
        <button type="button" onClick={copy} className="jarvis-md-codebox-copy">
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="jarvis-md-codebox-pre">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export default function MessageContent({
  text,
  isDark = true,
}: {
  text: string;
  isDark?: boolean;
}) {
  const blocks = parseBlocks(text || '');

  return (
    <div className="jarvis-md">
      {blocks.map((b, i) => {
        if (b.type === 'code') {
          return <CodeBlock key={i} code={b.content} language={b.language || 'text'} isDark={isDark} />;
        }

        if (b.type === 'heading') {
          return (
            <div key={i} className={'jarvis-md-h jarvis-md-h' + b.level}>
              {renderInline(b.content, 'h' + i)}
            </div>
          );
        }

        if (b.type === 'table' && b.rows && b.rows.length) {
          const head = b.rows[0];
          const body = b.rows.slice(1);
          return (
            <div key={i} className="jarvis-md-table-wrap">
              <table className="jarvis-md-table">
                <thead>
                  <tr>{head.map((c, j) => <th key={j}>{renderInline(c, 'th' + i + '-' + j)}</th>)}</tr>
                </thead>
                <tbody>
                  {body.map((row, r) => (
                    <tr key={r}>
                      {row.map((c, j) => <td key={j}>{renderInline(c, 'td' + i + '-' + r + '-' + j)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }

        if (b.type === 'list' && b.items && b.items.length) {
          if (b.ordered) {
            return (
              <ol key={i} className="jarvis-md-list">
                {b.items.map((it, j) => <li key={j}>{renderInline(it, 'li' + i + '-' + j)}</li>)}
              </ol>
            );
          }
          return (
            <ul key={i} className="jarvis-md-list">
              {b.items.map((it, j) => <li key={j}>{renderInline(it, 'li' + i + '-' + j)}</li>)}
            </ul>
          );
        }

        return (
          <p key={i} className="jarvis-md-p">
            {renderInline(b.content, 'p' + i)}
          </p>
        );
      })}
    </div>
  );
}
