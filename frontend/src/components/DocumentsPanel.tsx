import { useCallback, useEffect, useState } from 'react';
import {
  createFsaReceipt,
  downloadDocumentFile,
  listDocuments,
  listEmployees,
  previewFsaClaim,
} from '../api/client';
import type { Document, DocumentType, Employee, FsaPreview } from '../api/types';
import { formatDate, formatDateTime, formatMoney, isZeroAmount, todayIso } from '../format';

const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  PAY_STUB: 'Pay stub',
  FSA_RECEIPT: 'FSA receipt',
  SCHEDULE_H: 'Schedule H',
  W2: 'W-2',
  W3: 'W-3',
  FORM_1040ES: '1040-ES',
  EARNINGS_SUMMARY: 'Earnings summary',
  YEAR_VIEW_CSV: 'Year view CSV',
};

/** Types a filter is offered for. SCHEDULE_H/W2/W3/1040-ES have no generator
 * yet, so they are absent from the picker rather than listed as dead ends. */
const FILTERABLE_TYPES: DocumentType[] = ['PAY_STUB', 'FSA_RECEIPT', 'YEAR_VIEW_CSV'];

const currentYear = new Date().getFullYear();

/** What a document covers, in the employer's own terms: the pay date for an
 * artifact tied to one run (a pay stub), the covered date range for one that
 * spans several (an FSA receipt, a filtered year-view export), and otherwise
 * the whole tax year. Run IDs are deliberately not shown — they are opaque,
 * and the pay date is what the employer is actually looking for. Pay stubs
 * generated before the server stored a pay date fall back to the tax year. */
function describeCoverage(doc: Document): string {
  if (doc.pay_date) return `Pay date ${formatDate(doc.pay_date)}`;
  if (doc.period_start && doc.period_end) {
    return `${formatDate(doc.period_start)} – ${formatDate(doc.period_end)}`;
  }
  return `All of ${doc.tax_year}`;
}

