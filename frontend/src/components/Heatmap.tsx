'use client';
import { Treemap, ResponsiveContainer } from 'recharts';
import type { Position } from '@/lib/types';

export function pnlColor(pnlPct: number): string {
  const mag = Math.min(Math.abs(pnlPct) / 5, 1); // saturate at 5%
  const alpha = 0.35 + mag * 0.55;
  return pnlPct >= 0 ? `rgba(63,185,80,${alpha})` : `rgba(248,81,73,${alpha})`;
}

interface CellProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  pnl_pct?: number;
}

function Cell({ x = 0, y = 0, width = 0, height = 0, name, pnl_pct = 0 }: CellProps) {
  if (!name) return <g />;
  return (
    <g data-testid={`heatmap-cell-${name}`} data-pnl={pnl_pct >= 0 ? 'profit' : 'loss'}>
      <rect x={x} y={y} width={width} height={height} fill={pnlColor(pnl_pct)} stroke="#0d1117" strokeWidth={2} />
      {width > 40 && height > 30 && (
        <>
          <text x={x + 6} y={y + 16} fill="#fff" fontSize={12} fontWeight={600}>
            {name}
          </text>
          <text x={x + 6} y={y + 30} fill="#fff" fontSize={11}>
            {pnl_pct >= 0 ? '+' : ''}
            {pnl_pct.toFixed(2)}%
          </text>
        </>
      )}
    </g>
  );
}

export default function Heatmap({ positions }: { positions: Position[] }) {
  const data = positions
    .map((p) => ({ name: p.ticker, size: Math.max(p.quantity * p.current_price, 0.01), pnl_pct: p.pnl_pct }))
    .filter((d) => d.size > 0);

  return (
    <section className="flex h-full min-h-0 flex-col border border-border bg-panel">
      <h2 className="border-b border-border px-3 py-1.5 text-xs font-semibold uppercase text-muted">
        Portfolio Heatmap
      </h2>
      <div data-testid="heatmap" data-count={data.length} className="relative min-h-[150px] flex-1">
        {data.length === 0 ? (
          <div className="flex h-full items-center justify-center text-muted">No positions yet</div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <Treemap data={data} dataKey="size" isAnimationActive={false} content={<Cell />} />
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}
