// SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
// Copyright 2026 SymonSaysLLC
// SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
/* The rack: what is running, what the weight store holds, and what has drifted.
 *
 * Every figure comes from the component that owns it — the board owns configured and live,
 * the store owns the weights, the agents runtime owns the runs. Nothing is computed here.
 * A page that derived the GPU figure itself would be a second implementation of a number the
 * board already publishes, and two implementations of one number always drift.
 *
 * WHEN A SOURCE DOES NOT ANSWER it is named, with the reason, rather than omitted. This page
 * replaced one that said "not built yet" — honest, and useless. The failure it must not repeat
 * is the opposite: a frame that renders cleanly while half the estate is down.
 */
import { fromService } from "@/lib/server";

export const dynamic = "force-dynamic";

interface Source {
  component: string;
  ok: boolean;
  status: number;
  why: string | null;
}

interface LiveRow {
  key: string;
  value: string;
  note: string;
  differs: boolean;
}

export default async function Page() {
  const [live, check, models, where, runs] = await Promise.all([
    fromService("board", "/api/board/live"),
    fromService("board", "/api/board/check"),
    fromService("store", "/api/store/models"),
    fromService("store", "/api/store/where"),
    fromService("agents", "/api/agents/runs"),
  ]);

  const sources: Source[] = [live, check, models, where, runs].map((r) => ({
    component: r.component,
    ok: r.ok,
    status: r.status,
    why: r.why,
  }));

  const liveRows: LiveRow[] = live.ok
    ? (((live.data as Record<string, unknown>)?.live as LiveRow[]) ?? [])
    : [];
  const drifted = liveRows.filter((r) => r.differs);
  const checkData = check.ok ? (check.data as { ok: boolean; problems: { kind: string; name: string; why: string }[] }) : null;
  const modelRows = models.ok ? (((models.data as Record<string, unknown>)?.models as Record<string, unknown>[]) ?? []) : [];
  const storeInfo = where.ok ? (where.data as Record<string, unknown>) : null;
  const runRows = runs.ok ? (((runs.data as Record<string, unknown>)?.runs as Record<string, unknown>[]) ?? []) : [];

  const down = sources.filter((s) => !s.ok);

  return (
    <>
      <header className="page-head">
        <h1 className="page-title">Rack</h1>
        <p className="page-sub">Units, weights and runs — each read from the component that owns it.</p>
      </header>

      {down.length > 0 && (
        <div className="panel">
          <div className="card-body stack">
            <span className="badge badge-warn">{down.length} source(s) not answering</span>
            {down.map((s) => (
              <p key={s.component} className="muted" style={{ margin: 0 }}>
                <strong>{s.component}</strong> — {s.why ?? `HTTP ${s.status}`}
              </p>
            ))}
            <p className="muted" style={{ margin: 0 }}>
              Unconfigured and broken are different states. A service that names the variable it
              wants is waiting for provisioning, not failing.
            </p>
          </div>
        </div>
      )}

      {liveRows.length > 0 && (
        <div className="panel panel-lifted">
          <div className="card-body stack">
            <span className="card-title">Live</span>
            {drifted.length > 0 && (
              <span className="badge badge-warn">
                {drifted.length} value(s) differ from the board
              </span>
            )}
            {liveRows.map((r) => (
              <div key={r.key} className="row between">
                <span className="mono">{r.key}</span>
                <span className={r.differs ? "badge badge-warn" : "muted"}>{r.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {checkData && (
        <div className="panel">
          <div className="card-body stack">
            <span className="card-title">Board check</span>
            {checkData.ok ? (
              <span className="badge">every path exists, every port is a port, nothing is stale</span>
            ) : (
              checkData.problems.map((p) => (
                <p key={p.name} className="muted" style={{ margin: 0 }}>
                  <strong>{p.kind}</strong> {p.name} — {p.why}
                </p>
              ))
            )}
          </div>
        </div>
      )}

      {storeInfo && (
        <div className="panel">
          <div className="card-body stack">
            <span className="card-title">Weight store</span>
            <div className="row between">
              <span className="mono">{String(storeInfo.store)}</span>
              <span className={storeInfo.is_disk ? "muted" : "badge badge-warn"}>
                {storeInfo.is_disk ? `${storeInfo.free_gib} GiB free` : String(storeInfo.why)}
              </span>
            </div>
            <span className="muted">uuid {String(storeInfo.uuid ?? "none")}</span>
            {modelRows.map((m) => (
              <div key={String(m.name)} className="row between">
                <span className="mono">{String(m.name)}</span>
                <span className={m.manifest ? "muted" : "badge badge-warn"}>
                  {m.manifest ? `${m.tracked_files} files tracked` : "no manifest — cannot be verified"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {runs.ok && (
        <div className="panel">
          <div className="card-body stack">
            <span className="card-title">Agent runs</span>
            {runRows.length === 0 ? (
              <span className="muted">none</span>
            ) : (
              runRows.map((r) => (
                <div key={String(r.id)} className="row between">
                  <span className="mono">{String(r.name)}</span>
                  <span className="muted">
                    {String(r.state)} · {String(r.elapsed_s)}s · {String(r.calls)} call(s)
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </>
  );
}
