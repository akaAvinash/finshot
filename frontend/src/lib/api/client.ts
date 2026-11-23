import { createMockClient, type PreviewScenario } from "./mock";
import type { TradeoClient } from "./types";

export function createTradeoClient(options: { previewScenario?: PreviewScenario } = {}): TradeoClient {
  return createMockClient(options.previewScenario);
}
