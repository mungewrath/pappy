import { useEffect, useMemo, useState } from 'react';
import {
  backfillHistory,
  createPayRunDraft,
  deletePayRunDraft,
  downloadDocumentUrl,
  finalizePayRun,
  finalizePendingRuns,
  generatePayStub,
  getPayRun,
  listEmployees,
  listPayRuns,
  updatePayRunDraft,
} from '../api/client';
import type {
  BackfillResult,
  Employee,
  ExtraPayLine,
  HourLine,
  HourCategory,
  PayrollResult,
  PayRun,
} from '../api/types';
import { HOUR_CATEGORIES } from '../api/types';
import {
  formatDate,
  formatDateTime,
  formatHours,
  formatMoney,
  isZeroAmount,
  todayIso,
} from '../format';

/**
 * Pay runs (design-doc.md §3.2, §6.1): open a DRAFT seeded from the
 * employee's default schedule, adjust hours, review gross, then finalize —
 * which locks it for good (corrections come later as Adjustment entries).
 * This is the mobile-primary weekly flow called out in §6.7.
 */

const currentYear = new Date().getFullYear();

/** Monday of the current week .. Sunday, paid the following Friday. */
function defaultDraftDates(): { period_start: string; period_end: string; pay_date: string } {
  const now = new Date();
  const day = (offset: number) => {
    const d = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
    d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7) + offset);
    return d.toISOString().slice(0, 10);
  };
  return { period_start: day(0), period_end: day(6), pay_date: day(11) };
}

