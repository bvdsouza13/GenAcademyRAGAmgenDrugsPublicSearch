import streamlit as st
from ui.common import action, navigate


def render(service,corpus,active):
    st.subheader('Entire source library')
    status = service.library_status()
    a,b,c = st.columns(3)
    a.metric('Local source PDFs',status.get('source_documents',0))
    b.metric('Searchable documents',status.get('searchable_documents',0))
    c.metric('Verified Pinecone records',status.get('record_count',0))
    st.caption('PDFs and the consolidated XML stay local. A build sends extracted chunks and metadata to Pinecone.')
    with st.expander('Import options'):
        replace_existing=st.checkbox('Replace matching filenames',help='Use only when intentionally replacing an existing source. Prior library snapshots remain available.')
    uploads = st.file_uploader('Add source PDFs',type=['pdf'],accept_multiple_files=True,key='library_uploads')
    if st.button('Import PDFs',disabled=not uploads):
        from amgen_explorer.source_import import SourceUpload
        ok,result = action('Import PDFs',lambda:service.import_documents([SourceUpload(filename=f.name,payload=f.getvalue(),replace_existing=replace_existing) for f in uploads]))
        if ok:
            st.success(f"Imported {len(result.get('imported',[]))} PDFs; {len(result.get('duplicates',[]))} duplicates retained as existing sources.")
    missing=status.get('missing_sources',[])
    if missing:
        st.error('Missing registered source PDFs. Restore these files before rebuilding:')
        for name in missing: st.text(name)
    inventory=service.inventory()
    if inventory:
        st.dataframe(inventory,hide_index=True,width='stretch')
    else:
        st.info('No local source PDFs are available. Add the complete source collection before building.')
    label = 'Retry entire library build' if st.session_state.get('library_build_failed') else 'Build / update entire library'
    if st.button(label,type='primary',disabled=not inventory):
        with st.status('Reading documents → Preparing text → Uploading → Checking search',expanded=True) as progress:
            def update(report):
                phase=report.get('stage') or report.get('phase') or report.get('status','Preparing text')
                st.caption(f"{phase} · {report.get('succeeded',0):,} of {report.get('record_count',0):,} records processed")
            ok,result=action('Build entire library',lambda:service.build_library(service.latest_library_settings(),activate=True,on_progress=update))
            success=ok and result and result.get('status') in {'verified','active','published','ready','complete','searchable'}
            st.session_state['library_build_failed']=not success
            if success:
                st.session_state['library_build_result']=result
                progress.update(label='Ready · Entire library is searchable',state='complete',expanded=False)
                st.success('The entire verified library is ready to search.')
            else:
                progress.update(label='Build incomplete · Previous searchable library preserved',state='error')
                if ok:
                    st.error('The build has not completed verification. The previous searchable library remains available. Retry the full build.')
    result=st.session_state.get('library_build_result')
    if result:
        st.caption(f"Last completed build: {result.get('run_id','unknown')} · {result.get('record_count',0):,} verified records")
    if active or result:
        st.button('Search the library',on_click=navigate,args=('Search & Learn',))
    st.caption('Automatic source verification establishes extraction provenance. It does not establish clinical accuracy or human review.')
    with st.expander('Details'):
        # Only allow-listed local build metadata is shown. Config/secrets are never rendered.
        st.json({key:status.get(key) for key in ('source_documents','source_products','searchable_documents','searchable_products','record_count','is_full_library')})
        if result:
            st.json({key:result.get(key) for key in ('run_id','namespace','status','coverage','record_count','document_ids','product_ids') if key in result})