export function DocumentsPanel() {
  const [docs, setDocs] = useState<Document[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [year, setYear] = useState<number | 'all'>('all');
  const [docType, setDocType] = useState<DocumentType | 'all'>('all');
  const [downloading, setDownloading] = useState<string | null>(null);

  const load = useCallback(() => {
    setDocs(null);
    listDocuments(year === 'all' ? undefined : year, docType === 'all' ? undefined : docType)
      .then(setDocs)
      .catch((err: unknown) => {
        setDocs([]);
        setError(err instanceof Error ? err.message : String(err));
      });
  }, [year, docType]);

  useEffect(load, [load]);

  const years = new Set<number>([currentYear]);
  for (const doc of docs ?? []) years.add(doc.tax_year);

  const handleDownload = async (doc: Document) => {
    setDownloading(doc.doc_id);
    try {
      await downloadDocumentFile(doc.doc_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="panel">
      <FsaCard onCreated={() => { setError(null); load(); }} />

      <div className="panel-header">
        <h2>Documents</h2>
        <label className="field inline">
          <span>Year</span>
          <select
            value={String(year)}
            onChange={(e) =>
              setYear(e.target.value === 'all' ? 'all' : Number(e.target.value))
            }
          >
            <option value="all">All</option>
            {[...years].sort((a, b) => b - a).map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
        <label className="field inline">
          <span>Type</span>
          <select
            value={docType}
            onChange={(e) => setDocType(e.target.value as DocumentType | 'all')}
          >
            <option value="all">All</option>
            {FILTERABLE_TYPES.map((t) => (
              <option key={t} value={t}>
                {DOCUMENT_TYPE_LABELS[t]}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="error-banner">{error}</p>}

      {docs !== null && docs.length === 0 && (
        <p className="muted">
          No documents yet. Generate a pay stub from a finalized pay run, an FSA
          receipt above, or export the year view from the Year tab.
        </p>
      )}

      {docs && docs.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Type</th>
              <th>Tax year</th>
              <th>Generated</th>
              <th>Covers</th>
              <th>SHA-256</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {docs.map((doc) => (
              <tr key={doc.doc_id}>
                <td>{DOCUMENT_TYPE_LABELS[doc.document_type] ?? doc.document_type}</td>
                <td>{doc.tax_year}</td>
                <td>{formatDateTime(doc.created_at)}</td>
                <td>
                  {describeCoverage(doc)}
                  {doc.claimed_amount && (
                    <>
                      <br />
                      <span className="muted">Claimed {formatMoney(doc.claimed_amount)}</span>
                    </>
                  )}
                </td>
                <td>
                  <code>{doc.sha256.slice(0, 12)}…</code>
                </td>
                <td className="actions">
                  <button
                    type="button"
                    className="secondary"
                    disabled={downloading === doc.doc_id}
                    onClick={() => void handleDownload(doc)}
                  >
                    {downloading === doc.doc_id ? 'Loading…' : 'Download'}
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

/** Dependent care FSA receipt generator (design-doc.md §6.3).
 *
 * The preview endpoint recomputes the eligible wages, cumulative claimed, and
 * any over-limit warning as the dates change, without writing anything — so
 * the figures are live before a receipt exists. The provider TIN is sent
 * transiently with the generate request and is never stored by the backend
 * (§7.3), so it is deliberately not persisted in this form either.
 */
function FsaCard({ onCreated }: { onCreated: () => void }) {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [employeeId, setEmployeeId] = useState('');
  const [start, setStart] = useState(`${currentYear}-01-01`);
  const [end, setEnd] = useState(todayIso());
  const [dependentName, setDependentName] = useState('');
  const [providerTin, setProviderTin] = useState('');
  const [claimAmount, setClaimAmount] = useState('');
  const [preview, setPreview] = useState<FsaPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [created, setCreated] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listEmployees()
      .then((list) => {
        setEmployees(list);
        // Default to the first employee: the care provider is the employee.
        if (list.length > 0) setEmployeeId(list[0].employee_id);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      );
  }, []);

  const ready = Boolean(employeeId && start && end);

  useEffect(() => {
    if (!ready) {
      setPreview(null);
      return;
    }
    let cancelled = false;
    previewFsaClaim({
      employeeId,
      periodStart: start,
      periodEnd: end,
      claimAmount: claimAmount || undefined,
    })
      .then((result) => {
        if (!cancelled) {
          setPreview(result);
          setPreviewError(null);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setPreview(null);
        setPreviewError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [ready, employeeId, start, end, claimAmount]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    try {
      const result = await createFsaReceipt({
        employee_id: employeeId,
        period_start: start,
        period_end: end,
        dependent_name: dependentName,
        provider_tin: providerTin,
        claim_amount: claimAmount || null,
      });
      setCreated(result.document.filename);
      setClaimAmount('');
      // The TIN has served its purpose; do not leave it sitting in the form.
      setProviderTin('');
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setGenerating(false);
    }
  };

  if (employees.length === 0) {
    return (
      <div className="card">
        <h3>Dependent care FSA</h3>
        <p className="muted">Add an employee first — the care provider is the employee.</p>
      </div>
    );
  }

  return (
    <div className="card">
      <h3>Dependent care FSA receipt</h3>
      <p className="muted">
        Sums the gross wages paid for a service period and produces a
        provider-signed receipt for reimbursement.
      </p>

      <div className="grid3">
        <label className="field">
          <span>Service from</span>
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="field">
          <span>Service to</span>
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <label className="field">
          <span>Care provider</span>
          <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
            {employees.map((e) => (
              <option key={e.employee_id} value={e.employee_id}>
                {e.full_name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Dependent's name</span>
          <input
            type="text"
            value={dependentName}
            maxLength={120}
            placeholder="Child Smith"
            onChange={(e) => setDependentName(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Provider TIN / SSN</span>
          <input
            type="text"
            value={providerTin}
            maxLength={20}
            placeholder="123-45-6789"
            onChange={(e) => setProviderTin(e.target.value)}
          />
        </label>
        <label className="field">
          <span>Claim amount (blank = full total)</span>
          <input
            type="text"
            inputMode="decimal"
            value={claimAmount}
            placeholder="0.00"
            onChange={(e) => setClaimAmount(e.target.value)}
          />
        </label>
      </div>

      {previewError && <p className="error-banner">{previewError}</p>}

      {preview && (
        <>
          <table className="data">
            <tbody>
              <PreviewRow label="Finalized runs in period" value={String(preview.pay_run_count)} />
              <PreviewRow label="Gross wages" value={formatMoney(preview.gross_wages)} />
              {preview && !isZeroAmount(preview.employer_fica) && (
                <PreviewRow
                  label="Employer FICA (informational)"
                  value={formatMoney(preview.employer_fica)}
                />
              )}
              <PreviewRow label="Eligible wages" value={formatMoney(preview.eligible_wages)} strong />
              <PreviewRow label="Already claimed this year" value={formatMoney(preview.already_claimed)} />
              <PreviewRow
                label={
                  preview.limit_source === 'plan'
                    ? 'Plan limit (your plan)'
                    : preview.limit_source === 'statutory'
                      ? 'Plan limit (statutory)'
                      : 'Plan limit (unknown — no cap applied)'
                }
                value={
                  preview.limit_source === 'unknown' ? '—' : formatMoney(preview.plan_limit)
                }
              />
              <PreviewRow label="Claim amount" value={formatMoney(preview.claim_amount)} strong />
            </tbody>
          </table>

          {preview.over_limit && preview.warning && (
            <p className="notice blocking">{preview.warning}</p>
          )}
        </>
      )}

      {error && <p className="error-banner">{error}</p>}
      {created && <p className="notice">Saved {created} to Documents.</p>}

      <div className="actions-bar">
        <button
          type="button"
          disabled={generating || !ready || !dependentName.trim() || !providerTin.trim()}
          onClick={() => void handleGenerate()}
        >
          {generating ? 'Generating…' : 'Generate receipt'}
        </button>
        {preview && <span className="muted">The receipt is left unsigned for the provider.</span>}
      </div>
    </div>
  );
}

function PreviewRow({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="num">{strong ? <strong>{value}</strong> : value}</td>
    </tr>
  );
}
