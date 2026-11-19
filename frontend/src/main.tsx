import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import { QueryClientProvider } from "@tanstack/react-query";
import { z } from "zod";
import { router } from "./app/router";
import { ToastProvider } from "./components/toast";
import { queryClient } from "./lib/client";
import { migrateLocal } from "./lib/migrate-local";
import { applyTheme, getTheme } from "./lib/local";
import "./index.css";

z.config({ jitless: true }); // the page CSP forbids dynamic code generation
// Radix (react-remove-scroll) injects a <style> when a dialog opens; give it the page nonce or the CSP blocks it.
(globalThis as { __webpack_nonce__?: string }).__webpack_nonce__ =
  document.querySelector<HTMLScriptElement>("script[nonce]")?.nonce || undefined;
applyTheme(getTheme());

void migrateLocal().then(() => queryClient.invalidateQueries());
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
