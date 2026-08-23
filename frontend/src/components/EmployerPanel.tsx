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
    address: Address;
  }>({
    legal_name: employer.legal_name,
    ein: employer.ein,
    wa_esd_account_number: employer.wa_esd_account_number ?? '',
    ubi: employer.ubi ?? '',
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
    setBusy(true);
    setStatus(null);
    try {
      const updated = await updateEmployer({
        legal_name: form.legal_name,
        ein: form.ein,
        wa_esd_account_number: form.wa_esd_account_number || null,
        ubi: form.ubi || null,
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
      </div>
      <AddressFields address={form.address} onChange={setAddress} />
      {status && <p className={status === 'Saved.' ? 'saved-note' : 'error-banner'}>{status}</p>}
      <button type="submit" disabled={busy || !form.legal_name || !form.ein}>
        {busy ? 'Saving…' : 'Save changes'}
      </button>
    </form>
  );
}
