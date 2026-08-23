import { useEffect, useState } from 'react';
import {
  addW4Election,
  createEmployee,
  deleteEmployee,
  emptyAddress,
  listEmployees,
  listW4Elections,
  updateEmployee,
} from '../api/client';
import type {
  Address,
  DefaultScheduleLine,
  Employee,
  FilingStatus,
  OvertimePolicy,
  W4Election,
} from '../api/types';
import { FILING_STATUSES, FILING_STATUS_LABELS, OVERTIME_POLICIES } from '../api/types';
import { formatDate, formatHours, formatMoney, formatRate, todayIso, weekdayName } from '../format';
import { AddressFields } from './Onboarding';

/** Employee CRUD (design-doc.md §3.1): the nanny record — name, address,
 * hire date, pay rate, overtime policy, default weekly schedule. */

interface EmployeeFormState {
  full_name: string;
  hourly_rate: string;
  hire_date: string;
  termination_date: string;
  overtime_policy: OvertimePolicy;
  address: Address;
  schedule: { weekday: number; hours: string }[];
}

const emptyForm = (): EmployeeFormState => ({
  full_name: '',
  hourly_rate: '',
  hire_date: todayIso(),
  termination_date: '',
  overtime_policy: 'APPLIES',
  address: emptyAddress(),
  schedule: [],
});

const toForm = (employee: Employee): EmployeeFormState => ({
  full_name: employee.full_name,
  hourly_rate: employee.hourly_rate,
  hire_date: employee.hire_date,
  termination_date: employee.termination_date ?? '',
  overtime_policy: employee.overtime_policy,
  address: {
    line1: employee.address.line1,
    line2: employee.address.line2,
    city: employee.address.city,
    state: employee.address.state,
    zip_code: employee.address.zip_code,
  },
  schedule: employee.default_schedule.map((line) => ({
    weekday: line.weekday,
    hours: line.hours,
  })),
});

