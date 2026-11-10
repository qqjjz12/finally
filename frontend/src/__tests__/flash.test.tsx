import { act, render, screen } from '@testing-library/react';
import PriceCell, { FLASH_MS } from '@/components/PriceCell';

describe('PriceCell flash', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('flashes green on uptick, red on downtick, then clears', () => {
    const { rerender } = render(<PriceCell ticker="AAPL" price={100} />);
    const el = screen.getByTestId('price-AAPL');
    expect(el).toHaveAttribute('data-flash', '');

    rerender(<PriceCell ticker="AAPL" price={101} />);
    expect(el).toHaveClass('flash-up');

    act(() => {
      vi.advanceTimersByTime(FLASH_MS + 10);
    });
    expect(el).toHaveAttribute('data-flash', '');

    rerender(<PriceCell ticker="AAPL" price={99} />);
    expect(el).toHaveClass('flash-down');
  });

  it('does not flash when price is unchanged', () => {
    const { rerender } = render(<PriceCell ticker="AAPL" price={100} />);
    rerender(<PriceCell ticker="AAPL" price={100} />);
    expect(screen.getByTestId('price-AAPL')).toHaveAttribute('data-flash', '');
  });
});
