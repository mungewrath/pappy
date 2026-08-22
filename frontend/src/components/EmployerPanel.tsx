import { useEffect, useState } from 'react';
import { getEmployer, updateEmployer } from '../api/client';
import { loadStoredEmployerId } from '../api/employerStorage';
import type { Address, Employer, EmployerUpdate } from '../api/types';
import { formatDateTime } from '../format';
import { AddressFields } from './Onboarding';

/** Views and edits the employer profile; offers switching to another profile. */
export function EmployerPanel({ onSwitch }: { onSwitch: () => void }) {
  const [employer, setEmployer] = useState<Employer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const employerId = loadStoredEmployerId() ?? '';

  useEffect(() => {
    if (!employerId) return;
    let cancelled = false;
    getEmployer(employerId)
      .then((e) => !cancelled && setEmployer(e))
      .catch((err: unknown) =>
        !cancelled &&
        setError(err instanceof Error ? err.message : String(err)),
      );
    return () => {
      cancelled = true;
    };
  }, [employerId]);

  const save = async (patch: EmployerUpdate) => {
    const updated = await updateEmployer(employerId, patch);
    setEmployer(updated);
  };

  return (
    <div className="panel">
      {error && <p className="error-banner">Could not load employer: {error}</p>}
      {!employer && !error && <p>Loading…</p>}
      {employer && (
        <>
          <ProfileForm key={employer.updated_at} employer={employer} onSave={save} />
          <p className="muted">
            Created {formatDateTime(employer.created_at)} · ID <code>{employer.employer_id}</code>
          </p>
          <button type="button" className="secondary" onClick={onSwitch}>
            Switch to a different employer…
          </button>
        </>
      )}
    </div>
  );
}

function ProfileForm({
  employer,
  onSave,
}: {
  employer: Employer;
  onSave: (patch: EmployerUpdate) => Promise<void>;
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
      await onSave({
        legal_name: form.legal_name,
        ein: form.ein,
        wa_esd_account_number: form.wa_esd_account_number || null,
        ubi: form.ubi || null,
        address: form.address,
      });
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
