from html import escape
import streamlit as st
from ui.common import hero, navigate


def render_catalog(service, corpus, active):
    hero('Explore the science. Understand the medicine.', 'Learn about Amgen medicines, one clear explanation at a time.')
    search = st.text_input('Find a medicine',placeholder='Search by medicine or generic name…', key='catalog_search')
    heading, sort = st.columns([4,1])
    with heading:
        st.subheader('Start with a medicine')
    with sort:
        st.selectbox('Sort', ['A–Z','Z–A'], label_visibility='collapsed',key='catalog_sort')
    if not corpus or not corpus.products:
        st.info('No XML collection is available yet. Build the collection from your source PDFs in Manage sources.')
        inventory = service.inventory()
        st.caption(f'{len(inventory)} source files available locally')
        st.button('Set up the library',on_click=navigate,args=('Manage sources',),type='primary')
        return
    st.caption(f'{len(corpus.products)} medicines · {len(corpus.documents)} source documents · {sum(d.page_count for d in corpus.documents):,} pages')
    products = [p for p in corpus.products if search.strip().casefold() in (p.name+' '+p.generic_name).casefold()]
    products.sort(key=lambda p:p.name,reverse=st.session_state['catalog_sort']=='Z–A')
    searchable = set((active or {}).get('product_ids',[]))
    if not products:
        st.info('No medicines match that search. Try a brand or generic name from your library.')
    for start in range(0,len(products),3):
        for col,product in zip(st.columns(3),products[start:start+3]):
            with col:
                ready = product.id in searchable
                st.html(f'<div class="medicine"><h3>{escape(product.name)}</h3><p>{escape(product.generic_name or "Uses, how it works, and safety")}</p><span class="pill">{"Published sources" if ready else "Source review / publication needed"}</span></div>')
                st.button('Start learning →' if ready else 'Explore source →',key=f'learn_{product.id}',on_click=navigate,args=('Learn with chat',product.id),width='stretch')
    st.html('<div class="learning-note"><strong>New to medicines?</strong> Start with approved uses, how it works, and the safety sections of prescribing information.</div>')
    st.caption('Educational prototype · Counts reflect the current local XML collection.')


def render(service, corpus, active):
    """Discovery is global; provider work happens only on form submission."""
    from ui.common import action
    from ui.search_results import render as render_results
    hero('Search all medicine information', 'Find words, questions and cited passages across the searchable library.')
    if hasattr(service, 'library_status'):
        status = service.library_status()
    else:
        status = {'searchable_documents': len((active or {}).get('document_ids', [])), 'searchable_products': len((active or {}).get('product_ids', [])), 'source_documents': len(service.inventory())}
    global_ready=bool(active and status.get('is_full_library',active.get('full_library',False)))
    a, b = st.columns(2)
    a.metric('Searchable documents', status.get('searchable_documents', 0))
    b.metric('Searchable medicines', status.get('searchable_products', 0))
    st.caption(f"{status.get('source_documents', 0)} source PDFs present locally. Local files become searchable after a complete verified build.")
    with st.form('global_library_search'):
        query = st.text_input('Search all medicine information', placeholder='Try ACTIMMUNE, latex, or storage temperature', key='library_query')
        with st.expander('Optional search filters'):
            products = {p.id:p.name for p in corpus.products} if corpus else {}
            documents = {d.id:d.filename for d in corpus.documents} if corpus else {}
            product_ids = st.multiselect('Medicines', list(products), format_func=lambda x:products[x], key='search_products')
            document_ids = st.multiselect('Source documents', list(documents), format_func=lambda x:documents[x], key='search_documents')
        submitted = st.form_submit_button('Search', type='primary', disabled=not global_ready)
    if not global_ready:
        st.info('No verified full library is available for global search. Build the entire library in Admin.')
        st.button('Set up the library', on_click=navigate, args=('Admin',))
    if submitted and query.strip():
        ok, results = action('Search library', lambda:service.search_library(query.strip(), product_ids=product_ids or None, document_ids=document_ids or None))
        if ok:
            st.session_state['library_results'] = results
    elif submitted:
        st.info('Enter a word or question to search the source text.')
    results = st.session_state.get('library_results')
    if results:
        render_results(service, results, active)
    if corpus and corpus.products:
        with st.expander('Browse medicines'):
            products = sorted(corpus.products, key=lambda p:p.name)
            for product in products:
                st.markdown(f'**{product.name}** · {product.generic_name}')
                if global_ready and product.id in active.get('product_ids', []):
                    st.button('Start learning →', key=f'learn_{product.id}', on_click=navigate, args=('Search & Learn',product.id,None,active['run_id']))
