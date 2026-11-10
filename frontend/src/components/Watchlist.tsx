'use client';
import { useState } from 'react';
import { usePriceStore } from '@/lib/priceStore';
import { dailyChange, pct, pnlClass } from '@/lib/format';
import type { WatchlistItem } from '@/lib/types';
import PriceCell from './PriceCell';
import Sparkline from './Sparkline';

interface Props {
  items: WatchlistItem[];
  selected: string | null;
  onSelect: (t: string) => void;
  onAdd: (t: string) => Promise<string | null>;
  onRemove: (t: string) => void;
}

export default function Watchlist({ items, selected, onSelect, onAdd, onRemove }: Props) {
  const store = usePriceStore();
  const [input, setInput] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = input.trim().toUpperCase();
    if (!t) return;
    const err = await onAdd(t);
    setError(err);
    if (!err) setInput('');
  };

  return (
    <section className="flex h-full min-h-0 flex-col border border-border bg-panel">
      <h2 className="border-b border-border px-3 py-1.5 text-xs font-semibold uppercase text-muted">Watchlist</h2>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full">
          <tbody>
            {items.map((it) => {
              const tick = store.ticks.get(it.ticker);
              const price = tick?.price ?? it.price ?? null;
              const ref = tick?.reference_price ?? it.reference_price ?? null;
              const chg = dailyChange(price, ref);
              const hist = store.history.get(it.ticker) ?? [];
              return (
                <tr
                  key={it.ticker}
                  data-testid={`watchlist-row-${it.ticker}`}
                  onClick={() => onSelect(it.ticker)}
                  className={`cursor-pointer border-b border-border/50 hover:bg-white/5 ${
                    selected === it.ticker ? 'bg-primary/10' : ''
                  }`}
                >
                  <td className="px-3 py-1 font-semibold">{it.ticker}</td>
                  <td className="px-1 py-1 text-right">
                    <PriceCell ticker={it.ticker} price={price} />
                  </td>
                  <td
                    data-testid={`change-${it.ticker}`}
                    className={`px-1 py-1 text-right font-mono ${chg == null ? 'text-muted' : pnlClass(chg)}`}
                  >
                    {pct(chg)}
                  </td>
                  <td className="px-1 py-1">
                    <Sparkline data={hist} up={hist.length < 2 || hist[hist.length - 1].value >= hist[0].value} />
                  </td>
                  <td className="px-2 py-1 text-right">
                    <button
                      data-testid={`remove-${it.ticker}`}
                      aria-label={`Remove ${it.ticker}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemove(it.ticker);
                      }}
                      className="text-muted hover:text-down"
                    >
                      x
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <form onSubmit={submit} className="flex gap-2 border-t border-border p-2">
        <input
          data-testid="add-ticker-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Add ticker"
          className="w-full rounded border border-border bg-bg px-2 py-1 uppercase outline-none focus:border-primary"
        />
        <button
          data-testid="add-ticker-button"
          type="submit"
          className="rounded bg-secondary px-3 py-1 font-semibold text-white hover:opacity-90"
        >
          Add
        </button>
      </form>
      {error && (
        <div data-testid="watchlist-error" className="px-3 pb-2 text-xs text-down">
          {error}
        </div>
      )}
    </section>
  );
}
