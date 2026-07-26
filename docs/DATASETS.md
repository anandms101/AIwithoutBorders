# Datasets — selection, licensing and clearance

> **What this is.** The evidence behind every dataset Outpost uses, and every one it
> rejected. It exists so that (a) whoever provisions the USB drive has a checklist rather
> than a conversation to reconstruct, and (b) the Rule 06 third-party clearance in the
> submission writeup can be audited without re-doing the research.
>
> **Status:** research complete, nothing downloaded yet. No fetch tooling exists — see
> `AGENTS.md` §Current state.

**One-line answer:** images from **TBX11K** and the **COVID-19 Radiography Database** (both
CC BY 4.0), speech validation from **MediaSpeech FR** and **African Accented French**,
consultation audio **self-recorded in French**, case definitions **paraphrased from the WHO
2023 EWAR operational guide**.

---

## 1. Selection criteria

Every dataset below is judged against these four. A dataset failing any one is rejected,
and §6 records which criterion each rejection failed.

| # | Criterion | Why |
| --- | --- | --- |
| C1 | **PNG or JPEG** | DICOM parsing is an explicit non-goal (`PRD.md` §2, `DECISIONS.md` D3). We will not write a DICOM reader on the day. |
| C2 | **No credentialing delay** | PhysioNet-style credentialed access needs CITI training and review — days, not hours. The build is one day. |
| C3 | **Fits a USB drive** | The venue has no usable Wi-Fi and there is no network access at build time (`AGENTS.md` §Working conventions). Everything ships on the drive. |
| C4 | **Licence permits public presentation** | The demo video may be posted publicly, and the pitch names paying customers. Non-commercial and no-redistribution clauses are therefore disqualifying for anything shown on camera. |

C4 is the one that eliminates otherwise-excellent datasets. Read §7 before putting any
image or audio on screen.

---

## 2. Chest X-rays

| Dataset | Format | Download | Images | Licence | Verdict |
| --- | --- | --- | --- | --- | --- |
| **TBX11K** | PNG 512² | ~3.3–4 GB | 11,200 | **CC BY 4.0** | ✅ **Primary** |
| **COVID-19 Radiography Database** | PNG 1024² | ~1 GB compressed (~4–5 GB unpacked) | 21,165 | **CC BY 4.0** | ✅ **Primary** |
| NIH ChestX-ray14 — Kaggle sample | PNG 1024² | ~1 GB | ~5,606 | "No restrictions" + attribution | ✅ Test volume |
| NIH ChestX-ray14 — full | PNG 1024² | 42–45 GB | 112,120 | Same | ⚠️ Only with a 64 GB+ drive |
| NLM Montgomery County TB | PNG 4020×4892 | **588 MB** ✔︎measured | 138 (80 normal / 58 TB) | No formal grant; see §2.4 | ⚠️ Cite, don't re-host |
| NLM Shenzhen Hospital TB | PNG ~3000² | **3.6 GB** ✔︎measured | 662 (326 / 336) | Same as Montgomery | ⚠️ Optional |
| Indiana University Open-i | XML reports | **228 MB** ✔︎measured | 3,955 reports | CC BY-NC-ND 4.0 | ⚠️ Offline only — §7 |

✔︎measured = size obtained by HTTP HEAD against the live URL during this research.
Unmarked sizes are as published by the provider.

### 2.1 TBX11K — primary

- **What:** 11,200 chest X-rays at 512×512 PNG from the Media Computing Lab, Nankai
  University, with **bounding boxes on TB lesions** and **4-level ordinal labels**
  (healthy → sick-but-non-TB → latent TB → active TB).
- **Licence, verbatim:** *"This dataset belongs to the Media Computing Lab at Nankai
  University and is licensed under a Creative Commons Attribution 4.0 License."*
  CC BY 4.0 permits commercial use, redistribution, public display and public video.
- **Why it wins.** Three reasons, in order of importance:
  1. **The licence survives our use case.** CC BY 4.0 is one of only two licences in this
     table that cleanly permit a *publicly posted* video for a *commercially pitched*
     product. That is a hard requirement, not a preference.
  2. **The bounding boxes are the demo.** We can draw a literal box around the region the
     model scored, which makes the "abnormality score" legible to a non-radiologist judge
     rather than an unexplained number.
  3. **Ordinal severity labels are the only sanity check available** for a 0–100 score. No
     public dataset ships a continuous severity scale; TBX11K's four levels let us assert
     a monotonic expectation (healthy ≈ 0–25, active TB ≈ 75–100) and catch a
     miscalibrated scorer before the pitch.
