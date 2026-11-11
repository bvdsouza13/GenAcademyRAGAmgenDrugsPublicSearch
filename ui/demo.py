"""A portable three-minute source-to-learning tour. All state is session-local."""
import streamlit as st

from amgen_explorer.demo import DemoUnavailable, load_example
from ui.common import hero, navigate, source_text

STEPS = ('Bulk library setup', 'Global content search', 'Chunk comparison', 'Cited lesson', 'Knowledge check')
STEP_KEY = 'demo_step'


def _move(step):
    st.session_state[STEP_KEY] = max(0, min(len(STEPS) - 1, step))


def _restart():
    for key in list(st.session_state):
        if key.startswith('demo_'):
            del st.session_state[key]
    st.session_state[STEP_KEY] = 0


def _exit():
    st.query_params.pop('demo', None)
    navigate('Explore medicines' if st.query_params.get('legacy') == '1' else 'Search & Learn')


def _reference(example, *, show_quote=True):
    ref = example.citation
    st.caption(f"[1] {ref['filename']} · physical PDF page {ref['page_start']} · 12.1 Mechanism of Action")
    if show_quote:
        st.markdown('**Exact supporting quote**')
        source_text(ref['supporting_quote'])
    with st.expander('Inspect source passage and provenance'):
        source_text(ref['source_text'])
        st.json({'document_id': ref['document_id'], 'document_sha256': ref['document_sha256'],
                 'xml_sha256': ref['xml_hash'], 'source_spans': example.prepared['source_spans']})


