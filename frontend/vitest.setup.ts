import "@testing-library/jest-dom/vitest";
import { vi } from 'vitest';

// jsdom has no canvas: stub Lightweight Charts.
vi.mock('lightweight-charts', () => {
  const series = { setData: vi.fn(), applyOptions: vi.fn(), update: vi.fn() };
  const chart = {
    addLineSeries: () => series,
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: vi.fn(),
  };
  return { createChart: () => chart };
});
