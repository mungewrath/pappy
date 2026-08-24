import { useEffect, useState } from 'react';
import {
  downloadEfw2,
  getEarningsSummaries,
  getQuarterlyEstimates,
  getScheduleH,
  getW2Summaries,
} from '../api/client';
import type {
  EarningsSummary,
  QuarterEstimate,
  QuarterlyEstimates,
  ScheduleHWorksheet,
  W2Summary,
} from '../api/types';
import { formatDate, formatHours, formatMoney } from '../format';

/**
 * Tax year artifacts (design-doc.md §6.4–§6.6): quarterly 1040-ES figures,
 * the Schedule H worksheet with its contributing runs, annual earnings
 * summaries, W-2 box values, and the SSA EFW2 upload file. Everything is
 * computed server-side from finalized runs — this view only formats.
 */

const currentYear = new Date().getFullYear();
const YEAR_OPTIONS = [currentYear + 1, currentYear, currentYear - 1, currentYear - 2, currentYear - 3];

export function TaxPanel() {
  const [year, setYear] = useState(currentYear);
  const [estimates, setEstimates] = useState<QuarterlyEstimates | null>(null);
  const [scheduleH, setScheduleH] = useState<ScheduleHWorksheet | null>(null);
  const [w2s, setW2s] = useState<W2Summary[] | null>(null);
  const [summaries, setSummaries] = useState<EarningsSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    Promise.all([
      getQuarterlyEstimates(year),
      getScheduleH(year),
      getW2Summaries(year),
      getEarningsSummaries(year),
    ])
      .then(([est, sch, w2list, sums]) => {
        if (cancelled) return;
        setEstimates(est);
        setScheduleH(sch);
        setW2s(w2list);
        setSummaries(sums);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [year]);

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Tax year</h2>
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
      </div>

      {error && <p className="error-banner">{error}</p>}
      {!error && estimates === null && <p>Loading…</p>}

      {estimates !== null && <QuarterlyEstimatesCard estimates={estimates} />}
      {scheduleH !== null && <ScheduleHCard worksheet={scheduleH} />}
      {summaries !== null && summaries.length > 0 && <EarningsSummariesCard summaries={summaries} />}
      {w2s !== null && w2s.length > 0 && <W2Card taxYear={year} summaries={w2s} />}
    </div>
  );
}

