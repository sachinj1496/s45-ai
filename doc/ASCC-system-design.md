# Questions and Doubts I had and what I did to clarify them.
First I started with questions: 
what is Authorised share capital change ?
what is DRHP documents ?
what is PAS-3?
what is SH-7?
After knowing them, what they are I opened the google doc shared with me. I searched what each doc meant and what its for. At the start reading the doc didn't made any sense. So I fed the doc to ChatGPT to make sense out of it. I read some starting lines of the doc and some doc to the half length, and they made some sense.

I read the problem statement again and again, to understand what needs to be implemented. Also took the help of ChatGPT in designing and understanding the problem. And reading 2-3 times the problem statement and what chatGPT suggested, the problem had break down to simpler point, I have to read different types of document and compile them to form some kind of a table. That's it.

# System Design: Authorised Share Capital Change Reconstruction

## 1. Problem Understanding

The goal of this system is to reconstruct how a company’s **Authorised Share Capital** has changed over time using various compliance documents such as SH-7, resolutions, MOA, and PAS-3.

Authorised share capital represents the **maximum capital a company is allowed to issue**, and any change to it is formally recorded through SH-7 filings.

However, the challenge is that:

* Information is spread across multiple documents
* Not all documents have equal authority
* Some documents contain draft or misleading values
* There are dependencies across documents
---

## 2. Documents and Their Roles

From the dataset, we identified the following document types:

### Primary Document

* **SH-7**

  * This is the official filing with ROC
  * It contains old and new authorised capital
  * This acts as the **source of truth**

---

### Supporting Documents (Attachments)

These can be grouped into 3 categories:

1. **Resolution Documents**

   * Board Resolution (proposal)
   * EGM Resolution (approval)

2. **Altered MOA**

   * Shows final authorised capital after change

3. **EGM Notice + Explanatory Statement**

   * Contains intent and reasoning
   * May contain draft values (not always reliable)

---

### Secondary Documents

* **PAS-3 (Return of Allotment)** 

  * Tracks shares actually allotted
  * Example: 960 shares allotted on 15/05/2019 
  * Shows authorised capital = ₹3,00,000 after allotment 

Important:
PAS-3 does NOT change authorised capital, but helps in:

* validation
* understanding capital usage

---

## 3. Key Challenges

1. **Different authority levels**

   * SH-7 is most reliable
   * EGM Notice is least reliable

2. **Conflicting values**

   * Draft vs final values in same document

3. **Unstructured text**

   * Legal documents are not consistent

4. **Cross-document dependency**

   * One document alone is not sufficient

5. **Temporal reconstruction**

   * Need to build a timeline

---

## 4. System Architecture

The system is designed as a pipeline:

```
Document Ingestion
        ↓
Document Classification
        ↓
Information Extraction
        ↓
Validation Layer
        ↓
Timeline Builder
        ↓
Final Output
```

---

## 5. Document Classification

### AI-based

Unknown documents are ambiguous, especially:

* EGM Notice vs EGM Resolution

Each document is classified into:

* type (SH7, MOA, etc.)
* authority level (high/medium/low)
* event type (capital change, allotment, proposal)

---

## 6. Information Extraction

Extraction is done using an AI-assisted approach.

Each extracted value is stored with:

* source document
* supporting documents

---

## 7. Validation Layer

This is the most important part of the system.

### Validation rules:

1. **SH-7 vs MOA**

   * Final capital must match

2. **SH-7 vs Resolution**

   * Change must be supported by resolutions

3. **Draft filtering**

   * Ignore values from explanatory sections

4. **PAS-3 validation**

   * Issued capital ≤ authorised capital
   * Example from PAS-3:

     * authorised = ₹3,00,000
     * issued ≈ ₹1,93,210 

5. **Chronology check**

   * Previous new capital = next old capital

If any rule fails:

* mark entry as warning or error

---

## 8. Timeline Reconstruction

All SH-7 documents are sorted by date.

For each document:

* determine change type (increase/decrease)
* compute delta
* attach supporting documents
* egm/agm events

Final output looks like:

```
2018 → ₹3,00,000 (increase)
2020 → ₹10,00,000 (increase)
2022 → ₹20,00,000 (increase)
2023 → ₹15,00,000 (decrease)
```

---

## 9. Traceability

Every value in the output must be traceable.

Example:

* ₹3,00,000

  * source: SH-7
  * verified by: MOA, Resolution

This ensures:

* no hallucination
* full auditability

---

## 10. Role of PAS-3

PAS-3 is not used to compute capital changes, but:

1. Validates issued capital
2. Detects inconsistencies
3. Links events (capital increase → share allotment)

Example:

* 960 shares allotted @ ₹10 each 

---

## 11. Dataset Design

We created 4 SH-7 document groups.

Each group includes:

* SH-7
* Board Resolution
* EGM Resolution
* MOA
* EGM Notice

Additionally:

* PAS-3 documents for some events

Edge cases included:

* conflicting values
* missing attachments
* capital reduction
* PAS-3 violations

---

## 12. Final Thoughts

This system is not just about extracting data.

It is about:

* understanding document hierarchy
* reasoning across documents
* validating correctness
* reconstructing a reliable financial timeline

The use of AI helps handle unstructured data, but correctness is ensured through:

* validation rules
* authority hierarchy
* traceability

This combination makes the system robust and suitable for real-world compliance use cases.

---

