import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Page from '@/app/page';
import * as api from '@/lib/api';

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
  return {
    ApiError: actual.ApiError,
    STREAM_URL: actual.STREAM_URL,
    getPortfolio: vi.fn(),
    getHistory: vi.fn(),
    getWatchlist: vi.fn(),
    getChat: vi.fn(),
    sendChat: vi.fn(),
    trade: vi.fn(),
    addTicker: vi.fn(),
    removeTicker: vi.fn(),
  };
});

const portfolio = {
  cash_balance: 10000,
  total_value: 10000,
  unrealized_pnl: 0,
  positions: [],
};

describe('watchlist CRUD (page)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getPortfolio).mockResolvedValue(portfolio);
    vi.mocked(api.getHistory).mockResolvedValue([]);
    vi.mocked(api.getChat).mockResolvedValue([]);
    vi.mocked(api.getWatchlist).mockResolvedValue([
      { ticker: 'AAPL', price: 190, previous_price: 189, reference_price: 189 },
      { ticker: 'MSFT', price: 400, previous_price: 400, reference_price: 395 },
    ]);
  });

  it('renders rows with prices and daily change', async () => {
    render(<Page />);
    expect(await screen.findByTestId('watchlist-row-AAPL')).toBeInTheDocument();
    expect(screen.getByTestId('price-MSFT')).toHaveTextContent('400.00');
    expect(screen.getByTestId('change-MSFT')).toHaveTextContent('+1.27%');
    await waitFor(() => expect(screen.getByTestId('cash-balance')).toHaveTextContent('$10,000.00'));
  });

  it('adds a ticker and refreshes', async () => {
    vi.mocked(api.addTicker).mockResolvedValue({});
    render(<Page />);
    await screen.findByTestId('watchlist-row-AAPL');
    await userEvent.type(screen.getByTestId('add-ticker-input'), 'pypl');
    await userEvent.click(screen.getByTestId('add-ticker-button'));
    expect(api.addTicker).toHaveBeenCalledWith('PYPL');
    await waitFor(() => expect(api.getWatchlist).toHaveBeenCalledTimes(2));
  });

  it('shows add errors', async () => {
    vi.mocked(api.addTicker).mockRejectedValue(new api.ApiError('Unknown ticker', 'unknown_ticker', 400));
    render(<Page />);
    await screen.findByTestId('watchlist-row-AAPL');
    await userEvent.type(screen.getByTestId('add-ticker-input'), 'zzzz');
    await userEvent.click(screen.getByTestId('add-ticker-button'));
    expect(await screen.findByTestId('watchlist-error')).toHaveTextContent('Unknown ticker');
  });

  it('removes a ticker', async () => {
    vi.mocked(api.removeTicker).mockResolvedValue({});
    render(<Page />);
    await userEvent.click(await screen.findByTestId('remove-MSFT'));
    expect(api.removeTicker).toHaveBeenCalledWith('MSFT', false);
  });

  it('confirms and retries with confirm=true on position_open', async () => {
    vi.mocked(api.removeTicker)
      .mockRejectedValueOnce(new api.ApiError('position open', 'position_open', 409))
      .mockResolvedValueOnce({});
    render(<Page />);
    await userEvent.click(await screen.findByTestId('remove-AAPL'));
    await userEvent.click(await screen.findByTestId('confirm-remove-yes'));
    await waitFor(() => expect(api.removeTicker).toHaveBeenLastCalledWith('AAPL', true));
  });
});
