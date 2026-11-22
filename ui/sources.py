"""Explicit local review and staging/publication workflow. No cloud work on reruns."""
from dataclasses import asdict, is_dataclass
from pathlib import Path
from html import escape
import json
import streamlit as st
from amgen_explorer.auth import require_admin
from ui.common import action, hero, source_text, source_variant, source_view


def render(service,corpus,active,*,settings=None):
    require_admin(settings)
    hero('Build a trusted learning library.', 'From source PDFs to searchable, cited explanations.','KNOWLEDGE WORKSHOP')
    st.html('<div class="journey"><span>1 · Source files</span><span>2 · Build XML</span><span>3 · Review content</span><span>4 · Stage & publish</span></div>')
    st.caption('Local curator workspace · Review decisions apply to the exact source passage and content hash.')
    inventory = service.inventory()
    a,b,c=st.columns(3)
    a.metric('Source PDFs',len(inventory))
    b.metric('Medicines',len(corpus.products) if corpus else 0)
    c.metric('PDF pages',f'{sum(d.page_count for d in corpus.documents):,}' if corpus else '—')
    tabs=st.tabs(['Source library & XML','Review passages','Chunking & staging','Connections & releases'])
    with tabs[0]:
        corpus=library(service,corpus,inventory)
    with tabs[1]:
        review(service,corpus)
    with tabs[2]:
        chunking(service,corpus,active)
    with tabs[3]:
        releases(service,corpus,active)


def library(service,corpus,inventory):
    st.subheader('Your source library')
    st.write('Build one consolidated XML collection from the PDFs in the configured local source folder. Building does not upload or publish content.')
    if inventory:
        st.dataframe(inventory,hide_index=True,width='stretch')
    else:
        st.info('No source PDFs were found. Add PDFs to the configured Documents folder, then reload.')
    if st.button('Build XML',type='primary',disabled=not inventory):
        with st.status('Extracting and validating the XML collection…',expanded=True) as status:
            st.write('Reading local PDFs and preserving source passages and page references.')
            ok, report=action('Build XML',service.build)
            if ok:
                st.session_state['build_report']=asdict(report) if is_dataclass(report) else report
                st.session_state.pop('chunk_preview',None)
                status.update(label='XML built · Needs review',state='complete',expanded=False)
                corpus=service.corpus()
            else:
                status.update(label='Failed · XML build',state='error')
    report=st.session_state.get('build_report')
    if report:
        if report.get('schema_valid'):
            st.success('XML built and structurally validated. Clinical passage review is still required.')
        else:
            st.warning('XML build did not report structural validation. Inspect the extraction report before indexing.')
        st.caption(f"{report.get('document_count',0)} documents · {report.get('block_count',0):,} extracted passages · {report.get('page_count',0):,} pages")
        with st.expander('Extraction report'):
            st.json(report)
    if corpus:
        st.info('Original PDFs remain the source of truth. Review extracted passages before making them available in chat.')
        st.caption(f'Current XML hash: {corpus.xml_hash}')
        try:
            path=Path(corpus.xml_path).resolve()
            # Restrict downloads to files inside the configured project root.
            root=Path(service.config.root).resolve()
            if path.is_relative_to(root) and path.is_file():
                st.download_button('Download AmgenProducts.xml',path.read_bytes(),file_name='AmgenProducts.xml',mime='application/xml')
            else:
                st.warning('The XML artifact is unavailable inside the configured project folder.')
        except OSError:
            st.warning('The XML artifact could not be read. Rebuild it from the local source PDFs.')
        with st.expander('XML preview'):
            try:
                if path.is_relative_to(root):
                    st.code(path.read_text(encoding='utf-8')[:15000],language='xml')
                    st.caption('Preview limited to the first 15,000 characters; download the full collection above.')
            except (OSError,UnicodeDecodeError):
                st.caption('XML preview unavailable.')
        if corpus.warnings:
            with st.expander(f'{len(corpus.warnings)} extraction warnings'):
                for warning in corpus.warnings:
                    st.warning(str(warning))
    return corpus


