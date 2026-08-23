import { useEffect, useMemo, useState } from 'react';
import {
  createPayRunDraft,
  finalizePayRun,
  getPayRun,
  listEmployees,
  listPayRuns,
  updatePayRunHours,
} from '../api/client';
import type { Employee, HourLine, HourCategory, PayRun } from '../api/types';
import { HOUR_CATEGORIES } from '../api/types';
import {
  formatDate,
  formatDateTime,
  formatHours,
  formatMoney,
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
  const [year, setYear] = useState<number | 'all'>(currentYear);
  const [creating, setCreating] = useState(false);
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

  const employeeName = (employeeId: string) =>
    employees.find((e) => e.employee_id === employeeId)?.full_name ?? 'Unknown employee';

  if (selectedId !== null) {
    return (
      <div className="panel">
        <button type="button" className="secondary" onClick={() => setSelectedId(null)}>
          ← All pay runs
        </button>
        <PayRunDetail runId={selectedId} employeeName={employeeName} />
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
          <button type="button" onClick={() => setCreating(true)}>
            New draft
          </button>
        )}
      </div>

      {error && <p className="error-banner">{error}</p>}

      {creating && (
        <NewDraftCard
          employees={employees}
          onDone={(message) => {
            setCreating(false);
            if (message) {
              setError(message);
            } else {
              setError(null);
              listPayRuns(year === 'all' ? undefined : year)
                .then(setRuns)
                .catch(() => {});
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
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
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

function PayRunDetail({
  runId,
  employeeName,
}: {
  runId: string;
  employeeName: (employeeId: string) => string;
}) {
  const [run, setRun] = useState<PayRun | null>(null);
  const [lines, setLines] = useState<HourLine[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    getPayRun(runId)
      .then((result) => {
        setRun(result);
        setLines(result.hour_lines);
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      );
  };

  useEffect(load, [runId]);

  if (!run) {
    return error ? <p className="error-banner">{error}</p> : <p>Loading…</p>;
  }

  const isDraft = run.status === 'DRAFT';
  const editingLines = lines ?? [];

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
    setBusy(true);
    try {
      const updated = await updatePayRunHours(runId, editingLines);
      setRun(updated);
      setLines(updated.hour_lines);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const finalize = async () => {
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
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const setLine = (index: number, patch: Partial<HourLine>) =>
    setLines((prev) => prev!.map((line, i) => (i === index ? { ...line, ...patch } : line)));

  const addLine = () => {
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

      <GrossBreakdown run={run} />

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
                      onClick={() => setLines((prev) => prev!.filter((_, i) => i !== index))}
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

      {isDraft && (
        <div className="actions-bar">
          <button type="button" onClick={addLine}>
            Add line
          </button>
          <button type="button" disabled={busy || lines === null} onClick={() => void validateAndSave()}>
            {busy ? 'Saving…' : 'Save hours'}
          </button>
          <button type="button" className="primary" disabled={busy} onClick={() => void finalize()}>
            Finalize…
          </button>
        </div>
      )}

      {!isDraft && (
        <p className="muted">
          {run.status === 'FINALIZED'
            ? `Immutable since ${formatDateTime(run.finalized_at ?? '')} · rate table v${run.rate_table_version}. Corrections happen via adjustment entries.`
            : 'This run was voided.'}
        </p>
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
          <td>
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
