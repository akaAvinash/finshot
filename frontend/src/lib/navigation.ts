import { Bell, ChartNoAxesCombined, ClipboardList, FlaskConical, Layers, LayoutDashboard, Network, Plug, Settings, Zap } from "lucide-react";

export const dashboardRoute = { slug: "dashboard", title: "Dashboard", icon: LayoutDashboard };
export const marketRoute = { slug: "markets", title: "Markets", icon: ChartNoAxesCombined };
export const autoTradingRoute = { slug: "auto-trading", title: "Auto Trading", icon: Zap };
export const brokersRoute = { slug: "brokers", title: "Brokers", icon: Plug };
export const strategiesRoute = { slug: "strategies", title: "Strategies", icon: Layers };
export const backtestingRoute = { slug: "backtesting", title: "Backtesting", icon: FlaskConical };
export const agentsRoute = { slug: "agents", title: "Agents", icon: Network };

const reportsSection = { slug: "reports", title: "Reports", icon: ClipboardList, description: "Profit and loss, trade history and performance reports.", empty: "There are no reports to export in this preview." } as const;
const remainingSections = [
  { slug: "alerts", title: "Alerts", icon: Bell, description: "Workspace alerts and market notifications.", empty: "There are no alerts. The preview has no background monitoring." },
  { slug: "settings", title: "Settings", icon: Settings, description: "Workspace preferences and account settings.", empty: "Account settings become available when real authentication is connected." },
] as const;

export const sections = [reportsSection, ...remainingSections];
export const workspaceRoutes = [dashboardRoute, marketRoute, autoTradingRoute, brokersRoute, strategiesRoute, backtestingRoute, reportsSection, agentsRoute, ...remainingSections];
