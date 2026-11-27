"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { DashboardSkeleton, DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Status } from "@/components/ui/status";
import type { PaperEngineCommand } from "@/lib/api/auto-trading-types";
import { stagingError } from "@/lib/api/staging-client";
import { getStagingPaper, sendStagingPaper, type StagingPaperResult } from "@/lib/api/staging-paper";
import { formatInr, formatSnapshotDate } from "@/lib/format";
import { PaperActivity, paperTime } from "./paper-activity";
import { KillSwitch, PaperControls } from "./paper-controls";
import { StagingTradeControls } from "./staging-trade-controls";

const replayPollMs = 1500;
type PaperData = Extract<StagingPaperResult, { status: "ready" }>["data"];
const blockedReasons = {
  HALTED: "The paper engine is halted.",
  LOSS_LIMIT: "The daily loss limit was reached.",
  TRADE_LIMIT: "The daily trade limit was reached.",
  PROFIT_CAP: "The daily profit cap was reached.",
  CONSECUTIVE_LOSSES: "The consecutive-loss limit was reached.",
} as const;

function ServerTradeControls({ snapshot }: { snapshot: PaperData }) {
  const { risk, account, replay } = snapshot;
  const limits = [
    ["Daily loss used", `${formatInr(risk.dailyLossPaise / 100)} / ${formatInr(risk.lossLimitPaise / 100)}`],
    ["Trades this session", `${risk.tradesToday} / ${risk.tradeLimit}`],
    ...(risk.consecutiveLosses === undefined ? [] : [["Consecutive losses", String(risk.consecutiveLosses)]]),
    ["Per-trade risk limit", formatInr(account.perTradeRiskPaise / 100)],
    ["Paper equity", formatInr(account.equityPaise / 100)],
  ];
  return <Card aria-labelledby="paper-risk-status" className="space-y-4 p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 id="paper-risk-status" className="font-semibold">Paper risk status</h2>
      <Status tone={risk.status === "approved" ? "positive" : "negative"} dot>{risk.status === "approved" ? "Within limits" : "Risk blocked"}</Status>
    </div>
    <dl className="grid gap-3 min-[430px]:grid-cols-2 xl:grid-cols-4">
      {limits.map(([label, value]) => <div key={label} className="min-w-0 rounded-lg border border-border bg-background/45 p-3">
        <dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 text-sm font-semibold tabular-nums">{value}</dd>
      </div>)}
    </dl>
    {risk.controlsRevision !== undefined && <p className="text-xs text-muted-foreground">
      Limits revision {risk.controlsRevision}{risk.blockedReason && ` · ${blockedReasons[risk.blockedReason]}`}
    </p>}
    {replay.sessionsTotal > 0 && <p className="text-sm text-muted-foreground">
      Replay sessions {replay.sessionsDone} / {replay.sessionsTotal}{replay.sessionDate && <> · <time dateTime={replay.sessionDate}>{replay.sessionDate}</time></>}
      {replay.finished && " · Finished"}
    </p>}
  </Card>;
}

export function StagingAutoTrading({ readOnlyControls = false }: { readOnlyControls?: boolean }) {
  const [result, setResult] = useState<StagingPaperResult>();
  const [loadError, setLoadError] = useState("");
  const [commandError, setCommandError] = useState<{ action: PaperEngineCommand["action"]; message: string }>();
  const [pending, setPending] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const reading = useRef<AbortController | null>(null);
  const writing = useRef<AbortController | null>(null);
  const snapshot = result?.status === "ready" ? result.data : undefined;
  const running = snapshot?.engine === "running";

  useEffect(() => {
    if (pending) return;
    const controller = new AbortController();
    reading.current = controller;
    let timer: ReturnType<typeof setTimeout>;

    async function read() {
      try {
        const next = await getStagingPaper(controller.signal);
        if (!controller.signal.aborted) {
          setResult(next);
          setLoadError("");
        }
      } catch (error) {
        if (!controller.signal.aborted) setLoadError(stagingError(error, "The staging paper API could not refresh."));
      }
      if (running && !controller.signal.aborted) timer = setTimeout(read, replayPollMs);
    }

    timer = setTimeout(read, running ? replayPollMs : 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [pending, refresh, running]);

  useEffect(() => () => writing.current?.abort(), []);

  async function run(command: PaperEngineCommand) {
    if (writing.current || (command.action !== "halt" && (!snapshot || loadError))) return false;
    const controller = new AbortController();
    reading.current?.abort();
    writing.current = controller;
    setPending(true);
    setCommandError(undefined);
    try {
      const data = await sendStagingPaper(command, controller.signal);
      if (controller.signal.aborted) return false;
      setResult({ status: "ready", data });
      return true;
    } catch (error) {
      if (!controller.signal.aborted) setCommandError({ action: command.action, message: stagingError(error, "The paper command could not complete. Check the engine status before retrying.") });
      return false;
    } finally {
      writing.current = null;
      if (!controller.signal.aborted) {
        setPending(false);
        setRefresh((value) => value + 1);
      }
    }
  }

  return <div className="space-y-4 sm:space-y-5">
    <PageHeading title="Auto Trading" description="Run an approved strategy against demo history and inspect simulated orders and fills."
      actions={<div className="flex flex-wrap items-center gap-2"><Status tone="accent" dot>Staging paper demo</Status>
        <Button variant="outline" disabled={pending} onClick={() => setRefresh((value) => value + 1)}>Refresh paper data</Button></div>} />
    {!result && !loadError && <DashboardSkeleton label="Loading paper workspace" />}
    {loadError && <DataState error title={snapshot ? "Paper data could not refresh" : "Paper workspace could not load"}
      description={snapshot ? `${loadError} Showing the last server snapshot. The paper kill switch is still available.` : loadError}
      action={snapshot ? undefined : <KillSwitch disabled={pending} pending={pending} onRun={run}
        error={commandError?.action === "halt" ? commandError.message : undefined} />} />}
    {result?.status === "empty" && <DataState title="No paper activity" description="Activate an approved demo strategy to prepare a paper replay."
      action={<Button asChild variant="outline"><Link href="/strategies">Open Strategies</Link></Button>} />}
    {snapshot && <>
      <p className="text-xs text-muted-foreground">Staging snapshot · <time dateTime={snapshot.asOf}>{formatSnapshotDate(snapshot.asOf)} · {paperTime.format(new Date(snapshot.asOf))} IST</time></p>
      {commandError && commandError.action !== "halt" && <p role="alert" className="text-sm text-negative">{commandError.message}</p>}
      {pending && <p role="status" className="sr-only">Updating paper controls</p>}
      <PaperControls snapshot={snapshot} stale={!!loadError} pending={pending} onRun={run} allowStaleHalt
        canStart={!snapshot.replay.finished && snapshot.strategies.some(({ id }) => id === snapshot.strategyId)}
        finished={snapshot.replay.finished} haltError={commandError?.action === "halt" ? commandError.message : undefined} />
      <ServerTradeControls snapshot={snapshot} />
    </>}
    <StagingTradeControls readOnly={readOnlyControls} engineRunning={running} onSaved={() => setRefresh((value) => value + 1)} />
    {snapshot && <PaperActivity snapshot={snapshot} />}
  </div>;
}
