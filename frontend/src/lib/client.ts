import { QueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";

/** One cache for the whole app; also used by the imperative note actions in `shelves.ts`. */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: true,
      retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
    },
  },
});
