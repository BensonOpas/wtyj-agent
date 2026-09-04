# Curaçao Papiamentu critical text review — issue #342

Status: **PENDING qualified native Curaçao review.** This draft is not certified.

Reviewer name: pending  
Qualification / native Curaçao language background: pending  
Date and exact approved commit/version: pending  
Corrections and approval: pending

## Current wording correction — 4 September 2026

The user requires **standard written Curaçao Papiamentu: correct spelling, accents and grammar, with polite, professional, concise wording rather than street register**. The initial change applied 23 reviewed copy groups across six existing files; the final guidance amendment is recorded below. Reference checking and assistant wording review are complete for this scope; **a qualified native human sign-off is unavailable in the retained evidence and is not claimed**. Native approval remains pending. The fresh 12-conversation review is complete with preserved findings; the final wording update is deployed and its service checks passed.

| Current source/key group | Correction applied |
| --- | --- |
| `client.json` → `agent_persona.language_register`; `response_policy.json` → `glossary.pap` | Professional standard-writing guidance reaches both generated reply fields, including language switches. The expanded glossary supplies food, drink, clothing, money and accommodation vocabulary plus all seven existing weekday spellings. German guidance is preserved. |
| `reservation_catalog.json` → PAP trip/contact, hotel and pickup copy; policy `pickup_round_trip` | Consistent `biahe`, `alohamentu`, `tim` and `na total`; prices, return coverage, times, ages and placeholders are preserved. |
| Policy `review_active`; workflow `COPY.pap.human`; recovery `HUMAN_COPY.pap` | Active copy now says “Un miembro di e tim ta atendé e kombersashon aki.” Queued copy still explicitly waits for team review and retains saved details/general-question support. Recorded state continues to select the wording. |
| Workflow `COPY.pap.intro` | “Bon bini na Mermaid! Mi ta TRACY, asistente virtual di reservashon. Mi ta yuda bo ku bo biahe i prepara bo oferta di demo aki den WhatsApp.” |
| Workflow `FAQ_COPY.pap.included`; document `DOCUMENT_COPY.pap.included_items`; glossary | Consistent `almuerso di barbekiú` and `máskara di snòrkel`; drink guidance uses `refresko`, `djus`, `serbes` and `biña`, preserving which items cost extra. |
| Glossary `cash` and `cash_for_optional_drinks_example` | `sèn kèsh`; “Hiba sèn kèsh si bo ke serbes òf biña.” This retains optional-drink cash advice without adding a cash-only payment policy. |
| Workflow `COPY.pap.invalid_day`, `FAQ_COPY.pap.price`; document date/protocol labels | Correct `djárason` and `detayá`; use `Fecha di biahe` and `Protokòl di biahe`. |

