import type { ReactNode } from 'react';

interface ChatMarkdownProps {
  text: string;
  onArticleClick: (articleId: number) => void;
}

/** **bold**, `code` and article references [#123] (also [#12, #34]) inside a line. */
function renderInline(text: string, onArticleClick: (id: number) => void, keyPrefix: string): ReactNode[] {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[#\d+(?:\s*,\s*#\d+)*\])/g);
  return parts.map((part, i) => {
    const key = `${keyPrefix}-${i}`;
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return <code key={key}>{part.slice(1, -1)}</code>;
    }
    const ids = /^\[#\d+(?:\s*,\s*#\d+)*\]$/.test(part) ? part.match(/\d+/g) : null;
    if (ids) {
      return (
        <span key={key} className="chat-refs">
          {ids.map((id) => (
            <button
              key={id}
              type="button"
              className="chat-ref"
              onClick={() => onArticleClick(Number(id))}
              title={`Haber #${id} — aç`}
            >
              #{id}
            </button>
          ))}
        </span>
      );
    }
    return part;
  });
}

function isTableRow(line: string): boolean {
  return /^\s*\|.*\|\s*$/.test(line);
}

function tableCells(line: string): string[] {
  return line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
}

/**
 * The small Markdown subset the report prompt asks for: headings, bullet/numbered lists,
 * pipe tables, paragraphs and the inline marks above. Rendered as React elements (never as HTML),
 * so model output can't inject markup.
 */
function ChatMarkdown({ text, onArticleClick }: ChatMarkdownProps) {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const key = `b${i}`;
    if (!line.trim()) {
      i += 1;
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6);
      const Tag = `h${level}` as 'h3' | 'h4' | 'h5' | 'h6';
      blocks.push(<Tag key={key} className="chat-md-heading">{renderInline(heading[2], onArticleClick, key)}</Tag>);
      i += 1;
      continue;
    }
    if (isTableRow(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const header = tableCells(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && isTableRow(lines[i])) {
        rows.push(tableCells(lines[i]));
        i += 1;
      }
      blocks.push(
        <div key={key} className="chat-chart-table-wrap">
          <table className="chat-table">
            <thead><tr>{header.map((h, c) => <th key={c}>{renderInline(h, onArticleClick, `${key}h${c}`)}</th>)}</tr></thead>
            <tbody>
              {rows.map((row, r) => (
                <tr key={r}>{row.map((cell, c) => <td key={c}>{renderInline(cell, onArticleClick, `${key}r${r}c${c}`)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    const bullet = /^\s*[-*•]\s+/;
    const numbered = /^\s*\d+[.)]\s+/;
    if (bullet.test(line) || numbered.test(line)) {
      const ordered = numbered.test(line);
      const pattern = ordered ? numbered : bullet;
      const items: string[] = [];
      while (i < lines.length && pattern.test(lines[i])) {
        items.push(lines[i].replace(pattern, ''));
        i += 1;
      }
      const ListTag = ordered ? 'ol' : 'ul';
      blocks.push(
        <ListTag key={key} className="chat-md-list">
          {items.map((item, n) => <li key={n}>{renderInline(item, onArticleClick, `${key}i${n}`)}</li>)}
        </ListTag>,
      );
      continue;
    }
    // Always take the current line (a lone "|…|" row without a separator is just text).
    const paragraph: string[] = [line];
    i += 1;
    while (i < lines.length && lines[i].trim() && !/^(#{1,4})\s/.test(lines[i])
      && !bullet.test(lines[i]) && !numbered.test(lines[i]) && !isTableRow(lines[i])) {
      paragraph.push(lines[i]);
      i += 1;
    }
    blocks.push(<p key={key}>{renderInline(paragraph.join(' '), onArticleClick, key)}</p>);
  }

  return <div className="chat-md">{blocks}</div>;
}

export default ChatMarkdown;
