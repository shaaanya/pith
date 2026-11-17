import { createHashRouter } from "react-router";
import { Inbox } from "@/features/inbox";
import { Library } from "@/features/library";
import { Reader } from "@/features/reader";
import { Search } from "@/features/search";
import { Settings } from "@/features/settings";
import { Today } from "@/features/today";
import { RouteError, Shell } from "./shell";

/**
 * Hash routing on purpose: the Python server serves only `/` and `/index.html`, so path-based deep
 * links would 404 on reload. (Route-level code splitting is also unavailable: the server cannot serve chunk files.)
 */
export const router = createHashRouter([
  {
    element: <Shell />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Today /> },
      { path: "inbox", element: <Inbox /> },
      { path: "library", element: <Library /> },
      { path: "note/:id", element: <Reader /> },
      { path: "search", element: <Search /> },
      { path: "settings", element: <Settings /> },
    ],
  },
]);