The [government-published FPI spelling rules and word list](https://gobiernu.cw/wp-content/uploads/2025/12/196-GT.-Lb-schrijfwijze-Papiamentu-en-Nederlands.pdf) support the selected spellings and weekdays. Contextual usage comes from the [Ministry of Finance beverage notice](https://minfin.cw/wp-content/uploads/2019/09/FIN-Anunsio-Medida-PAP-4klx20cm-1.pdf), [CMC's Papiamentu patient booklet](https://www.cmc.cw/wp-content/uploads/2024/09/Beibi-Prematuro-Foyeto-ougustus-2024.pdf), and [Curaçao Tourist Board accommodation reporting](https://www.curacaotouristboard.com/2024/06/13/korsou-a-risibi-53-970-turista-di-estadia-na-mei-2024/). These establish spelling or usage, not approval of our complete sentences. Ordinary attested loanwords remain valid; `beibi` is not banned, and existing `handuk` is retained. Fare labels keep explicit ages. Complete combinations such as `paña di landa` and `máskara di snòrkel` remain assistant phrasing decisions, not independently certified expressions.

The [CBCS/CGA/FIU Papiamentu notice of 28 March 2025](https://www.centralbank.cw/storage/app/media/press_releases_2025/20250328_persbericht_cbcs_cga_fiu_introductie_caribische_gulden_pa.pdf) uses `sèn kèsh` for cash deposits and purchases. It supports the cash term; the complete optional-drink sentence remains assistant-authored wording, without native human sign-off.

The exact before/after mapping and reference limits are retained in `output/remediation-342-2026-09-04/papiamentu-correction-2026-09-04/{copy-plan-final.json,final-amendment.json,references-review.json}`. No language classifier, generated-text blacklist, business-rule change or extra model call is introduced. Earlier transcripts, raw grades and all historical rows below remain unchanged; they must not be read as the current copy inventory or erased after a later improvement.

### Fresh PAP12 evidence and final guidance

The run on `d61582302369c9b01e9e4f087923b23941dc1666` completed **12 conversations, 72 turns and 71 model calls**, with no generation failures. Raw results remain **9/10 Papiamentu originals + 1/1 Papiamentu paraphrase + 1/1 English/Papiamentu switch**. All turns and seven simulated receipts were reviewed; seven booked, one cancelled and four review-only outcomes retain correct recorded amounts and state.

Concrete findings remain in `editorial-review.{json,md}`: BASE-005 T3 omits the requested arrival answer from its visible reply although the dedicated field contains it; BASE-059 T4 says “sombré òf kacho”; BASE-035/041/059 use “september”; BASE-035 has malformed contact/party phrasing; BASE-055 T3 uses unclear “blokmènt di solo”. These remain actual recorded defects, including those missed by raw assertions. Improved food/drink vocabulary does not establish perfect professional language.

Source `9261d4a6d1d5efc030ab9706c3037c7607e4f3f3` adds the [twelve FPI month spellings](https://gobiernu.cw/wp-content/uploads/2025/12/196-GT.-Lb-schrijfwijze-Papiamentu-en-Nederlands.pdf#page=168), positive `sombré`, `pet`, `krema solar` packing guidance, existing catalog contact examples using `alkansá`, and an acknowledgement restricted to supplied or recorded details. Ordinary questions outside review and critical routes now receive explicit guidance to put the complete answer in `reply`, not split it across fields. Existing review routing is unchanged. `pet` remains existing document vocabulary, not a claimed FPI-listed word.

The amendment passed **22 offline tests for prompt delivery and existing behavior**. Those checks do not generate fresh language or prove the recorded defects cannot recur. **No further paid audit was run after this amendment; no raw result or native-review status is regraded.** Exact additions and limits are in `final-amendment.json` beside the retained audit evidence. Final source `9261d4a` is deployed: **530 exact-image tests and 19/19 live checks passed** at 17:32 UTC. Tracy is active/available; controls and peers are preserved. These service checks do not change the language-quality limits above. See the [release report](mermaid-audit-342-release.md).

## Retained historical review packet

The reviewer should check clarity, Curaçao spelling, natural guest-service tone and factual meaning. Accept unaccented/Aruba-style incoming messages without forcing those spellings into output. Business facts are already approved: pickup and return are included in the configured vehicle price; do not change prices or policy while editing language.

Weekday spelling reference: [Curaçao government locations and opening hours](https://gobiernu.cw/sitionan/). This reference supports weekday spellings only, not native approval of these sentences.

| Meaning / key | Draft Papiamentu | Reviewer correction / approval |
| --- | --- | --- |
| These dates follow our published schedule: {dates}. Which date would you like? | E fechanan aki ta sigui nos programa publiká: {dates}. Ki fecha bo ke? | pending |
| Our published operating days are {days}. | Nos dianan di biahe publiká ta {days}. | pending |
| There are no remaining scheduled dates in that period. Please choose another date. | No tin mas fecha programá den e período ei. Skohe un otro fecha, por fabor. | pending |
| Your request is queued for Mermaid’s team. I can still help with general trip questions. | Bo petishon ta warda pa e tim di Mermaid revisá. Mi por sigui kontestá pregunta general tokante e biahe. | pending |
| A team member has taken over this conversation. | Un miembro di e tim a tuma e kombersashon aki over. | pending |
| There is no pending staff-review request recorded for this chat. | No tin un petishon pa e tim revisá registrá pa e kombersashon aki. | pending |
| Your demo payment is not recorded as completed yet. No real money is taken in this demo. | Bo pago di demo no ta registrá komo kompletá ainda. Den e demo aki no ta kobra plaka di berdat. | pending |
| Your simulated payment is recorded as completed. No real money was charged. | Bo pago simulá ta registrá komo kompletá. No a kobra plaka di berdat. | pending |
| There is no completed demo payment recorded for this conversation. | No tin un pago di demo kompletá registrá pa e kombersashon aki. | pending |
| The document is recorded as delivered in this WhatsApp conversation. | E dokumento ta registrá komo entregá den e kombersashon di WhatsApp aki. | pending |
| Document delivery in this WhatsApp conversation is not confirmed yet. | Entrega di e dokumento den e kombersashon di WhatsApp aki no ta konfirmá ainda. | pending |
| The document delivery failed. Your reservation details are still saved. | No a logra entregá e dokumento. E datonan di bo reservashon ta wardá ainda. | pending |
| There is no document delivery recorded for this conversation. | No tin entrega di dokumento registrá pa e kombersashon aki. | pending |
| The quoted vehicle price includes pickup and the return to your accommodation. | E preis indiká pa vehíkulo ta inkluí buska bo i trese bo bèk na bo alojamentu. | pending |
| The quoted transport price does not yet establish whether return transport is included; the team needs to confirm that. | E preis indiká no ta konfirmá ainda si e biahe di regreso ta inkluí; e tim mester konfirmá esei. | pending |
| I can help with Mermaid trip questions, but I can’t change approved prices, invent payment or share private information. | Mi por yuda ku pregunta tokante e biahe di Mermaid, pero mi no por kambia preis aprobá, inventá pago ni kompartí informashon privá. | pending |
| Hi, I’m TRACY, Mermaid’s virtual reservation assistant. I’ll arrange your trip and prepare the full demo quote right here in WhatsApp. | Bon dia, mi ta TRACY, asistente virtual di reservashon di Mermaid. Mi ta regla bo trip i prepara e oferta demo kompleto aki mes den WhatsApp. | pending |
| What date would you like to visit Klein Curaçao? | Ki fecha bo ke bishitá Klein Curaçao? | pending |
| Please reply *YES* if everything is correct, or tell me exactly what to change. | Kontestá *SI* si tur kos ta korekto, òf bisa mi eksaktamente kiko mester kambia. | pending |
| Perfect, I have your confirmed details. I’m preparing your demo reservation and quote now. | Perfekto, bo datonan ta konfirmá. Awor mi ta prepara bo reservashon demo i oferta. | pending |
| Your demo reservation request is cancelled. No payment was taken. | Bo petishon di reservashon demo ta kanselá. No a tuma ningun pago. | pending |
| I’ve passed this to Mermaid’s team for review. Your details are saved, and I can still help with general trip questions. | Mi a pasa esaki pa tim di Mermaid revisá. Bo datonan ta wardá i mi por sigui yuda ku preguntanan general tokante e trip. | pending |
| pickup_vehicle_priced | Nos ta pasa buska bo na {location} pa {pickup_time}. Por fabor, ta kla na e ora ei. {quantity} × {vehicle}; {currency} {amount} pa pickup en total, inkluí den e reservashon aki. E preis indiká pa vehíkulo ta inkluí buska bo i trese bo bèk na bo alojamentu. | pending |
| pickup_car | Pickup ku outo (máx. {capacity} persona) | pending |
| pickup_van | Pickup ku van (máx. {capacity} persona) | pending |
| checkout_link | Kompletá bo reservashon demo aki: | pending |
| trip_total | Total di trip | pending |
| paid | Demo pagá | pending |
| adults_one | {count} tarifa di adulto | pending |
| children_one | {count} mucha (4-12) | pending |
| infants_one | {count} mucha chikitu (0-3) | pending |

Weekdays, Monday through Sunday: djaluna, djamars, djárason, djaweps, djabièrnè, djasabra, djadumingu.


| FAILURE_COPY meaning | Draft Papiamentu | Reviewer correction / approval |
| --- | --- | --- |
| I couldn't answer that just now. Your details are saved. Please try again shortly, or ask to speak to a person. | Mi no a logra kontestá bo aworaki. Bo datonan ta wardá. Purba atrobe den un ratu òf pidi pa papia ku un hende di e tim. | pending |

| HUMAN_COPY meaning | Draft Papiamentu | Reviewer correction / approval |
| --- | --- | --- |
| Your request is queued for Mermaid's team. Your details are saved, and I can still help with general trip questions. | Bo petishon ta warda pa e tim di Mermaid revisá. Bo datonan ta wardá i mi por sigui yuda ku preguntanan general tokante e trip. | pending |

| Document meaning | Draft Papiamentu | Reviewer correction / approval |
| --- | --- | --- |
| DEMO QUOTE - NOT A VALID TICKET | OFERTA DEMO - NO TA UN TIKÈT VÁLIDO | pending |
| SIMULATED PAYMENT - DEMO ONLY | PAGO SIMULÁ - SOLAMENTE UN DEMO | pending |
| Klein Curaçao demo reservation | Reservashon demo pa Klein Curaçao | pending |

Fresh conversational paraphrases and language switches require transcript review as well; passing locale metadata checks does not establish fluent language. All copy above remains a draft until the reviewer signs the exact release version.


## Packet revision and evidence boundaries

Packet refreshed on 4 September 2026 after the pickup and review-status repairs
were merged as `74b2331` and `1e14037`. The added wording below is copied exactly
from `clients/mermaid/config/response_policy.json`, version
`mermaid-response-policy-342-v2` (SHA256
`aaf0cafbbfdb1862831e2c9e2d42455de09c9d3f5d22e90d2e03d94db62bbd4a`). This records what needs review; it is not an approved release
version or evidence of deployment. Native reviewer identity, qualifications,
corrections and the exact approved release remain **pending**.

The transcript excerpts come from the initial isolated candidate at source
`2286d9f83b7c568831e37d70ad1acff41d2e2a60`, image digest
`sha256:109ad1f8f269f5352b42bb93bb9e357445d23f979f262a6bd1f50e2c7655f4d9`.
They were checked against the actual guest inputs and replies in
[NL/PAP transcripts](/Users/calvin/Documents/ChatGPT/Mermaid/output/remediation-342-2026-09-04/review-nl-pap.jsonl)
and [EN/DE transcripts](/Users/calvin/Documents/ChatGPT/Mermaid/output/remediation-342-2026-09-04/review-en-de.jsonl).
These are historical findings, not claims that a later candidate still produces
each sentence. The original 47/60 functional and 32/60 accepted baseline stays
unchanged. Assistant review and passing deterministic tests do not certify
Papiamentu fluency.

## Added pickup and wildlife draft copy

Preserve the placeholders and factual meaning while reviewing the wording.
Passenger totals include adults, children and infants. The currently approved
car has capacity five and costs USD 75 per vehicle; the van has capacity nine
and costs USD 125. Pickup and return are included in those rates; scheduled
pickup is 05:45 Curaçao local time. These example values remain configuration
owned. Existing booked amounts and vehicle plans may differ and must retain
their recorded values. An enquiry or the following copy never establishes
pickup consent, vehicle availability, driver assignment or completed staff work.

| Key / intended meaning | Exact draft Papiamentu | Native correction / approval |
| --- | --- | --- |
| `pickup_party_count` — {count} guests in total. | {count} persona na total. | pending |
| `pickup_option` — Pickup option: {quantity} × {vehicle}, {currency} {amount} per vehicle. | Opshon di transporte: {quantity} × {vehicle}, {currency} {amount} pa vehíkulo. | pending |
| `pickup_option_total` — Total for pickup: {currency} {amount}. | Total pa transporte: {currency} {amount}. | pending |
| `pickup_recorded_vehicle` — Your recorded pickup: {quantity} × {vehicle}, {currency} {amount} in total. | Bo transporte registrá: {quantity} × {vehicle}, {currency} {amount} na total. | pending |
| `pickup_recorded_amount` — Your recorded pickup amount is {currency} {amount}; no vehicle type is recorded. | E montante registrá pa bo transporte ta {currency} {amount}; no tin un tipo di vehíkulo registrá. | pending |
| `pickup_not_included` — Pickup is not included in your saved booking. Adding it needs the team’s review. | Transporte no ta inkluí den bo reservashon wardá. Pa agregá esaki, e tim mester revisá e petishon. | pending |
| `pickup_need_party` — How many adults, children aged 4–12 and children aged 0–3 will travel? | Kuantu adulto, mucha di 4–12 aña i mucha di 0–3 aña ta bai? | pending |
| `pickup_offer_review` — This group needs the team to confirm suitable transport and its price. | Pa e grupo aki, e tim mester konfirmá transporte adekuá i su preis. | pending |
| `pickup_unpriced` — The pickup price needs confirmation from the team. | E tim mester konfirmá e preis pa transporte. | pending |
| `pickup_schedule` — Scheduled demo pickup is at {time}, Curaçao local time. | E ora di pickup programá den e demo aki ta {time}, ora lokal di Kòrsou. | pending |
| `pickup_current_amount` — The current pickup price is {currency} {amount} per booking. | E preis aktual pa transporte ta {currency} {amount} pa reservashon. | pending |
| `wildlife_guarantee` — Turtles and other wildlife may be seen, but sightings are never guaranteed. | Ta posibel pa mira turtuga i otro bestia, pero no tin garantia ku bo lo mira nan. | pending |

`pickup_current_amount` is for a configured legacy per-booking fee, not the
current per-vehicle policy. `pickup_recorded_amount` deliberately avoids naming
a vehicle where an older booking recorded no vehicle type. For wildlife, retain
the clear distinction between possible sightings and a guarantee. When a review
exists, the wildlife reply may append the separate queued/active copy above;
only recorded operator takeover justifies the active wording.

## Actual transcript examples requiring native review

Every quoted excerpt below was present in the initial candidate's visible
reply. Suggested alternatives are **assistant drafts for review**, not native
corrections or approvals. Borrowed vocabulary alone is not automatically a
material error; review clarity, consistency and meaning in context.

| Source case / turn | Attested excerpt and context | Question for the native reviewer / draft direction | Native correction / approval |
| --- | --- | --- | --- |
| PAP BASE-011 T1 | “Pa kumenså, kon fecha bo ta pensa pa e biahe?” — asks for the booking date. | Review the anomalous spelling and natural question. Draft: “Pa kuminsá, ki fecha bo ke bai?” | pending |
| PAP BASE-011 T7 | “e kosto ta USD 75 pa un karchi (máximo 5 pasahero)” — describes a pickup vehicle. | The vehicle noun differs from catalog `outo`; confirm the natural word for a car. Draft: “e kosto ta USD 75 pa un outo (máximo 5 pasahero)”. | pending |
| PAP BASE-023 T3 | “Pa un grupo di 5 persona, un auto tin kapasidat pa tur kuater” — guest asked the price and explicitly had not chosen pickup. | Factual contradiction: 3 adults + 1 child + 1 infant = 5. The new server route supplies the count, capacity and amount. Review its new copy above; a count-word draft would be “tur sinku”, never “tur kuater”. | pending |
| PAP BASE-035 T1 | “Ku muhitu alegria bo ke bai Klein Curaçao.” — opening response to a booking enquiry. | Review meaning, spelling and whether this adds unnecessary ceremonial language. No approved replacement is claimed. | pending |
| PAP BASE-035 T2 | “Kuantu adulto i piká lo bai?” — asks for party composition. | Clarify the child/infant vocabulary because these counts affect fares and vehicle capacity. Review the explicit age-band question in `pickup_need_party` above. | pending |
| PAP BASE-035 T7 | “Bo ke nos drecha bo of bo ke bai na e pier mes” — asks whether pickup is wanted. | Check that this clearly means collecting the guest. Draft: “Bo ke nos pasa buska bo, òf bo ta bai na e pier ku bo mes transporte?” | pending |
| PAP BASE-035 T2 and BASE-041 T2 | “diasabra” — refers to Saturday 12 September. | Compare with configured Curaçao output `djasabra`; the stored date is correct. Accept incoming variants without forcing the guest to rewrite them. | pending |
| PAP BASE-005 T3 | “Beer i wijn”; also “refresco i djùis” — discusses drinks included or costing extra. | Review consistent local guest-service vocabulary and spelling; the paid-extra qualification is factually present. | pending |
| PAP BASE-017 T4 | “refreshment (soft drinks i jugo)”; “almuerso BBQ” — answers an inclusions question. | Review the mixed register and spelling; preserve the factual inclusions. | pending |
| PAP BASE-029 T1 | “mi ta yudabo buka e biahe” — introduction and booking help. | Review spacing and the natural booking verb. The separate “Mi ta Tracy” introduction is present; that alone does not certify the rest of the sentence. | pending |
| PAP BASE-059 T4 | “zwemkleding”; “Si bo ke bèk òf wijn, hiba kèsh tambe” — packing advice and paid drinks. | Review swimwear and beverage/cash vocabulary. `bèk` occupies the drink position here, unlike its return-trip use in catalog copy. Draft direction: “paña di landa” and “Si bo ke e bebidanan ku ta kosta ekstra, hiba plaka tambe.” | pending |
| EN BASE-055 T3, explicitly switched to PAP | “zwemropa”; “Si bo ke serbesa òf bino, hiba un pokito di kashó paso esnan ta kosta ekstra.” | Guest asked “Por fabor kontestá na Papiamentu. Kiko mi mester hiba?” Review the swimwear blend and intended cash wording. Draft direction: “Hiba paña di landa … hiba plaka pa e bebidanan ku ta kosta ekstra.” | pending |

BASE-055 and BASE-059 later stopped because of the initial audit harness's
SQLite-row conversion error. The quoted language turns occurred before that
error and remain available for review; this packet does not mark their complete
security scenarios as passed. EN BASE-055 T3 is a supplemental Papiamentu
language-switch example, not an additional case in the ten-case PAP denominator.

Please review at least one complete corrected pickup enquiry and one complete
wildlife/review follow-up in context, as well as these individual sentences.
Record proposed corrections, reviewer identity and qualifications, date, exact
release commit/policy hash and explicit approval before changing any native
acceptance status. Until then, **native Curaçao Papiamentu approval remains
pending for the entire packet and all related transcripts**.

## Historical follow-up and third-attempt examples

Added on 4 September 2026. Every excerpt below was verified against the saved visible reply from the identified isolated run. These are **historical, pending native-review findings**, not claims about the output of the runtime currently being built or a later release. This documentation-only addition does not change runtime code, policy copy, candidate image contents or the source/image identity recorded for any run.

| Historical run | Exact source commit | Image digest |
| --- | --- | --- |
| Follow-up 24 | `535508cd8dec55982dd5e178ff4fcde5a6e9f8bd` | `sha256:e2b28d7dd5b3cc6252f0b2f480667480f44527d1f31d50752fb1b189a3bb9344` |
| Third attempt 12 | `178ba564fe8fc9388d68d2f17e6241d02882bf40` | `sha256:21cb0edffc278f59a132a4f4c6d1b3b0913499097bd550b4e15092ab2d325a29` |

The follow-up retains its raw 16/18 original-case and 5/6 paraphrase results. The third attempt retains its raw 2/6 accessibility and 2/6 paraphrase results. Neither these findings nor suggested wording regrade those records. Locale labels and functional passes are separate from native language approval.

Evidence: [follow-up NL/PAP review](/Users/calvin/Documents/ChatGPT/Mermaid/output/remediation-342-2026-09-04/review-followup-nl-pap.jsonl), [complete follow-up originals, including the English-origin Papiamentu switch](/Users/calvin/Documents/ChatGPT/Mermaid/output/remediation-342-2026-09-04/followup-run/results/followup-18-results.jsonl), and [third-attempt NL/PAP review](/Users/calvin/Documents/ChatGPT/Mermaid/output/remediation-342-2026-09-04/review-final12-nl-pap.jsonl). The corresponding review reports preserve the saved state, failure classifications and exact case hashes.

| Historical source case / turn | Exact attested excerpt | Native review question / assistant draft direction | Native correction / approval |
| --- | --- | --- | --- |
| Follow-up 24, BASE-023 T1 | “Cu mucho gusto mi yuda bo reserva pa Klein Kòrsou.”; “Pa kua fecha bo ta pensando di bai?” | Review the mixed introductory phrase, Curaçao output spelling and natural date question. These are fluency/register concerns; the later five-person count, USD 75 return-inclusive car price and USD 600 quote are correct. Draft direction: “Mi ta yuda bo ku bo reservashon pa Klein Kòrsou. Ki fecha bo ke bai?” | pending |
| Follow-up 24, BASE-059 T2 | “Sabra 12 di september ta bon!”; “much (4-12) aña, i pittu (0-3) aña” | Review weekday spelling against configured djasabra and the unclear/truncated child and infant category words. The numeric date and age bands are correct. The category words repeat at T4 and T6. Draft direction: “mucha di 4–12 aña i beibi di 0–3 aña”. | pending |
| Follow-up 24, BASE-059 T4 | “Hiba un toaya, krema di solo, un pet i roupa di bañu.” | Review swimwear vocabulary and consistent Curaçao spelling. Draft direction: “paña di landa”. Do not classify an ordinary borrowing as a material error solely because of its origin. | pending |
| Follow-up 24, BASE-059 T4 | “Si bo ke bèbè serbes of wijn, trese un poko di sèn en man.” | Review beverage/cash wording, accents and natural guest-service register. The intended instruction is to bring money for optional paid drinks. Draft direction: “hiba plaka pa e bebidanan ku ta kosta ekstra”. | pending |
| Follow-up 24, BASE-059 T6 | “Bo mester yega na Fishermen's Pier pa 06:45 aña.” | The numeric arrival time is correct, but aña (year) is attached to it. Review the operational wording; the original numeric assertion passing does not establish correct prose. Draft: “Bo mester yega na Fishermen’s Pier pa 06:45.” | pending |
| Follow-up 24, PARA-005 T4 | “Si bo ke serbes of vino, esakinan ta kosta ekstra , trese kashi si bo ke.” | Check the intended cash noun kashi and mixed spelling/register. This is a suspect meaning-changing operational instruction, not an approved native correction. Draft direction: “hiba plaka pa e bebidanan ku ta kosta ekstra”. | pending |
| Follow-up 24, BASE-047 T6 | “Sí, desayuno ta inkluí, huntu ku almuerzo BBQ, refresco i djùs.” | Review consistent Curaçao spelling and the natural words for lunch, soft drinks and juice. The inclusions and following 06:45 arrival are factually correct; this is a native style/clarity question. | pending |
| Follow-up 24, BASE-055 T3 | “zwemropa”; “hiba plaka kèshi”; “Kuantu adulto, yiu (4–12 aña) i beibi (0–3 aña) lo bai?” | English-origin conversation explicitly switched to Papiamentu. The unclear swimwear blend recurs. Plaka makes the cash meaning clearer than the first attempt, but kèshi and the party-category use of yiu need local review. Draft direction: “paña di landa”, “plaka” and the explicit mucha/beibi age bands. This supplemental turn does not add a case to the Papiamentu denominator. | pending |
| Third attempt 12, BASE-047 T1 | “Ku placer mi yuda bo ku e reservashon.” | Review whether this borrowing/phrase is natural for a Curaçao guest-service greeting. No independent business-state defect is inferred from the borrowed term alone. | pending |
| Third attempt 12, BASE-047 T5 | “Bo reservashon ta den man di e tim di Mermaid pa konfirmasion tokante e stul di rueda i posibilidad di mira turtuga.”; “Nan lo kontaktá bo ku e information di mester.” | Review wording and factual meaning together: the recorded request was queued, not confirmed as actively handled, and staff contact was not established. The guest had only acknowledged details. Do not polish a promise into approved copy; use the existing queued-review draft and preserve the no-wildlife-guarantee distinction. This visible claim follows a failed wildlife answer, but is a separate historical finding. | pending |
| Third attempt 12, BASE-047 T6 | “Sí, desayuno ta inkluí, huntu ku almoerso BBQ, refresco i jugo.” | Compare lunch/juice spelling with the other attested variants. Food inclusions and 06:45 are correct; native consistency review is still required. | pending |
| Third attempt 12, PARA-005 T4 | “Sí, almorso BBQ ta inkluí den e biahe, huntu ku desayuno, refresco i djus. Serbes i bino ta kòsta èkstra.” | Review lunch/beverage spelling, accents and natural register. The paid-extra distinction is present and this journey produced its correct USD 450 quote after one approval. Functional success does not certify these sentences. | pending |

In the third attempt, BASE-047 T4 and Dutch PARA-002 T5 returned localized generation-failure notices while preserving saved booking state. Those are runtime/adapter failures, not evidence that the displayed notice used the wrong language. The discarded raw SDK tool input was not recorded in that run; this packet does not invent it. BASE-047 T5 is separately included above because its later visible staff-contact claim must not be mistaken for an approved queued-status message.

The earlier five-versus-four passenger sentence did not recur in the reviewed follow-up pickup enquiry. The third-attempt Papiamentu paraphrase also reached its canonical summary and quote correctly. These bounded improvements do not clear the historical wording findings or certify a later model response.

The native reviewer should assess whole turns and their guest context, distinguish ordinary loanwords from unclear or meaning-changing words, preserve approved facts, and record their own correction or acceptance for every row. All suggested alternatives are assistant drafts only. **Reviewer identity, qualifications, exact approved release/version and native Curaçao Papiamentu approval remain pending for the full packet.**
