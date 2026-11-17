import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { z } from "zod";
import { router } from "./app/router";
import { ToastProvider } from "./components/toast";
import { ApiError } from "./lib/api";
import { applyTheme, getTheme } from "./lib/local";
import "./index.css";

z.config({ jitless: true }); // the page CSP forbids dynamic code generation
// Radix (react-remove-scroll) injects a <style> when a dialog opens; give it the page nonce or the CSP blocks it.
(globalThis as { __webpack_nonce__?: string }).__webpack_nonce__ =
  document.querySelector<HTMLScriptElement>("script[nonce]")?.nonce || undefined;
applyTheme(getTheme());

// React Query's styles-free runtime; one cache for the whole app.
const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: true,
      retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  </StrictMode>,
);
