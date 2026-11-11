# Three-minute bulk-library and learning demo

```bash
.venv-corpus/bin/python -m streamlit run app.py
```

Open **http://127.0.0.1:8501/?demo=1** or select **Demo tour**. The tour needs the included source files and installed dependencies, with no API keys, published manifest, review database or cloud index.

Follow five stops using **Next →** and **← Back**:

1. **Bulk library setup** explains the one-action Admin build, its complete-inventory checks, source-verification policy and local/provider boundary. It shows the included Repatha PDF's physical page 10.
2. **Global content search** illustrates a body-text query such as `PCSK9`, its exact supporting source and canonical XML. No medicine selection is required for real discovery; source teaching keeps one selected document and library version.
3. **Chunk comparison** contrasts current 600/80 controls with an example 900/80 draft. Recall, quote coverage, latency and usage are explicitly **not measured in this prepared tour**. The source-backed chunk illustrates exact provenance; no candidate or evaluation is built.
4. **Cited lesson** shows a saved source-backed answer and its supporting quote, with PDF/XML hashes and character spans available for inspection.
5. **Knowledge check** asks a prepared source-reading question, shows cited feedback and allows another attempt.

Allow about 30–40 seconds per stop. **Restart tour** clears only demo state. **Exit demo** returns to Search & Learn. Quiz state stays in the current session and does not count as live lesson completion.

## Prepared example boundary

Every stop is labeled prepared/offline. Navigation, source download and quiz feedback do not call providers, build XML, create databases, approve sources, activate a library or run retrieval evaluations. Setup/search/comparison screens explain the real workflow using the included source example. A larger example chunk size is not presented as an improvement.

The prepared mechanism source is:

- `Documents/repatha_not_made_with_natural_rubber_latex_prescribing_information.pdf`, physical page 10.
- `XML/AmgenProducts.xml`, document `doc-repatha-not-made-with-natural-rubber-latex-prescribing-information`, section 12.1 Mechanism of Action.
- `demos/repatha-mechanism.json`, saved answer, quote, exact spans and prepared quiz.

The loader checks XML/PDF hashes, source identity, exact page text and block/archive spans on each step. These checks establish local source integrity, not clinical approval or current labeling. A missing/changed source hides the prepared clinical content and explains how to restore the included bundle; restart retries verification without silently repairing files.

## Verification

```bash
.venv-corpus/bin/python -m pytest tests/test_demo.py tests/test_demo_navigation.py -q
```

The tests verify source integrity, reject altered/missing evidence and exercise navigation/quiz state under offline constraints. Actual release results are recorded in the [bulk-refactor release report](implementation/bulk-refactor-release-report.md), separately from this walkthrough. Historical demo descriptions based on PDF → XML → chunk alone are superseded by these five stops.
