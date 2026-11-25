import { Bell, ChartNoAxesCombined, ClipboardList, FlaskConical, Layers, LayoutDashboard, Network, Plug, Settings, Zap } from "lucide-react";

export const dashboardRoute = { slug: "dashboard", title: "Dashboard", icon: LayoutDashboard };
export const marketRoute = { slug: "markets", title: "Markets", icon: ChartNoAxesCombined };
export const autoTradingRoute = { slug: "auto-trading", title: "Auto Trading", icon: Zap };
export const brokersRoute = { slug: "brokers", title: "Brokers", icon: Plug };
export const strategiesRoute = { slug: "strategies", title: "Strategies", icon: Layers };
export const backtestingRoute = { slug: "backtesting", title: "Backtesting", icon: FlaskConical };
export const alertsRoute = { slug: "alerts", title: "Alerts", icon: Bell };
export const settingsRoute = { slug: "settings", title: "Settings", icon: Settings };

export const sections = [
  { slug: "reports", title: "Reports", icon: ClipboardList, description: "Profit and loss, trade history and performance reports.", empty: "There are no reports to export in this preview." },
  { slug: "agents", title: "Agents", icon: Network, description: "Activity and status for trading agents.", empty: "There are no running agents in this preview." },
] as const;

export const workspaceRoutes = [dashboardRoute, marketRoute, autoTradingRoute, brokersRoute, strategiesRoute, backtestingRoute, ...sections, alertsRoute, settingsRoute];
