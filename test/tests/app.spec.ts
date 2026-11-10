import { test, expect } from '@playwright/test';
import { DEFAULTS, load, cash, trade } from './helpers';

test('fresh start: 10 tickers, $10,000, prices streaming', async ({ page }) => {
  await load(page);
  for (const t of DEFAULTS) await expect(page.getByTestId(`watchlist-row-${t}`)).toBeVisible();
  await expect(page.getByTestId('cash-balance')).toContainText('10,000');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-status', 'connected');
  const el = page.getByTestId('price-AAPL');
  await expect(el).toHaveText(/\d/);
  const first = await el.innerText();
  await expect.poll(async () => el.innerText(), { timeout: 15_000 }).not.toBe(first);
});

test('add and remove a ticker', async ({ page }) => {
  await load(page);
  await page.getByTestId('add-ticker-input').fill('PYPL');
  await page.getByTestId('add-ticker-button').click();
  await expect(page.getByTestId('watchlist-row-PYPL')).toBeVisible();
  await expect(page.getByTestId('price-PYPL')).toHaveText(/\d/);
  await page.getByTestId('remove-PYPL').click();
  await expect(page.getByTestId('watchlist-row-PYPL')).toHaveCount(0);
});

test('duplicate add shows error', async ({ page }) => {
  await load(page);
  await page.getByTestId('add-ticker-input').fill('AAPL');
  await page.getByTestId('add-ticker-button').click();
  await expect(page.getByTestId('watchlist-error')).toBeVisible();
});

test('buy then sell shares; heatmap and P&L chart', async ({ page }) => {
  await load(page);
  const start = await cash(page);
  await trade(page, 'MSFT', 5, 'buy');
  await expect(page.getByTestId('position-row-MSFT')).toBeVisible();
  await expect(page.getByTestId('position-qty-MSFT')).toContainText('5');
  expect(await cash(page)).toBeLessThan(start);
  await expect(page.getByTestId('heatmap')).toBeVisible();
  await expect(page.getByTestId('heatmap-cell-MSFT')).toBeVisible();
  await expect
    .poll(async () => Number(await page.getByTestId('pnl-chart').getAttribute('data-points')))
    .toBeGreaterThanOrEqual(1);

  const mid = await cash(page);
  await trade(page, 'MSFT', 2, 'sell');
  await expect(page.getByTestId('position-qty-MSFT')).toContainText('3');
  expect(await cash(page)).toBeGreaterThan(mid);

  await trade(page, 'MSFT', 3, 'sell');
  await expect(page.getByTestId('position-row-MSFT')).toHaveCount(0);
});

test('trade errors: insufficient cash and shares', async ({ page }) => {
  await load(page);
  await trade(page, 'NVDA', 1_000_000, 'buy');
  await expect(page.getByTestId('trade-message')).toContainText(/cash|available|need/i);
  await trade(page, 'JPM', 1, 'sell');
  await expect(page.getByTestId('trade-message')).toContainText(/hold|share/i);
});

test('removing a held ticker asks for confirmation', async ({ page }) => {
  await load(page);
  await trade(page, 'V', 1, 'buy');
  await expect(page.getByTestId('position-row-V')).toBeVisible();
  await page.getByTestId('remove-V').click();
  await page.getByTestId('confirm-remove-no').click();
  await expect(page.getByTestId('watchlist-row-V')).toBeVisible();
  await page.getByTestId('remove-V').click();
  await page.getByTestId('confirm-remove-yes').click();
  await expect(page.getByTestId('watchlist-row-V')).toHaveCount(0);
  // position stays
  await expect(page.getByTestId('position-row-V')).toBeVisible();
});

test('AI chat (mock): buy, sell, watchlist, analysis', async ({ page }) => {
  await load(page);
  const send = async (text: string) => {
    await page.getByTestId('chat-input').fill(text);
    await page.getByTestId('chat-send').click();
  };
  await send('please buy some');
  await expect(page.getByTestId('chat-message').filter({ hasText: 'Bought 10 shares of AAPL.' })).toBeVisible();
  await expect(page.getByTestId('chat-action').first()).toHaveAttribute('data-status', 'ok');
  await expect(page.getByTestId('position-row-AAPL')).toBeVisible();

  await send('now sell');
  await expect(page.getByTestId('chat-message').filter({ hasText: 'Sold 5 shares of AAPL.' })).toBeVisible();
  await expect(page.getByTestId('position-qty-AAPL')).toContainText('5');

  await send('watch something');
  await expect(page.getByTestId('chat-message').filter({ hasText: 'Added PYPL to your watchlist.' })).toBeVisible();
  await expect(page.getByTestId('watchlist-row-PYPL')).toBeVisible();

  await send('how am I doing?');
  await expect(page.getByTestId('chat-message')).toHaveCount(8);

  // history survives reload
  await page.reload();
  await expect(page.getByTestId('chat-message').filter({ hasText: 'Bought 10 shares of AAPL.' })).toBeVisible();
});

test('SSE resilience: reconnects after connection drop', async ({ page }) => {
  await load(page);
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-status', 'connected');
  // Block the stream endpoint and reload so the EventSource cannot connect.
  await page.route('**/api/stream/prices', (r) => r.abort());
  await page.reload();
  await expect(page.getByTestId('connection-status')).not.toHaveAttribute('data-status', 'connected', {
    timeout: 20_000,
  });
  await page.unroute('**/api/stream/prices');
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-status', 'connected', {
    timeout: 30_000,
  });
  const el = page.getByTestId('price-AAPL');
  const v = await el.innerText();
  await expect.poll(async () => el.innerText(), { timeout: 15_000 }).not.toBe(v);
});

test('charts have non-zero height and page screenshots are captured', async ({ page }) => {
  await load(page);
  await trade(page, 'MSFT', 1, 'buy');
  await expect(page.getByTestId('position-row-MSFT')).toBeVisible();
  for (const id of ['main-chart', 'pnl-chart', 'heatmap']) {
    await expect
      .poll(async () => (await page.getByTestId(id).boundingBox())?.height ?? 0, { message: id })
      .toBeGreaterThan(50);
  }
  await page.waitForTimeout(3000); // let sparklines fill
  await page.screenshot({ path: 'test-results/full-page.png', fullPage: true });
  await page.getByTestId('watchlist-row-AAPL').screenshot({ path: 'test-results/watchlist-row.png' });
});