def render(service, corpus, active):
    """Same page contract as the app; deliberately no methods on service called."""
    hero('From source to understanding.',
         'Explore bulk setup, content search, a controlled chunk comparison, a cited lesson, and a quiz.',
         'THE THREE-MINUTE GUIDED DEMO')
    st.info('Prepared source-backed example · No live provider result is generated in this tour. Navigation reads included local files only.')
    step = st.session_state.get(STEP_KEY, 0)
    if type(step) is not int or not 0 <= step < len(STEPS):
        step = 0
        st.session_state[STEP_KEY] = step
    st.progress((step + 1) / len(STEPS), text=f'Step {step + 1} of {len(STEPS)} · {STEPS[step]}')
    try:
        example = load_example()
    except DemoUnavailable as error:
        st.warning(str(error))
        a, b = st.columns(2)
        a.button('Restart tour', on_click=_restart, key='demo_restart_missing')
        b.button('Exit demo', on_click=_exit, key='demo_exit_missing')
        return

    main, aside = st.columns([2.2, 1], gap='large')
    with aside:
        with st.container(border=True):
            st.caption('ONE SOURCE. ONE DOCUMENT SCOPE.')
            st.subheader('REPATHA')
            st.write('Evolocumab · Mechanism of Action')
            st.caption('Example document: presentation not made with natural rubber latex.')
            st.write('Physical PDF page 10')
            st.caption('The PDF bytes, XML hash, exact passage and page spans are checked locally on each step.')
            st.download_button('Download example PDF', example.pdf_bytes, file_name=example.citation['filename'],
                               mime='application/pdf', key='demo_pdf_download')
        st.caption('Tour state stays in this session. Prepared content does not record lesson completion or approve sources. No live library is built or activated here.')
    with main:
        if step == 0:
            st.subheader('1 · Build the entire source library')
            st.markdown('In **Admin → Library**, add all source PDFs and select **Build / update entire library**. One build verifies the complete inventory, prepares every readable text interval and enables global search without individual passage decisions.')
            st.write('Reading documents → Preparing text → Uploading → Checking search → Ready')
            st.caption('PDFs and XML stay local. Extracted chunks and metadata go to Pinecone only during a real build. Automatic source verification establishes provenance, not clinical accuracy.')
            st.write('This prepared tour follows one source: section 12.1 on physical page 10. Its original page is shown below.')
            st.image(example.page_image(), caption='Included source PDF · physical page 10', width='stretch')
        elif step == 1:
            st.subheader('2 · Preserve sources and search their content')
            st.markdown('Use **Search all medicine information** to discover body text across the library. A medicine selection is optional. A content query such as **PCSK9** can find this source without naming REPATHA.')
            st.caption('PREPARED SEARCH EXAMPLE · No search provider called')
            st.markdown(f"**REPATHA · {example.citation['filename']} · 12.1 Mechanism of Action**")
            source_text(example.citation['supporting_quote'])
            st.write('View source opens the original PDF. Ask about this source starts a source-scoped conversation and carries the result’s library version; it waits for you to submit a question.')
            st.write('The canonical XML preserves document identity, physical page and exact character offsets for that citation.')
            st.caption('Actual section from XML/AmgenProducts.xml · local extraction format')
            st.code(example.canonical_xml, language='xml', wrap_lines=True)
            st.caption('Structural validation and exact text checks preserve provenance; they do not establish clinical approval.')
        elif step == 2:
            st.subheader('3 · Keep context with each chunk')
            st.markdown('In **Admin → Chunk experiments**, adjust **Chunk size** and **Overlap**, then choose **Test settings**. A real test builds an isolated full-library candidate and compares both versions using identical sources, questions and evidence budgets.')
            left,right=st.columns(2)
            with left:
                st.markdown('**Current configuration**')
                st.write('Size 600 · Overlap 80')
                st.caption('Not measured in this prepared tour: recall, quote coverage, latency and provider usage.')
            with right:
                st.markdown('**Example draft configuration**')
                st.write('Size 900 · Overlap 80')
                st.caption('Not measured in this prepared tour. A larger size does not demonstrate improvement.')
            st.write('Use this configuration activates a successfully tested full library. Reset to defaults changes only draft controls; Revert restores the previous full-library version. Every source remains in scope.')
            st.caption('The exact source-backed passage below illustrates preserved provenance. No candidate was built and no evaluation ran for this tour.')
            st.code(example.chunk_text, language=None, wrap_lines=True)
            st.caption(f'{len(example.chunk_text.encode("utf-8")) + 8} · UTF-8 byte upper bound + 8 reserve, not an exact model token count')
            _reference(example, show_quote=False)
        elif step == 3:
            st.subheader('4 · Read an explanation with its evidence')
            st.caption('PREPARED LESSON · SAVED SOURCE-BACKED EXAMPLE')
            st.markdown(f"**{example.prepared['question']}**")
            with st.container(border=True):
                st.write(example.prepared['answer'])
            _reference(example)
            st.caption('The [1] marker points to the supporting passage above. The saved example is shown as prepared; no search or generation runs here.')
        else:
            st.subheader('5 · Check what the passage says')
            st.caption('PREPARED QUIZ · SESSION-ONLY PRACTICE')
            quiz = example.prepared['quiz']
            st.markdown(f"**{quiz['question']}**")
            # The widget key is cleaned up when another tour step is shown.
            if 'demo_answer' not in st.session_state:
                st.session_state['demo_answer'] = st.session_state.get('demo_selected_answer')
            answer = st.radio('Your answer', range(len(quiz['choices'])),
                              format_func=lambda i: quiz['choices'][i], index=None, key='demo_answer',
                              on_change=lambda: st.session_state.pop('demo_checked', None))
            st.session_state['demo_selected_answer'] = answer
            if st.button('Check answer', disabled=answer is None, key='demo_check'):
                st.session_state['demo_checked'] = True
            if st.session_state.get('demo_checked'):
                if answer == quiz['correct_index']:
                    st.success('Correct · you found the target named in the source.')
                else:
                    st.info(f"Look again at the supporting quote: {quiz['choices'][quiz['correct_index']]}")
                st.write(quiz['rationale'])
                _reference(example)
            st.write('You have followed the complete path: bulk setup → global search → controlled chunk test → cited explanation → knowledge check.')
    st.divider()
    back, forward, restart, leave = st.columns(4)
    back.button('← Back', disabled=step == 0, on_click=_move, args=(step - 1,), key='demo_back', width='stretch')
    forward.button('Next →', disabled=step == len(STEPS) - 1, on_click=_move, args=(step + 1,), type='primary', key='demo_next', width='stretch')
    restart.button('Restart tour', on_click=_restart, key='demo_restart', width='stretch')
    leave.button('Exit demo', on_click=_exit, key='demo_exit', width='stretch')
    st.caption('Educational prototype based on included prescribing information. Personal treatment questions belong with your healthcare professional.')
