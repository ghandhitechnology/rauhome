import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import './ChatMarkdown.css'

type Props = {
  text: string
  className?: string
}

/** Safe GFM markdown for chat bubbles (no raw HTML). */
export default function ChatMarkdown({ text, className = '' }: Props) {
  const source = (text || '').trimEnd()
  if (!source) return null

  return (
    <div className={`chat-md ${className}`.trim()}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
          // Avoid nested <p> layout quirks inside the bubble.
          p: ({ children }) => <p>{children}</p>,
          pre: ({ children }) => <pre>{children}</pre>,
          code: ({ className: codeClass, children, ...rest }) => (
            <code className={codeClass || 'chat-md-inline'} {...rest}>
              {children}
            </code>
          ),
        }}
      >
        {source}
      </Markdown>
    </div>
  )
}
