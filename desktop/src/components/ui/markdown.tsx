import { Fragment, type ReactNode } from "react";

// A tiny, dependency-free markdown renderer for transcript messages. Covers the
// common cases (fenced code, inline code, bold, bullet lists, headings,
// paragraphs with soft line breaks). Not a full CommonMark parser — just enough
// to make agent messages read cleanly instead of showing raw `**`/backticks.

/** Inline `code` and **bold** (code wins, so `**` inside code stays literal). */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /`([^`]+)`|\*\*([^*]+)\*\*/g;
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] != null) {
      out.push(
        <code
          key={key++}
          className="rounded bg-surface-sunken px-1 font-mono text-[0.85em] text-ink"
        >
          {m[1]}
        </code>,
      );
    } else {
      out.push(
        <strong key={key++} className="font-semibold text-ink">
          {m[2]}
        </strong>,
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const lines = text.split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block.
    if (line.trimStart().startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      i++; // skip closing fence
      blocks.push(
        <pre
          key={key++}
          className="my-1 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-line-strong bg-surface-sunken px-2.5 py-1.5 font-mono text-[11px] leading-relaxed text-ink-soft"
        >
          {buf.join("\n")}
        </pre>,
      );
      continue;
    }

    // Bullet list.
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={key++} className="my-1 list-disc space-y-0.5 pl-4">
          {items.map((it, j) => (
            <li key={j}>{inline(it)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    // Heading.
    const h = line.match(/^(#{1,6})\s+(.*)/);
    if (h) {
      blocks.push(
        <p key={key++} className="mt-2 mb-0.5 font-semibold text-ink">
          {inline(h[2])}
        </p>,
      );
      i++;
      continue;
    }

    // Blank line.
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph: gather contiguous plain lines (soft line breaks preserved).
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trimStart().startsWith("```") &&
      !/^\s*[-*]\s+/.test(lines[i]) &&
      !/^#{1,6}\s+/.test(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key++} className="my-0.5 whitespace-pre-wrap break-words">
        {inline(para.join("\n"))}
      </p>,
    );
  }

  return <Fragment>{blocks}</Fragment>;
}