def review(service,corpus):
    st.subheader('Review before indexing')
    st.write('Compare the exact extracted passage with the original PDF. Acceptance approves this raw passage for retrieval; it does not certify a normalized clinical fact.')
    if not corpus or not corpus.documents:
        st.info('Build XML first to inspect extracted passages.')
        return
    docs={d.id:d for d in corpus.documents}
    document=st.selectbox('Document to review',list(docs),format_func=lambda x:docs[x].filename,key='review_document')
    blocks=[b for b in corpus.blocks if b.document_id==document]
    if not blocks:
        st.info('This source has no extracted passages. Inspect the extraction warnings and original PDF.')
        return
    filters=['All','needs-review','accepted','rejected']
    selected_filter=st.selectbox('Review status filter',filters,key='review_status_filter')
    blocks=[b for b in blocks if selected_filter=='All' or service.reviews.status(b)==selected_filter]
    if not blocks:
        st.info('No passages match this review filter.')
        return
    by_id={b.id:b for b in blocks}
    block_id=st.selectbox('Extracted passage',list(by_id),format_func=lambda x:f'{by_id[x].section_title} · PDF pp. {by_id[x].page_start}–{by_id[x].page_end} · {x[:12]}',key='review_block')
    block=by_id[block_id]
    left,right=st.columns([1.2,1],gap='large')
    with left:
        with st.container(border=True):
            st.markdown(f'**{block.section_title}**')
            st.caption(f'Status: {service.reviews.status(block)} · PDF pages {block.page_start}–{block.page_end}')
            source_text(block.text)
            if block.warnings:
                for warning in block.warnings:
                    st.warning(str(warning))
            st.caption(f'Passage hash: {block.content_hash}')
    with right:
        st.markdown('**Original source**')
        doc=docs[document]
        st.write(doc.filename)
        variant=source_variant(doc.filename,doc.variant_hint)
        st.caption(f'Revision: {doc.revision or "not identified"}'+(f' · {variant}' if variant else ''))
        source_view(service,doc.id,doc.filename,f'review_{block.id}',block.page_start)
        st.divider()
        decisions=['needs-review','accepted','rejected']
        current=service.reviews.status(block)
        decision=st.selectbox('Review decision',decisions,index=decisions.index(current) if current in decisions else 0,key=f'decision_{block.id}')
        reviewer=st.text_input('Reviewer name',key='reviewer',placeholder='Record who reviewed this passage')
        note=st.text_area('Review note',key=f'note_{block.id}',placeholder='Record scope, layout, table, or extraction concerns…')
        if st.button('Save review',type='primary',disabled=not reviewer.strip()):
            ok,_=action('Save review',lambda:service.review(block.id,decision,reviewer.strip(),note))
            if ok:
                st.success(f'Review saved: {decision}. Preview chunks again to use the updated review state.')
                st.session_state.pop('chunk_preview',None)


def restore_chunk_settings(target=600,overlap=80):
    st.session_state['target_tokens']=target
    st.session_state['overlap_tokens']=overlap
    st.session_state.pop('chunk_preview',None)


