"use client";

import type { ComponentProps, ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownResponseProps {
  content: string;
}

type MarkdownComponentProps<T extends keyof JSX.IntrinsicElements> = ComponentProps<T> & {
  node?: unknown;
  children?: ReactNode;
};

export function MarkdownResponse({ content }: MarkdownResponseProps) {
  const components: Components = {
    h1: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"h1">) => (
      <h1
        className={`text-3xl font-semibold tracking-tight text-foreground ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </h1>
    ),
    h2: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"h2">) => (
      <h2
        className={`text-2xl font-semibold tracking-tight text-foreground ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </h2>
    ),
    h3: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"h3">) => (
      <h3
        className={`text-xl font-semibold text-foreground ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </h3>
    ),
    h4: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"h4">) => (
      <h4
        className={`text-lg font-semibold text-foreground ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </h4>
    ),
    h5: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"h5">) => (
      <h5
        className={`text-base font-semibold text-foreground ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </h5>
    ),
    h6: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"h6">) => (
      <h6
        className={`text-sm font-semibold uppercase tracking-wider text-muted-foreground ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </h6>
    ),
    p: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"p">) => (
      <p className={`leading-7 ${className ?? ""}`.trim()} {...rest}>
        {children}
      </p>
    ),
    ul: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"ul">) => (
      <ul
        className={`list-disc space-y-2 pl-6 marker:text-muted-foreground ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </ul>
    ),
    ol: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"ol">) => (
      <ol
        className={`list-decimal space-y-2 pl-6 marker:text-muted-foreground ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </ol>
    ),
    li: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"li">) => (
      <li className={`leading-7 ${className ?? ""}`.trim()} {...rest}>
        {children}
      </li>
    ),
    blockquote: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"blockquote">) => (
      <blockquote
        className={`border-l-2 border-border pl-4 text-muted-foreground ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </blockquote>
    ),
    code: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"code"> & { inline?: boolean }) => {
      const isInline = (rest as { inline?: boolean }).inline;
      if (isInline) {
        return (
          <code
            className={`rounded-md bg-muted px-1.5 py-0.5 font-mono text-[0.92em] text-foreground ${className ?? ""}`.trim()}
            {...rest}
          >
            {children}
          </code>
        );
      }
      return (
        <code
          className={`font-mono text-[0.92em] text-foreground ${className ?? ""}`.trim()}
          {...rest}
        >
          {children}
        </code>
      );
    },
    pre: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"pre">) => (
      <pre
        className={`overflow-x-auto rounded-2xl border border-border/70 bg-muted/40 p-4 text-sm leading-6 ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </pre>
    ),
    table: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"table">) => (
      <div className="my-2 overflow-x-auto rounded-2xl border border-border/70">
        <table
          className={`w-full border-collapse text-left text-sm ${className ?? ""}`.trim()}
          {...rest}
        >
          {children}
        </table>
      </div>
    ),
    thead: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"thead">) => (
      <thead
        className={`border-b border-border/70 bg-muted/40 ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </thead>
    ),
    tbody: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"tbody">) => (
      <tbody className={className} {...rest}>
        {children}
      </tbody>
    ),
    tr: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"tr">) => (
      <tr
        className={`border-b border-border/40 last:border-b-0 ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </tr>
    ),
    th: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"th">) => (
      <th
        className={`px-4 py-2 font-semibold text-foreground ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </th>
    ),
    td: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"td">) => (
      <td
        className={`px-4 py-2 align-top text-foreground/90 ${className ?? ""}`.trim()}
        {...rest}
      >
        {children}
      </td>
    ),
    a: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"a">) => (
      <a
        className={`text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary ${className ?? ""}`.trim()}
        target="_blank"
        rel="noreferrer noopener"
        {...rest}
      >
        {children}
      </a>
    ),
    hr: ({ node: _node, className, ...rest }: MarkdownComponentProps<"hr">) => (
      <hr
        className={`my-6 border-border/60 ${className ?? ""}`.trim()}
        {...rest}
      />
    ),
    strong: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"strong">) => (
      <strong className={`font-semibold text-foreground ${className ?? ""}`.trim()} {...rest}>
        {children}
      </strong>
    ),
    em: ({ node: _node, className, children, ...rest }: MarkdownComponentProps<"em">) => (
      <em className={className} {...rest}>
        {children}
      </em>
    ),
  };

  return (
    <div className="markdown-response space-y-4 text-[15px] leading-7 text-foreground/90">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
