import { useEffect, useState } from 'react';
import {
  acknowledgeReminder,
  listReminders,
  testSendReminder,
} from '../api/client';
import type { Reminder, ReminderRule, ReminderStatus } from '../api/types';
import { REMINDER_RULES, REMINDER_RULE_LABELS } from '../api/types';
import { formatDate, formatDateTime, todayIso } from '../format';

/**
 * Reminders (design-doc.md §6.6): what is due, whether the email went out,
 * and one-click acknowledgement. Unacknowledged reminders stay in this list
 * — they re-nag until dealt with, so a missed quarterly payment doesn't
 * disappear into an inbox.
 *
 * The test-send card fires any rule on demand through the same backend code
 * path as the scheduled Lambda; locally (docker compose) the email is
 * logged to the backend container instead of being sent.
 */

const STATUS_LABEL: Record<ReminderStatus, string> = {
  PENDING: 'Pending',
  SENT: 'Emailed',
  ACKNOWLEDGED: 'Acknowledged',
};

export function RemindersPanel({
  onDataChanged,
}: {
  /** Notifies the shell (tab badge) whenever the open set may have changed. */
  onDataChanged?: () => void;
}) {
  const [reminders, setReminders] = useState<Reminder[] | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // `showAll` checked -> include acknowledged history; the API's
  // `open_only` is the inverse.
  const reload = (includeAcknowledged: boolean) => {
    listReminders(!includeAcknowledged)
      .then((result) => {
        setReminders(result);
        setError(null);
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      );
    onDataChanged?.();
  };

  useEffect(() => {
    setReminders(null);
    reload(showAll);
  }, [showAll]);

  const acknowledge = (reminderId: string) => {
    acknowledgeReminder(reminderId)
      .then(() => reload(showAll))
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : String(err)),
      );
  };

  return (
    <>
      <div className="panel-header">
        <h2>Reminders</h2>
        <label>
          <input
            type="checkbox"
            checked={showAll}
            onChange={(e) => setShowAll(e.target.checked)}
          />{' '}
          Show acknowledged
        </label>
      </div>

      <p className="muted">
        Reminders are emailed by a schedule and nag here until acknowledged.
        Use the card below to fire one on demand for testing.
      </p>

      {error && <p className="error-banner">{error}</p>}
      {notice && <p className="notice">{notice}</p>}

      {reminders !== null && reminders.length === 0 && (
        <p className="muted">
          {showAll
            ? 'No reminders yet.'
            : 'Nothing open. Fire a test reminder below to see the flow.'}
        </p>
      )}

      {reminders && reminders.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Due</th>
              <th>Rule</th>
              <th>Status</th>
              <th>Sent</th>
              <th>Acknowledged</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {reminders.map((r) => (
              <tr key={`${r.due_date}:${r.rule}`}>
                <td>{formatDate(r.due_date)}</td>
                <td>{REMINDER_RULE_LABELS[r.rule]}</td>
                <td>{STATUS_LABEL[r.status]}</td>
                <td>{r.sent_at ? formatDateTime(r.sent_at) : '—'}</td>
                <td>{r.acknowledged_at ? formatDateTime(r.acknowledged_at) : '—'}</td>
                <td>
                  {r.status !== 'ACKNOWLEDGED' && (
                    <button
                      type="button"
                      onClick={() => acknowledge(`${r.due_date}:${r.rule}`)}
                    >
                      Acknowledge
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <TestSendCard onDone={() => reload(showAll)} onError={setError} onNotice={setNotice} />
    </>
  );
}

function TestSendCard({
  onDone,
  onError,
  onNotice,
}: {
  onDone: () => void;
  onError: (message: string | null) => void;
  onNotice: (message: string | null) => void;
}) {
  const [rule, setRule] = useState<ReminderRule>('WEEKLY_PAY');
  const [fireDate, setFireDate] = useState(todayIso());
  const [createDrafts, setCreateDrafts] = useState(true);
  const [sendEmail, setSendEmail] = useState(true);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const result = await testSendReminder({
        rule,
        fire_date: fireDate || undefined,
        create_drafts: createDrafts,
        send_email: sendEmail,
      });
      onError(null);
      const transport =
        result.email_transport === 'log'
          ? 'logged to the backend (local mode — no real email)'
          : `sent via ${result.email_transport}`;
      onNotice(
        result.created.length === 0
          ? `Already exists for that due date — nothing new created (${transport}).`
          : `Created ${result.created.length} reminder(s); email ${transport}.`,
      );
      onDone();
    } catch (err: unknown) {
      onError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card left" onSubmit={(e) => void submit(e)}>
      <h3>Send a test reminder</h3>
      <label>
        Rule{' '}
        <select value={rule} onChange={(e) => setRule(e.target.value as ReminderRule)}>
          {REMINDER_RULES.map((r) => (
            <option key={r} value={r}>
              {REMINDER_RULE_LABELS[r]}
            </option>
          ))}
        </select>
      </label>
      <label>
        Fire date{' '}
        <input
          type="date"
          value={fireDate}
          onChange={(e) => setFireDate(e.target.value)}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={createDrafts}
          onChange={(e) => setCreateDrafts(e.target.checked)}
        />{' '}
        Also create weekly draft pay runs (WEEKLY_PAY)
      </label>
      <label>
        <input
          type="checkbox"
          checked={sendEmail}
          onChange={(e) => setSendEmail(e.target.checked)}
        />{' '}
        Send the email
      </label>
      <button type="submit" disabled={busy}>
        {busy ? 'Sending…' : 'Fire reminder'}
      </button>
    </form>
  );
}
