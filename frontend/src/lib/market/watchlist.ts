"use client";

import { useMemo, useSyncExternalStore } from "react";

const storageKey = "tradeo-market-watchlist-v1";
const updatedEvent = "tradeo:watchlist-updated";

export const defaultWatchlist = ["NSE:NIFTY50", "NSE:BANKNIFTY", "NSE:RELIANCE", "NSE:HDFCBANK", "NSE:SBIN"];

let inMemory: string | null = null;
let storageUnavailable = false;

function getSnapshot() {
  if (storageUnavailable) return inMemory;
  try {
    return window.localStorage.getItem(storageKey);
  } catch {
    return inMemory;
  }
}

function getServerSnapshot() {
  return null;
}

function subscribe(listener: () => void) {
  function syncStorage(event: StorageEvent) {
    if (event.key === storageKey || event.key === null) listener();
  }

  window.addEventListener(updatedEvent, listener);
  window.addEventListener("storage", syncStorage);
  return () => {
    window.removeEventListener(updatedEvent, listener);
    window.removeEventListener("storage", syncStorage);
  };
}

export function parseWatchlist(value: string | null): string[] {
  if (value === null) return defaultWatchlist;
  try {
    const parsed: unknown = JSON.parse(value);
    if (Array.isArray(parsed) && parsed.every((id) => typeof id === "string")) return [...new Set<string>(parsed)];
  } catch {
    return defaultWatchlist;
  }
  return defaultWatchlist;
}

export function updateWatchlist(instrumentId: string, add: boolean) {
  const current = parseWatchlist(getSnapshot());
  const next = add ? [...new Set([...current, instrumentId])] : current.filter((id) => id !== instrumentId);
  inMemory = JSON.stringify(next);

  try {
    window.localStorage.setItem(storageKey, inMemory);
  } catch {
    storageUnavailable = true;
  }
  window.dispatchEvent(new Event(updatedEvent));
}

export function useWatchlist() {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return useMemo(() => parseWatchlist(snapshot), [snapshot]);
}
