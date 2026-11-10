'use client';
import { useEffect, useRef, useState } from 'react';
import { num } from '@/lib/format';

export const FLASH_MS = 500;

/** Shows a price; briefly applies flash-up / flash-down when the value changes. */
export default function PriceCell({ ticker, price }: { ticker: string; price: number | null | undefined }) {
  const prev = useRef<number | null | undefined>(price);
  const [flash, setFlash] = useState<'' | 'flash-up' | 'flash-down'>('');

  useEffect(() => {
    if (price == null || prev.current == null || price === prev.current) {
      prev.current = price;
      return;
    }
    setFlash(price > prev.current ? 'flash-up' : 'flash-down');
    prev.current = price;
    const t = setTimeout(() => setFlash(''), FLASH_MS);
    return () => clearTimeout(t);
  }, [price]);

  return (
    <span data-testid={`price-${ticker}`} data-flash={flash} className={`price-cell font-mono ${flash}`}>
      {num(price)}
    </span>
  );
}