function QuarterlyEstimatesCard({ estimates }: { estimates: QuarterlyEstimates }) {
  const quarters = estimates.quarters;
  const hasAdditionalMedicare = quarters.some((q) => Number(q.additional_medicare) > 0);
  const moneyRow = (
    label: string,
    pick: (q: QuarterEstimate) => string,
    { strong = false }: { strong?: boolean } = {},
  ) => (
    <tr key={label}>
      <td>{strong ? <strong>{label}</strong> : label}</td>
      {quarters.map((q) => (
        <td key={q.quarter} className="num">
          {strong ? <strong>{pick(q)}</strong> : pick(q)}
        </td>
      ))}
    </tr>
  );
  return (
    <div className="card left">
      <div className="panel-header">
        <h3>Quarterly estimated tax — Form 1040-ES</h3>
        <span className={`badge finalized`}>Grand total {formatMoney(estimates.grand_total)}</span>
      </div>
      <table className="data">
        <thead>
          <tr>
            <th></th>
            {quarters.map((q) => (
              <th key={q.quarter} className="num">
                Q{q.quarter}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Payment due</td>
            {quarters.map((q) => (
              <td key={q.quarter} className="num">
                {formatDate(q.due_date)}
              </td>
            ))}
          </tr>
          <tr>
            <td>Pay runs</td>
            {quarters.map((q) => (
              <td key={q.quarter} className="num">
                {q.pay_run_count}
              </td>
            ))}
          </tr>
          {moneyRow('Gross wages', (q) => formatMoney(q.gross))}
          {moneyRow('Federal income tax withheld', (q) => formatMoney(q.federal_income_tax_withheld))}
          {moneyRow('Social Security (employee + employer)', (q) => formatMoney(q.social_security))}
          {moneyRow('Medicare (employee + employer)', (q) => formatMoney(q.medicare))}
          {hasAdditionalMedicare &&
            moneyRow('Additional Medicare', (q) => formatMoney(q.additional_medicare))}
          {moneyRow('Household employment taxes', (q) => formatMoney(q.household_employment_taxes))}
          {moneyRow('FUTA', (q) => formatMoney(q.futa))}
          {moneyRow('Owed via 1040-ES', (q) => formatMoney(q.total), { strong: true })}
          {moneyRow('Year-to-date total', (q) => formatMoney(q.ytd_total))}
        </tbody>
      </table>
      <p className="muted">
        Household employment taxes flow through Schedule H into Form 1040 — these are the amounts to
        send with each quarterly 1040-ES voucher. Runs are attributed by pay date.
      </p>
    </div>
  );
}


function ScheduleHCard({ worksheet }: { worksheet: ScheduleHWorksheet }) {
  const lines: [string, string, string][] = [
    ['A', 'Total cash wages subject to Social Security', formatMoney(worksheet.line_a_ss_wages)],
    ['B', 'Social Security tax (12.4%)', formatMoney(worksheet.line_b_ss_tax)],
    ['C', 'Total cash wages subject to Medicare', formatMoney(worksheet.line_c_medicare_wages)],
    ['D', 'Medicare tax (2.9%)', formatMoney(worksheet.line_d_medicare_tax)],
    ['E', 'Add lines B and D', formatMoney(worksheet.line_e_subtotal)],
    ['F', 'Wages subject to Additional Medicare Tax', formatMoney(worksheet.line_f_addl_medicare_wages)],
    ['G', 'Additional Medicare Tax withheld (0.9%)', formatMoney(worksheet.line_g_addl_medicare_tax)],
    ['H', 'Add lines E and G', formatMoney(worksheet.line_h_household_fica_taxes)],
    ['I', 'Federal income tax withheld', formatMoney(worksheet.line_i_fit_withheld)],
    ['J', 'Total household employment taxes', formatMoney(worksheet.line_j_total_household_employment_taxes)],
    ['L', 'FUTA tax', formatMoney(worksheet.line_l_futa_tax)],
    ['M', 'Total (goes on Schedule 2, Form 1040)', formatMoney(worksheet.line_m_total)],
  ];
  return (
    <div className="card left">
      <div className="panel-header">
        <h3>Schedule H — {worksheet.employer_name}</h3>
        <span className="muted">EIN {worksheet.employer_ein}</span>
      </div>
      <table className="data">
        <thead>
          <tr>
            <th>Line</th>
            <th>Description</th>
            <th className="num">Amount</th>
          </tr>
        </thead>
        <tbody>
          {lines.map(([lineNo, label, amount]) => (
            <tr key={lineNo}>
              <td>{lineNo}</td>
              <td>{label}</td>
              <td className="num">{amount}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <details>
        <summary className="muted">Worksheet: pay runs behind these lines</summary>
        <table className="data">
          <thead>
            <tr>
              <th>Pay date</th>
              <th>Employee</th>
              <th className="num">Gross</th>
              <th className="num">Social Security</th>
              <th className="num">Medicare</th>
              <th className="num">Fed tax</th>
              <th className="num">FUTA</th>
            </tr>
          </thead>
          <tbody>
            {worksheet.contributing_runs.map((run) => (
              <tr key={run.run_id}>
                <td>{formatDate(run.pay_date)}</td>
                <td>{run.employee_name ?? run.employee_id}</td>
                <td className="num">{formatMoney(run.gross)}</td>
                <td className="num">{formatMoney(run.social_security)}</td>
                <td className="num">{formatMoney(run.medicare)}</td>
                <td className="num">{formatMoney(run.federal_income_tax_withheld)}</td>
                <td className="num">{formatMoney(run.futa)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
function EarningsSummariesCard({ summaries }: { summaries: EarningsSummary[] }) {
  return (
    <div className="card left">
      <div className="panel-header">
        <h3>Annual earnings summary</h3>
      </div>
      {summaries.map((s) => (
        <EmployeeSummary key={s.employee_id} summary={s} />
      ))}
      {summaries.length === 0 && <p className="muted">No employees yet.</p>}
    </div>
  );
}

function EmployeeSummary({ summary }: { summary: EarningsSummary }) {
  const w = summary.withholding;
  return (
    <details open>
      <summary>
        <strong>{summary.employee_name}</strong>{' '}
        <span className="muted">
          · {summary.finalized_run_count} finalized run{summary.finalized_run_count === 1 ? '' : 's'} ·
          gross {formatMoney(summary.gross)}
        </span>
      </summary>

      <table className="data breakdown">
        <tbody>
          <tr>
            <td>Regular hours</td>
            <td className="num">{formatHours(summary.hours_regular)}</td>
            <td>Straight-time pay</td>
            <td className="num">{formatMoney(summary.straight_time_pay)}</td>
          </tr>
          <tr>
            <td>Overtime hours</td>
            <td className="num">{formatHours(summary.hours_overtime)}</td>
            <td>Overtime premium (0.5×)</td>
            <td className="num">{formatMoney(summary.overtime_premium_pay)}</td>
          </tr>
          <tr>
            <td>Other paid hours</td>
            <td className="num">{formatHours(summary.hours_other_paid)}</td>
            <td>Hourly rate</td>
            <td className="num">{formatMoney(summary.hourly_rate)}</td>
          </tr>
          <tr>
            <td>Unpaid hours</td>
            <td className="num">{formatHours(summary.hours_unpaid)}</td>
            <td><strong>Gross</strong></td>
            <td className="num"><strong>{formatMoney(summary.gross)}</strong></td>
          </tr>
        </tbody>
      </table>

      <table className="data breakdown">
        <thead>
          <tr>
            <th colSpan={2}>Withholding &amp; net pay (year totals)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Social Security (employee)</td>
            <td className="num">{formatMoney(w.social_security)}</td>
          </tr>
          <tr>
            <td>Medicare (employee)</td>
            <td className="num">{formatMoney(w.medicare)}</td>
          </tr>
          {Number(w.additional_medicare) > 0 && (
            <tr>
              <td>Additional Medicare</td>
              <td className="num">{formatMoney(w.additional_medicare)}</td>
            </tr>
          )}
          <tr>
            <td>Federal income tax</td>
            <td className="num">{formatMoney(w.federal_income_tax)}</td>
          </tr>
          <tr>
            <td>WA Paid Family &amp; Medical Leave</td>
            <td className="num">{formatMoney(w.wa_pfml_employee)}</td>
          </tr>
          <tr>
            <td>WA Cares Fund</td>
            <td className="num">{formatMoney(w.wa_cares_employee)}</td>
          </tr>
          <tr>
            <td><strong>Net pay</strong></td>
            <td className="num"><strong>{formatMoney(summary.net_pay)}</strong></td>
          </tr>
        </tbody>
      </table>

      <details>
        <summary className="muted">Employer accruals &amp; wage bases</summary>
        <table className="data breakdown">
          <tbody>
            <tr>
              <td>Social Security match</td>
              <td className="num">{formatMoney(summary.employer_accruals.social_security)}</td>
              <td>Medicare match</td>
              <td className="num">{formatMoney(summary.employer_accruals.medicare)}</td>
            </tr>
            <tr>
              <td>FUTA</td>
              <td className="num">{formatMoney(summary.employer_accruals.futa)}</td>
              <td>WA unemployment (UI)</td>
              <td className="num">{formatMoney(summary.employer_accruals.wa_ui)}</td>
            </tr>
            <tr>
              <td>WA PFML employer share</td>
              <td className="num">{formatMoney(summary.employer_accruals.wa_pfml_employer)}</td>
              <td></td>
              <td></td>
            </tr>
          </tbody>
        </table>
        <table className="data">
          <thead>
            <tr>
              <th>Wage base</th>
              <th className="num">Used</th>
              <th className="num">Cap</th>
              <th className="num">Remaining</th>
            </tr>
          </thead>
          <tbody>
            {summary.wage_bases.map((base) => (
              <tr key={base.name}>
                <td>{base.label}</td>
                <td className="num">{formatHours(base.wages_used)}</td>
                <td className="num">{base.wage_base == null ? '—' : formatHours(base.wage_base)}</td>
                <td className="num">{base.remaining == null ? '—' : formatHours(base.remaining)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </details>
  );
}
function W2Card({ taxYear, summaries }: { taxYear: number; summaries: W2Summary[] }) {
  return (
    <div className="card left">
      <div className="panel-header">
        <h3>Form W-2 summary</h3>
      </div>
      {summaries.map((w2) => (
        <W2Employee key={w2.employee_id} w2={w2} />
      ))}
      <Efw2Download taxYear={taxYear} summaries={summaries} />
    </div>
  );
}

function W2Employee({ w2 }: { w2: W2Summary }) {
  const boxes: [string, string, string][] = [
    ['1', 'Wages, tips, other compensation', formatMoney(w2.box1_wages)],
    ['2', 'Federal income tax withheld', formatMoney(w2.box2_fit_withheld)],
    ['3', 'Social Security wages', formatMoney(w2.box3_ss_wages)],
    ['4', 'Social Security tax withheld', formatMoney(w2.box4_ss_tax_withheld)],
    ['5', 'Medicare wages and tips', formatMoney(w2.box5_medicare_wages)],
    ['6', 'Medicare tax withheld (incl. additional)', formatMoney(w2.box6_medicare_tax_withheld)],
  ];
  return (
    <details>
      <summary>
        <strong>{w2.employee_name}</strong>{' '}
        <span className="muted">· employer {w2.employer_name}, EIN {w2.employer_ein}</span>
      </summary>
      <table className="data">
        <thead>
          <tr>
            <th>Box</th>
            <th>Description</th>
            <th className="num">Amount</th>
          </tr>
        </thead>
        <tbody>
          {boxes.map(([boxNo, label, amount]) => (
            <tr key={boxNo}>
              <td>{boxNo}</td>
              <td>{label}</td>
              <td className="num">{amount}</td>
            </tr>
          ))}
          {w2.box14_items.map((item) => (
            <tr key={item.label}>
              <td>14</td>
              <td>{item.label}</td>
              <td className="num">{formatMoney(item.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function Efw2Download({ taxYear, summaries }: { taxYear: number; summaries: W2Summary[] }) {
  const [ssns, setSsns] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      await downloadEfw2(taxYear, ssns);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h3>EFW2 file for SSA Business Services Online</h3>
      <p className="muted">
        Generates the fixed-width Copy A upload file. Enter each employee's SSN — it is used for
        this one download and never stored or logged.
      </p>
      {summaries.map((w2) => (
        <label key={w2.employee_id} className="field inline" style={{ marginRight: '1rem' }}>
          <span>{w2.employee_name} SSN</span>
          <input
            inputMode="numeric"
            placeholder="123-45-6789"
            value={ssns[w2.employee_id] ?? ''}
            onChange={(e) => setSsns((prev) => ({ ...prev, [w2.employee_id]: e.target.value }))}
          />
        </label>
      ))}
      <div className="actions-bar">
        <button type="button" disabled={busy || summaries.length === 0} onClick={() => void download()}>
          {busy ? 'Generating…' : `Download EFW2-${taxYear}.txt`}
        </button>
      </div>
      {error && <p className="error-banner">{error}</p>}
    </>
  );
}
