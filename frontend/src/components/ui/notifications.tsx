"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { CheckCircle2, X } from "lucide-react";
import { Button } from "./button";

const NotificationContext = createContext<(message: string) => void>(() => {});

export function Notifications({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState("");
  const timeout = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const dismiss = useCallback(() => {
    clearTimeout(timeout.current);
    setMessage("");
  }, []);

  const notify = useCallback((text: string) => {
    clearTimeout(timeout.current);
    setMessage(text);
    timeout.current = setTimeout(dismiss, 5000);
  }, [dismiss]);

  useEffect(() => () => clearTimeout(timeout.current), []);

  return (
    <NotificationContext.Provider value={notify}>
      {children}
      <div className="fixed inset-x-4 bottom-4 z-60 flex justify-end sm:left-auto" role="status" aria-atomic="true">
        {message && (
          <div className="flex w-full items-center gap-3 rounded-xl border border-border bg-card py-2 pl-4 pr-2 text-sm shadow-xl sm:w-auto">
            <CheckCircle2 aria-hidden className="size-4 shrink-0 text-positive" />
            <span>{message}</span>
            <Button size="icon" variant="ghost" aria-label="Dismiss notification" onClick={dismiss} className="ml-auto size-8">
              <X aria-hidden />
            </Button>
          </div>
        )}
      </div>
    </NotificationContext.Provider>
  );
}

export function useNotification() {
  return useContext(NotificationContext);
}
