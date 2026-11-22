import streamlit as st
from datetime import datetime, timezone
from ui.common import action, navigate


def checked_at(value):
    try:
        return datetime.fromtimestamp(value, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    except (TypeError, ValueError, OSError, OverflowError):
        return 'not checked'


def health_controls(service,status,active):
    run_id=(active or {}).get('run_id')
    if hasattr(service,'verify_library'):
        if st.button('Verify stored library',disabled=not run_id):
            with st.spinner('Comparing expected records and checking every document…'):
                ok,report=action('Verify library',lambda:service.verify_library(run_id))
            if ok:st.session_state['library_health']=report
        report=st.session_state.get('library_health') or status.get('latest_verification')
        if report and report.get('run_id')==run_id:
            outcome=report.get('outcome')
            st.caption(f"Last checked: {checked_at(report.get('checked_at'))}")
            if outcome=='verified':st.success('Expected records verified · Every document is searchable.')
            elif outcome=='drift':
                st.warning(f"Stored library differs: {report.get('missing_count',0)} missing records; {report.get('mismatched_count',0)} changed records. Some documents may not yet be visible in search.")
                if st.button('Repair missing or changed records'):
                    with st.spinner('Restoring original records and checking the entire library…'):
                        ok,repaired=action('Repair library',lambda:service.verify_library(run_id,repair=True))
                    if ok:
                        st.session_state['library_health']=repaired
                        st.rerun()
            else:st.warning('Current verification is unavailable.' if outcome=='unavailable' else 'Local library assets need recovery before verification.')
            for error in report.get('errors',[]):st.warning(error)
            if report.get('repair_usage'):
                st.caption('Repair usage includes reported embedding tokens for this operation only. Missing responses or interrupted attempts can leave additional usage unknown.')
                st.json(report['repair_usage'])
            st.caption('Checks compare expected record IDs, content and metadata, plus search visibility. Extra remote records are not enumerated.')
        else:st.caption('Current remote integrity has not been checked in this session. The record count above is historical.')
        if status.get('last_verified_at'):
            st.caption(f"Last successful verification: {checked_at(status['last_verified_at'])}")
    if hasattr(service,'check_readiness'):
        with st.expander('Connection and answer readiness'):
            st.caption('This explicit check tests source reading, semantic search, model access, and one cited generated answer. It uses provider requests.')
            if st.button('Check search and generated answers'):
                with st.spinner('Checking search and a supported teaching answer…'):
                    ok,report=action('Check readiness',lambda:service.check_readiness(require_generation=True))
                if ok:st.session_state['provider_readiness']=report
            report=st.session_state.get('provider_readiness')
            if report is None and hasattr(service,'latest_readiness'):
                ok,report=action('Read readiness history',service.latest_readiness)
            if report:
                st.caption(f"Last checked: {checked_at(report.get('checked_at'))} · Historical result; check again after changing credentials or configuration.")
                if report.get('run_id') and report['run_id']!=run_id:
                    st.warning('This readiness check belongs to an earlier library. Check again for the active version.')
                elif (report.get('ok') is True and report.get('generation_requested') is True
                      and report.get('generation',{}).get('ok') is True
                      and report.get('generation',{}).get('state')=='verified'):
                    st.success('Source reading, search and generated answers passed.')
                else:st.warning(f"Readiness incomplete · Generated answer: {report.get('generation',{}).get('state','not_checked')}")
                st.json({key:report.get(key) for key in ('source_reading','semantic_search','model_access','index_profile','generation')})
            else:st.caption('Readiness has not been checked. Model access alone does not verify generated answers.')


def render(service,corpus,active):
    st.subheader('Entire source library')
    ok,status = action('Read library status',service.library_status)
    if not ok:
        from ui import recovery
        recovery.render(service)
        return
    for warning in status.get('warnings',[]):st.warning(warning)
    a,b,c = st.columns(3)
    a.metric('Local source PDFs',status.get('source_documents',0))
    b.metric('Searchable documents',status.get('searchable_documents',0))
    c.metric('Records at last build',status.get('record_count',0))
    st.caption('PDFs and the consolidated XML stay local. A build sends extracted chunks and metadata to Pinecone.')
    if corpus:
        from amgen_explorer.coverage import coverage_summary
        coverage=coverage_summary(corpus)
        st.caption(f"Pages with searchable text: {coverage['searchable_text_pages']:,} / {coverage['total_pages']:,}. No text detected: {coverage['no_text_pages']:,} (blank or image-only; OCR unavailable).")
        with st.expander('Page coverage and source limitations'):
            st.dataframe(coverage['documents'],hide_index=True,width='stretch')
            if coverage['limitations']:st.dataframe(coverage['limitations'],hide_index=True,width='stretch')
    health_controls(service,status,active)
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
        if st.button('Open library recovery'):
            st.session_state['show_library_recovery']=True
        if st.session_state.get('show_library_recovery'):
            from ui import recovery
            recovery.render(service)
        if hasattr(service,'config') and hasattr(service.config,'path'):
            from amgen_explorer.retention import plan_cleanup
            ok,retention=action('Read retained storage',lambda:plan_cleanup(service.config))
            if ok:
                st.caption(f'Retained manifest and source-snapshot storage: {retention.local_bytes/1024**2:.1f} MiB. Shared snapshots are counted once.')
                st.caption('Remote storage and dollar cost are unknown. Provider usage is not a dollar estimate. Build usage covers initial and resumed ingestion; repair usage is recorded separately and may be incomplete.')
                for warning in retention.warnings:st.caption(warning)
                if retention.runs:st.dataframe(retention.runs,hide_index=True,width='stretch')
                if retention.last_provider_usage:st.json(retention.last_provider_usage)
