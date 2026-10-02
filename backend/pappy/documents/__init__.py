"""PDF document generators (design-doc.md §6.2–§6.5).

Each generator takes structured data and returns raw PDF bytes. They are
pure I/O — no AWS imports, no DynamoDB access (design principle 3).

Per design-doc.md §2.2, `reportlab` is used for custom-layout artifacts
(pay stubs, FSA receipts, earnings summaries), while `pypdf` fills
official IRS AcroForm PDFs (W-2, Schedule H). The AcroForm generators are
not written yet; the custom-layout ones delivered so far are `pay_stub` and
`fsa_receipt`.
"""
