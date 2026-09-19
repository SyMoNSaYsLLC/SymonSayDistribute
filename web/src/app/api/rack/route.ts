// SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
// Copyright 2026 SymonSaysLLC
// SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
/* The rack, assembled from the components that own each part of it.
 *
 * Nothing here computes anything. The board owns what is configured and what is live, the
 * store owns what weights exist, the agents runtime owns what is running. This asks each of
 * them and puts the answers side by side.
 *
 * That matters more than it sounds: a page that derived the GPU figure itself would be a
 * second implementation of a number the board already publishes, and the two would drift.
 * One owner per fact.
 */
import { fromService } from "@/lib/server";

export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  const [live, check, models, store, agents] = await Promise.all([
    fromService("board", "/api/board/live"),
    fromService("board", "/api/board/check"),
    fromService("store", "/api/store/models"),
    fromService("store", "/api/store/where"),
    fromService("agents", "/api/agents/runs"),
  ]);

  // Which parts answered, and which did not and why. A surface that shows only what worked
  // is a surface that looks healthy when half the estate is down.
  const sources = [live, check, models, store, agents].map((r) => ({
    component: r.component,
    ok: r.ok,
    status: r.status,
    why: r.why,
  }));

  return Response.json(
    {
      at: new Date().toISOString(),
      live: live.ok ? live.data : null,
      check: check.ok ? check.data : null,
      models: models.ok ? models.data : null,
      store: store.ok ? store.data : null,
      agents: agents.ok ? agents.data : null,
      sources,
      degraded: sources.some((s) => !s.ok),
    },
    { headers: { "cache-control": "no-store" } },
  );
}
