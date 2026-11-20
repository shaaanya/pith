import { createHashRouter } from "react-router";
import { Inbox } from "@/features/inbox";
import { Library } from "@/features/library";
import { Reader } from "@/features/reader";
import { Search } from "@/features/search";
import { Settings } from "@/features/settings";
import { ShelfPage, Shelves } from "@/features/shelf";
import { Desk } from "@/features/desk";
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
      { index: true, element: <Desk /> },
      { path: "inbox", element: <Inbox /> },
      { path: "shelves", element: <Shelves /> },
      { path: "shelf/:id", element: <ShelfPage /> },
      { path: "library", element: <Library /> },
      { path: "note/:id", element: <Reader /> },
      { path: "search", element: <Search /> },
      { path: "settings", element: <Settings /> },
    ],
  },
]);
