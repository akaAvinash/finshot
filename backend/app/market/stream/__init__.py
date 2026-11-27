"""Owner-only live market stream (contracts/live-market-stream.asyncapi.yaml).

Read-only. A server-side upstream feed (a mock, or Zerodha Kite Connect) is
fanned out to the owner's WebSocket connections. Nothing in this package
places, modifies or reads orders, and no provider data is written to the
database (Kite terms 4(b), backend/docs/DATA_RIGHTS.md)."""
