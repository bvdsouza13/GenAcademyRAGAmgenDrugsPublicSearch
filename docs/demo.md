# A three-minute source-to-learning demo

Run the app from the repository root:

```sh
.venv-corpus/bin/python -m streamlit run app.py
```

Open `http://127.0.0.1:8501/?demo=1`, or select **Demo tour** in the app. The tour works with the included source files and installed application dependencies. It needs no API keys, published manifest, existing review database, or cloud index.

Follow the five stops with **Next →** and **← Back**:

1. **Source PDF** — inspect physical page 10 of the included Repatha prescribing information for the presentation not made with natural rubber latex. Download the original PDF if useful.
2. **Canonical XML** — inspect the actual section in `XML/AmgenProducts.xml`, including its exact page evidence.
3. **Chunk preview** — see the source passage with its medicine/section context and original page spans.
4. **Cited lesson** — read a saved example answer and its exact supporting quote. Expand the provenance panel to inspect the PDF/XML hashes and character offsets.
5. **Knowledge check** — answer a prepared question, check it against the supporting passage, and try again.

Allow about 30–40 seconds per stop. **Restart tour** clears only the demo's step and quiz state. **Exit demo** opens Explore medicines. Tour state stays in the current session and does not count toward the main learning dashboard.

## What the example represents

Every step is labeled as a **prepared source-backed example**. The saved answer was derived from a previously exercised cited response. The fixture deliberately omits connection results, index hosts, namespaces, review decisions and local user paths. Entering, navigating, downloading, restarting and answering the demo quiz do not search, generate content, build XML, create a database, approve a source, or write to a cloud service.

The example question is about the target described in section 12.1. It is educational source inspection, not personal treatment guidance. Its supporting passage comes from:

- `Documents/repatha_not_made_with_natural_rubber_latex_prescribing_information.pdf` — physical page 10.
- `XML/AmgenProducts.xml` — document `doc-repatha-not-made-with-natural-rubber-latex-prescribing-information`, section `12.1 Mechanism of Action`.
- `demos/repatha-mechanism.json` — portable saved answer, quote, exact spans and prepared quiz.

The loader checks the pinned XML SHA-256, canonical XML structure and passage hashes, PDF identity and SHA-256, actual PDF page text, exact block/archive offsets, page scope and supporting quote on every step. It uses the included sources directly, independently of the application's active library. These checks establish local source integrity; they do not constitute clinical review or approval.

If a source is missing or changed, the prepared clinical content is hidden and the app explains that the included XML, PDF and fixture must be restored. Restart retries verification. The tour never repairs or rebuilds source files automatically.

## Verification

```sh
python -m pytest tests/test_demo.py -q
```

The tests validate the real included PDF/XML, reject altered quotes/spans and missing or changed files, and exercise all five screens, wrong/correct quiz feedback, Back, Restart and Exit through Streamlit AppTest. They run the tour against a minimal copied source bundle with no credentials and block service calls, HTTP requests, socket connections and SQLite connections.
