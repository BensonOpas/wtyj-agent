import imaplib, smtplib, email, base64, urllib.request, urllib.parse, json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

CLIENT_ID = "28e94343-2f77-444c-ac32-58b7bed33b65"
TENANT_ID = "caac06b5-1420-4223-9dcc-ba4a670ec26a"
EMAIL_ADDR = "hello@wetakeyourjob.com"
REFRESH_TOKEN = "1.ARMBtQasyiAUI0KdzLpKZw7CakND6Sh3L0xErDJYt77TO2UAACMTAQ.BQABAwEAAAADAOz_BQD0_0V2b1N0c0FydGlmYWN0cwIAAAAAAEk4ZwMR_-eseDoPjXSE9VM-Lkf57K9-ybPKrO9SgWAYoKNg88QlFOaWAuft9F--G8A4_GUyCUSr0L5Uze20Cknmrryp-r9OuIiLdx0x6CGk_WLy0EFNtrNZbOEyRhDY8Scw14skYYwRM9IJLaU0FZKk-sMq4S3bQXueY67f88448xBHBxetDKMvtfENQLFiO3FEFbBjluh36XncO4k1coWIYMf17HqNOijR5eecmD4gj_lH4L7VG14e_iPqfS8FnqGwNMl0eNK6HUsYJjZ579TKUH1SJQnyraow47fYA9r_Qrwa5w6FtguhlA1fDqZeRBeMZkY8qDsJVUzuxoPsvvB2EnDFhpcAmqnsDzEIZE4V47NOXFGydHiGDQTP1SozJybKHZ374zUt_UjNt3ZRTzF0AYd4OTxuOPxU0S2INmav1xKE3uzTmoD7IhFUfrxiPZqzB25j2RdD0wJu9kYbmybWM7uwyDNUUckb7kaIQa5_UM1lohQIbbueYfks-jPtvjWSQUiGrtOzUTHioAyz4rxlpeuYn5gmEbru6dIp4Uuama1akwtj89230fm31oeKPjcJL2l53SPmlRQUHtK-1DK8yAURKbLL-YC1SpQsG1aRtTIW3q3ujUolPclQiafAdYvIAR-YNxOuJIkbkz7vKTcgpX6Gs13ilEtiB_FzzK5BUJUgoNXUEjphKl-siXWQbTd2b8FYHbUYriQsnkEvTUWw3dPJ_vQe2hFFHvkrqobiZS3fFhXlCmIGu0xVt7xrTsYTKtu11RLW_60fvD-71WCB0SIeCtIUVa_8y-nv8j48iacNRfrQvf2i2gtUzsDYU15XfQYJdl5IZKNNa2ckmITSJdepiTaZjmarPo8zHjl62h-z1bFbKK_ZfTX2povzGqDWe0KpLXQ6t42icAIN1oMulpcflOdPoI9VGE-NekBdvvHo8jsQdAACy_scqH3oaMSX3rX48KFAahGKPWam8qREKwkym0hW2VHaoSCN9gCpMF6BjXS79gBx12WjXlEaOaQNP1qmNucHyNZVaRApE2_vJULfSNR05huucVoVXsMkow5akyzFrhU14tpFCNMST775S9R0CySuoAo4TggXxX8Ba3j-z0nyPXN0ZYJkJha2GWZwBBZthJX5qgy_lZBycDhkpFqCcfFKnr0lVQ5Av1Et1d7unA1BZ2OQWUNp50VEiwOptcNxrEtXQL50XR1_Jfj-0rj8KywPMu4NDOwZeGMMeTn7NNRo4AHFSYJ_cfdX1C0RLGaIAo22HEaOVMcA3PSQIa8u4a5K7vMTFibeCuv3nGRV7pbb1-_fKc1XJV64Tl_7lwo_WuxVh_4K6-qvikPAMvLxE9MU3eTfWZLYUhfbeGmLmAROuAnDokKl8nW3asTN1SRLIJAcOrVo1hv5F9-l6oQfQDm6tuOVGmbsIWDFdWSlSW9dM3S4Vmm72z6InLm7AExp_hXmQ37LsPs2T6Ct4lIYLIkcu-k0RU9HgIgeP-kn7J0JIc22VoSVq32pdCgBS135-Iunl9N4-LYzaUvbPTCxAI-pJd7K65ya1qBZIWX4Z85rz_USKSfLo75ZDKkoxPfSS3yFDtu1_NOysSLCLp-ZNTDsbgJ0kbmLOaws90MZPtfelvPRJ17X0uI"

def get_token():
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "refresh_token": REFRESH_TOKEN,
        "grant_type": "refresh_token",
        "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access"
    }).encode()
    resp = json.loads(urllib.request.urlopen(
        urllib.request.Request(f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token", data)
    ).read())
    return resp["access_token"]

def get_auth_b64(token):
    auth_string = "user=%s\x01auth=Bearer %s\x01\x01" % (EMAIL_ADDR, token)
    return base64.b64encode(auth_string.encode("ascii")).decode("ascii")

def get_imap(token):
    auth_b64 = get_auth_b64(token)
    imap = imaplib.IMAP4_SSL("outlook.office365.com", 993)
    imap.authenticate("XOAUTH2", lambda x: base64.b64decode(auth_b64))
    return imap

def read_unread():
    token = get_token()
    imap = get_imap(token)
    imap.select("INBOX")
    _, msg_ids = imap.search(None, "UNSEEN")
    emails = []
    for mid in msg_ids[0].split():
        _, msg_data = imap.fetch(mid, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
        emails.append({
            "id": mid.decode(),
            "from": msg["From"],
            "subject": msg["Subject"],
            "body": body.strip()
        })
    imap.logout()
    return emails

def send_email(to, subject, body):
    token = get_token()
    auth_b64 = get_auth_b64(token)
    smtp = smtplib.SMTP("smtp.office365.com", 587)
    smtp.ehlo()
    smtp.starttls()
    smtp.ehlo()
    smtp.docmd("AUTH", "XOAUTH2 " + auth_b64)
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDR
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    smtp.sendmail(EMAIL_ADDR, to, msg.as_string())
    smtp.quit()
    return True

if __name__ == "__main__":
    print("Reading unread emails...")
    emails = read_unread()
    print(f"Unread: {len(emails)}")
    for e in emails:
        print(f"FROM: {e['from']}")
        print(f"SUBJECT: {e['subject']}")
        print(f"BODY: {e['body'][:300]}")
        print("---")
