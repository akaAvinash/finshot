import { Bell, ChartNoAxesCombined, ClipboardList, FlaskConical, Layers, LayoutDashboard, Network, Plug, Settings, Zap } from "lucide-react";

export const dashboardRoute = { slug: "dashboard", title: "Dashboard", icon: LayoutDashboard };
export const marketRoute = { slug: "markets", title: "Markets", icon: ChartNoAxesCombined };
export const autoTradingRoute = { slug: "auto-trading", title: "Auto Trading", icon: Zap };
export const brokersRoute = { slug: "brokers", title: "Brokers", icon: Plug };
export const strategiesRoute = { slug: "strategies", title: "Strategies", icon: Layers };

export const sections = [
  { slug: "backtesting", title: "Backtesting", icon: FlaskConical, description: "Review historical strategy simulations.", empty: "There are no backtest results in this preview." },
  { slug: "reports", title: "Reports", icon: ClipboardList, description: "Profit and loss, trade history and performance reports.", empty: "There are no reports to export in this preview." },
  { slug: "agents", title: "Agents", icon: Network, description: "Activity and status for trading agents.", empty: "There are no running agents in this preview." },
  { slug: "alerts", title: "Alerts", icon: Bell, description: "Workspace alerts and market notifications.", empty: "There are no alerts. The preview has no background monitoring." },
  { slug: "settings", title: "Settings", icon: Settings, description: "Workspace preferences and account settings.", empty: "Account settings become available when real authentication is connected." },
] as const;

export const workspaceRoutes = [dashboardRoute, marketRoute, autoTradingRoute, brokersRoute, strategiesRoute, ...sections];
