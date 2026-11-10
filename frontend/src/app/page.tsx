'use client';
import { useCallback, useEffect, useMemo, useState } from 'react';
import * as api from '@/lib/api';
import { liveValuation } from '@/lib/live';
import { priceStore, usePriceStore } from '@/lib/priceStore';
import type { HistoryPoint, Portfolio, WatchlistItem } from '@/lib/types';
import ChatPanel from '@/components/ChatPanel';
import Header from '@/components/Header';
import Heatmap from '@/components/Heatmap';
import MainChart from '@/components/MainChart';
import PnlChart from '@/components/PnlChart';
import PositionsTable from '@/components/PositionsTable';
import TradeBar from '@/components/TradeBar';
import Watchlist from '@/components/Watchlist';

export default function Page() {
  const store = usePriceStore();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);

  const refreshPortfolio = useCallback(() => api.getPortfolio().then(setPortfolio).catch(() => {}), []);
  const refreshHistory = useCallback(() => api.getHistory().then(setHistory).catch(() => {}), []);
  const refreshWatchlist = useCallback(
    () =>
      api
        .getWatchlist()
        .then((w) => {
          setWatchlist(w);
          setSelected((s) => s ?? w[0]?.ticker ?? null);
        })
        .catch(() => {}),
    [],
  );
  const refreshAll = useCallback(() => {
    refreshPortfolio();
    refreshHistory();
    refreshWatchlist();
  }, [refreshPortfolio, refreshHistory, refreshWatchlist]);

  useEffect(() => {
    priceStore.connect();
    refreshAll();
    const fast = setInterval(refreshPortfolio, 5000);
    const slow = setInterval(refreshHistory, 30000);
    return () => {
      clearInterval(fast);
      clearInterval(slow);
      priceStore.disconnect();
    };
  }, [refreshAll, refreshPortfolio, refreshHistory]);

  const live = useMemo(
    () => liveValuation(portfolio, store.ticks),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [portfolio, store.version],
  );

  const doTrade = async (ticker: string, qty: number, side: 'buy' | 'sell') => {
    try {
      await api.trade(ticker, qty, side);
      refreshAll();
      return null;
    } catch (e) {
      return (e as Error).message;
    }
  };

  const doAdd = async (ticker: string) => {
    try {
      await api.addTicker(ticker);
      await refreshWatchlist();
      return null;
    } catch (e) {
      return (e as Error).message;
    }
  };

  const finishRemove = async (ticker: string, confirm: boolean) => {
    try {
      await api.removeTicker(ticker, confirm);
      setSelected((s) => (s === ticker ? null : s));
      await refreshWatchlist();
      refreshPortfolio();
    } catch (e) {
      if (e instanceof api.ApiError && e.code === 'position_open' && !confirm) setConfirmRemove(ticker);
    }
  };

  return (
    <div className="flex h-screen flex-col gap-1 bg-bg p-1">
      <Header totalValue={live.total} cash={live.cash} status={store.status} />
      <div className="flex min-h-0 flex-1 gap-1">
        <div className="grid min-h-0 min-w-0 flex-1 grid-cols-[320px_1fr_1fr] grid-rows-[minmax(0,1.2fr)_minmax(0,1fr)_auto] gap-1">
          <div className="row-span-2 flex min-h-0 flex-col">
            <Watchlist
              items={watchlist}
              selected={selected}
              onSelect={setSelected}
              onAdd={doAdd}
              onRemove={(t) => finishRemove(t, false)}
            />
          </div>
          <div className="col-span-2 flex min-h-0 flex-col">
            <MainChart ticker={selected} />
          </div>
          <div className="flex min-h-0 flex-col">
            <Heatmap positions={live.positions} />
          </div>
          <div className="flex min-h-0 flex-col">
            <PnlChart points={history} />
          </div>
          <div className="col-span-3">
            <TradeBar selected={selected} onTrade={doTrade} />
          </div>
        </div>
        <ChatPanel onActions={refreshAll} />
      </div>
      <div className="h-44 shrink-0">
        <PositionsTable positions={live.positions} />
      </div>

      {confirmRemove && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div data-testid="confirm-dialog" role="dialog" className="w-96 rounded border border-border bg-panel p-4">
            <p className="mb-4">
              You hold a position in <b>{confirmRemove}</b>. Removing it from the watchlist stops its price from
              updating (the position stays, valued at the last price). Remove anyway?
            </p>
            <div className="flex justify-end gap-2">
              <button
                data-testid="confirm-remove-no"
                onClick={() => setConfirmRemove(null)}
                className="rounded border border-border px-3 py-1"
              >
                Cancel
              </button>
              <button
                data-testid="confirm-remove-yes"
                onClick={() => {
                  const t = confirmRemove;
                  setConfirmRemove(null);
                  finishRemove(t, true);
                }}
                className="rounded bg-secondary px-3 py-1 font-semibold text-white"
              >
                Remove
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
