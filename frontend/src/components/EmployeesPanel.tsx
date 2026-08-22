import { useEffect, useState } from 'react';
import {
  createEmployee,
  deleteEmployee,
  emptyAddress,
  listEmployees,
  updateEmployee,
} from '../api/client';
import type { Address, DefaultScheduleLine, Employee, OvertimePolicy } from '../api/types';
import { OVERTIME_POLICIES } from '../api/types';
import { formatDate, formatHours, formatRate, todayIso, weekdayName } from '../format';
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

export function EmployeesPanel({ employerId }: { employerId: string }) {
  const [employees, setEmployees] = useState<Employee[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Employee | 'new' | null>(null);

  const reload = () => {
    listEmployees(employerId)
      .then(setEmployees)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      );
  };

  useEffect(reload, [employerId]);

  const remove = async (employee: Employee) => {
    if (!window.confirm(`Delete ${employee.full_name}? Existing pay runs keep their records.`)) {
      return;
    }
    try {
      await deleteEmployee(employerId, employee.employee_id);
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="panel">
      <div className="panel-header">
        <h2>Employees</h2>
        {!editing && (
          <button type="button" onClick={() => setEditing('new')}>
            Add employee
          </button>
        )}
      </div>

      {error && <p className="error-banner">{error}</p>}

      {editing && (
        <EmployeeFormCard
          employerId={employerId}
          employee={editing === 'new' ? null : editing}
          initial={editing === 'new' ? emptyForm() : toForm(editing)}
          onDone={(message) => {
            setEditing(null);
            setError(message ?? null);
            if (!message) reload();
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
  employerId,
  employee,
  initial,
  onDone,
}: {
  employerId: string;
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
        await createEmployee(employerId, {
          full_name: form.full_name,
          address: form.address,
          hire_date: form.hire_date,
          hourly_rate: form.hourly_rate,
          overtime_policy: form.overtime_policy,
          default_schedule: schedule,
        });
      } else {
        await updateEmployee(employerId, employee.employee_id, {
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