- **Also relevant:** TB aligns with the WHO computer-aided detection recommendation we
  already cite in the pitch (§4.4), so the imaging modality and the narrative agree.
- **Source:** https://mmcheng.net/tb/ (also on Academic Torrents). No registration.

### 2.2 COVID-19 Radiography Database — primary, for visual legibility

- **What:** 21,165 PNGs from Qatar University et al. — COVID-19 3,616 · Normal 10,192 ·
  Lung Opacity 6,012 · Viral Pneumonia 1,345. Ships per-image lung masks.
- **Licence:** **CC BY 4.0.** Commercial use, redistribution and public display permitted.
- **Why:** best *visual drama per gigabyte* in the whole survey. Bilateral ground-glass
  opacity and consolidation read as obvious "white lung" on a projector; a judge who has
  never seen a chest film can tell the abnormal from the normal in about a second. At ~1 GB
  compressed it is also the cheapest thing on the drive.
- **Use:** pick 20–30 severe cases and 10–15 normals for the demo set.
- **Source:** https://www.kaggle.com/datasets/tawsifurrahman/covid19-radiography-database

### 2.3 NIH ChestX-ray14 — testing volume

- **Licence, verbatim:** *"There are no restrictions on the use of the NIH chest x-ray
  images. However, the dataset has the following attribution requirements: Provide a link
  to the NIH download site; Include a citation to the CVPR 2017 paper; Acknowledge that the
  NIH Clinical Center is the data provider."*
- **Why only for testing:** the cleanest licence of any dataset here, but many of its 14
  labels (Infiltration, Atelectasis, Nodule) are subtle findings a non-radiologist cannot
  see on a projector, and there are no bounding boxes to point at. Excellent for volume,
  weak for stage.
- **Note:** NIH explicitly does **not** release the reports — *"original radiology reports
  are not meant to be publicly shared for many reasons."*
- **Source:** https://nihcc.app.box.com/v/ChestXray-NIHCC · sample:
  https://www.kaggle.com/datasets/nih-chest-xrays/sample

### 2.4 NLM Montgomery + Shenzhen — usable but with irreducible ambiguity

Genuinely convenient: US government hosted, no authentication, no click-through, IRB
exempted, 800 TB-labelled images totalling ~4.2 GB. But there is **no explicit open licence
grant**, and the 2014 source paper states: *"We ask that requesters do not share the
datasets outside of their research groups and organization."*

That 2014 wording predates the current open portal and most plausibly addresses
*redistributing the archives*, not *showing images with attribution*. Still, absent an
explicit grant the ambiguity cannot be fully resolved. **Position: cite them, do not mirror
the zips, and prefer TBX11K or the COVID database for anything on camera.** The zero-risk
path is to not need them.

### 2.5 Radiology reports — what exists and why we mostly can't use it

We may want real report text to make synthetic clinical notes read realistically.

| Dataset | Reports | Licence on the text | Usable? |
| --- | --- | --- | --- |
| MIMIC-CXR | 227,827 — the gold standard | PhysioNet DUA | ❌ credentialing + DUA |
| CheXpert | 224,316 | Stanford RUA: NC + no redistribution | ❌ |
| **Indiana Open-i** | 3,955 XML, finding + impression | **CC BY-NC-ND 4.0** | ⚠️ **offline only** |
| NLM Montgomery/Shenzhen | ~800 brief readings | No formal grant | ⚠️ partial |

Indiana Open-i is the only immediately downloadable option with real structured reports.
Its **NC clause** means it may inform *how we write* synthetic notes but must not appear in
the video or in any commercially-framed output. See §7.

---

## 3. Speech — the language decision

### 3.1 Decision: French. This resolves `DECISIONS.md` Q1.

| Metric | French | Arabic |
| --- | --- | --- |
| Whisper large-v3 WER | **~5–6%** | 9.3% headline — but see below |
| Whisper large-v3 WER, Levantine dialect | — | **37.8%** |
| Whisper large-v3 WER, Maghrebi dialect | — | **84.7%** |
| CoVoST-2 → English BLEU | **38.1** | 21.4 |

