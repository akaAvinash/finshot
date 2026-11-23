import type { Instrument } from "@/lib/api/market-types";

function normalize(value: string) {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

export function searchInstruments(instruments: readonly Instrument[], query: string): Instrument[] {
  const term = normalize(query);
  if (!term) return query.trim() ? [] : [...instruments];

  return instruments.flatMap((instrument) => {
    const symbol = normalize(instrument.symbol);
    const identifiers = [instrument.id, ...instrument.aliases].map(normalize);
    const name = normalize(instrument.name);
    const score = symbol === term || identifiers.includes(term) ? 0
      : symbol.startsWith(term) || identifiers.some((alias) => alias.startsWith(term)) ? 1
        : name.startsWith(term) ? 2
          : [symbol, name, ...identifiers].some((value) => value.includes(term)) ? 3
            : -1;
    return score < 0 ? [] : [{ instrument, score }];
  }).sort((left, right) => left.score - right.score).map(({ instrument }) => instrument);
}
