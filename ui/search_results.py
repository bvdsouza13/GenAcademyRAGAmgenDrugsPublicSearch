"""Cited global discovery results pinned to one immutable library version."""
from collections import OrderedDict
import streamlit as st
from ui.common import navigate, source_text, source_view, source_variant


def render(service, results, active=None):
    run_id = results.run_id
    st.subheader('Matching source passages')
    st.caption(f'Library version: {run_id} · Results for “{results.query}”')
    if active and active.get('run_id') != run_id:
        st.info('These results belong to an earlier library version. Search again to use the latest library; source actions keep this version.')
    if results.degraded:
        st.warning('Local text search is available. Semantic search is temporarily unavailable.')
    for warning in results.warnings:
        # Search warnings are locally controlled status text, never provider payloads.
        st.warning(str(warning))
    grouped = OrderedDict()
    for hit in results.hits:
        meta = hit.get('metadata', {})
        grouped.setdefault((meta.get('product_id'),meta.get('document_id')), []).append(hit)
    if not grouped:
        st.info('No matching passages were found. Try another word or remove optional filters.')
    for (product_id,document_id), hits in grouped.items():
        first = hits[0]
        meta = first.get('metadata', {})
        filename = first.get('filename') or meta.get('filename','Source PDF')
        name = first.get('product_name') or meta.get('product_name','Medicine')
        with st.container(border=True):
            st.markdown(f'**{name} · {filename}**')
            revision = first.get('revision') or meta.get('label_revision') or 'not identified'
            variant = source_variant(filename, first.get('variant_hint') or meta.get('source_variant_hint'))
            st.caption(f'Revision: {revision}' + (f' · {variant}' if variant else ''))
            key = f'{run_id}_{document_id}'
            st.button('Ask about this source', key=f'ask_{key}', on_click=navigate, args=('Search & Learn',product_id,document_id,run_id,results.query))
            def show_passage(hit):
                detail = hit.get('metadata', {})
                st.caption(f"{detail.get('section_title','Source passage')} · Physical PDF page {detail.get('page_start','unknown')}")
                source_text(hit.get('text',''))
                if st.button(f"View PDF page {detail.get('page_start','unknown')}",key=f"view_passage_{key}_{hit.get('id','')}"):
                    st.session_state[f'show_source_{key}']=True
                    st.session_state[f'source_page_{key}']=detail.get('page_start')
                if detail.get('layout_limitations') or detail.get('extraction_warnings') or detail.get('extraction_limitations'):
                    st.caption('Layout limitation: inspect the original PDF before interpreting tables or figures.')
            for hit in hits[:3]:
                show_passage(hit)
            if len(hits)>3:
                with st.expander(f'Show {len(hits)-3} more matching passages'):
                    for hit in hits[3:]: show_passage(hit)
            if st.button('View source', key=f'view_{key}'):
                st.session_state[f'show_source_{key}'] = True
            if st.session_state.get(f'show_source_{key}'):
                source_view(service,document_id,filename,key,page=st.session_state.get(f'source_page_{key}',meta.get('page_start')),xml_hash=results.xml_hash)
