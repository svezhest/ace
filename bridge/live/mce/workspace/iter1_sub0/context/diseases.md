# Disease Diagnosis Reference

Use this reference to diagnose a patient from their free-text symptoms.
The output label must be exactly one of the 22 conditions below.

## How to use this reference (read first)

1. Parse the patient's reported symptoms into keywords and body systems involved (skin, eyes, nose/sinuses, throat, chest/lungs/breathing, fever/immune, stomach/intestines/urine, joints/back, head/balance).
2. For each of the 22 conditions, compare the symptoms against its **core top symptoms** (the 2-4 most characteristic). Count matches (1 per core symptom clearly present).
3. Resolve overlaps and conflicts with the **Discrimination guidance** and **Conflict resolution** sections.
4. Return the condition with the highest total score. If multiple conditions are plausible, pick the single closest/most specific match and return only that label.
5. **Do not invent** symptoms, dosages, lab values, or quantitative thresholds. Judge only on which clinical pointers best and most specifically fit the presented symptoms. Informational only -- not a substitute for a licensed doctor.

---

## Condition profiles (core top symptoms)

### 1. drug reaction
Distinct timeline tied to starting or changing a medication -- reaction begins within hours to days. Core: **fever + body aches**, often with skin involvement (rash, itch, or mucosal/hourglass-mouth lesions). Repetitive exposure (a previously tolerated drug now causing a reaction) is a hallmark. Fever + body aches alone, without a drug story and without skin involvement, point toward a simple viral/fever illness.

### 2. allergy
Recurrent sneezing, red/sore/watery **itchy** eyes, and runny/stuffy nose -- classic hay-fever/allergic inflammation. Body itch/rash and sore throat can appear. An itchy-nose + itchy-eyes context is the key trigger (allergic rhinitis/atopy is common).

### 3. chicken pox
Very itchy skin **full of small blisters that turn into scabs**, with fever. Classic lesions are small clear fluid-filled vesicles, often in **wavefronts (a few generations of lesions at different stages)**, concentrated on **trunk and scalp**.

### 4. diabetes
**Ongoing thirst (polydipsia) + urgent/frequent urination (polyuria) + hunger**, together with fatigue and mood swings. Thirst + polyuria + fatigue is the signature.

### 5. psoriasis
Rough, dry skin with **scaly patches (often silvery flakes)**, skin itch, and skin coloring. Scalp/joint plaques can appear.

### 6. malaria
Fever is the core; the malaria-typical cluster is **fever + joint pain + photophobia (light sensitivity)**, sometimes with chills. It weights strongly when fever + joint pain + photophobia accompany fever.

### 7. pneumonia
**Chest infection + cough + sneezing + sore throat + difficulty breathing (with headache)** -- lung infection with clear airway involvement; mucus. Wheeze alongside lung infection and cough is a weak pneumonia sign.

### 8. impetigo
Skin sores with fluid-filled blisters, clustered scabs near **the mouth, around the nose, eyes**, and on arms/hands; oozing honey-coloured sores in a child with a face.

### 9. arthritis
**Joint pain + joint stiffness + joint swelling.** Chronic joint pain + stiffness + swelling, often with a family/autoimmune link for the inflammatory kind, or bone/joint pain in older age.

### 10. GERD
 Re flux/heartburn -- **chest pain or a rising fluid sensation + nausea**, and abdominal/lower-stomach sensation. Reflux points to GERD. (Anti-reflux drug/surgery hints are alignment notes, not symptoms.)

### 11. typhoid fever
**High fever + abdominal pain + loose bowel movements**, with prolonged fever, abdominal soreness/lump, nausea/belly pain, cough. Gastrointestinal involvement points toward typhoid.

### 12. hypertension (high blood pressure)
A **chronic, often asymptomatic high blood pressure** in adults, usually managed with lifestyle + medication.

### 13. bronchial asthma
**Chest tightness + wheeze + shortness of breath + wheezing difficulty**, often linked to allergy/allergic reactions, commonly with cough. Chronic lung narrowing with breath difficulty + chest tightness.

### 14. dengue fever
**Bone/muscle joint aches, nosebleed, blood in vomit/stool/urine, nausea, loss of appetite, backache/body pain, weakness**, often with fever + rash + conjunctivitis. Dengue weights strongly when fever + rash + conjunctivitis + itching.

### 15. syphilis
Stages spread together: **painless chancres on genitals years after first contact**, with dark rash on genitals, **body rash on palms/soles**, and **purulent urethral discharge/genital sores**.

### 16. cervical spondylosis
Age-related spine degeneration -- **neck pain and stiffness**, often with headache, muscle weakness, and lower back pain/dizziness.

### 17. jaundice
**Yellowness jaundice of eyes + dry/flaky skin** (itch) + dark urine and pale stool. Liver-biliary involvement points to jaundice.

### 18. common cold
Blocked/runny nose + sore throat + sneezing + cough -- usually a self-limiting viral respiratory infection.

### 19. peptic ulcer disease
**Stomach pain with meal-related pain + nausea**, and heartburn/acid/indigestion. Peptic ulcer with burning, often worsened by eating.

### 20. bacterial infection (sepsis / cellulitis / bacterial sores)
Bacterial infection -- skin sores / cellulitis / bacterial infection (cellulitis) -- pointer toward a bacterial infection.

### 21. varicose veins
Chronic venous insufficiency -- **thickened, twisted, bulging/red leg veins**, leg pain, heaviness/edema/swelling, worsening pain after standing. Chronic leg localization.

### 22. migraine
**Severe throbbing head pain + neck stiffness**, often with **nausea, blurred vision**, typically aggravated by motion, light, or sound.

---

## Discrimination guidance

- **Skin / sores / blisters:** only chase skin phrases that genuinely fit the disease. A nonspecific, patchy, itchy-red rash with a few small fluid-filled bumps inclines toward **chicken pox**; do not rescue smallpox from vague codes.
- **Respiratory triad (asthma vs pneumonia):** wheeze + shortness of breath / chest tightness / wheezing (asthma) => **bronchial asthma**. Chest infection + difficulty breathing + cough/sore throat => **pneumonia**.
- **Recurring sneezing + blocked/stuffy nose => allergy:** itchy eyes + itchy nose (atopy is common) => **allergy** (allergic rhinitis affects many people).
- **Allergic itch vs syphilis vs leg vein:** itching + vague skin => chase itch for **allergy**; bulging leg-vein clues => **varicose veins**.
- **Bacterial sores / granuloma => bacterial infection.**

---

## Conflict resolution

If more than one condition is congruent over most patient presentations, choose the single closest/most-specific match and return only that label.

---

## Disclaimer

Context is educational and based on symptom pointers only. It is not a substitute for an in-person licensed clinician. Do not fabricate dosages, lab values, or quantitative thresholds.