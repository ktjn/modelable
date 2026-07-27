import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function MarkdownText({ children }: { children: string }) {
  return (
    <div className="chat-markdown">
      <Markdown remarkPlugins={[remarkGfm]}>
        {children}
      </Markdown>
    </div>
  );
}
