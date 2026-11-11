from html import escape
import streamlit as st
from ui.common import hero, navigate


def render(service, corpus, active):
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
