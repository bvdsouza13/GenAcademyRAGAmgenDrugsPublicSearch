from hashlib import sha256
import streamlit as st
from ui.common import action, citations, document_selector, hero, navigate, product_selector, source_variant, source_view

LESSONS = [
    ('The essentials','What approved uses and important limitations does the prescribing information describe?'),
    ('How it works','Explain the mechanism of action in the prescribing information, preserving its limits.'),
    ('Safety and precautions','What warnings, contraindications, and precautions are highlighted in the prescribing information?'),
]


def readiness(service, product, active):
    if not product:
        return False, 'No XML collection is available. Build and review sources in Manage sources.'
    if not active:
        return False, 'No verified library has been published. Review sources, load a staging index, then publish it in Manage sources.'
    if product.id not in active.get('product_ids',[]):
        return False, 'This medicine has no reviewed content in the published library. Review and publish its sources to enable chat.'
    errors = service.config.validate(require_chat=True,require_secrets=True,require_host=True)
    if errors:
        # Configuration validation is explicitly sanitized by the config contract.
        return False, ' '.join(errors)
    return True, ''


def scope_key(product_id, document_id):
    return sha256(f'{product_id}:{document_id}'.encode()).hexdigest()[:12]


def explanation_status(abstained, citations, mode):
    if abstained:
        return 'Source excerpt · explanation not verified' if citations else 'Explanation withheld · see the response for details'
    return f'{mode} · Source-grounded explanation'


def render(service,corpus,active):
    st.html('<div class="eyebrow">GUIDED DISCOVERY</div>')
    left, main, right = st.columns([1.1,2.5,1.1],gap='large')
    with left:
        st.subheader('Your learning path')
        product = product_selector(corpus)
        document = document_selector(corpus,product) if product else None
        key = scope_key(product.id if product else '',document)
        done = st.session_state.setdefault('lesson_progress',{}).setdefault(key,[])
        lesson = st.radio('Learning steps',[x[0] for x in LESSONS]+['Check your understanding'],key=f'lesson_{key}')
        st.progress(len(done)/3,text=f'{len(done)} of 3 lessons understood')
    ready, reason = readiness(service,product,active)
    if ready and 'document_ids' in active and not any(d.id in active['document_ids'] for d in corpus.documents if d.product_id==product.id):
        ready=False
        reason='This medicine has no source documents in the published library. Review and publish its sources in Manage sources.'
    if ready and document and 'document_ids' in active and document not in active['document_ids']:
        ready=False
        reason='This source document is not in the published library. Choose a published source or review and publish this document in Manage sources.'
    if ready and product and not document:
        indexed_docs=set((active or {}).get('document_ids',[]))
        variants=[d for d in corpus.documents if d.product_id==product.id and (not indexed_docs or d.id in indexed_docs)]
        if len(variants)>1:
            ready=False
            reason='This medicine has multiple source scopes. Choose a specific Source scope in your learning path so the explanation uses the right document.'
    with main:
        st.title(f'Let’s learn about {product.name}' if product else 'Let’s start learning')
        st.caption('Ask freely. Go deeper when you’re ready.')
        mode = st.radio('Explanation style',['Plain language','Technical detail'],horizontal=True,key='learning_mode')
        history = st.session_state.setdefault('chats',{}).setdefault(key,[])
        if history and history[-1]['role']=='assistant':
            previous=history[-1]
            prior_response=previous.get('response')
            can_reexplain=ready and prior_response is not None and getattr(prior_response,'evidence',None) is not None and not previous.get('abstained') and previous.get('mode')!=mode
            if st.button('Re-explain last answer',disabled=not can_reexplain,key=f'reexplain_{key}',help='Use the same retrieved passages in the selected explanation style. Runs only when clicked.'):
                ok,response=action('Re-explain last answer',lambda:service.reexplain(previous['question'],prior_response,mode,product.id,document_id=document),spinner='Explaining the same evidence in your selected style…')
                if ok:
                    history.append({'role':'assistant','content':response.answer,'mode':mode,'citations':response.citations,'abstained':response.abstained,'lesson':previous.get('lesson'),'response':response,'question':previous['question']})
        if not ready:
            st.info(reason)
            st.button('Open Manage sources',key='chat_setup',on_click=navigate,args=('Manage sources',))
        elif active.get('xml_hash') != corpus.xml_hash:
            st.warning('Update available. Answers use the verified published library; your newer local XML has not been published yet.')
        with st.container(border=True):
            st.subheader('Start with the useful questions')
            st.write('Explore what the source label says about approved uses, how the medicine works, and important safety information. Each explanation includes its supporting passages.')
            if lesson != 'Check your understanding':
                st.caption(f'CURRENT STEP · {lesson.upper()}')
                st.write(next(prompt for name,prompt in LESSONS if name==lesson))
                begin = st.button('Begin the lesson',type='primary',disabled=not ready)
            else:
                begin = False
                quiz_panel(service,product,document,key,ready)
        prompt = None
        if begin:
            prompt = next(q for n,q in LESSONS if n==lesson)
        for i,entry in enumerate(history):
            with st.chat_message(entry['role']):
                st.markdown(entry['content'])
                if entry['role']=='assistant':
                    st.caption(explanation_status(entry.get('abstained'),entry.get('citations'),entry.get('mode','Plain language')))
                    citations(service,entry.get('citations',[]),f'{key}_{i}')
        typed = st.chat_input('Ask about this medicine…',disabled=not ready,key=f'question_{key}')
        if typed:
            prompt = typed
        if prompt and ready:
            prior = [{'role':h['role'],'content':h['content']} for h in history[-12:]]
            with st.chat_message('user'):
                st.markdown(prompt)
            with st.chat_message('assistant'):
                ok,response = action('Create explanation',lambda:service.answer(prompt,product.id,mode=mode,document_id=document,history=prior),spinner='Finding passages and preparing a cited explanation…')
                if ok:
                    st.write_stream(iter([response.answer]))
                    st.caption(explanation_status(response.abstained,response.citations,mode))
                    citations(service,response.citations,f'{key}_{len(history)+1}')
                    history.extend([{'role':'user','content':prompt},{'role':'assistant','content':response.answer,'mode':mode,'citations':response.citations,'abstained':response.abstained,'lesson':lesson if begin else None,'response':response,'question':prompt}])
                    for followup in response.followups:
                        st.caption(f'Try next: {followup}')
        if history and history[-1]['role']=='assistant' and not history[-1].get('abstained'):
            last_lesson = history[-1].get('lesson')
            if last_lesson and last_lesson not in done:
                if st.button('Mark this lesson understood',key=f'understood_{key}'):
                    done.append(last_lesson)
                    st.rerun()
        if history:
            st.button('Clear this conversation',key=f'clear_{key}',on_click=lambda:history.clear())
        st.caption('For learning. Your healthcare professional can help with personal treatment questions.')
    with right:
        st.subheader('Learning sources')
        st.caption('LOCAL DOCUMENT LIBRARY')
        if product:
            docs = [d for d in corpus.documents if d.product_id==product.id and (not document or d.id==document)]
            for doc in docs:
                with st.container(border=True):
                    st.markdown(f'**{doc.filename}**')
                    st.caption(f'{doc.page_count} pages · Revision {doc.revision or "not identified"}')
                    if variant := source_variant(doc.filename,doc.variant_hint):
                        st.caption(variant)
                    source_view(service,doc.id,doc.filename,f'learn_doc_{doc.id}')
        st.caption('Expand a citation below an explanation to read the exact source passage and view its original PDF page.')


