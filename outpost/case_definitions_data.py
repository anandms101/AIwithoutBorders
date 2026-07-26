"""WHO syndromic case definitions, paraphrased into our own schema (D14).

WHO material is CC BY-NC-SA 3.0 IGO. The NC clause is a genuine risk given the
pitch names paying customers, so per ``docs/DECISIONS.md`` D14 we paraphrase the
clinical criteria — which are facts and standards — into our own fields, carry
the required adaptation disclaimer on every row, and use no WHO logo.

Codes are internal. ICD-11 is CC BY-ND (no adaptation of codes permitted) and
SNOMED CT needs an affiliate licence, so neither is embedded here.
"""

from __future__ import annotations

DISCLAIMER = (
    "Adapted from WHO Early Warning, Alert and Response System (EWARS) standard "
    "syndromic case definitions (WHO/UXH/EPR/2023.1). This is an adaptation by "
    "Outpost and is not endorsed by WHO. Thresholds are calibrated per setting."
)

# (code, title, definition)
CASE_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    (
        "acute_watery_diarrhoea",
        "Acute watery diarrhoea",
        "Three or more loose or watery stools in the past 24 hours, of less than "
        "14 days duration, without visible blood. Often with vomiting, rapid "
        "onset dehydration, sunken eyes, reduced skin turgor and intense thirst. "
        "Stools may be described as rice-water in appearance.",
    ),
    (
        "acute_bloody_diarrhoea",
        "Acute bloody diarrhoea",
        "Diarrhoea with visible blood in the stool. Often with abdominal cramps, "
        "fever, painful straining on defecation and dysentery-like presentation.",
    ),
    (
        "acute_respiratory_infection",
        "Acute respiratory infection",
        "Cough or difficulty breathing of recent onset, with or without fever. "
        "May include shortness of breath, fast or laboured breathing, chest "
        "indrawing, sore throat, runny nose or productive sputum.",
    ),
    (
        "acute_febrile_illness",
        "Acute febrile illness",
        "Fever of 38 degrees Celsius or higher, or a reported history of fever, "
        "of less than 14 days duration, without a localising source. Often with "
        "chills, sweats, headache, generalised body aches, joint pain, fatigue "
        "and malaise.",
    ),
    (
        "acute_jaundice_syndrome",
        "Acute jaundice syndrome",
        "Recent onset of yellowing of the skin or whites of the eyes. Often with "
        "dark urine, pale stools, loss of appetite, nausea, abdominal discomfort "
        "in the right upper region and profound fatigue.",
    ),
    (
        "acute_haemorrhagic_fever",
        "Acute haemorrhagic fever syndrome",
        "Acute fever of less than three weeks duration with any unexplained "
        "bleeding: bleeding gums, nosebleed, blood in vomit or stool, petechiae, "
        "purpura or bleeding into the skin. May include severe headache, muscle "
        "pain and prostration.",
    ),
    (
        "acute_neurological_syndrome",
        "Acute neurological syndrome",
        "Sudden onset of altered consciousness, confusion, seizures, neck "
        "stiffness or new focal weakness, with or without fever. May include "
        "severe headache, photophobia and vomiting.",
    ),
    (
        "acute_malnutrition",
        "Acute malnutrition",
        "Visible severe wasting, or bilateral pitting oedema of the feet, or a "
        "mid-upper arm circumference below the age-appropriate threshold. Often "
        "with lethargy, poor appetite and recurrent infection.",
    ),
    (
        "suspected_measles",
        "Fever with generalised rash",
        "Fever with a generalised maculopapular rash, together with cough, runny "
        "nose or red eyes. Rash typically begins on the face and spreads.",
    ),
    (
        "suspected_tuberculosis",
        "Prolonged cough syndrome",
        "Cough lasting two weeks or longer, with any of: coughing blood, fever, "
        "drenching night sweats, unintended weight loss or persistent chest pain.",
    ),
)


def all_codes() -> tuple[str, ...]:
    return tuple(code for code, _, _ in CASE_DEFINITIONS)
