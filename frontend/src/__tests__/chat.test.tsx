import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ChatPanel from '@/components/ChatPanel';
import * as api from '@/lib/api';

vi.mock('@/lib/api', () => ({ getChat: vi.fn(), sendChat: vi.fn() }));

describe('ChatPanel', () => {
  beforeEach(() => {
    vi.mocked(api.getChat).mockResolvedValue([
      { role: 'user', content: 'hi' },
      { role: 'assistant', content: 'hello there', actions: [] },
    ]);
  });

  it('loads stored history', async () => {
    render(<ChatPanel onActions={() => {}} />);
    expect(await screen.findByText('hello there')).toBeInTheDocument();
  });

  it('shows loading indicator then reply with inline ok and error actions', async () => {
    let resolve!: (v: never) => void;
    vi.mocked(api.sendChat).mockReturnValue(new Promise((r) => (resolve = r as never)) as never);
    const onActions = vi.fn();
    render(<ChatPanel onActions={onActions} />);
    await screen.findByText('hello there');

    await userEvent.type(screen.getByTestId('chat-input'), 'buy some');
    await userEvent.click(screen.getByTestId('chat-send'));
    expect(screen.getByTestId('chat-loading')).toBeInTheDocument();

    resolve({
      message: 'Done.',
      actions: [
        { type: 'trade', ticker: 'AAPL', side: 'buy', quantity: 10, status: 'ok' },
        {
          type: 'trade',
          ticker: 'TSLA',
          side: 'buy',
          quantity: 1000000,
          status: 'error',
          code: 'insufficient_cash',
          message: 'Not enough cash',
        },
      ],
    } as never);
    await waitFor(() => expect(screen.queryByTestId('chat-loading')).not.toBeInTheDocument());
    const actions = screen.getAllByTestId('chat-action');
    expect(actions).toHaveLength(2);
    expect(actions[0]).toHaveAttribute('data-status', 'ok');
    expect(actions[1]).toHaveAttribute('data-status', 'error');
    expect(actions[1]).toHaveTextContent('Not enough cash');
    expect(onActions).toHaveBeenCalled();
  });
});
