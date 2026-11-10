import type { ConnectionState } from '@/lib/types';
import { money } from '@/lib/format';

const dot: Record<ConnectionState, string> = {
  connected: 'bg-up',
  reconnecting: 'bg-accent',
  disconnected: 'bg-down',
};

export default function Header({
  totalValue,
  cash,
  status,
}: {
  totalValue: number | null;
  cash: number | null;
  status: ConnectionState;
}) {
  return (
    <header className="flex items-center justify-between border-b border-border bg-panel px-4 py-2">
      <div className="text-lg font-bold tracking-wide">
        Fin<span className="text-accent">Ally</span>
      </div>
      <div className="flex items-center gap-6 font-mono">
        <div>
          <span className="mr-2 text-xs uppercase text-muted">Total</span>
          <span data-testid="total-value" className="text-base font-semibold text-primary">
            {money(totalValue)}
          </span>
        </div>
        <div>
          <span className="mr-2 text-xs uppercase text-muted">Cash</span>
          <span data-testid="cash-balance" className="text-base">
            {money(cash)}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted">
          <span
            data-testid="connection-status"
            data-status={status}
            title={status}
            className={`inline-block h-2.5 w-2.5 rounded-full ${dot[status]}`}
          />
          {status}
        </div>
      </div>
    </header>
  );
}
