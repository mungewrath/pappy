import { useState } from 'react';
import { createEmployer, emptyAddress, getEmployer } from '../api/client';
import { storeEmployerId } from '../api/employerStorage';
import type { Address, EmployerCreate } from '../api/types';

/**
 * First-run gate (design-doc.md §3.1: one employer per deployment).
 *
 * Until the API derives `employerId` from the JWT `sub` claim (§7.1), the
 * client supplies it on every call; this screen creates the single employer
 * profile — or links to an existing one by pasting its ID — and persists the
 * resulting ID in localStorage for subsequent visits.
 */

export function Onboarding({ onReady }: { onReady: (employerId: string) => void }) {
  return (
    <div className="card">
      <h2>Welcome</h2>
      <p>
        Pappy manages payroll for one household employer. Create your employer
        profile, or link an existing one by its ID.
      </p>
      <CreateForm onCreated={onReady} />
      <hr />
      <LinkExistingForm onLinked={onReady} />
    </div>
  );
}

function CreateForm({ onCreated }: { onCreated: (employerId: string) => void }) {
  const [form, setForm] = useState<EmployerCreate>({
    legal_name: '',
    ein: '',
    wa_esd_account_number: null,
    ubi: null,
    address: emptyAddress(),
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof EmployerCreate>(key: K, value: EmployerCreate[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const setAddress = (key: keyof EmployerCreate['address'], value: string) =>
    set('address', { ...form.address, [key]: value === '' && key !== 'line1' ? null : value });

  const submit = async () => {
    if (!form.legal_name || !form.ein) {
      setError('Legal name and EIN are required.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const employer = await createEmployer(form);
      storeEmployerId(employer.employer_id);
      onCreated(employer.employer_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <h3>Create employer profile</h3>
      <div className="grid2">
        <label className="field">
          <span>Legal name *</span>
          <input
            value={form.legal_name}
            onChange={(e) => set('legal_name', e.target.value)}
            placeholder="Jane Doe"
          />
        </label>
        <label className="field">
          <span>EIN *</span>
          <input value={form.ein} onChange={(e) => set('ein', e.target.value)} placeholder="12-3456789" />
        </label>
        <label className="field">
          <span>WA ESD account #</span>
          <input
            value={form.wa_esd_account_number ?? ''}
            onChange={(e) => set('wa_esd_account_number', e.target.value || null)}
          />
        </label>
        <label className="field">
          <span>UBI</span>
          <input value={form.ubi ?? ''} onChange={(e) => set('ubi', e.target.value || null)} />
        </label>
      </div>
      <AddressFields address={form.address} onChange={setAddress} />
      {error && <p className="error-banner">{error}</p>}
      <button type="submit" disabled={busy}>
        {busy ? 'Creating…' : 'Create profile'}
      </button>
    </form>
  );
}

function LinkExistingForm({ onLinked }: { onLinked: (employerId: string) => void }) {
  const [id, setId] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await getEmployer(id.trim());
      storeEmployerId(id.trim());
      onLinked(id.trim());
    } catch (err) {
      setError(
        err instanceof Error ? `Could not load that profile: ${err.message}` : String(err),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <h3>Link existing profile</h3>
      <label className="field">
        <span>Employer ID</span>
        <input value={id} onChange={(e) => setId(e.target.value)} placeholder="uuid" />
      </label>
      {error && <p className="error-banner">{error}</p>}
      <button type="submit" disabled={!id.trim() || busy}>
        Link profile
      </button>
    </form>
  );
}

export function AddressFields({
  address,
  onChange,
}: {
  address: Address;
  onChange: (key: keyof Address, value: string) => void;
}) {
  return (
    <fieldset className="address">
      <legend>Address</legend>
      <label className="field">
        <span>Street</span>
        <input value={address.line1} onChange={(e) => onChange('line1', e.target.value)} />
      </label>
      <label className="field">
        <span>Apt / line 2</span>
        <input value={address.line2 ?? ''} onChange={(e) => onChange('line2', e.target.value)} />
      </label>
      <div className="grid3">
        <label className="field">
          <span>City</span>
          <input value={address.city} onChange={(e) => onChange('city', e.target.value)} />
        </label>
        <label className="field">
          <span>State</span>
          <input value={address.state} onChange={(e) => onChange('state', e.target.value)} placeholder="WA" />
        </label>
        <label className="field">
          <span>ZIP</span>
          <input value={address.zip_code} onChange={(e) => onChange('zip_code', e.target.value)} />
        </label>
      </div>
    </fieldset>
  );
}
