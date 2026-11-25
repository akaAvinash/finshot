import { useEffect, useRef, useState } from "react";
import type { WorkspaceRequestOptions, WorkspaceResult, WorkspaceScenario } from "@/lib/api/workspace-controls-types";
import { WorkspacePreviewError } from "@/lib/workspace-controls";

type Request = { scenario: WorkspaceScenario };

export function useWorkspacePreview<T, C>(
  read: (options?: WorkspaceRequestOptions) => Promise<WorkspaceResult<T>>,
  mutate: (command: C, options?: WorkspaceRequestOptions) => Promise<T>,
) {
  const [request, setRequest] = useState<Request>({ scenario: "ready" });
  const [settled, setSettled] = useState<{ request: Request; result: WorkspaceResult<T> | { status: "error" } }>();
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  const result = settled?.request === request ? settled.result : undefined;

  useEffect(() => {
    const controller = new AbortController();
    read({ scenario: request.scenario, signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setSettled({ request, result }); })
      .catch(() => { if (!controller.signal.aborted) setSettled({ request, result: { status: "error" } }); });
    return () => controller.abort();
  }, [read, request]);

  useEffect(() => () => active.current?.abort(), []);

  function load(scenario: WorkspaceScenario) {
    if (active.current) return;
    setActionError(null);
    setRequest({ scenario });
  }

  async function run(command: C) {
    if (active.current || result?.status !== "ready") return false;
    const controller = new AbortController();
    active.current = controller;
    setBusy(true);
    setActionError(null);
    try {
      const data = await mutate(command, { scenario: request.scenario, signal: controller.signal });
      if (controller.signal.aborted) return false;
      setSettled({ request, result: { status: "ready", data } });
      return true;
    } catch (error) {
      if (!controller.signal.aborted) setActionError(error instanceof WorkspacePreviewError ? error.message : "The demo action could not be saved. Try again.");
      return false;
    } finally {
      active.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return { scenario: request.scenario, result, busy, actionError, setActionError, load, run };
}
