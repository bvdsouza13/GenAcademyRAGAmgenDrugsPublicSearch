"""Draft controls are local; complete experiments run only on explicit clicks."""
import streamlit as st
from ui.common import action, source_text


def restore(config):
    st.session_state['experiment_size']=config.target_tokens
    st.session_state['experiment_overlap']=config.overlap_tokens
    st.session_state.pop('experiment_preview',None)


def render(service,corpus,active):
    from amgen_explorer.chunking import ChunkConfig
    st.subheader('Test chunk settings')
    current=service.latest_library_settings()
    st.session_state.setdefault('experiment_size',current.target_tokens)
    st.session_state.setdefault('experiment_overlap',current.overlap_tokens)
    size=st.slider('Chunk size',300,1200,step=50,key='experiment_size')
    overlap=st.slider('Overlap',0,200,step=10,key='experiment_overlap')
    st.caption('Conservative UTF-8 byte budgets plus an 8-unit reserve, not exact model-token counts. Defaults 600/80 are a starting point, not a measured optimum.')
    a,b=st.columns(2)
    a.button('Reset to defaults',on_click=restore,args=(ChunkConfig(),))
    b.button('Restore current settings',on_click=restore,args=(current,))
    config=service.chunk_config(target_tokens=size,overlap_tokens=overlap)
    signature=(getattr(corpus,'xml_hash',None),size,overlap,(active or {}).get('run_id'))
    if st.button('Preview locally',disabled=not corpus):
        ok,plan=action('Preview chunks',lambda:service.preview_library(config))
        if ok:
            st.session_state['experiment_preview']={'signature':signature,'plan':plan}
    preview=st.session_state.get('experiment_preview')
    if preview and preview['signature']==signature:
        plan=preview['plan']
        a,b=st.columns(2)
        a.metric('Prepared chunks',len(plan.chunks))
        b.metric('Estimated embedding volume',sum(getattr(c,'token_count',0) for c in plan.chunks))
        st.caption('Local preview across the entire source inventory. No provider calls are made by previewing.')
        coverage=getattr(plan,'coverage',{})
        if coverage:
            st.caption(f"Readable text covered: {coverage.get('covered_characters',0):,} of {coverage.get('expected_characters',coverage.get('total_characters',0)):,} source characters. Blank or image-only pages: {len(coverage.get('blank_pages',[]))}. OCR is not included.")
            if not coverage.get('complete'):
                st.warning('Readable source coverage is incomplete. Inspect the missing intervals before testing.')
            with st.expander('Coverage details'):
                st.json(coverage)
        if plan.excluded: st.caption(f'{len(plan.excluded)} source units have preparation notes. Inspect coverage details.')
        if plan.chunks:
            with st.expander('Example chunk'):
                source_text(plan.chunks[0].text)
    elif preview:
        st.caption('Draft settings or library changed. Preview again to inspect the current draft.')
    baseline_ready=bool(active and active.get('full_library',active.get('is_full_library',False)))
    if not baseline_ready:
        st.info('Build an active full library before comparing chunk settings. Every test uses the entire inventory and the same saved questions.')
    if st.button('Test settings',type='primary',disabled=not baseline_ready):
        with st.status('Building the full-library candidate, then evaluating saved questions…',expanded=True) as progress:
            ok,report=action('Test settings',lambda:service.test_chunk_configuration(config,suite_id='learner-search',on_progress=lambda p:st.caption(str(p.get('stage') or p.get('phase') or p.get('status','Testing')))))
            if ok:
                st.session_state['chunk_experiment']={'signature':signature,'report':report}
                progress.update(label='Experiment complete',state='complete',expanded=False)
            else:
                progress.update(label='Experiment failed · Active library preserved',state='error')
    saved=st.session_state.get('chunk_experiment')
    if saved:
        report=saved['report']
        if saved['signature']!=signature:
            st.info('These measurements belong to earlier draft settings or a different baseline. Test the current settings before choosing them.')
        display_report(report)
        compatible=report.get('compatible',True) is True
        candidate=report.get('candidate_run_id')
        candidate_info=report.get('candidate',{})
        verified=bool(candidate_info.get('status')=='verified' and candidate_info.get('full_library',candidate_info.get('is_full_library',False)))
        if st.button('Use this configuration',disabled=not (compatible and verified and candidate and saved['signature']==signature)):
            ok,_=action('Use configuration',lambda:service.use_configuration(candidate))
            if ok:
                st.success('The verified full-library configuration is active.')
                st.rerun()
    if st.button('Revert to previous version',disabled=not active):
        ok,_=action('Revert library',service.revert_library)
        if ok:
            st.success('The previous verified full-library version is active.')
            st.rerun()
    st.caption('Reset changes draft controls only. Reverting changes the active full-library pointer and preserves citations and stored versions.')


def display_report(report):
    if report.get('compatible',True) is not True:
        st.warning('A controlled comparison is unavailable because sources, policy or evaluation settings differ. Update the library before testing.')
    st.caption(f"Baseline: {report.get('baseline_run_id','unknown')} · Candidate: {report.get('candidate_run_id','unknown')}")
    st.caption('Measured retrieval results describe the saved questions. They do not establish clinical accuracy.')
    metrics=report.get('metrics',{})
    labels={'document_recall_at_k':'Expected-document recall at k','mean_reciprocal_rank':'Mean reciprocal rank','quote_coverage':'Expected quote coverage','citation_resolution':'Citations resolved','contamination_rate':'Cross-source contamination','mean_latency_ms':'Mean search latency (ms)','question_count':'Questions measured'}
    for col,label,key in zip(st.columns(2),('Current library','Test configuration'),('baseline','candidate')):
        with col:
            st.markdown(f'**{label}**')
            measured=metrics.get(key,{})
            for metric,value in measured.items():
                st.write(f"{labels.get(metric,metric.replace('_',' ').capitalize())}: {value}")
            if not measured:
                st.caption('No measured metrics were returned for this version.')
    cases=report.get('rows',[])
    if cases:
        st.markdown('**Compare a saved question**')
        if st.session_state.get('experiment_question',0) >= len(cases):
            st.session_state['experiment_question']=0
        choice=st.selectbox('Question',range(len(cases)),format_func=lambda i:cases[i].get('question',''),key='experiment_question')
        case=cases[choice]
        for col,label,key in zip(st.columns(2),('Current results','Test results'),('baseline','candidate')):
            with col:
                st.markdown(f'**{label}**')
                hits=case.get(key,{}).get('hits',[])
                for hit in hits[:5]:
                    meta=hit.get('metadata',{})
                    st.caption(f"{meta.get('filename','Source')} · Physical PDF page {meta.get('page_start','unknown')}")
                    source_text(hit.get('text',''))
                if len(hits)>5:st.caption('First 5 passages shown. Download the complete report for all measured evidence.')
    if report.get('note'): st.caption(report['note'])
    for warning in report.get('warnings',[]): st.warning(str(warning))
    with st.expander('Measurement details'):
        import json
        st.json({k:v for k,v in report.items() if k not in {'rows','candidate'}})
        st.download_button('Download comparison report',json.dumps(report,ensure_ascii=False,indent=2),file_name='chunk-comparison.json',mime='application/json')
