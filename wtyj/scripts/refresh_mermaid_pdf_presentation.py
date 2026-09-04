"""Re-render existing Mermaid demo documents; never alter bookings or resend.

Old files remain available for rollback. Document IDs and delivery jobs stay
unchanged, so existing unexpired download links resolve to the refreshed file.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.social import mermaid_documents as documents, mermaid_reservation_store as store
from pypdf import PdfReader


def refresh():
    conn = documents._conn()
    try:
        rows = [dict(row) for row in conn.execute(
            "SELECT * FROM mermaid_documents WHERE tenant_slug='mermaid' AND kind IN ('quote','receipt')"
        )]
        changed = 0
        for row in rows:
            if Path(row['path']).parent.name == 'presentation-v2':
                continue
            reservation = store.get_reservation(row['reservation_public_id'])
            if not reservation:
                raise RuntimeError('Document reservation missing; no changes made to this document')
            if row['kind'] == 'quote':
                filename = f"Mermaid - Demo Trip Quote - {reservation['public_id'][-10:].upper()}.pdf"
            else:
                filename = f"Mermaid - Demo Payment Receipt - {reservation['booking_code']}.pdf"
            target = documents._root() / reservation['public_id'] / 'presentation-v2' / filename
            if row['kind'] == 'quote':
                digest = documents.render_quote_pdf(reservation, target)
            else:
                payment = conn.execute(
                    "SELECT * FROM mermaid_demo_payments WHERE reservation_public_id=? AND tenant_slug='mermaid'",
                    (reservation['public_id'],),
                ).fetchone()
                if not payment:
                    raise RuntimeError('Receipt payment snapshot missing')
                digest = documents.render_receipt_pdf(reservation, dict(payment), target)
            pdf = PdfReader(target)
            assert pdf.pages[0].images and pdf.metadata.title.startswith('Mermaid - ')
            assert len(pdf.pages) == (2 if row['kind'] == 'quote' else 1)
            backup = target.parent / (row['kind'] + '-previous-record.json')
            if not backup.exists():
                backup.write_text(json.dumps(row, indent=2), encoding='utf-8')
                backup.chmod(0o600)
            with conn:
                update = conn.execute(
                    "UPDATE mermaid_documents SET filename=?,path=?,sha256=? "
                    "WHERE public_id=? AND tenant_slug='mermaid' AND sha256=?",
                    (filename, str(target), digest, row['public_id'], row['sha256']),
                )
                if update.rowcount != 1:
                    raise RuntimeError('Concurrent document change; refresh stopped safely')
            changed += 1
        print(f'Refreshed {changed} documents; booking, payment and delivery states unchanged.')
    finally:
        conn.close()


if __name__ == '__main__':
    refresh()
