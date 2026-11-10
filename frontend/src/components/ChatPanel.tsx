'use client';
import { useEffect, useRef, useState } from 'react';
import { getChat, sendChat } from '@/lib/api';
import type { ChatAction, ChatMessage } from '@/lib/types';

export function describeAction(a: ChatAction): string {
  if (a.type === 'trade') {
    return `${a.side === 'sell' ? 'Sell' : 'Buy'} ${a.quantity} ${a.ticker}`;
  }
  return `${a.action === 'remove' ? 'Remove' : 'Add'} ${a.ticker} ${a.action === 'remove' ? 'from' : 'to'} watchlist`;
}

export function ActionLine({ action }: { action: ChatAction }) {
  const ok = action.status !== 'error';
  return (
    <div
      data-testid="chat-action"
      data-status={ok ? 'ok' : 'error'}
      className={`mt-1 rounded border px-2 py-1 text-xs ${
        ok ? 'border-up/50 bg-up/10 text-up' : 'border-down/50 bg-down/10 text-down'
      }`}
    >
      {ok ? 'OK: ' : 'Failed: '}
      {describeAction(action)}
      {!ok && (action.message || action.code) ? ` - ${action.message || action.code}` : ''}
    </div>
  );
}

export default function ChatPanel({ onActions }: { onActions: () => void }) {
  const [open, setOpen] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getChat()
      .then(setMessages)
      .catch(() => {});
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' });
  }, [messages, loading, open]);

  const send = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput('');
    setMessages((m) => [...m, { role: 'user', content: text }]);
    setLoading(true);
    try {
      const r = await sendChat(text);
      setMessages((m) => [...m, { role: 'assistant', content: r.message, actions: r.actions }]);
      if (r.actions?.length) onActions();
    } catch (err) {
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: (err as Error).message || 'Sorry, something went wrong.', actions: [] },
      ]);
    } finally {
      setLoading(false);
    }
  };

  if (!open) {
    return (
      <button
        data-testid="chat-toggle"
        onClick={() => setOpen(true)}
        className="w-10 border border-border bg-panel text-xs font-semibold uppercase text-primary [writing-mode:vertical-rl]"
      >
        AI Chat
      </button>
    );
  }

  return (
    <aside className="flex min-h-0 w-80 shrink-0 flex-col border border-border bg-panel">
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5">
        <h2 className="text-xs font-semibold uppercase text-primary">FinAlly AI</h2>
        <button
          data-testid="chat-toggle"
          onClick={() => setOpen(false)}
          className="text-muted hover:text-white"
          aria-label="Collapse chat"
        >
          &raquo;
        </button>
      </div>
      <div data-testid="chat-messages" className="min-h-0 flex-1 space-y-3 overflow-auto p-3">
        {messages.length === 0 && !loading && (
          <div className="text-muted">Ask about your portfolio, or tell me to buy, sell or watch a ticker.</div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : ''}>
            <div
              data-testid="chat-message"
              data-role={m.role}
              className={`inline-block max-w-full whitespace-pre-wrap rounded px-2 py-1.5 text-left ${
                m.role === 'user' ? 'bg-secondary/60' : 'bg-bg'
              }`}
            >
              {m.content}
            </div>
            {m.actions?.map((a, j) => (
              <ActionLine key={j} action={a} />
            ))}
          </div>
        ))}
        {loading && (
          <div data-testid="chat-loading" className="animate-pulse text-muted">
            FinAlly is thinking...
          </div>
        )}
        <div ref={end} />
      </div>
      <form onSubmit={send} className="flex gap-2 border-t border-border p-2">
        <input
          data-testid="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Message FinAlly..."
          className="w-full rounded border border-border bg-bg px-2 py-1 outline-none focus:border-primary"
        />
        <button
          data-testid="chat-send"
          type="submit"
          disabled={loading}
          className="rounded bg-secondary px-3 py-1 font-semibold text-white disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </aside>
  );
}