**The headline Arabic number is misleading for our use case.** The ~9.3% figure averages
benchmarks built on Modern Standard Arabic read speech (FLEURS, Common Voice). A clinician
in a field hospital does not speak MSA — they speak a regional dialect. Measured
zero-shot on dialects, Whisper large-v3 degrades to 37.8% WER on Levantine and 84.7% on
Maghrebi. The benchmark authors state plainly that *"Whisper has insufficient Maghrebi
Arabic in pretraining… QLoRA cannot bring it within range of other dialects in this
training budget."*

At roughly one word in three wrong, a live Arabic transcript on stage is a demo failure.
French is a Tier-1 Whisper language and holds ~5–6% WER, degrading to a still-workable
8–12% on noisy real-world audio. Translation quality is nearly double (BLEU 38.1 vs 21.4).

Secondary considerations that point the same way: French avoids RTL bidi rendering work in
the UI; a francophone team member is easier to source than a native dialectal Arabic
speaker; and African-accented French can be validated directly against a public corpus.

### 3.2 Corpora

| Dataset | Language | Hours | Licence | Size | Purpose |
| --- | --- | --- | --- | --- | --- |
| **MediaSpeech FR** | French | 10 | **CC BY 4.0** | **637 MB** | Broadcast-quality validation |
| **African Accented French** (OpenSLR 57) | French, African accents | ~20 | **Apache 2.0** | **1.8 GB** | Validates the actual target accent |
| Common Voice FR — test split | French | — | **CC0 1.0** | ~200–500 MB | Public-domain fallback |
| FLEURS FR — test split | French | — | CC BY 4.0 | ~140 MB | Standard benchmark |
| CoVoST 2 fr→en — test split | French→EN | — | CC BY-**NC** 4.0 | ~240 MB | ⚠️ translation scoring, **offline only** |

**African Accented French earns its 1.8 GB**: it is the only corpus that tests the exact
speaker profile in our story — a clinician from francophone West or Central Africa — rather
than metropolitan French. If Whisper degrades on that accent we need to know before the
demo, not during it.

### 3.3 Consultation audio: we record it ourselves

**No public clinical consultation audio exists in French or Arabic.** The gap is absolute —
FRASIMED is text-only, PriMock57 is English-only. This is not a shortcut we are taking; the
data simply does not exist, which is itself a useful thing to be able to say on stage.

Self-recording also gives the cleanest possible licence position: we own it outright.
`PriMock57` supplies the *structure* of a realistic consultation (presenting complaint →
history → examination → assessment and plan) as a template for the French script, without
using its audio.

### 3.4 Whisper failure modes — a safety finding, not just a quality one