def chunking(service,corpus,active):
    st.subheader('Make every passage traceable')
    st.write('Preview locally, stage a reviewed configuration, compare its retrieval, then publish deliberately.')
    defaults=service.config.settings['chunking']
    with st.expander('Advanced chunking settings',expanded=False):
        st.caption('Fixed strategy: section-aware · Preserves medicine, document variant, section, and PDF pages.')
        target=st.slider('Target budget (UTF-8 bytes + reserve)',300,1200,step=50,value=defaults['target_tokens'],key='target_tokens')
        overlap=st.slider('Overlap budget (UTF-8 bytes + reserve)',0,200,step=10,value=defaults['overlap_tokens'],key='overlap_tokens')
        st.caption('The current tokenizer uses UTF-8 bytes plus an 8-unit reserve as a conservative token upper bound. These controls are byte budgets, not exact model token counts.')
        presets=service.presets()
        if presets:
            chosen=st.selectbox('Saved configuration',list(presets),key='preset_choice')
            preset=presets[chosen]
            values=preset.get('settings',preset) if isinstance(preset,dict) else {}
            st.button('Restore selected configuration',on_click=restore_chunk_settings,args=(values.get('target_tokens',600),values.get('overlap_tokens',80)))
        name=st.text_input('Configuration name',placeholder='e.g. reviewed-sections-600',key='preset_name')
        save,restore=st.columns(2)
        if save.button('Save configuration',disabled=not name.strip(),width='stretch'):
            ok,_=action('Save configuration',lambda:service.save_preset(name.strip(),service.chunk_config(target_tokens=target,overlap_tokens=overlap)))
            if ok:
                st.success('Configuration saved locally.')
        restore.button('Restore defaults',on_click=restore_chunk_settings,args=(defaults['target_tokens'],defaults['overlap_tokens']),width='stretch')
    if not corpus:
        st.info('Build and review the XML collection before previewing a load.')
        return
    docs={d.id:d for d in corpus.documents}
    document=st.selectbox('Preview source', [None]+list(docs),format_func=lambda x:docs[x].filename if x else 'All documents in this XML collection',key='chunk_document')
    signature=(corpus.xml_hash,target,overlap,document)
    if st.button('Preview Pinecone load',type='primary'):
        ok,plan=action('Preview Pinecone load',lambda:service.preview(service.chunk_config(target_tokens=target,overlap_tokens=overlap),document_id=document),spinner='Preparing a local reviewed chunk plan…')
        if ok:
            st.session_state['chunk_preview']={'signature':signature,'plan':plan}
    saved=st.session_state.get('chunk_preview')
    if not saved:
        st.info('Preview a load to see eligible chunks, excluded passages, and the exact text that will be embedded. Previewing makes no paid API calls.')
        return
    if saved['signature']!=signature:
        st.warning('Settings or sources changed. Preview again before staging or publishing this configuration.')
        return
    plan=saved['plan']
    a,b,c=st.columns(3)
    a.metric('Ready to index',len(plan.chunks))
    b.metric('Excluded passages',len(plan.excluded))
    c.metric('Conservative token budget',f'{sum(chunk.token_count for chunk in plan.chunks):,}')
    st.caption(f'Plan fingerprint: {plan.fingerprint} · XML: {plan.xml_hash}')
    with st.expander('Excluded passages and reasons'):
        if plan.excluded:
            st.dataframe(plan.excluded,width='stretch',hide_index=True)
        else:
            st.caption('No passages were excluded from this plan.')
    if not plan.chunks:
        st.warning('Needs review · No eligible reviewed chunks. Accept source passages after comparing them with the original PDF, then preview again.')
        return
    selected=st.selectbox('Inspect embedded chunk',range(len(plan.chunks)),format_func=lambda i:f'{i+1} · {plan.chunks[i].metadata.get("section_title","Source section")} · {plan.chunks[i].token_count} budgeted tokens',key='inspect_chunk')
    chunk=plan.chunks[selected]
    source,embedded=st.columns(2)
    with source:
        st.markdown('**Original source passage**')
        ids=chunk.metadata.get('block_ids',[])
        if isinstance(ids,str):
            try:
                ids=json.loads(ids)
            except ValueError:
                ids=[ids]
        if not ids and chunk.metadata.get('block_id'):
            ids=[chunk.metadata['block_id']]
        passages=[b for b in corpus.blocks if b.id in ids]
        if not passages:
            passages=[b for b in corpus.blocks if b.document_id==chunk.metadata.get('document_id') and b.section_title==chunk.metadata.get('section_title')]
        if passages:
            source_text('\n\n'.join(b.text for b in passages))
        else:
            st.caption('Use the source passage IDs in the metadata to inspect this chunk in Review passages.')
        st.caption(f'PDF pages {chunk.metadata.get("page_start","?")}–{chunk.metadata.get("page_end","?")}')
    with embedded:
        st.markdown('**Exact text prepared for embedding**')
        source_text(chunk.text)
        st.caption(f'{chunk.token_count:,} conservative budgeted tokens · Overlap budget: {overlap}')
        # Highlight only overlap that actually matches the preceding chunk.
        if selected:
            prior=plan.chunks[selected-1]
            previous_source=prior.metadata.get('source_text',prior.text)
            current_source=chunk.metadata.get('source_text',chunk.text)
            overlap_text=''
            if prior.metadata.get('document_id')==chunk.metadata.get('document_id'):
                for count in range(min(len(previous_source),len(current_source),5000),0,-1):
                    if previous_source.endswith(current_source[:count]):
                        overlap_text=current_source[:count]; break
            if overlap_text:
                st.markdown('**Matching overlap with previous chunk**')
                st.html('<mark style="display:block;padding:12px;border-radius:8px;background:#fff0ac;white-space:pre-wrap">'+escape(overlap_text)+'</mark>')
            else:
                st.caption('No literal prefix/suffix overlap with the preceding chunk; section boundaries or prefixes may separate them.')
    with st.expander('Chunk provenance'):
        st.json(chunk.metadata)
    st.info('Loading creates or resumes a staging namespace and verifies it. Publication is a separate explicit action.')
    load,test=st.columns(2)
    load_clicked=load.button('Load Pinecone',type='primary',width='stretch')
    test_clicked=test.button('Build test index',width='stretch',help='Stage this configuration for a retrieval comparison. Does not publish it.')
    if load_clicked or test_clicked:
        label='Build test index' if test_clicked else 'Load Pinecone'
        with st.status('Indexing reviewed passages…',expanded=True) as status:
            bar=st.progress(0,text='Staging the pinned XML and review plan')
            def progress(manifest):
                total=manifest.get('record_count',0)
                complete=manifest.get('succeeded',0)
                phase=manifest.get('status','indexing')
                if total:
                    bar.progress(min(complete/total,1.0),text=f'{phase.title()} · {complete:,} of {total:,} records uploaded')
                status.update(label='Verifying staging records…' if phase=='verifying' else 'Indexing reviewed passages…')
            ok,result=action(label,lambda:service.load(plan,on_progress=progress))
            if ok:
                st.session_state['last_load']=result
                state=str(result.get('status','unknown'))
                if state.lower() in {'verified','ready','searchable','complete'}:
                    bar.progress(1.0,text='Staging verification complete')
                    status.update(label='Verified staging index · Awaiting publication',state='complete')
                elif state.lower() in {'failed','error'}:
                    status.update(label='Failed · Staging index was not published',state='error')
                else:
                    status.update(label=f'Staging state: {state} · Not published',state='complete')
            else:
                status.update(label='Failed · Existing published library preserved',state='error')
    if st.session_state.get('last_load'):
        result=st.session_state['last_load']
        st.caption(f"Last staging action: {result.get('status','unknown')} · Run {result.get('run_id','not reported')}")


