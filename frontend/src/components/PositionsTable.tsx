import type { Position } from '@/lib/types';
import { money, num, pct, pnlClass, signed } from '@/lib/format';

export default function PositionsTable({ positions }: { positions: Position[] }) {
  return (
    <section className="flex h-full min-h-0 flex-col border border-border bg-panel">
      <h2 className="border-b border-border px-3 py-1.5 text-xs font-semibold uppercase text-muted">Positions</h2>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-right font-mono">
          <thead className="text-xs text-muted">
            <tr>
              <th className="px-3 py-1 text-left">Ticker</th>
              <th className="px-2">Qty</th>
              <th className="px-2">Avg Cost</th>
              <th className="px-2">Price</th>
              <th className="px-2">Unrealized P&amp;L</th>
              <th className="px-3">% Chg</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.ticker} data-testid={`position-row-${p.ticker}`} className="border-t border-border/50">
                <td className="px-3 py-1 text-left font-sans font-semibold">{p.ticker}</td>
                <td className="px-2" data-testid={`position-qty-${p.ticker}`}>
                  {num(p.quantity, 2)}
                </td>
                <td className="px-2">{money(p.avg_cost)}</td>
                <td className="px-2">{money(p.current_price)}</td>
                <td className={`px-2 ${pnlClass(p.unrealized_pnl)}`}>{signed(p.unrealized_pnl)}</td>
                <td className={`px-3 ${pnlClass(p.pnl_pct)}`}>{pct(p.pnl_pct)}</td>
              </tr>
            ))}
            {positions.length === 0 && (
              <tr>
                <td colSpan={6} className="py-3 text-center font-sans text-muted">
                  No open positions
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
