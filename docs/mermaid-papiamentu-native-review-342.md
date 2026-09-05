# Formal Curaçao Papiamentu product review — issue #342

Status:

- **Official-reference review of deterministic product copy: complete.**
- **Native-human certification of arbitrary generated sentences: not performed
  and not claimed.**

The release uses formal written Curaçao Papiamentu. Fixed customer copy was
reviewed against the official Fundashon pa Planifikashon di Idioma (FPI)
orthography and word list, known defects from the retained transcript audits
were corrected, and generated Papiamentu now passes a server-side gate for the
known defective and mixed forms before it can be stored or sent.

This is an official-source language review of fixed product copy and runtime
rules. A finite automated gate cannot prove that every possible free-form
sentence has perfect grammar or native register. That stronger claim requires
review and acceptance by a qualified Curaçao Papiamentu language professional.

## Production controls

- `response_policy.json` records
  `formal_written_curacao_reference_review_complete` and names the FPI
  standard used for the review.
- `client.json` and `mermaid_understanding.py` require complete, professional
  Curaçao Papiamentu sentences and prohibit street register, slang, phonetic
  spelling, texting shortcuts, Aruba output spelling, and unnecessary Spanish,
  Dutch, or English mixing.
- `mermaid_model_recovery.py` rejects generated customer text containing known
  defective forms from the retained audits. Rejected text is never persisted or
  sent; normal durable retry and the fixed formal fallback remain available.
- `test_mermaid_papiamentu_copy.py` scans the complete deterministic production
  inventory. Model-recovery tests exercise both `reply` and
  `other_question_reply` at the send boundary.

## Corrections included in the release

The release standardizes `bèrdat`, `periodo`, `kòmbersashon`, `prepará`,
`bishitante`, `bebé`, `mobilidat`, `lansamentu`, `toaya`, `kas di playa`, and
the formal `pasa buska bo` transport wording. The final static inventory also
uses `katalòk`, `lansamentu`, and `pèchi`; the output gate rejects the
nonstandard or Dutch forms `katálogo`, `lansementu`, and `pet`. It removes fixed-output uses of
`pickup`, `beibi`, `berdat`, `kombersashon`, `período`, `movilidat`, `aworaki`,
unaccented `prepara`, `adjuntá`, and `beach house` from Papiamentu copy.

The formal wheelchair acknowledgement is:

> Sí, no tin problema. Nos ta prepará pa risibí bishitantenan ku ta usa stul di rueda. Mi a registrá un nota pa e tripulashon por prepará pa duna asistensia.

The formal withdrawal acknowledgement is:

> Mi a komprondé. Mi a kita e nota tokante e stul di rueda for di e reservashon aki.

## Reference basis

- [FPI Ortografia i Lista di palabra Papiamentu](https://gobiernu.cw/wp-content/uploads/2025/12/196-GT.-Lb-schrijfwijze-Papiamentu-en-Nederlands.pdf)
- [Curaçao government use of `persona ku ta den stul di rueda`](https://gobiernu.cw/notisia_di_ministernan/prome-minister-gilmar-pisas-a-partisipa-na-aktividat-di-dia-internashonal-di-personanan-ku-tin-desabilidat/)
- [Curaçao government tourism use of `bishitante` and `bishitantenan`](https://gobiernu.cw/notisia_di_ministernan/diskurso-nashonal-di-prome-minister-pisas-1-di-yanuari-2026/)
- [Curaçao government use of `prepará` and `duna asistensia`](https://gobiernu.cw/wp-content/uploads/2021/03/Sifranan-Anual-Brantwer-Korsou-2020.pdf)
- [CBCS/CGA/FIU use of `sèn kèsh`](https://www.centralbank.cw/storage/app/media/press_releases_2025/20250328_persbericht_cbcs_cga_fiu_introductie_caribische-gulden_pa.pdf)

These references support the written standard and relevant usage. Proper names,
customer-supplied facts, and established Papiamentu loanwords remain intact.

## Retained audit evidence

Raw historical conversations, grades, receipts, and editorial findings remain
under `output/remediation-342-2026-09-04/`. They document earlier model defects
such as mixed food vocabulary, `september`, `kacho`, `zwemropa`, and
`blokmènt di solo`. They describe superseded builds and do not define the
current production copy or release status.

This review changes language only. Prices, pickup and return coverage, booking
state, payment simulation, delivery state, and staff-review authority remain
server controlled.
