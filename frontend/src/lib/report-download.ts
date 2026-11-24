import type { ReportSnapshot } from "./api/report-types";
import { formatSnapshotDate } from "./format";
import { reportDay, reportTradePnl, reportTradesCsv, summarizeReport } from "./reporting";

export function downloadReportCsv(snapshot: ReportSnapshot) {
  const file = new Blob([reportTradesCsv(snapshot)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = `tradeo-demo-trades-${snapshot.range.from}-${snapshot.range.to}.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function amount(paise: number | null) {
  return paise === null ? "Unavailable" : `INR ${(paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export async function downloadReportPdf(snapshot: ReportSnapshot, stale: boolean) {
  const { jsPDF } = await import("jspdf");
  const doc = new jsPDF();
  const totals = summarizeReport(snapshot);
  const margin = 15;
  const footer = 281;
  const period = `${formatSnapshotDate(snapshot.range.from)} to ${formatSnapshotDate(snapshot.range.to)} IST`;
  doc.setProperties({ title: "Tradeo demo performance report", subject: period, creator: "Tradeo" });

  function heading(continued = false) {
    doc.setFont("helvetica", "bold").setFontSize(17).setTextColor(28);
    doc.text("Tradeo demo performance report", margin, 21);
    doc.setFont("helvetica", "normal").setFontSize(10).setTextColor(75);
    doc.text(`${period} | ${stale ? "Stale demo snapshot" : "Demo snapshot"} ${formatSnapshotDate(snapshot.asOf)}`, margin, 28);
    if (continued) doc.text("Closed trade journal (continued)", margin, 37);
  }

  function tableHeader(y: number) {
    doc.setFillColor(242, 241, 237).rect(margin, y - 4, 180, 7, "F");
    doc.setFont("helvetica", "bold").setFontSize(9).setTextColor(35);
    doc.text("Close date (IST)", margin + 2, y);
    doc.text("Symbol", 56, y);
    doc.text("Broker", 86, y);
    doc.text("Qty", 126, y, { align: "right" });
    doc.text("Charges", 157, y, { align: "right" });
    doc.text("Net realized", 193, y, { align: "right" });
  }

  heading();
  doc.setFontSize(11).setTextColor(28);
  const entries: [string, number | null][] = [
    ["Gross realized P&L", totals.grossPaise], ["Brokerage", totals.brokeragePaise], ["Taxes and other charges", totals.taxesPaise],
    ["Net realized P&L", totals.realizedPaise], ["Unrealized P&L at snapshot", totals.unrealizedPaise], ["Combined net P&L", totals.netPaise],
  ];
  entries.forEach(([label, value], index) => {
    const y = 42 + index * 7;
    doc.text(label, margin, y);
    doc.text(amount(value), 195, y, { align: "right" });
  });
  doc.setFontSize(9).setTextColor(75);
  doc.text("Simulated ledger. Open-position P&L excludes unincurred closing charges.", margin, 87);
  doc.setFont("helvetica", "bold").setFontSize(12).setTextColor(28);
  doc.text(`Closed trade journal (${snapshot.trades.length})`, margin, 99);

  let y = 108;
  tableHeader(y);
  for (const trade of snapshot.trades) {
    y += 7;
    if (y > footer - 10) {
      doc.addPage();
      heading(true);
      tableHeader(45);
      y = 52;
    }
    const accounting = reportTradePnl(trade);
    doc.setFont("helvetica", "normal").setFontSize(9).setTextColor(35);
    doc.text(reportDay(trade.closedAt), margin + 2, y);
    doc.text(trade.symbol, 56, y);
    doc.text(trade.broker, 86, y);
    doc.text(String(trade.quantity), 126, y, { align: "right" });
    doc.text(amount(accounting.chargesPaise), 157, y, { align: "right" });
    doc.text(amount(accounting.netPaise), 193, y, { align: "right" });
  }

  for (let page = 1; page <= doc.getNumberOfPages(); page++) {
    doc.setPage(page).setFont("helvetica", "normal").setFontSize(9).setTextColor(75);
    doc.text(`DEMO DATA | ${page} / ${doc.getNumberOfPages()}`, 195, footer, { align: "right" });
  }
  doc.save(`tradeo-demo-report-${snapshot.range.from}-${snapshot.range.to}.pdf`);
}
