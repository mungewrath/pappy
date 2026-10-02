import { useEffect, useState } from 'react';
import {
  downloadDocumentFile,
  exportYearViewCsv,
  getYearView,
  listEmployees,
} from '../api/client';
import type { Employee, YearView, YearViewRow } from '../api/types';
import { formatDate, formatHours, formatMoney, formatPeriod, isZeroAmount } from '../format';

const currentYear = new Date().getFullYear();
const YEAR_OPTIONS = [currentYear + 1, currentYear, currentYear - 1, currentYear - 2, currentYear - 3];

/** The year view (design-doc.md §6.2): every finalized run with the year's
 * running totals, filterable by pay-date range and exportable as CSV.
 *
 * The running YTD columns arrive pre-computed from the server. Summing them
 * here would mean adding money in JavaScript, which §5.5 rules out — the panel
 * only ever formats the exact decimal strings the ledger produced.
 *
 * Overtime is broken out into straight-time and the 0.5x premium as separate
 * columns, per §5.4, so an overtime question can be answered from the archive
 * without recomputing anything. Each row expands to the full withholding and
 * employer-accrual detail, which keeps the main table scannable while the CSV
 * carries all 28 columns.
 */
export function YearViewPanel() {
  const [year, setYear] = useState(currentYear);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [employeeId, setEmployeeId] = useState('');
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [view, setView] = useState<YearView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    listEmployees()
      .then(setEmployees)
      .catch(() => setEmployees([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    // Built from the primitive state so the effect depends on the values
    // themselves rather than a fresh object identity on every render.
    const filters = {
      start: start || undefined,
      end: end || undefined,
      employeeId: employeeId || undefined,
    };
    getYearView(year, filters)
      .then((result) => {
        if (cancelled) return;
        setView(result);
        setExported(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setView(null);
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [year, start, end, employeeId]);

  const filtered = Boolean(start || end || employeeId);
  const filters = { start: start || undefined, end: end || undefined, employeeId: employeeId || undefined };

  const handleExport = async () => {
    setExporting(true);
    setError(null);
    try {
      const doc = await exportYearViewCsv(year, filters);
      setExported(doc.filename);
      // The export is an archived artifact, so it goes through the same
      // download path as any other document. That path fetches the bytes with
      // the caller's token when the API is serving them, which a plain
      // `window.open` navigation could not do.
      await downloadDocumentFile(doc.doc_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setExporting(false);
    }
  };

  const totals = view?.totals;

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Year view</h2>
        <label className="field inline">
          <span>Year</span>
          <select value={String(year)} onChange={(e) => setYear(Number(e.target.value))}>
            {YEAR_OPTIONS.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="secondary"
          disabled={exporting || view === null || view.rows.length === 0}
          onClick={() => void handleExport()}
        >
          {exporting ? 'Exporting…' : 'Export CSV'}
        </button>
      </div>

      <div className="filters">
        <label className="field inline">
          <span>From</span>
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="field inline">
          <span>To</span>
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <label className="field inline">
          <span>Employee</span>
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
            <option value="">All</option>
            {employees.map((e) => (
              <option key={e.employee_id} value={e.employee_id}>
                {e.full_name}
              </option>
            ))}
          </select>
        </label>
        {filtered && (
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setStart('');
              setEnd('');
              setEmployeeId('');
            }}
          >
            Clear filters
          </button>
        )}
      </div>

      {error && <p className="error-banner">{error}</p>}
      {exported && !error && (
        <p className="notice">Saved {exported} to Documents. It is archived with its SHA-256.</p>
      )}
      {!error && view === null && <p>Loading…</p>}

      {view !== null && view.rows.length === 0 && (
        <p className="muted">
          {filtered
            ? 'No finalized pay runs in this range.'
            : `No finalized pay runs in ${year}. Drafts appear on the Pay runs tab until they are finalized.`}
        </p>
      )}

      {view !== null && view.rows.length > 0 && (
        <>
          <p className="muted">
            {totals?.finalized_run_count} finalized run
            {totals?.finalized_run_count === 1 ? '' : 's'}
            {view.period_start && view.period_end && (
              <> · {formatDate(view.period_start)} – {formatDate(view.period_end)}</>
            )}
          </p>

          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th>Pay date</th>
                  <th>Employee</th>
                  <th className="num">Hours</th>
                  <th className="num">Straight-time</th>
                  <th className="num">OT premium</th>
                  <th className="num">Extra pay</th>
                  <th className="num">Gross</th>
                  <th className="num">Withholding</th>
                  <th className="num">Net pay</th>
                  <th className="num">YTD gross</th>
                  <th className="num">YTD withholding</th>
                  <th className="num">YTD net</th>
                </tr>
              </thead>
              <tbody>
                {view.rows.map((row) => (
                  <RowGroup
                    key={row.run_id}
                    row={row}
                    expanded={expanded === row.run_id}
                    onToggle={() => setExpanded(expanded === row.run_id ? null : row.run_id)}
                  />
                ))}
                <tr className="totals">
                  <td>Total</td>
                  <td />
                  <td />
                  <td />
                  <td />
                  <td />
                  <td className="num">{formatMoney(totals?.gross ?? '0')}</td>
                  <td className="num">{formatMoney(totals?.total_withholding ?? '0')}</td>
                  <td className="num">{formatMoney(totals?.net_pay ?? '0')}</td>
                  <td className="num">{formatMoney(totals?.ytd_gross ?? '0')}</td>
                  <td className="num">{formatMoney(totals?.ytd_total_withholding ?? '0')}</td>
                  <td className="num">{formatMoney(totals?.ytd_net_pay ?? '0')}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <p className="muted">
            Select a row for its full withholding and employer-tax breakdown.
          </p>
        </>
      )}
    </div>
  );
}

function RowGroup({
  row,
  expanded,
  onToggle,
}: {
  row: YearViewRow;
  expanded: boolean;
  onToggle: () => void;
}) {
  const w = row.withholding;
  const er = row.employer_accruals;
  return (
    <>
      <tr className="clickable" onClick={onToggle}>
        <td>{formatDate(row.pay_date)}</td>
        <td>{row.employee_name}</td>
        <td className="num">
          {formatHours(row.regular_hours)}
          {Number(row.overtime_hours) > 0 && ` / ${formatHours(row.overtime_hours)} OT`}
        </td>
        <td className="num">{formatMoney(row.straight_time_pay)}</td>
        <td className="num">
          {isZeroAmount(row.overtime_premium_pay) ? '—' : formatMoney(row.overtime_premium_pay)}
        </td>
        <td className="num">
          {isZeroAmount(row.extra_pay) ? '—' : formatMoney(row.extra_pay)}
        </td>
        <td className="num">{formatMoney(row.gross)}</td>
        <td className="num">{formatMoney(row.total_withholding)}</td>
        <td className="num">{formatMoney(row.net_pay)}</td>
        <td className="num">{formatMoney(row.ytd_gross)}</td>
        <td className="num">{formatMoney(row.ytd_total_withholding)}</td>
        <td className="num">{formatMoney(row.ytd_net_pay)}</td>
      </tr>
      {expanded && (
        <tr className="detail">
          <td colSpan={12}>
            <div className="grid2">
              <div>
                <strong>
                  Period {formatPeriod(row.period_start, row.period_end)}
                </strong>
                <table className="breakdown">
                  <tbody>
                    <Line label="Social Security" value={w.social_security} />
                    <Line label="Medicare" value={w.medicare} />
                    <Line label="Additional Medicare" value={w.additional_medicare} />
                    <Line label="Federal income tax" value={w.federal_income_tax} />
                    <Line label="WA PFML" value={w.wa_pfml_employee} />
                    <Line label="WA Cares" value={w.wa_cares_employee} />
                    <Line label="Total withholding" value={row.total_withholding} strong />
                    <Line label="Net pay" value={row.net_pay} strong />
                  </tbody>
                </table>
              </div>
              <div>
                <strong>Employer taxes (not withheld)</strong>
                <table className="breakdown">
                  <tbody>
                    <Line label="Social Security" value={er.social_security} />
                    <Line label="Medicare" value={er.medicare} />
                    <Line label="FUTA" value={er.futa} />
                    <Line label="WA UI" value={er.wa_ui} />
                    <Line label="WA PFML" value={er.wa_pfml_employer} />
                    <Line label="Total employer taxes" value={er.total} strong />
                  </tbody>
                </table>
                <p className="muted">
                  {formatHours(row.regular_hours)} regular · {formatHours(row.overtime_hours)}{' '}
                  overtime · {formatHours(row.other_paid_hours)} other paid ·{' '}
                  {formatHours(row.unpaid_hours)} unpaid
                </p>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function Line({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="num">
        {strong ? <strong>{formatMoney(value)}</strong> : isZeroAmount(value) ? '—' : formatMoney(value)}
      </td>
    </tr>
  );
}
