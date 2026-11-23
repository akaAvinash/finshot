import { createMockClient, type PreviewScenario } from "./mock";
import { createMarketMock, type MarketChartScenario } from "./market-mock";
import { createPaperTradingMock } from "./auto-trading-mock";
import type { TradeoClient } from "./types";

export function createTradeoClient(options: {
  previewScenario?: PreviewScenario;
  marketChartScenario?: MarketChartScenario;
} = {}): TradeoClient {
  return {
    ...createMockClient(options.previewScenario),
    ...createMarketMock(options.marketChartScenario),
    ...createPaperTradingMock(),
  };
}
