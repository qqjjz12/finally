'use client';
import { useEffect, useRef } from 'react';
import { createChart, type IChartApi, type ISeriesApi } from 'lightweight-charts';
import type { HistPoint } from '@/lib/priceStore';

export default function Sparkline({ data, up }: { data: HistPoint[]; up: boolean }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<'Line'> | null>(null);

  useEffect(() => {
    if (!el.current) return;
    const c = createChart(el.current, {
      width: 80,
      height: 26,
      layout: { attributionLogo: false, background: { color: "transparent" }, textColor: "transparent", fontSize: 1 },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      rightPriceScale: { visible: false },
      leftPriceScale: { visible: false },
      timeScale: { visible: false },
      crosshair: { mode: 2, vertLine: { visible: false }, horzLine: { visible: false } },
      localization: { priceFormatter: () => "" },
      handleScroll: false,
      handleScale: false,
    });
    chart.current = c;
    series.current = c.addLineSeries({ lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    return () => {
      c.remove();
      chart.current = null;
      series.current = null;
    };
  }, []);

  const len = data.length;
  useEffect(() => {
    if (!series.current) return;
    series.current.applyOptions({ color: up ? '#3fb950' : '#f85149' });
    series.current.setData(data.map((d) => ({ time: d.time as never, value: d.value })));
    chart.current?.timeScale().fitContent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [len, up, data[len - 1]?.value]);

  return <div ref={el} className="h-[26px] w-[80px] overflow-hidden" />;
}