Whisper large-v3 **hallucinates plausible text on silence and non-speech audio**, and can
loop a phrase indefinitely (arXiv:2501.11378; OpenAI's own model card). On a noisy field
recording it can fabricate symptoms, drug names or treatment plans that were never spoken.

**This is direct evidence for invariant 5** (`AGENTS.md`): alerts fire on structured fields
only, never on translated free text. A hallucinated clause must not be able to manufacture
an outbreak. We can now cite a paper for that design choice rather than asserting it.

Mitigations to apply at the ASR boundary when it is built:

| Setting | Value | Why |
| --- | --- | --- |
| VAD pre-filter (e.g. Silero, MIT) | on | Never hand silence to the decoder — the strongest single defence |
| `language` | `"fr"` explicitly | Auto-detection can silently switch language mid-audio |
| `condition_on_prev_tokens` | `False` | Stops a hallucination in one segment seeding the next |
| `compression_ratio_threshold` | `1.35` | Detects repetitive looping output |
| `no_speech_threshold` | `0.6` | Suppresses output on silence |
| `logprob_threshold` | `-1.0` | Drops low-confidence segments |
| `temperature` | `(0.0, 0.2, 0.4, 0.6, 0.8, 1.0)` | Fallback ladder to escape loops |

Plus the architectural mitigation already in the design: native and English transcripts are
shown side by side for clinician verification, and nothing is auto-accepted.

---

## 4. Case definitions

### 4.1 Source

**Early Warning Alert and Response in Emergencies: an operational guide.** Geneva: World
Health Organization; 2023 (WHO/UXH/EPR/2023.1). Licence: **CC BY-NC-SA 3.0 IGO.**

Verified definition text was obtained for nine syndromes: acute watery diarrhoea, acute
bloody diarrhoea, acute respiratory infection / SARI, acute jaundice syndrome, acute
haemorrhagic fever syndrome, suspected measles, suspected meningitis, acute flaccid
paralysis, and malaria.

> The 2012 EWARN guide (WHO/HSE/GAR/DCE/2012.1) is **not** a safe source — it predates
> WHO's routine CC licensing and carries no visible grant. Do not cite it as freely usable.

### 4.2 The non-commercial clause is a real constraint

WHO's licence permits copying and adaptation **for non-commercial purposes**, and WHO's
copyright page states that *"Permission is required for commercial uses and licensing of
WHO materials."* Our pitch explicitly names paying customers (mining, rigs, cruise lines),
so we cannot treat the NC clause as inapplicable.

**Position, in order:**

1. **Paraphrase into our own schema.** Clinical criteria — "three or more loose stools in
   24 hours" — are closer to facts and standards than to protected expression. We express
   them in our own fields (`code`, `title`, `definition`, `criteria_json`, `source_note`)
   rather than reproducing WHO's text.
2. **Carry the adaptation disclaimer**, verbatim as WHO requires:

   > *"This is an adaptation of an original work '[Title]. Geneva: World Health
   > Organization (WHO); [Year]. Licence: CC BY-NC-SA 3.0 IGO'. This adaptation was not
   > created by WHO. WHO is not responsible for the content or accuracy of this adaptation.
   > The original edition shall be the binding and authentic edition."*

3. **Never use the WHO logo**, and never phrase anything so as to imply WHO endorsement.
   The licence prohibits both: *"there should be no suggestion that WHO endorses any
   specific organization, products or services. The use of the WHO logo is not permitted."*
4. **Say so in the writeup.** Suggested wording: *"Syndrome codes are operationalized using
   clinical criteria derived from WHO EWARN syndromic surveillance standards
   (WHO/UXH/EPR/2023.1). Case criteria are expressed in our own schema; see adaptation
   disclaimer."*

### 4.3 Coding system: our own codes, with a documented mapping

- **ICD-11** is CC BY-**ND** 3.0 IGO. Commercial use is permitted, but *"no adaptation of
  the codes"* — mapping WHO syndromes into our own compressed code set is arguably
  adaptation, so adopting ICD-11 codes wholesale creates the exact friction we are trying
  to avoid.
- **SNOMED CT** requires an affiliate licence; free in member countries but needs
  registration with a National Release Center. Not a one-day step.
- **Decision:** internal codes (`acute_watery_diarrhoea`, `sari`, …) with the WHO source
  recorded per row in `case_definitions.source_note`. This preserves the interoperability
  story without the licence entanglement.

### 4.4 The TB / CAD citation we already use

WHO has recommended computer-aided detection for TB screening since 2021, with the explicit
requirement that thresholds be **calibrated locally** to population and setting. This is the
basis for our claim that alert thresholds are calibrated per setting rather than universal.

**Cite:** WHO consolidated guidelines on tuberculosis. Module 2: Screening — systematic
screening for tuberculosis disease. Geneva: World Health Organization; 2021.
Recommendation 14. ISBN 978-92-4-002267-6.

---

## 5. What each dataset is actually for

| Need | Asset | Why this one |
| --- | --- | --- |
| Demo films, obviously abnormal on a projector | COVID-19 Radiography DB | Highest visual legibility per GB; CC BY 4.0 |
| Demo films with a box to point at | TBX11K (active TB subset) | Bounding boxes; CC BY 4.0 |
| Score calibration sanity check | TBX11K 4-level labels | Only ordinal severity available under a clean licence |
| Bulk testing volume | NIH CXR14 Kaggle sample | ~5,600 images, unrestricted licence |
| ASR accent validation | African Accented French | Matches the clinician profile in the story |
| ASR quality baseline | MediaSpeech FR | Clean broadcast audio, CC BY 4.0 |
| Translation scoring | CoVoST 2 fr→en | Reference English translations — **offline only, NC** |
| Consultation audio for the demo | **Self-recorded French** | No public clinical audio exists; we own it |
| Note-writing style reference | Indiana Open-i / PriMock57 | Structure only — **offline only, NC** |
| Syndrome definitions | WHO 2023 EWAR guide | The standard we are automating |

---

## 6. Rejected datasets

| Dataset | Fails | Reason |
| --- | --- | --- |
| **MIMIC-CXR-JPG** | C2, C3, C4 | PhysioNet credentialing needs CITI training and review — days. DUA clause 3: *"The LICENSEE will not share access to PhysioNet restricted data with anyone else."* Clause 6 limits use to *"the sole purpose of lawful use in scientific research and no other."* A public video violates both. Also ~300 GB. |
| **VinDr-CXR** | C1, C2 | DICOM only — *"All images are in DICOM format"* — and PhysioNet credentialed access. Double disqualification. |
| **PadChest** | C3, C4 | ~1.02 TB. RUA clause 5: *"YOU MAY NOT DISTRIBUTE, PUBLISH, OR REPRODUCE A COPY of any portion or all of the PadChest Dataset to others without specific prior written permission."* Showing images in a posted video is reproducing a copy. |
| **CheXpert / CheXpert-v1.0-small** | C4 | Stanford Research Use Agreement: non-commercial research only, no redistribution to third parties. Fast to obtain, but the licence is wrong for a commercially-pitched public demo. |
| **RSNA Pneumonia Detection Challenge** | C1 | Official release is DICOM. Community PNG conversions exist but lack clear provenance, which is worse than useless for a clearance table. |
| **Brixia severity scores** | C1, C4 | DICOM only; research use with ethical approval required. |
| **MuST-C** (speech) | C4 | FBK research-only licence, explicitly non-commercial, no public redistribution. |
| **MGB-2 / MGB-3** (Arabic speech) | C2, C4 | Apply-only access via arabicspeech.org; QCRI research licence. Moot once French is chosen. |
| **Casablanca** (Arabic dialects) | C4 | CC BY-NC-ND. Moot once French is chosen. |

The rejections matter as much as the selections: they are the record that a licence review
actually happened, which is what Rule 06 asks us to demonstrate.

---

## 7. Publicly postable vs offline-validation only

**Read this before putting anything on camera.** The demo video may be published, and the
project is pitched commercially. Non-commercial material must not appear in it.

### ✅ May appear in the recorded video, deck, or any public artifact

| Asset | Licence |
| --- | --- |
| Self-recorded consultation audio | We own it |
| TBX11K | CC BY 4.0 |
| COVID-19 Radiography Database | CC BY 4.0 |
| NIH ChestX-ray14 | "No restrictions" + attribution |
| MediaSpeech FR | CC BY 4.0 |
| African Accented French | Apache 2.0 |
| Common Voice FR | CC0 1.0 |
| FLEURS | CC BY 4.0 |

### ⛔ Offline validation only — never shown, never in a public artifact

| Asset | Licence | Restriction |
| --- | --- | --- |
| CoVoST 2 | CC BY-NC 4.0 | Non-commercial |
| mTEDx | CC BY-NC-ND 4.0 | Non-commercial + no derivatives |
| Indiana Open-i reports | CC BY-NC-ND 4.0 | Non-commercial + no derivatives |
| PriMock57 | Babylon research licence | Template/structure only; do not redistribute audio |
| NLM Montgomery / Shenzhen | No explicit grant | Ambiguous — prefer to avoid on camera (§2.4) |

---

## 8. USB manifest

Nothing here is downloaded yet. Sizes marked ✔︎ were measured by HTTP HEAD; the rest are
as published.

| # | Asset | Size | Licence | Needed for |
| --- | --- | --- | --- | --- |
| 1 | COVID-19 Radiography Database | ~1 GB | CC BY 4.0 | Demo films |
| 2 | TBX11K | ~3.3–4 GB | CC BY 4.0 | Demo films + score calibration |
| 3 | NIH CXR14 Kaggle sample | ~1 GB | No restrictions | Testing volume |
| 4 | MediaSpeech FR | 637 MB | CC BY 4.0 | ASR validation |
| 5 | African Accented French | 1.8 GB | Apache 2.0 | Accent validation |
| 6 | Common Voice FR test split | ~200–500 MB | CC0 | Fallback |
| 7 | CoVoST 2 fr→en test split | ~240 MB | CC BY-NC | Translation scoring (offline) |
| 8 | Whisper large-v3 weights | ~2.9–3.1 GB | Model licence | ASR + translation |
| 9 | MedGemma 4B (`medgemma:4b`) | **3.3 GB** ✔︎ | Model licence | Film scoring |
| | **Total** | **~15 GB** | | Comfortable on a 32 GB drive |

Optional extras if drive space allows: NLM Shenzhen (3.6 GB ✔︎), NLM Montgomery
(588 MB ✔︎), Indiana Open-i reports (228 MB ✔︎), NIH CXR14 full (42–45 GB — needs 64 GB+).

> **Correction to `PRD.md` §Model memory budget:** `medgemma:4b` is **3.3 GB** in the Ollama
> registry, not the ~9 GB budgeted. That frees roughly 5.7 GB toward the Nemotron variant
> decision (`DECISIONS.md` Q2). `medgemma:27b` (17 GB) and `medgemma1.5:4b` also exist.

---

## 9. Attribution

Copy-paste ready for the writeup and deck credits.

**Images**

- Liu et al. "Rethinking Computer-Aided Tuberculosis Diagnosis." *CVPR* 2020. TBX11K,
  Media Computing Lab, Nankai University. Licensed CC BY 4.0. https://mmcheng.net/tb/
- Rahman T. et al. "Exploring the Effect of Image Enhancement Techniques on COVID-19
  Detection using Chest X-ray Images." *Computers in Biology and Medicine*, 2021.
  COVID-19 Radiography Database. Licensed CC BY 4.0.
- Wang X. et al. "ChestX-Ray8: Hospital-Scale Chest X-Ray Database and Benchmarks on
  Weakly-Supervised Classification and Localization of Common Thorax Diseases." *CVPR*
  2017. DOI 10.1109/CVPR.2017.369. Data provider: NIH Clinical Center.
  https://nihcc.app.box.com/v/ChestXray-NIHCC
- *(if used)* Jaeger S. et al. "Two public chest X-ray datasets for computer-aided screening
  of pulmonary diseases." *Quant Imaging Med Surg* 2014. PMCID PMC4256233. Courtesy of the
  National Library of Medicine.

**Speech**

- Kolobov R. et al. MediaSpeech. Licensed CC BY 4.0. https://openslr.org/108/
- African Accented French, OpenSLR SLR57. Licensed Apache 2.0. https://openslr.org/57/
- Mozilla Common Voice. Licensed CC0 1.0.

**Case definitions**

- Early Warning Alert and Response in Emergencies: an operational guide. Geneva: World
  Health Organization; 2023 (WHO/UXH/EPR/2023.1). Licence: CC BY-NC-SA 3.0 IGO.
- WHO consolidated guidelines on tuberculosis. Module 2: Screening — systematic screening
  for tuberculosis disease. Geneva: World Health Organization; 2021. Recommendation 14.
  ISBN 978-92-4-002267-6.

Plus the WHO adaptation disclaimer from §4.2, reproduced verbatim.

---

## 10. Open items

| # | Item | Action |
| --- | --- | --- |
| 1 | NLM Montgomery/Shenzhen have no explicit licence grant, and the 2014 paper asks recipients not to share the data (§2.4). | Prefer TBX11K / COVID DB on camera. If they are used, cite and do not re-host. |
| 2 | The WHO case-definition table was read from a **staging** URL (`docs.staging.ewars.ws`). A staging host is not a citable source. | Cite the 2023 operational guide document (WHO/UXH/EPR/2023.1) itself, not the URL. Confirm the definitions against the published PDF before submission. |
| 3 | Model weight licences (Whisper large-v3, MedGemma, Nemotron, embeddings) are not yet individually confirmed. | Confirm each and record it in `DECISIONS.md` §Third-party content before the writeup. |
| 4 | Kaggle-hosted assets need an account. | Ensure someone has credentials **before** travelling — there is no usable Wi-Fi at the venue. |
| 5 | Sizes marked ✔︎ were measured; the rest are as published and unverified. | Verify on download; correct the manifest in §8 in the same commit. |

---

## Related

`PRD.md` §8 Demo data requirements · `ARCHITECTURE.md` §3 SQLite schema (the
`case_definitions` table this feeds) · `DECISIONS.md` §Third-party content ·
`AGENTS.md` §Non-negotiable invariants.
