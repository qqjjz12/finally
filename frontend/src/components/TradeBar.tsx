'use client';
import { useEffect, useState } from 'react';

interface Props {
  selected: string | null;
  onTrade: (ticker: string, qty: number, side: 'buy' | 'sell') => Promise<string | null>;
}

export default function TradeBar({ selected, onTrade }: Props) {
  const [ticker, setTicker] = useState('');
  const [qty, setQty] = useState('');
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null);

  useEffect(() => {
    if (selected) setTicker(selected);
  }, [selected]);

  const go = async (side: 'buy' | 'sell') => {
    const q = Number(qty);
    const t = ticker.trim().toUpperCase();
    if (!t || !(q > 0)) {
      setMsg({ text: 'Enter a ticker and a quantity above 0', ok: false });
      return;
    }
    const err = await onTrade(t, q, side);
    setMsg(err ? { text: err, ok: false } : { text: `${side === 'buy' ? 'Bought' : 'Sold'} ${q} ${t}`, ok: true });
  };

  const input = 'rounded border border-border bg-bg px-2 py-1 outline-none focus:border-primary';
  return (
    <section className="flex items-center gap-2 border border-border bg-panel px-3 py-2">
      <span className="text-xs font-semibold uppercase text-muted">Trade</span>
      <input
        data-testid="trade-ticker"
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
        placeholder="Ticker"
        className={`${input} w-24 uppercase`}
      />
      <input
        data-testid="trade-quantity"
        value={qty}
        onChange={(e) => setQty(e.target.value)}
        placeholder="Qty"
        type="number"
        min="0"
        step="any"
        className={`${input} w-24`}
      />
      <button
        data-testid="trade-buy"
        onClick={() => go('buy')}
        className="rounded bg-up px-4 py-1 font-semibold text-black hover:opacity-90"
      >
        Buy
      </button>
      <button
        data-testid="trade-sell"
        onClick={() => go('sell')}
        className="rounded bg-down px-4 py-1 font-semibold text-black hover:opacity-90"
      >
        Sell
      </button>
      {msg && (
        <span data-testid="trade-message" className={`text-xs ${msg.ok ? 'text-up' : 'text-down'}`}>
          {msg.text}
        </span>
      )}
    </section>
  );
}
