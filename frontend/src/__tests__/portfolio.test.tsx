import { render, screen } from '@testing-library/react';
import Header from '@/components/Header';
import PositionsTable from '@/components/PositionsTable';
import { liveValuation } from '@/lib/live';
import type { Portfolio, PriceTick } from '@/lib/types';

const portfolio: Portfolio = {
  cash_balance: 5000,
  total_value: 6000,
  unrealized_pnl: 0,
  positions: [{ ticker: 'AAPL', quantity: 10, avg_cost: 100, current_price: 100, unrealized_pnl: 0, pnl_pct: 0 }],
};

describe('portfolio display', () => {
  it('revalues positions and total with live ticks', () => {
    const ticks = new Map<string, PriceTick>([
      ['AAPL', { ticker: 'AAPL', price: 110, previous_price: 100, reference_price: 100, timestamp: '', direction: 'up' }],
    ]);
    const v = liveValuation(portfolio, ticks);
    expect(v.total).toBe(6100);
    expect(v.positions[0].unrealized_pnl).toBeCloseTo(100);
    expect(v.positions[0].pnl_pct).toBeCloseTo(10);
  });

  it('renders positions table rows and header values', () => {
    const v = liveValuation(portfolio, new Map());
    render(
      <>
        <Header totalValue={v.total} cash={v.cash} status="connected" />
        <PositionsTable positions={v.positions} />
      </>,
    );
    expect(screen.getByTestId('cash-balance')).toHaveTextContent('$5,000.00');
    expect(screen.getByTestId('total-value')).toHaveTextContent('$6,000.00');
    expect(screen.getByTestId('connection-status')).toHaveAttribute('data-status', 'connected');
    expect(screen.getByTestId('position-row-AAPL')).toHaveTextContent('$100.00');
  });

  it('shows an empty state', () => {
    render(<PositionsTable positions={[]} />);
    expect(screen.getByText('No open positions')).toBeInTheDocument();
  });
});
