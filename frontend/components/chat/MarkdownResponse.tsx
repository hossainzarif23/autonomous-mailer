"use client";

import type { ReactNode } from "react";

function renderInline(text: string, keyPrefix: string) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g).filter(Boolean);

  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`;
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={key} className="font-semibold text-foreground">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return <em key={key} className="italic">{part.slice(1, -1)}</em>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={key} className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[0.92em] text-foreground">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={key}>{part}</span>;
  });
}

interface MarkdownResponseProps {
  content: string;
}

export function MarkdownResponse({ content }: MarkdownResponseProps) {
  const lines = content.split("\n");
  const elements: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const rawLine = lines[index];
    const line = rawLine.trim();

    if (!line) {
      index += 1;
      continue;
    }

    const headingMatch = line.match(/^(#{1,3})\s+(.*)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const headingText = headingMatch[2].trim();
      const className =
        level === 1
          ? "text-3xl font-semibold tracking-tight text-foreground"
          : level === 2
            ? "text-2xl font-semibold tracking-tight text-foreground"
            : "text-xl font-semibold text-foreground";
      const Tag = level === 1 ? "h1" : level === 2 ? "h2" : "h3";
      elements.push(
        <Tag key={`heading-${index}`} className={className}>
          {renderInline(headingText, `heading-${index}`)}
        </Tag>
      );
      index += 1;
      continue;
    }

    if (line.startsWith(">")) {
      const quoteLines: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      elements.push(
        <blockquote
          key={`quote-${index}`}
          className="border-l-2 border-border pl-4 text-[15px] leading-7 text-muted-foreground"
        >
          {quoteLines.map((quoteLine, quoteIndex) => (
            <p key={`quote-${index}-${quoteIndex}`}>{renderInline(quoteLine, `quote-${index}-${quoteIndex}`)}</p>
          ))}
        </blockquote>
      );
      continue;
    }

    if (/^([-*]|\d+\.)\s+/.test(line)) {
      const items: string[] = [];
      const ordered = /^\d+\./.test(line);
      while (index < lines.length && /^([-*]|\d+\.)\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^([-*]|\d+\.)\s+/, ""));
        index += 1;
      }
      const ListTag = ordered ? "ol" : "ul";
      elements.push(
        <ListTag
          key={`list-${index}`}
          className={ordered ? "list-decimal space-y-2 pl-6 text-[15px] leading-7" : "list-disc space-y-2 pl-6 text-[15px] leading-7"}
        >
          {items.map((item, itemIndex) => (
            <li key={`list-${index}-${itemIndex}`}>{renderInline(item, `list-${index}-${itemIndex}`)}</li>
          ))}
        </ListTag>
      );
      continue;
    }

    const paragraphLines: string[] = [];
    while (index < lines.length && lines[index].trim() && !/^(#{1,3})\s+/.test(lines[index].trim()) && !/^>\s?/.test(lines[index].trim()) && !/^([-*]|\d+\.)\s+/.test(lines[index].trim())) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }

    elements.push(
      <p key={`paragraph-${index}`} className="text-[15px] leading-8 text-foreground/90">
        {renderInline(paragraphLines.join(" "), `paragraph-${index}`)}
      </p>
    );
  }

  return <div className="space-y-5">{elements}</div>;
}
