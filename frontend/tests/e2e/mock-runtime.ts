import type { Route } from "@playwright/test";
import { runtime } from "../fixtures";

export async function fulfillRuntime(route: Route): Promise<boolean> {
  const path = new URL(route.request().url()).pathname;
  if (path.endsWith("/runtime")) { await route.fulfill({ json: runtime }); return true; }
  if (path.endsWith("/models") || path.endsWith("/providers")) { await route.fulfill({ json: [] }); return true; }
  return false;
}
