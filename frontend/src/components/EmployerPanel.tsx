import { useState } from 'react';
import { updateEmployer } from '../api/client';
import type { Address, Employer } from '../api/types';
import { formatDateTime } from '../format';
import { AddressFields } from './Onboarding';

/** Views and edits the signed-in user's employer profile — keyed server-side
 * by the JWT `sub` claim (design-doc.md §7.1). */
export function EmployerPanel({
  employer: initialEmployer,
  onUpdated,
}: {
  employer: Employer;
  onUpdated: (employer: Employer) => void;
}) {
  return (
    <div className="panel">
      <ProfileForm key={initialEmployer.updated_at} employer={initialEmployer} onSave={onUpdated} />
      <p className="muted">
        Created {formatDateTime(initialEmployer.created_at)} · ID{' '}
        <code>{initialEmployer.employer_id}</code>
      </p>
    </div>
  );
}

function ProfileForm({
  employer,
  onSave,
}: {
  employer: Employer;
  onSave: (updated: Employer) => void;
}) {
  const [form, setForm] = useState<{
    legal_name: string;
    ein: string;
    wa_esd_account_number: string;
    ubi: string;
    wa_ui_experience_rate: string;
    fsa_plan_limit: string;
    fsa_include_employer_taxes: boolean;
    address: Address;
  }>({
    legal_name: employer.legal_name,
    ein: employer.ein,
    wa_esd_account_number: employer.wa_esd_account_number ?? '',
    ubi: employer.ubi ?? '',
    wa_ui_experience_rate: employer.wa_ui_experience_rate ?? '',
    fsa_plan_limit: employer.fsa_plan_limit ?? '',
    fsa_include_employer_taxes: employer.fsa_include_employer_taxes,
    address: {
      line1: employer.address.line1,
      line2: employer.address.line2,
      city: employer.address.city,
      state: employer.address.state,
      zip_code: employer.address.zip_code,
    },
  });
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const setAddress = (key: keyof Address, value: string) =>
    setForm((prev) => ({
      ...prev,
      address: { ...prev.address, [key]: value === '' && key !== 'line1' ? null : value },
    }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (
      form.wa_ui_experience_rate !== '' &&
      !/^\d*\.?\d+$/.test(form.wa_ui_experience_rate)
    ) {
      setStatus('WA UI experience rate must be a decimal like 0.0128.');
      return;
    }
    if (form.fsa_plan_limit !== '' && !/^\d*\.?\d{1,2}$/.test(form.fsa_plan_limit)) {
      setStatus('FSA plan limit must be an amount like 5000 or 5000.00.');
      return;
    }
    setBusy(true);
    setStatus(null);
    try {
      const updated = await updateEmployer({
        legal_name: form.legal_name,
        ein: form.ein,
        wa_esd_account_number: form.wa_esd_account_number || null,
        ubi: form.ubi || null,
        wa_ui_experience_rate: form.wa_ui_experience_rate || null,
        fsa_plan_limit: form.fsa_plan_limit === '' ? null : form.fsa_plan_limit,
        fsa_include_employer_taxes: form.fsa_include_employer_taxes,
        address: form.address,
      });
      onSave(updated);
      setStatus('Saved.');
    } catch (err) {
      setStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)}>
      <div className="grid2">
        <label className="field">
          <span>Legal name</span>
          <input
            value={form.legal_name}
            onChange={(e) => setForm((p) => ({ ...p, legal_name: e.target.value }))}
          />
        </label>
        <label className="field">
          <span>EIN</span>
          <input value={form.ein} onChange={(e) => setForm((p) => ({ ...p, ein: e.target.value }))} />
        </label>
        <label className="field">
          <span>WA ESD account #</span>
          <input
            value={form.wa_esd_account_number}
            onChange={(e) => setForm((p) => ({ ...p, wa_esd_account_number: e.target.value }))}
          />
        </label>
        <label className="field">
          <span>UBI</span>
          <input value={form.ubi} onChange={(e) => setForm((p) => ({ ...p, ubi: e.target.value }))} />
        </label>
        <label className="field">
          <span>WA UI experience rate</span>
          <input
            inputMode="decimal"
            placeholder="0.0128"
            value={form.wa_ui_experience_rate}
            onChange={(e) => setForm((p) => ({ ...p, wa_ui_experience_rate: e.target.value }))}
          />
        </label>
      </div>
      <p className="muted">
        The UI experience rate comes from your annual ESD rate notice (a decimal like 0.0128);
        employer tax accruals compute at zero until it is entered.
      </p>
      <h3>Dependent care FSA</h3>
      <div className="grid2">
        <label className="field">
          <span>Plan limit (blank = statutory)</span>
          <input
            inputMode="decimal"
            placeholder="5000.00"
            value={form.fsa_plan_limit}
            onChange={(e) => setForm((p) => ({ ...p, fsa_plan_limit: e.target.value }))}
          />
        </label>
        <label className="field">
          <span>Employer taxes count toward claims</span>
          <input
            type="checkbox"
            checked={form.fsa_include_employer_taxes}
            onChange={(e) =>
              setForm((p) => ({ ...p, fsa_include_employer_taxes: e.target.checked }))
            }
          />
        </label>
      </div>
      <p className="muted">
        Leave the limit blank to use the statutory cap from that year's rate table
        (design-doc.md §5.2); set it when your plan elects less. Employer Social Security
        and Medicare are generally eligible for reimbursement — FUTA, WA UI, and WA PFML
        are not, so only the FICA halves are ever added.
      </p>
      <AddressFields address={form.address} onChange={setAddress} />
      {status && <p className={status === 'Saved.' ? 'saved-note' : 'error-banner'}>{status}</p>}
      <button type="submit" disabled={busy || !form.legal_name || !form.ein}>
        {busy ? 'Saving…' : 'Save changes'}
      </button>
    </form>
  );
}
