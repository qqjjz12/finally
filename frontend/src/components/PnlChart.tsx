'use client';
import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, type ISeriesApi } from 'lightweight-charts';
import type { HistoryPoint } from '@/lib/types';

export function toSeries(points: HistoryPoint[]) {
  const out: { time: number; value: number }[] = [];
  for (const p of points) {
    const time = Math.floor(Date.parse(p.recorded_at) / 1000);
    if (Number.isNaN(time)) continue;
    const last = out[out.length - 1];
    if (last && last.time === time) last.value = p.total_value;
    else if (!last || time > last.time) out.push({ time, value: p.total_value });
  }
  return out;
}

export default function PnlChart({ points }: { points: HistoryPoint[] }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<'Line'> | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      autoSize: true,
      layout: { attributionLogo: false, background: { color: '#161b22' }, textColor: '#8b949e' },
      grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
      timeScale: { timeVisible: true, borderColor: '#30363d' },
      rightPriceScale: { borderColor: '#30363d' },
    });
    chart.current = c;
    series.current = c.addLineSeries({ color: '#ecad0a', lineWidth: 2 });
    return () => {
      c.remove();
      chart.current = null;
      series.current = null;
    };
  }, []);

  useEffect(() => {
    if (!series.current) return;
    series.current.setData(toSeries(points).map((d) => ({ time: d.time as never, value: d.value })));
    chart.current?.timeScale().fitContent();
  }, [points]);

  return (
    <section className="flex h-full min-h-0 flex-col border border-border bg-panel">
      <h2 className="border-b border-border px-3 py-1.5 text-xs font-semibold uppercase text-muted">
        Portfolio Value
      </h2>
      <div data-testid="pnl-chart" data-points={points.length} ref={el} className="min-h-[150px] flex-1" />
    </section>
  );
}