export function PayRunsPanel() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [runs, setRuns] = useState<PayRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [year, setYear] = useState<number | 'all'>(currentYear);
  const [creating, setCreating] = useState(false);
  const [backfilling, setBackfilling] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    listEmployees().then(setEmployees).catch(() => setEmployees([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setRuns(null);
    listPayRuns(year === 'all' ? undefined : year)
      .then((result) => !cancelled && setRuns(result))
      .catch((err: unknown) => {
        if (cancelled) return;
        setRuns([]);
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [year]);

  const years = useMemo(() => {
    const set = new Set<number>([currentYear]);
    for (const run of runs ?? []) set.add(Number(run.pay_date.slice(0, 4)));
    return [...set].sort((a, b) => b - a);
  }, [runs]);

  /** The API returns runs oldest-first; the table reads better with the most
   * recent pay date on top, so the least recent sits at the bottom. */
  const orderedRuns = useMemo(() => {
    const ordered = [...(runs ?? [])];
    ordered.sort((a, b) => {
      if (a.pay_date !== b.pay_date) return a.pay_date < b.pay_date ? 1 : -1;
      return a.run_id < b.run_id ? 1 : -1;
    });
    return ordered;
  }, [runs]);

  const pendingDraftCount = (runs ?? []).filter((run) => run.status === 'DRAFT').length;

  const refreshRuns = () =>
    listPayRuns(year === 'all' ? undefined : year)
      .then(setRuns)
      .catch(() => {});

  /** Bulk-locks pending drafts oldest-first — the only order that keeps
   * wage-base caps correct when history arrives out of order. */
  const finalizePending = async () => {
    if (!window.confirm('Finalize all pending drafts oldest-pay-date-first?\n\nFinalized runs are immutable.')) {
      return;
    }
    setStatus('Finalizing…');
    try {
      const result = await finalizePendingRuns({ year: year === 'all' ? undefined : year });
      if (result.failed.length > 0) {
        const failure = result.failed[0];
        setError(
          `Finalized ${result.finalized.length} run(s), then stopped at ${formatDate(failure.pay_date)}: ${failure.detail}`,
        );
        setStatus(null);
      } else {
        setError(null);
        setStatus(`Finalized ${result.finalized.length} run(s), oldest first.`);
      }
      await refreshRuns();
    } catch (err) {
      setStatus(null);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const employeeName = (employeeId: string) =>
    employees.find((e) => e.employee_id === employeeId)?.full_name ?? 'Unknown employee';

  if (selectedId !== null) {
    return (
      <div className="panel">
        <button type="button" className="secondary" onClick={() => setSelectedId(null)}>
          ← All pay runs
        </button>
        <PayRunDetail
          runId={selectedId}
          employeeName={employeeName}
          onDeleted={(message) => {
            setSelectedId(null);
            setError(null);
            setStatus(message);
            refreshRuns();
          }}
        />
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Pay runs</h2>
        <label className="field inline">
          <span>Year</span>
          <select value={String(year)} onChange={(e) => setYear(e.target.value === 'all' ? 'all' : Number(e.target.value))}>
            <option value="all">All</option>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
        {!creating && (
          <button
            type="button"
            onClick={() => {
              setBackfilling(!backfilling);
              setCreating(false);
            }}
          >
            {backfilling ? 'Close backfill' : 'Backfill history…'}
          </button>
        )}
        {!backfilling && pendingDraftCount > 0 && (
          <button type="button" className="primary" onClick={() => void finalizePending()}>
            Finalize {pendingDraftCount} pending (oldest first)
          </button>
        )}
        {!creating && !backfilling && (
          <button
            type="button"
            onClick={() => {
              setCreating(true);
              setBackfilling(false);
            }}
          >
            New draft
          </button>
        )}
      </div>

      {error && <p className="error-banner">{error}</p>}
      {!error && status && <p className="saved-note">{status}</p>}

      {creating && (
        <NewDraftCard
          employees={employees}
          onDone={(message) => {
            setCreating(false);
            if (message) {
              setError(message);
            } else {
              setError(null);
              refreshRuns();
            }
          }}
        />
      )}

      {backfilling && (
        <BackfillCard
          employees={employees}
          onDone={(message, result) => {
            setBackfilling(false);
            if (message) {
              setError(message);
            } else {
              setError(null);
              const created = result?.created.length ?? 0;
              const skipped = result?.skipped.length ?? 0;
              setStatus(
                `Created ${created} draft${created === 1 ? '' : 's'}` +
                  (skipped > 0 ? ` (${skipped} week${skipped === 1 ? '' : 's'} skipped — overlapping or no hours)` : '') +
                  '. Review them below, then “Finalize pending” (oldest first).',
              );
              refreshRuns();
            }
          }}
        />
      )}

      {runs !== null && runs.length === 0 && !creating && (
        <p className="muted">No pay runs{year === 'all' ? '' : ` for ${year}`}. Open a draft to get started.</p>
      )}

      {runs && runs.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Status</th>
              <th>Period</th>
              <th>Pay date</th>
              <th>Employee</th>
              <th className="num">Gross</th>
              <th className="num">Net</th>
            </tr>
          </thead>
          <tbody>
            {orderedRuns.map((run) => (
              <tr key={run.run_id} className="clickable" onClick={() => setSelectedId(run.run_id)}>
                <td>
                  <span className={`badge ${run.status.toLowerCase()}`}>{run.status}</span>
                </td>
                <td>
                  {formatDate(run.period_start)} – {formatDate(run.period_end)}
                </td>
                <td>{formatDate(run.pay_date)}</td>
                <td>{employeeName(run.employee_id)}</td>
                <td className="num">{formatMoney(run.gross.gross)}</td>
                <td className="num">
                  {run.payroll ? formatMoney(run.payroll.net_pay) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function NewDraftCard({
  employees,
  onDone,
}: {
  employees: Employee[];
  onDone: (errorMessage?: string) => void;
}) {
  const defaults = defaultDraftDates();
  const [employeeId, setEmployeeId] = useState('');
  const [periodStart, setPeriodStart] = useState(defaults.period_start);
  const [periodEnd, setPeriodEnd] = useState(defaults.period_end);
  const [payDate, setPayDate] = useState(defaults.pay_date);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createPayRunDraft(employeeId, {
        period_start: periodStart,
        period_end: periodEnd,
        pay_date: payDate,
      });
      onDone();
    } catch (err) {
      setBusy(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h3>New pay run</h3>
      {employees.length === 0 ? (
        <>
          <p className="muted">Add an employee first.</p>
          <button type="button" className="secondary" onClick={() => onDone()}>
            Close
          </button>
        </>
      ) : (
        <>
          <div className="grid3">
            <label className="field">
              <span>Employee *</span>
              <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
                <option value="" disabled>
                  Choose…
                </option>
                {employees.map((employee) => (
                  <option key={employee.employee_id} value={employee.employee_id}>
                    {employee.full_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Period start</span>
              <input type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} />
            </label>
            <label className="field">
              <span>Period end</span>
              <input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
            </label>
            <label className="field">
              <span>Pay date</span>
              <input type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} />
            </label>
          </div>
          <p className="muted">
            Hours are pre-filled from the employee's default weekly schedule and can be adjusted after.
          </p>
          {error && <p className="error-banner">{error}</p>}
          <div className="actions-bar">
            <button type="submit" disabled={!employeeId || busy}>
              {busy ? 'Opening…' : 'Open draft'}
            </button>
            <button type="button" className="secondary" onClick={() => onDone()}>
              Cancel
            </button>
          </div>
        </>
      )}
    </form>
  );
}

/** Finalization is blocked server-side without a W-4 (§5.3) or a seeded rate
 * table (§5.2); point the employer at the fix instead of a bare 409. */
function finalizeErrorHint(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err);
  if (/W-4/i.test(message)) {
    return `${message} — add a Form W-4 election for this employee on the Employees tab.`;
  }
  if (/RateTable|rate table/i.test(message)) {
    return `${message} — the rate tables must be seeded before finalizing (see backend README).`;
  }
  if (/oldest-first|precedes/i.test(message)) {
    return `${message} Use “Finalize pending”, which locks drafts oldest-pay-date-first.`;
  }
  return message;
}

/** Historical entry (Phase 6): one call creates weekly drafts across a past
 * date range; they land as ordinary DRAFTs for review before finalizing. */
function BackfillCard({
  employees,
  onDone,
}: {
  employees: Employee[];
  onDone: (errorMessage?: string, result?: BackfillResult) => void;
}) {
  const [employeeId, setEmployeeId] = useState('');
  const [periodStart, setPeriodStart] = useState(`${currentYear}-01-01`);
  const [periodEnd, setPeriodEnd] = useState(todayIso());
  const [mode, setMode] = useState<'SCHEDULE' | 'FLAT'>('SCHEDULE');
  const [weeklyHours, setWeeklyHours] = useState('');
  const [payWeekday, setPayWeekday] = useState(4); // Friday
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (/^\d+(\.\d+)?$/.test(weeklyHours) === false && mode === 'FLAT') {
      setError('Weekly hours must be a decimal like 40 or 37.5.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await backfillHistory(employeeId, {
        period_start: periodStart,
        period_end: periodEnd,
        mode,
        pay_weekday: payWeekday,
        weekly_hours: mode === 'FLAT' ? weeklyHours : undefined,
      });
      onDone(undefined, result);
    } catch (err) {
      setBusy(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h3>Backfill historical pay runs</h3>
      {employees.length === 0 ? (
        <>
          <p className="muted">Add an employee first.</p>
          <button type="button" className="secondary" onClick={() => onDone()}>
            Close
          </button>
        </>
      ) : (
        <>
          <div className="grid3">
            <label className="field">
              <span>Employee *</span>
              <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
                <option value="" disabled>
                  Choose…
                </option>
                {employees.map((employee) => (
                  <option key={employee.employee_id} value={employee.employee_id}>
                    {employee.full_name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>First week starts</span>
              <input type="date" value={periodStart} onChange={(e) => setPeriodStart(e.target.value)} />
            </label>
            <label className="field">
              <span>Last day</span>
              <input type="date" value={periodEnd} onChange={(e) => setPeriodEnd(e.target.value)} />
            </label>
            <label className="field">
              <span>Hours per week</span>
              <select value={mode} onChange={(e) => setMode(e.target.value as 'SCHEDULE' | 'FLAT')}>
                <option value="SCHEDULE">Default schedule</option>
                <option value="FLAT">Flat total…</option>
              </select>
            </label>
            {mode === 'FLAT' && (
              <label className="field">
                <span>Weekly hours *</span>
                <input
                  inputMode="decimal"
                  placeholder="45"
                  value={weeklyHours}
                  onChange={(e) => setWeeklyHours(e.target.value)}
                />
              </label>
            )}
            <label className="field">
              <span>Paid on</span>
              <select value={String(payWeekday)} onChange={(e) => setPayWeekday(Number(e.target.value))}>
                {['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map(
                  (name, index) => (
                    <option key={name} value={index}>
                      following {name}
                    </option>
                  ),
                )}
              </select>
            </label>
          </div>
          <p className="muted">
            One draft per week, hours seeded from the employee's default schedule. Weeks that overlap
            existing runs are skipped. Drafts are not locked — review them, then use “Finalize pending”
            which locks oldest-first so wage-base caps stay correct.
          </p>
          {error && <p className="error-banner">{error}</p>}
          <div className="actions-bar">
            <button type="submit" disabled={!employeeId || busy || periodEnd < periodStart}>
              {busy ? 'Creating…' : 'Create drafts'}
            </button>
            <button type="button" className="secondary" onClick={() => onDone()}>
              Cancel
            </button>
          </div>
        </>
      )}
    </form>
  );
}

/** Earlier DRAFT runs for this employee in the same tax year — the runs whose
 * wages would be missing from the YTD accumulators if this one locked first
 * (§4). The server refuses the reverse case (a run preceding an already
 * finalized one) but lets this one through, so the check gates the Finalize
 * button here. Deliberately mirrors `_enforce_chronological_order`'s same-year
 * scope. */
async function earlierPendingRuns(run: PayRun): Promise<PayRun[]> {
  const siblings = await listPayRuns(Number(run.pay_date.slice(0, 4)));
  return siblings
    .filter(
      (other) =>
        other.run_id !== run.run_id &&
        other.employee_id === run.employee_id &&
        other.status === 'DRAFT' &&
        other.pay_date < run.pay_date,
    )
    .sort((a, b) => (a.pay_date < b.pay_date ? -1 : 1));
}

/** Whether finalizing this run is currently possible, and if not, why.
 *
 * `checking` covers the in-flight query. `failed` is treated as blocking: if
 * the earlier drafts can't be ruled out, they must be dealt with before this
 * run locks. */
type FinalizeGate =
  | { kind: 'checking' }
  | { kind: 'clear' }
  | { kind: 'blocked'; runs: PayRun[] }
  | { kind: 'failed'; message: string };

function PayRunDetail({
  runId,
  employeeName,
  onDeleted,
}: {
  runId: string;
  employeeName: (employeeId: string) => string;
  onDeleted: (message: string) => void;
}) {
  const [run, setRun] = useState<PayRun | null>(null);
  const [lines, setLines] = useState<HourLine[] | null>(null);
  const [extraPay, setExtraPay] = useState<ExtraPayLine[] | null>(null);
  const [dirty, setDirty] = useState(false);
  const [gate, setGate] = useState<FinalizeGate>({ kind: 'checking' });
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generatingStub, setGeneratingStub] = useState(false);
  const [stubStatus, setStubStatus] = useState<string | null>(null);

  const load = () => {
    getPayRun(runId)
      .then((result) => {
        setRun(result);
        setLines(result.hour_lines);
        setExtraPay(result.extra_pay_lines);
        setDirty(false);
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      );
  };

  useEffect(load, [runId]);

  // Re-check on every load *and* after each save: finalizing out of order
  // silently understates the YTD totals the tax artifacts read from (§4), so
  // this is a hard block rather than a heads-up the employer can click past.
  useEffect(() => {
    if (run === null) return;
    if (run.status !== 'DRAFT') {
      setGate({ kind: 'clear' });
      return;
    }
    let cancelled = false;
    setGate({ kind: 'checking' });
    earlierPendingRuns(run)
      .then((pending) => {
        if (cancelled) return;
        setGate(pending.length > 0 ? { kind: 'blocked', runs: pending } : { kind: 'clear' });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setGate({
          kind: 'failed',
          message: err instanceof Error ? err.message : String(err),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [run]);

  if (!run) {
    return error ? <p className="error-banner">{error}</p> : <p>Loading…</p>;
  }

  const isDraft = run.status === 'DRAFT';
  const editingLines = lines ?? [];
  const editingExtraPay = extraPay ?? [];
  const checking = gate.kind === 'checking';
  const blocked = gate.kind === 'blocked' || gate.kind === 'failed';
  const working = busy || deleting;
  const finalizeDisabled = working || dirty || blocked || checking;

  const validateAndSave = async () => {
    for (const line of editingLines) {
      if (!/^\d+(\.\d+)?$/.test(line.hours)) {
        setError(`Invalid hours "${line.hours}" — use a decimal like 8 or 8.5.`);
        return;
      }
      if (!line.work_date) {
        setError('Every hour line needs a date.');
        return;
      }
    }
    for (const line of editingExtraPay) {
      if (!line.note.trim()) {
        setError('Every extra pay line needs a note — it shows on the pay stub.');
        return;
      }
      if (!/^\d+(\.\d+)?$/.test(line.amount)) {
        setError(`Invalid amount "${line.amount}" — use a decimal like 250 or 250.00.`);
        return;
      }
    }
    setBusy(true);
    try {
      const updated = await updatePayRunDraft(runId, {
        hour_lines: editingLines,
        extra_pay_lines: editingExtraPay,
      });
      setRun(updated);
      setLines(updated.hour_lines);
      setExtraPay(updated.extra_pay_lines);
      setDirty(false);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const finalize = async () => {
    // The button is disabled in every blocking state; re-check here so an
    // activation on a stale render can't slip a run through either.
    if (dirty) {
      setError('Save your changes before finalizing this run.');
      return;
    }
    if (finalizeDisabled) return;
    if (
      !window.confirm(
        `Finalize the ${formatMoney(run.gross.gross)} run for ${employeeName(run.employee_id)}?\n\nFinalized runs are immutable.`,
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      setRun(await finalizePayRun(runId));
      setError(null);
    } catch (err) {
      setError(finalizeErrorHint(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    const unsaved = dirty
      ? '\n\nThe unsaved edits on this screen go with it.'
      : '';
    if (
      !window.confirm(
        `Delete the draft paid ${formatDate(run.pay_date)}?${unsaved}\n\nIt covers ${formatDate(run.period_start)} – ${formatDate(run.period_end)} and cannot be recovered.`,
      )
    ) {
      return;
    }
    setDeleting(true);
    try {
      await deletePayRunDraft(runId);
      onDeleted(`Deleted the draft paid ${formatDate(run.pay_date)}.`);
    } catch (err) {
      setDeleting(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const setLine = (index: number, patch: Partial<HourLine>) => {
    setDirty(true);
    setLines((prev) => prev!.map((line, i) => (i === index ? { ...line, ...patch } : line)));
  };

  const setExtraLine = (index: number, patch: Partial<ExtraPayLine>) => {
    setDirty(true);
    setExtraPay((prev) =>
      (prev ?? []).map((line, i) => (i === index ? { ...line, ...patch } : line)),
    );
  };

  const addLine = () => {
    setDirty(true);
    const lastDate =
      editingLines.length > 0 ? editingLines[editingLines.length - 1].work_date : run.period_start;
    const next = new Date(`${lastDate || todayIso()}T00:00:00Z`);
    next.setUTCDate(next.getUTCDate() + 1);
    setLines((prev) => [
      ...(prev ?? []),
      {
        line_id: crypto.randomUUID(),
        work_date: next.toISOString().slice(0, 10),
        hours: '',
        category: 'REGULAR',
      },
    ]);
  };

  const generateStub = async () => {
    setGeneratingStub(true);
    setStubStatus(null);
    setError(null);
    try {
      const doc = await generatePayStub(runId);
      const { url } = await downloadDocumentUrl(doc.doc_id);
      window.open(url, '_blank', 'noopener,noreferrer');
      setStubStatus('Pay stub generated.');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGeneratingStub(false);
    }
  };
  
  const addExtraLine = () => {
    setDirty(true);
    setExtraPay((prev) => [
      ...(prev ?? []),
      { line_id: crypto.randomUUID(), note: '', amount: '' },
    ]);
  };

  const removeLine = (index: number) => {
    setDirty(true);
    setLines((prev) => prev!.filter((_, i) => i !== index));
  };

  const removeExtraLine = (index: number) => {
    setDirty(true);
    setExtraPay((prev) => (prev ?? []).filter((_, i) => i !== index));
  };

  return (
    <div className="card left">
      <div className="panel-header">
        <h2>
          {formatDate(run.period_start)} – {formatDate(run.period_end)}{' '}
          <span className={`badge ${run.status.toLowerCase()}`}>{run.status}</span>
        </h2>
      </div>
      <p>
        {employeeName(run.employee_id)} · pay date {formatDate(run.pay_date)}
      </p>

      {isDraft && dirty && (
        <p className="notice blocking">
          You have unsaved changes on this draft. Save them before finalizing —
          finalization locks the run as it is stored, not as it is on screen.
        </p>
      )}

      {isDraft && gate.kind === 'blocked' && (
        <p className="notice blocking">
          {gate.runs.length} earlier run{gate.runs.length === 1 ? '' : 's'} for{' '}
          {employeeName(run.employee_id)} (
          {gate.runs.map((other) => formatDate(other.pay_date)).join(', ')}){' '}
          {gate.runs.length === 1 ? 'is' : 'are'} still a draft, so this run
          cannot be finalized yet. Go back to “All pay runs” and either use the
          “Finalize … pending (oldest first)” button or delete{' '}
          {gate.runs.length === 1 ? 'it' : 'them'} — locking this one first would
          leave those wages out of the year-to-date totals, so quarterly figures
          and wage-base caps would come out low.
        </p>
      )}

      {isDraft && gate.kind === 'failed' && (
        <p className="notice blocking">
          Could not check for earlier drafts: {gate.message}. Resolve that first
          so we can rule out finalizing out of order.
        </p>
      )}

      <GrossBreakdown run={run} />

      {run.payroll && <PayrollBreakdown payroll={run.payroll} />}

      <h3>Hour lines</h3>
      {(editingLines.length > 0 || !isDraft) && (
        <table className="data">
          <thead>
            <tr>
              <th>Date</th>
              <th>Category</th>
              <th className="num">Hours</th>
              {isDraft && <th></th>}
            </tr>
          </thead>
          <tbody>
            {editingLines.map((line, index) => (
              <tr key={line.line_id}>
                <td>
                  {isDraft ? (
                    <input type="date" value={line.work_date} onChange={(e) => setLine(index, { work_date: e.target.value })} />
                  ) : (
                    formatDate(line.work_date)
                  )}
                </td>
                <td>
                  {isDraft ? (
                    <select value={line.category} onChange={(e) => setLine(index, { category: e.target.value as HourCategory })}>
                      {HOUR_CATEGORIES.map((category) => (
                        <option key={category} value={category}>
                          {category}
                        </option>
                      ))}
                    </select>
                  ) : (
                    line.category
                  )}
                </td>
                <td className="num">
                  {isDraft ? (
                    <input
                      inputMode="decimal"
                      size={6}
                      value={line.hours}
                      onChange={(e) => setLine(index, { hours: e.target.value })}
                    />
                  ) : (
                    formatHours(line.hours)
                  )}
                </td>
                {isDraft && (
                  <td>
                    <button
                      type="button"
                      className="danger"
                      aria-label="Remove line"
                      onClick={() => removeLine(index)}
                    >
                      ✕
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editingLines.length === 0 && isDraft && (
        <p className="muted">No hour lines yet.</p>
      )}

      <h3>Extra pay</h3>
      <p className="muted">
        A flat amount on top of the hours — a bonus or gift. It is added straight to
        gross, not calculated from hours, and is taxed like any other wage.
      </p>
      {(editingExtraPay.length > 0 || !isDraft) && (
        <table className="data">
          <thead>
            <tr>
              <th>Note</th>
              <th className="num">Amount</th>
              {isDraft && <th></th>}
            </tr>
          </thead>
          <tbody>
            {editingExtraPay.map((line, index) => (
              <tr key={line.line_id}>
                <td>
                  {isDraft ? (
                    <input
                      value={line.note}
                      maxLength={120}
                      placeholder="Holiday bonus"
                      onChange={(e) => setExtraLine(index, { note: e.target.value })}
                    />
                  ) : (
                    line.note
                  )}
                </td>
                <td className="num">
                  {isDraft ? (
                    <input
                      inputMode="decimal"
                      size={8}
                      value={line.amount}
                      placeholder="250.00"
                      onChange={(e) => setExtraLine(index, { amount: e.target.value })}
                    />
                  ) : (
                    formatMoney(line.amount)
                  )}
                </td>
                {isDraft && (
                  <td>
                    <button
                      type="button"
                      className="danger"
                      aria-label="Remove extra pay line"
                      onClick={() => removeExtraLine(index)}
                    >
                      ✕
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editingExtraPay.length === 0 && isDraft && (
        <p className="muted">No extra pay on this run.</p>
      )}

      {isDraft && (
        <div className="actions-bar">
          <button type="button" disabled={working} onClick={addLine}>
            Add line
          </button>
          <button type="button" disabled={working} onClick={addExtraLine}>
            Add extra pay
          </button>
          <button
            type="button"
            disabled={working || lines === null}
            onClick={() => void validateAndSave()}
          >
            {busy ? 'Saving…' : 'Save changes'}
          </button>
          <button
            type="button"
            className="danger"
            disabled={working}
            onClick={() => void remove()}
          >
            {deleting ? 'Deleting…' : 'Delete draft'}
          </button>
          <button
            type="button"
            className="primary"
            disabled={finalizeDisabled}
            onClick={() => void finalize()}
          >
            {checking ? 'Checking…' : busy ? 'Finalizing…' : 'Finalize…'}
          </button>
        </div>
      )}

      {!isDraft && (
        <>
          <p className="muted">
            {run.status === 'FINALIZED'
              ? `Immutable since ${formatDateTime(run.finalized_at ?? '')} · rate table v${run.rate_table_version}. Corrections happen via adjustment entries.`
              : 'This run was voided.'}
          </p>
          {run.status === 'FINALIZED' && (
            <div className="actions-bar">
              <button
                type="button"
                disabled={generatingStub}
                onClick={() => void generateStub()}
              >
                {generatingStub ? 'Generating…' : 'Generate pay stub'}
              </button>
            </div>
          )}
          {stubStatus && <p className="saved-note">{stubStatus}</p>}
        </>
      )}

      {error && <p className="error-banner">{error}</p>}
    </div>
  );
}

function GrossBreakdown({ run }: { run: PayRun }) {
  const g = run.gross;
  return (
    <table className="data breakdown">
      <tbody>
        <tr>
          <td>Regular hours</td>
          <td className="num">{formatHours(g.regular_hours)}</td>
          <td>Straight-time pay</td>
          <td className="num">{formatMoney(g.straight_time_pay)}</td>
        </tr>
        <tr>
          <td>Overtime hours</td>
          <td className="num">{formatHours(g.overtime_hours)}</td>
          <td>Overtime premium (0.5×)</td>
          <td className="num">{formatMoney(g.overtime_premium_pay)}</td>
        </tr>
        <tr>
          <td>Other paid hours</td>
          <td className="num">{formatHours(g.other_paid_hours)}</td>
          <td>Hourly rate</td>
          <td className="num">{formatMoney(g.hourly_rate)}</td>
        </tr>
        <tr>
          <td>Unpaid hours</td>
          <td className="num">{formatHours(g.unpaid_hours)}</td>
          <td></td>
          <td className="num"></td>
        </tr>
        {!isZeroAmount(g.extra_pay) && (
          <tr>
            <td>
              Extra pay
              {run.extra_pay_lines.length > 1 ? ` (${run.extra_pay_lines.length} lines)` : ''}
            </td>
            <td className="num">—</td>
            <td>Lump sum</td>
            <td className="num">{formatMoney(g.extra_pay)}</td>
          </tr>
        )}
        <tr>
          <td colSpan={3}>
            <strong>Gross</strong>
          </td>
          <td className="num">
            <strong>{formatMoney(g.gross)}</strong>
          </td>
        </tr>
      </tbody>
    </table>
  );
}

/** The stored computation for a FINALIZED run (design-doc.md §5.1): employee
 * withholding with net pay, then the employer accruals that drive Schedule H
 * and quarterly estimates later. Display-only — no client-side arithmetic. */
function PayrollBreakdown({ payroll }: { payroll: PayrollResult }) {
  const w = payroll.withholding;
  const a = payroll.employer_accruals;
  return (
    <>
      <h3>Withholding &amp; net pay</h3>
      <table className="data breakdown">
        <tbody>
          <tr>
            <td>Social Security (6.2%)</td>
            <td className="num">{formatMoney(w.social_security)}</td>
            <td>Medicare (1.45%)</td>
            <td className="num">{formatMoney(w.medicare)}</td>
          </tr>
          {Number(w.additional_medicare) > 0 && (
            <tr>
              <td>Additional Medicare (0.9%)</td>
              <td className="num">{formatMoney(w.additional_medicare)}</td>
              <td></td>
              <td></td>
            </tr>
          )}
          <tr>
            <td>Federal income tax</td>
            <td className="num">{formatMoney(w.federal_income_tax)}</td>
            <td>WA Paid Family &amp; Medical Leave</td>
            <td className="num">{formatMoney(w.wa_pfml_employee)}</td>
          </tr>
          <tr>
            <td>WA Cares Fund</td>
            <td className="num">{formatMoney(w.wa_cares_employee)}</td>
            <td>
              <strong>Total withholding</strong>
            </td>
            <td className="num">
              <strong>{formatMoney(w.total)}</strong>
            </td>
          </tr>
          <tr>
            <td colSpan={2}></td>
            <td>
              <strong>Net pay</strong>
            </td>
            <td className="num">
              <strong>{formatMoney(payroll.net_pay)}</strong>
            </td>
          </tr>
        </tbody>
      </table>

      <details>
        <summary className="muted">Employer tax accruals (not withheld from the employee)</summary>
        <table className="data breakdown">
          <tbody>
            <tr>
              <td>Social Security match</td>
              <td className="num">{formatMoney(a.social_security)}</td>
              <td>Medicare match</td>
              <td className="num">{formatMoney(a.medicare)}</td>
            </tr>
            <tr>
              <td>FUTA</td>
              <td className="num">{formatMoney(a.futa)}</td>
              <td>WA unemployment (UI)</td>
              <td className="num">{formatMoney(a.wa_ui)}</td>
            </tr>
            <tr>
              <td>WA PFML employer share</td>
              <td className="num">{formatMoney(a.wa_pfml_employer)}</td>
              <td></td>
              <td></td>
            </tr>
          </tbody>
        </table>
      </details>
    </>
  );
}
