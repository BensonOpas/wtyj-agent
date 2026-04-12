# test_189_email_adapter.py — Brief 189: Email adapter layer extraction


# --- Test 1: normalize_subject works from email_adapter import ---
def test_normalize_subject_from_adapter():
    from agents.marina.email_adapter import normalize_subject
    assert normalize_subject("Re: Re: Fwd: Booking inquiry") == "Booking inquiry"
    assert normalize_subject("") == ""
    assert normalize_subject("No prefix here") == "No prefix here"
    assert normalize_subject("fw: RE: FWD: nested") == "nested"


# --- Test 2: strip_quotes works from email_adapter import ---
def test_strip_quotes_from_adapter():
    from agents.marina.email_adapter import strip_quotes
    text = "Hello there\n\nOn Jan 1 someone wrote:\noriginal quoted text"
    result = strip_quotes(text)
    assert result == "Hello there"


# --- Test 3: backward compat — re-exports from email_poller are the same objects ---
def test_reexport_identity():
    from agents.marina.email_poller import (
        normalize_subject, imap_connect, smtp_send, extract_text,
        strip_quotes, resolve_thread_key, sha, _is_new_email,
        IMAP_HOST, SMTP_HOST, EMAIL_ADDR,
    )
    from agents.marina.email_adapter import (
        normalize_subject as ns2, sha as sha2,
        imap_connect as ic2, IMAP_HOST as ih2,
    )
    # Re-exports should be the SAME objects, not copies
    assert normalize_subject is ns2, "normalize_subject re-export should be same object"
    assert sha is sha2, "sha re-export should be same object"
    assert imap_connect is ic2, "imap_connect re-export should be same object"
    assert IMAP_HOST is ih2, "IMAP_HOST re-export should be same object"