def quiz_panel(service,product,document,key,ready):
    quizzes = st.session_state.setdefault('quizzes',{})
    if st.button('Create a source-based quiz',disabled=not ready,key=f'make_quiz_{key}'):
        ok,quiz = action('Create quiz',lambda:service.quiz(product.id,document_id=document))
        if ok:
            if isinstance(quiz,dict) and 'error' not in quiz and isinstance(quiz.get('choices'),list) and isinstance(quiz.get('correct_index'),int) and 0 <= quiz['correct_index'] < len(quiz['choices']):
                quizzes[key]={'quiz':quiz,'submitted':False}
                st.session_state.pop(f'quiz_answer_{key}',None)
            else:
                st.warning('A supported quiz could not be created from the available evidence. Try another source or review the source coverage.')
    record = quizzes.get(key)
    if not record:
        st.caption('A short quiz is generated only when you request one. Your progress stays in this session.')
        return
    quiz=record['quiz']
    st.markdown(f"**{quiz['question']}**")
    answer = st.radio('Your answer',range(len(quiz['choices'])),format_func=lambda i:quiz['choices'][i],index=None,key=f'quiz_answer_{key}')
    if record.get('submitted') and record.get('checked_answer') != answer:
        record['submitted']=False
    if st.button('Check answer',disabled=answer is None,key=f'check_quiz_{key}'):
        record['submitted']=True
        record['checked_answer']=answer
        record['correct']=answer==quiz['correct_index']
    if record.get('submitted'):
        if record['correct']:
            st.success('Correct. Nice work checking the source.')
        else:
            st.info(f"Review this answer: {quiz['choices'][quiz['correct_index']]}")
        st.write(quiz.get('rationale',''))
        citations(service,quiz.get('citations',[]),f'quiz_{key}')


def progress_view(service,corpus,active):
    hero('Your next discovery starts here.', 'Build understanding one medicine, one lesson, and one question at a time.','MY LEARNING')
    progress=st.session_state.get('lesson_progress',{})
    completed=sum(len(items) for items in progress.values())
    quizzes=st.session_state.get('quizzes',{})
    chats=st.session_state.get('chats',{})
    a,b,c=st.columns(3)
    a.metric('Lessons understood',completed)
    b.metric('Quizzes checked',sum(bool(v.get('submitted')) for v in quizzes.values()))
    c.metric('Questions explored',sum(sum(h['role']=='user' for h in history) for history in chats.values()))
    st.subheader('Continue your learning')
    st.write('Choose a medicine, explore the three guided lessons, then check your understanding. Mark a lesson understood when you feel ready.')
    st.caption('Progress and chat history are session-local and reset when the session ends.')
    st.button('Continue learning →',type='primary',on_click=navigate,args=('Learn with chat',))
