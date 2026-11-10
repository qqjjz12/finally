'use client';
import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, type ISeriesApi } from 'lightweight-charts';
import { usePriceStore } from '@/lib/priceStore';

export default function MainChart({ ticker }: { ticker: string | null }) {
  const store = usePriceStore();
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<'Line'> | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      autoSize: true,
      layout: { attributionLogo: false, background: { color: '#161b22' }, textColor: '#8b949e' },
      grid: { vertLines: { color: '#21262d' }, horzLines: { color: '#21262d' } },
      timeScale: { timeVisible: true, secondsVisible: true, borderColor: '#30363d' },
      rightPriceScale: { borderColor: '#30363d' },
    });
    chart.current = c;
    series.current = c.addLineSeries({ color: '#209dd7', lineWidth: 2 });
    return () => {
      c.remove();
      chart.current = null;
      series.current = null;
    };
  }, []);

  const hist = ticker ? store.history.get(ticker) : undefined;
  useEffect(() => {
    if (!series.current) return;
    series.current.setData((hist ?? []).map((d) => ({ time: d.time as never, value: d.value })));
  }, [ticker, hist, store.version]);

  return (
    <section className="flex h-full min-h-0 flex-col border border-border bg-panel">
      <h2 className="border-b border-border px-3 py-1.5 text-xs font-semibold uppercase text-muted">
        {ticker ? `${ticker} - Price` : 'Select a ticker'}
      </h2>
      <div data-testid="main-chart" ref={el} className="min-h-[150px] flex-1" />
    </section>
  );
}
