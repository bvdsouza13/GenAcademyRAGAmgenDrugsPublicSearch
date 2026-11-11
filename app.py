"""Run locally with: streamlit run app.py."""
import streamlit as st
from amgen_explorer.service import ExplorerService
from ui.common import style, sidebar
from ui import demo, explore, learn, sources, admin

st.set_page_config(page_title='Amgen Medicine Explorer',page_icon='🔬',layout='wide',initial_sidebar_state='expanded')
style()
if not st.session_state.get('_demo_query_handled'):
    if st.query_params.get('demo') == '1':
        st.session_state['nav'] = 'Demo tour'
    st.session_state['_demo_query_handled'] = True
legacy = st.query_params.get('legacy') == '1'
page = st.session_state.get('nav', 'Explore medicines' if legacy else 'Search & Learn')
if page == 'Demo tour':
    # A portable tour must not open databases or require service configuration.
    sidebar(None, demo_mode=True)
    demo.render(None, None, None)
else:
    try:
        service = ExplorerService()
        active = service.active()
        try:
            corpus = service.corpus()
        except Exception:
            if legacy or not active:
                raise
            corpus = service.library_corpus(active['run_id'])
            st.warning('The working XML could not be opened. Search and existing conversations continue using the verified library snapshot. Repair or update local sources in Admin.')
    except Exception:
        st.error('The local library could not be opened. Check the configuration file and local source paths, then reload.')
        st.stop()
    sidebar(active)
    if page == 'Search & Learn':
        if st.session_state.get('learning_view'):
            learn.render(service,corpus,active)
        else:
            explore.render(service,corpus,active)
    elif page == 'Admin':
        admin.render(service,corpus,active)
    elif page == 'Explore medicines':
        explore.render_catalog(service,corpus,active)
    elif page == 'Learn with chat':
        learn.render(service,corpus,active)
    elif page == 'My learning':
        learn.progress_view(service,corpus,active)
    else:
        sources.render(service,corpus,active)
