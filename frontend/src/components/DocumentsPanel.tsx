import { useEffect, useState } from 'react';
import { downloadDocumentUrl, listDocuments } from '../api/client';
import type { Document } from '../api/types';
import { formatDateTime } from '../format';

const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  PAY_STUB: 'Pay stub',
  FSA_RECEIPT: 'FSA receipt',
  SCHEDULE_H: 'Schedule H',
  W2: 'W-2',
  W3: 'W-3',
  FORM_1040ES: '1040-ES',
  EARNINGS_SUMMARY: 'Earnings summary',
};

const currentYear = new Date().getFullYear();

export function DocumentsPanel() {
  const [docs, setDocs] = useState<Document[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [year, setYear] = useState<number | 'all'>('all');
  const [downloading, setDownloading] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDocs(null);
    listDocuments(year === 'all' ? undefined : year)
      .then((result) => !cancelled && setDocs(result))
      .catch((err: unknown) => {
        if (cancelled) return;
        setDocs([]);
        setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [year]);

  const years = new Set<number>([currentYear]);
  for (const doc of docs ?? []) years.add(doc.tax_year);

  const handleDownload = async (doc: Document) => {
    setDownloading(doc.doc_id);
    try {
      const result = await downloadDocumentUrl(doc.doc_id);
      window.open(result.url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="panel">
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
      </div>

      {error && <p className="error-banner">{error}</p>}

      {docs !== null && docs.length === 0 && (
        <p className="muted">
          No documents generated yet. Go to a finalized pay run and click
          "Generate pay stub" to create your first document.
        </p>
      )}

      {docs && docs.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Type</th>
              <th>Tax year</th>
              <th>Generated</th>
              <th>Pay runs</th>
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
                <td>{doc.pay_run_ids.join(', ') || '-'}</td>
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