export function EmployeesPanel() {
  const [employees, setEmployees] = useState<Employee[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Employee | 'new' | null>(null);
  const [w4For, setW4For] = useState<Employee | null>(null);

  const reload = () => {
    listEmployees()
      .then(setEmployees)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      );
  };

  useEffect(reload, []);

  const remove = async (employee: Employee) => {
    if (!window.confirm(`Delete ${employee.full_name}? Existing pay runs keep their records.`)) {
      return;
    }
    try {
      await deleteEmployee(employee.employee_id);
      if (w4For?.employee_id === employee.employee_id) setW4For(null);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Employees</h2>
        {!editing && !w4For && (
          <button type="button" onClick={() => setEditing('new')}>
            Add employee
          </button>
        )}
      </div>

      {error && <p className="error-banner">{error}</p>}

      {editing && (
        <EmployeeFormCard
          employee={editing === 'new' ? null : editing}
          initial={editing === 'new' ? emptyForm() : toForm(editing)}
          onDone={(message) => {
            setEditing(null);
            setError(message ?? null);
            if (!message) reload();
          }}
        />
      )}

      {w4For && (
        <W4Card
          employee={w4For}
          onDone={(message) => {
            setW4For(null);
            setError(message ?? null);
          }}
        />
      )}

      {employees !== null && employees.length === 0 && !editing && (
        <p className="muted">No employees yet. Add your household employee to start running payroll.</p>
      )}

      {employees && employees.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Name</th>
              <th>Hired</th>
              <th>Rate</th>
              <th>Overtime</th>
              <th>Default week</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {employees.map((employee) => (
              <tr key={employee.employee_id}>
                <td>
                  <strong>{employee.full_name}</strong>
                  {employee.termination_date && (
                    <div className="muted">Terminated {formatDate(employee.termination_date)}</div>
                  )}
                </td>
                <td>{formatDate(employee.hire_date)}</td>
                <td>{formatRate(employee.hourly_rate)}</td>
                <td>{employee.overtime_policy === 'APPLIES' ? 'Applies' : 'Exempt'}</td>
                <td>
                  {employee.default_schedule.length === 0
                    ? '—'
                    : employee.default_schedule
                        .map((line) => `${weekdayName(line.weekday)} ${formatHours(line.hours)}h`)
                        .join(', ')}
                </td>
                <td className="actions">
                  <button type="button" onClick={() => setEditing(employee)}>
                    Edit
                  </button>
                  <button type="button" onClick={() => setW4For(employee)}>
                    W-4
                  </button>
                  <button type="button" className="danger" onClick={() => void remove(employee)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function EmployeeFormCard({
  employee,
  initial,
  onDone,
}: {
  employee: Employee | null;
  initial: EmployeeFormState;
  onDone: (errorMessage?: string) => void;
}) {
  const [form, setForm] = useState<EmployeeFormState>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setAddress = (key: keyof Address, value: string) =>
    setForm((prev) => ({
      ...prev,
      address: { ...prev.address, [key]: value === '' && key !== 'line1' ? null : value },
    }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.full_name || !form.hourly_rate) {
      setError('Name and hourly rate are required.');
      return;
    }
    if (!/^\d+(\.\d+)?$/.test(form.hourly_rate)) {
      setError('Hourly rate must be a decimal like "25" or "25.50".');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const schedule: DefaultScheduleLine[] = form.schedule.map((line) => ({
        weekday: line.weekday,
        hours: line.hours,
      }));
      if (employee === null) {
        await createEmployee({
          full_name: form.full_name,
          address: form.address,
          hire_date: form.hire_date,
          hourly_rate: form.hourly_rate,
          overtime_policy: form.overtime_policy,
          default_schedule: schedule,
        });
      } else {
        await updateEmployee(employee.employee_id, {
          full_name: form.full_name,
          address: form.address,
          hourly_rate: form.hourly_rate,
          overtime_policy: form.overtime_policy,
          default_schedule: schedule,
          termination_date: form.termination_date || null,
        });
      }
      onDone();
    } catch (err) {
      setBusy(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <form className="card" onSubmit={(e) => void submit(e)}>
      <h3>{employee ? `Edit ${employee.full_name}` : 'Add employee'}</h3>
      <div className="grid2">
        <label className="field">
          <span>Full name *</span>
          <input
            value={form.full_name}
            onChange={(e) => setForm((p) => ({ ...p, full_name: e.target.value }))}
          />
        </label>
        <label className="field">
          <span>Hourly rate ($) *</span>
          <input
            inputMode="decimal"
            value={form.hourly_rate}
            placeholder="25.00"
            onChange={(e) => setForm((p) => ({ ...p, hourly_rate: e.target.value }))}
          />
        </label>
        <label className="field">
          <span>Hire date</span>
          <input
            type="date"
            disabled={employee !== null}
            value={form.hire_date}
            onChange={(e) => setForm((p) => ({ ...p, hire_date: e.target.value }))}
          />
        </label>
        <label className="field">
          <span>Termination date</span>
          <input
            type="date"
            value={form.termination_date}
            onChange={(e) => setForm((p) => ({ ...p, termination_date: e.target.value }))}
          />
        </label>
        <label className="field">
          <span>Overtime</span>
          <select
            value={form.overtime_policy}
            onChange={(e) =>
              setForm((p) => ({ ...p, overtime_policy: e.target.value as OvertimePolicy }))
            }
          >
            {OVERTIME_POLICIES.map((policy) => (
              <option key={policy} value={policy}>
                {policy === 'APPLIES' ? 'Applies (1.5× over 40h/week)' : 'Exempt'}
              </option>
            ))}
          </select>
        </label>
      </div>
      <AddressFields address={form.address} onChange={setAddress} />

      <fieldset className="address">
        <legend>Default weekly schedule (seeds new drafts)</legend>
        {form.schedule.length === 0 && <p className="muted">No scheduled days.</p>}
        {form.schedule.map((line, index) => (
          <div className="row" key={index}>
            <select
              value={line.weekday}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  schedule: prev.schedule.map((l, i) =>
                    i === index ? { ...l, weekday: Number(e.target.value) } : l,
                  ),
                }))
              }
            >
              {[0, 1, 2, 3, 4, 5, 6].map((weekday) => (
                <option key={weekday} value={weekday}>
                  {weekdayName(weekday)}
                </option>
              ))}
            </select>
            <input
              inputMode="decimal"
              placeholder="hours"
              value={line.hours}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  schedule: prev.schedule.map((l, i) =>
                    i === index ? { ...l, hours: e.target.value } : l,
                  ),
                }))
              }
            />
            <button
              type="button"
              className="danger"
              aria-label="Remove day"
              onClick={() =>
                setForm((prev) => ({
                  ...prev,
                  schedule: prev.schedule.filter((_, i) => i !== index),
                }))
              }
            >
              ✕
            </button>
          </div>
        ))}
        <button
          type="button"
          className="secondary"
          disabled={form.schedule.length >= 7}
          onClick={() => setForm((prev) => ({ ...prev, schedule: [...prev.schedule, { weekday: 0, hours: '' }] }))}
        >
          Add day
        </button>
      </fieldset>

      {error && <p className="error-banner">{error}</p>}
      <div className="actions-bar">
        <button type="submit" disabled={busy}>
          {busy ? 'Saving…' : employee ? 'Save changes' : 'Create employee'}
        </button>
        <button type="button" className="secondary" onClick={() => onDone()}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** Effective-dated Form W-4 elections (design-doc.md §5.3). Finalizing a pay
 * run requires an election in effect on its pay date, so this is a
 * prerequisite for running payroll. */
function W4Card({
  employee,
  onDone,
}: {
  employee: Employee;
  onDone: (errorMessage?: string) => void;
}) {
  const [elections, setElections] = useState<W4Election[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const reload = () => {
    listW4Elections(employee.employee_id)
      .then((result) => {
        setElections(result);
        setLoadError(null);
      })
      .catch((err: unknown) => setLoadError(err instanceof Error ? err.message : String(err)));
  };

  useEffect(reload, [employee.employee_id]);

  return (
    <div className="card left">
      <div className="panel-header">
        <h3>Form W-4 — {employee.full_name}</h3>
      </div>
      <p className="muted">
        Federal income tax withholding elections. A pay run uses the election in effect on
        its pay date, so a re-election never changes runs already finalized.
      </p>

      {elections && elections.length === 0 && (
        <p className="muted">
          No W-4 on file yet. Payroll cannot be finalized until one is.
        </p>
      )}

      {elections && elections.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Effective</th>
              <th>Filing status</th>
              <th>Step 2c</th>
              <th className="num">Step 3 credit/yr</th>
              <th className="num">Step 4c extra/pay</th>
            </tr>
          </thead>
          <tbody>
            {elections.map((election) => (
              <tr key={election.effective_date}>
                <td>{formatDate(election.effective_date)}</td>
                <td>{FILING_STATUS_LABELS[election.filing_status]}</td>
                <td>{election.multiple_jobs_step2c ? 'Checked' : '—'}</td>
                <td className="num">
                  {Number(election.dependent_credit_amount) > 0
                    ? formatMoney(election.dependent_credit_amount)
                    : '—'}
                </td>
                <td className="num">
                  {Number(election.extra_withholding) > 0
                    ? formatMoney(election.extra_withholding)
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {loadError && <p className="error-banner">{loadError}</p>}

      <AddElectionForm employeeId={employee.employee_id} onSaved={reload} />
      {elections !== null && elections.length > 0 && (
        <p className="muted">Re-submitting an existing effective date replaces that row.</p>
      )}

      <div className="actions-bar">
        <button type="button" className="secondary" onClick={() => onDone()}>
          Done
        </button>
      </div>
    </div>
  );
}

const emptyElection = (): W4Election => ({
  effective_date: todayIso(),
  filing_status: 'SINGLE_OR_MFS',
  multiple_jobs_step2c: false,
  dependent_credit_amount: '',
  other_income: '',
  deductions: '',
  extra_withholding: '',
});

function AddElectionForm({
  employeeId,
  onSaved,
}: {
  employeeId: string;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<W4Election>(emptyElection());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const moneyField = (key: keyof Pick<W4Election, 'dependent_credit_amount' | 'other_income' | 'deductions' | 'extra_withholding'>) => ({
    inputMode: 'decimal' as const,
    value: form[key],
    placeholder: '0.00',
    onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm((prev) => ({ ...prev, [key]: e.target.value })),
  });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.effective_date) {
      setError('Effective date is required.');
      return;
    }
    for (const key of ['dependent_credit_amount', 'other_income', 'deductions', 'extra_withholding'] as const) {
      if (form[key] !== '' && !/^\d+(\.\d+)?$/.test(form[key])) {
        setError(`"${form[key]}" is not a valid amount — use a decimal like 2000 or 25.00.`);
        return;
      }
    }
    setBusy(true);
    setError(null);
    try {
      await addW4Election(employeeId, {
        ...form,
        // blank means zero, not absent — the backend clamps at 0
        dependent_credit_amount: form.dependent_credit_amount || '0',
        other_income: form.other_income || '0',
        deductions: form.deductions || '0',
        extra_withholding: form.extra_withholding || '0',
      });
      setForm(emptyElection());
      setBusy(false);
      onSaved();
    } catch (err) {
      setBusy(false);
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)}>
      <fieldset className="address">
        <legend>Add election</legend>
        <div className="grid2">
          <label className="field">
            <span>Effective date *</span>
            <input
              type="date"
              value={form.effective_date}
              onChange={(e) => setForm((p) => ({ ...p, effective_date: e.target.value }))}
            />
          </label>
          <label className="field">
            <span>Filing status (Step 1c)</span>
            <select
              value={form.filing_status}
              onChange={(e) =>
                setForm((p) => ({ ...p, filing_status: e.target.value as FilingStatus }))
              }
            >
              {FILING_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {FILING_STATUS_LABELS[status]}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="field inline">
          <input
            type="checkbox"
            checked={form.multiple_jobs_step2c}
            onChange={(e) => setForm((p) => ({ ...p, multiple_jobs_step2c: e.target.checked }))}
          />
          <span>Multiple jobs or spouse works (Step 2c)</span>
        </label>
        <div className="grid2">
          <label className="field">
            <span>Dependent credit, annual $ (Step 3)</span>
            <input {...moneyField('dependent_credit_amount')} />
          </label>
          <label className="field">
            <span>Other income, annual $ (Step 4a)</span>
            <input {...moneyField('other_income')} />
          </label>
          <label className="field">
            <span>Deductions, annual $ (Step 4b)</span>
            <input {...moneyField('deductions')} />
          </label>
          <label className="field">
            <span>Extra withholding per pay $ (Step 4c)</span>
            <input {...moneyField('extra_withholding')} />
          </label>
        </div>
        {error && <p className="error-banner">{error}</p>}
        <div className="actions-bar">
          <button type="submit" disabled={busy}>
            {busy ? 'Saving…' : 'Save election'}
          </button>
        </div>
      </fieldset>
    </form>
  );
}