def releases(service,corpus,active):
    st.subheader('Connections & publication')
    st.write('Connection tests run only when requested. Credentials stay in the server environment or local secrets file.')
    if st.button('Test connections'):
        ok,result=action('Test connections',service.connection_status)
        if ok:
            st.session_state['connection_results']=result
    results=st.session_state.get('connection_results')
    if results:
        for name,result in results.items():
            if isinstance(result,dict):
                state=str(result.get('status', 'connected' if result.get('ok') is True else 'unavailable' if result.get('ok') is False else 'unknown'))
                message=result.get('message',result.get('error',''))
                text=f'{name}: {state}' + (f' · {message}' if message else '')
                if state.lower() in {'ok','connected','ready','passed','success'}:
                    st.success(text)
                else:
                    st.warning(text)
            else:
                st.info(f'{name}: {result}')
    st.divider()
    st.markdown('**Published library**')
    if active:
        st.success(f"Searchable · Run {active.get('run_id','not reported')}")
        st.caption(f"Namespace: {active.get('namespace','not reported')} · XML hash: {active.get('xml_hash','not reported')}")
        if corpus and active.get('xml_hash')!=corpus.xml_hash:
            st.warning('Update available · The current local XML differs from the published library. Existing answers continue to use the published version.')
    else:
        st.info('No verified library is published. Stage and verify reviewed sources first.')
    runs=service.index.runs()
    if not runs:
        st.caption('No staging or release runs have been recorded yet.')
        return
    rows=[{k:r.get(k,'') for k in ('run_id','status','namespace','xml_hash')} for r in runs]
    st.dataframe(rows,hide_index=True,width='stretch')
    by_id={r['run_id']:r for r in runs if r.get('run_id')}
    if not by_id:
        return
    selected=st.selectbox('Staged run',list(by_id),key='publish_run')
    run=by_id[selected]
    saved=st.session_state.get('chunk_preview')
    st.caption('Publication revalidates the current XML, review decisions, and chunk settings. Recreate the matching local preview after restarting the app.')
    eligible=str(run.get('status','')).lower() in {'verified','ready','searchable','complete','active','published'}
    current_signature=(corpus.xml_hash,st.session_state.get('target_tokens',600),st.session_state.get('overlap_tokens',80),st.session_state.get('chunk_document')) if corpus else None
    current_preview=bool(saved and saved.get('signature')==current_signature)
    if st.button('Publish configuration',type='primary',disabled=not eligible or not current_preview):
        ok,result=action('Publish configuration',lambda:service.publish(selected,saved['plan']))
        if ok:
            st.success('Configuration published. The verified library is now available for learning.')
            st.rerun()
    st.subheader('Compare retrieval')
    st.caption('Uses the selected two staged runs and explicit test questions. This action may call the configured search service.')
    other=st.selectbox('Compare with run',list(by_id),key='compare_run')
    if corpus and corpus.products:
        products={p.id:p.name for p in corpus.products}
        product=st.selectbox('Comparison medicine',list(products),format_func=lambda p:products[p],key='compare_product')
        questions=st.text_area('Test questions (one per line)',key='compare_questions',placeholder='What uses are described in the label?\nWhat warnings are highlighted?')
        if st.button('Compare retrieval',disabled=selected==other or not questions.strip()):
            ok,result=action('Compare retrieval',lambda:service.compare(selected,other,[q.strip() for q in questions.splitlines() if q.strip()],product))
            if ok:
                st.session_state['comparison_result']=result
        if st.session_state.get('comparison_result'):
            st.json(st.session_state['comparison_result'])
    st.divider()
    st.markdown('**Rollback to a verified run**')
    st.caption('Rollback changes the published pointer to the chosen verified run. It does not delete sources or staging records.')
    rollback=st.selectbox('Rollback target',list(by_id),key='rollback_run')
    target=by_id[rollback]
    permitted=str(target.get('status','')).lower() in {'verified','ready','searchable','complete','active','published'}
    if st.button('Rollback published library',disabled=not permitted or (active or {}).get('run_id')==rollback):
        ok,_=action('Rollback published library',lambda:service.rollback(rollback))
        if ok:
            st.success('Published library rolled back to the selected verified run.')
            st.rerun()
