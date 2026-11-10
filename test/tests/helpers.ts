import { expect, Page } from '@playwright/test';

export const DEFAULTS = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA', 'NVDA', 'META', 'JPM', 'V', 'NFLX'];

export async function load(page: Page) {
  await page.goto('/');
  await expect(page.getByTestId('watchlist-row-AAPL')).toBeVisible();
}

export async function cash(page: Page): Promise<number> {
  const t = (await page.getByTestId('cash-balance').innerText()).replace(/[^0-9.\-]/g, '');
  return parseFloat(t);
}

export async function trade(page: Page, ticker: string, qty: number, side: 'buy' | 'sell') {
  await page.getByTestId('trade-ticker').fill(ticker);
  await page.getByTestId('trade-quantity').fill(String(qty));
  await page.getByTestId(`trade-${side}`).click();
}
