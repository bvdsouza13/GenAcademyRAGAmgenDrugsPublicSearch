from html import escape
from hashlib import sha256
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
PAGES = ['Explore medicines', 'Learn with chat', 'My learning', 'Manage sources', 'Demo tour']


def style():
    st.html('''<style>
    :root { --amgen:#0063C3; --ink:#082346; }
    .stApp {background:#fbfdff;color:var(--ink)}
    [data-testid="stSidebar"] {background:linear-gradient(180deg,#ffffff 0%,#edfaff 100%);border-right:1px solid #d6e6f3}
    [data-testid="stSidebar"] h2 {font-size:1.23rem;letter-spacing:-.03em}
    [data-testid="stSidebar"] [data-testid="stRadio"] label {padding:.6rem .25rem}
    .block-container {max-width:1440px;padding-top:2.1rem;padding-bottom:3rem}
    h1,h2,h3 {color:#082346;letter-spacing:-.035em}
    h1 {font-size:2.55rem;line-height:1.12}
    h2 {font-size:1.85rem} h3 {font-size:1.28rem}
    .stButton>button, .stDownloadButton>button {border-radius:10px;min-height:2.7rem;font-weight:650}
    .stButton>button[kind="primary"] {background:#0063c3;border-color:#0063c3}
    [data-testid="stMetric"] {background:#e8f6ff;border-radius:13px;padding:16px 20px}
    [data-testid="stMetricValue"] {font-size:1.8rem;color:#003e88}
    [data-testid="stVerticalBlockBorderWrapper"] {border-radius:14px}
    [data-testid="stChatMessage"] {background:#edf7fe;border:1px solid #d7e9f7;border-radius:16px}
    .hero {position:relative;overflow:hidden;background:linear-gradient(115deg,#003b94,#0063c3 70%,#008bdd);padding:36px 40px;border-radius:18px;margin-bottom:24px;color:white;box-shadow:0 12px 30px #0063c317}
    .hero h1 {position:relative;color:white;font-size:clamp(2rem,3.6vw,3.4rem);max-width:850px;margin:15px 0;letter-spacing:-.04em}
    .hero p {position:relative;font-size:1.14rem;margin:0;max-width:760px;color:#ecfaff}
    .hero .eyebrow {position:relative;font-size:.76rem;font-weight:750;letter-spacing:.2em;text-transform:uppercase;color:#bcefff}
    .hero:after {content:'';position:absolute;width:320px;height:320px;border:44px solid #9deaff40;transform:rotate(-30deg);border-radius:35% 70% 35% 70%;right:-55px;top:-60px;pointer-events:none}
    .eyebrow {font-size:.8rem;text-transform:uppercase;letter-spacing:.15em;font-weight:700;color:#0063c3}
    .medicine {background:linear-gradient(120deg,#eaf7ff,#dcf5fb);padding:20px 22px;border-radius:13px;min-height:130px;margin-bottom:8px}
    .medicine h3 {font-size:1.45rem;margin:0 0 8px;color:#092441}
    .medicine p {color:#355571;font-size:.94rem;margin:0 0 8px}
    .pill {display:inline-block;font-size:.73rem;padding:3px 9px;border-radius:20px;background:white;color:#0057ad}
    .journey {display:flex;flex-wrap:wrap;gap:8px;margin:20px 0 25px}
    .journey span {flex:1;min-width:140px;padding:14px;background:#e2f3ff;border-radius:10px;color:#104773;font-weight:650}
    .learning-note {border-left:4px solid #00b3d4;background:#e9faff;padding:16px 20px;border-radius:8px;margin:20px 0}
    @media(max-width:700px) {.block-container {padding:1rem}.hero {padding:25px}.hero:after{opacity:.4}h1{font-size:2rem}}
    </style>''')


def hero(title, subtitle, eyebrow='YOUR MEDICINE LEARNING SPACE'):
    st.html(f'<div class="hero"><div class="eyebrow">{escape(eyebrow)}</div><h1>{escape(title)}</h1><p>{escape(subtitle)}</p></div>')


def navigate(page, product=None):
    st.session_state['nav'] = page
    if product is not None:
        st.session_state['product_id'] = product


def sidebar(active, *, demo_mode=False):
    with st.sidebar:
        st.image(str(ROOT / 'docs/assets/amgen-blue-logo.png'), width=195)
        st.header('Medicine Explorer')
        st.caption('Discover. Understand. Keep learning.')
        st.divider()
        st.radio('Your workspace', PAGES, key='nav', label_visibility='collapsed')
        st.divider()
        if demo_mode:
            st.info('Three-minute guided demo')
            st.caption('Prepared examples from included files. No API keys or live connections required.')
        elif active:
            st.success('Published library')
            st.caption('Reviewed content is published. Chat also needs configured connections.')
        else:
            st.info('Library setup in progress')
            st.caption('Review and publish sources to enable learning.')
        st.caption('LOCAL EDUCATIONAL PROTOTYPE')
        st.caption('Based on your prescribing-information library. Personal treatment decisions belong with your healthcare professional.')


def action(label, function, *, spinner=None):
    """Do not print exception payloads: providers may include request secrets."""
    try:
        with st.spinner(spinner or f'{label}…'):
            return True, function()
    except Exception:
        st.error(f'{label} failed. Check local configuration and service availability, then retry. The last published library remains available.')
        return False, None


def product_selector(corpus):
    if not corpus or not corpus.products:
        return None
    ids = [p.id for p in corpus.products]
    names = {p.id:p.name for p in corpus.products}
    if st.session_state.get('product_id') not in ids:
        st.session_state['product_id'] = ids[0]
    selected = st.selectbox('Medicine', ids, format_func=lambda p:names[p], key='product_id')
    return next(p for p in corpus.products if p.id == selected)


def source_variant(filename, hint):
    """Source scope may contain only the filename; do not repeat it as a variant."""
    return hint if hint and hint.strip().casefold() != str(filename).strip().casefold() else ''


def source_text(text):
    # st.text dedents and strips source whitespace. Escaped HTML with pre-wrap
    # preserves the exact quotation, including indentation and boundary newlines.
    st.html('<div class="source-passage" style="white-space:pre-wrap;overflow-wrap:anywhere;font-family:monospace;line-height:1.5">'+escape(text)+'</div>')


def document_selector(corpus, product, key='document_id'):
    docs = [d for d in corpus.documents if d.product_id == product.id]
    labels = {d.id:d.filename + (f' · {variant}' if (variant := source_variant(d.filename,d.variant_hint)) else '') for d in docs}
    options = [None] + [d.id for d in docs]
    if st.session_state.get(key) not in options:
        st.session_state[key] = None
    return st.selectbox('Source scope', options, format_func=lambda d:labels.get(d,'All source documents for this medicine'), key=key, help='Variants remain separate. Select a document when your question concerns a particular presentation.')


def source_view(service, document_id, filename, key, page=None, xml_hash=None):
    if not document_id:
        st.caption('Original source is unavailable for this reference.')
        return
    data = None
    try:
        data = service.source_pdf(document_id,xml_hash=xml_hash) if xml_hash else service.source_pdf(document_id)
        if data:
            st.download_button('Download source PDF', data, file_name=Path(str(filename)).name, mime='application/pdf', key=f'pdf_{key}')
    except Exception:
        st.caption('Source PDF unavailable. Restore the original local document to inspect it.')
    try:
        physical_page = int(page) if page else None
    except (TypeError, ValueError, OverflowError):
        physical_page = None
    # The widget key is only a view position: chat/quiz replacements reuse it.
    # Bind rendered bytes to the verified PDF itself, including mutable working
    # sources that have no pinned XML hash and may retain the same filename.
    identity = (document_id, xml_hash, physical_page, sha256(data).hexdigest()) if data and physical_page and physical_page > 0 else None
    cache_key = f'page_image_{key}'
    cached = st.session_state.get(cache_key)
    if not identity or not isinstance(cached,dict) or cached.get('identity') != identity:
        st.session_state.pop(cache_key,None)
    if page and st.button(f'View original page {page}',key=f'page_{key}',disabled=identity is None) and identity:
        ok, result = action('Open source page',lambda:service.source_page(document_id,physical_page,xml_hash=xml_hash) if xml_hash else service.source_page(document_id,physical_page))
        if ok and result:
            st.session_state[cache_key] = {'identity':identity,'image':result}
    cached = st.session_state.get(cache_key)
    if identity and isinstance(cached,dict) and cached.get('identity') == identity and cached.get('image'):
        st.image(cached['image'], caption=f'Original PDF · page {physical_page}', width='stretch')


def citations(service, items, key):
    for i, item in enumerate(items or []):
        meta = item.get('metadata',{})
        ref = {**meta, **item}
        filename = ref.get('filename',ref.get('source_filename','Source PDF'))
        page = ref.get('page_start',ref.get('page'))
        end = ref.get('page_end',page)
        pages = str(page) if page == end else f'{page}–{end}'
        section = ref.get('section_title',ref.get('section','Source passage'))
        with st.expander(f'[{i+1}] {filename} · {section} · PDF p. {pages if page else "unknown"}'):
            variant=source_variant(filename,ref.get('variant_hint') or ref.get('source_variant_hint'))
            revision = str(ref.get('revision') or ref.get('label_revision') or '').strip()
            revision_label = 'Revision not identified' if revision.casefold() in {'', 'not identified', 'revision not identified'} else f'Revision: {revision}'
            st.caption(f"{ref.get('product_name', 'Selected medicine')} · {revision_label}" + (f' · {variant}' if variant else ''))
            if ref.get('supporting_quote'):
                st.markdown('**Supporting quote**')
                source_text(ref['supporting_quote'])
            passage = ref.get('text',ref.get('passage',ref.get('chunk_text','')))
            if passage and passage != ref.get('supporting_quote'):
                if ref.get('supporting_quote'):
                    st.markdown('**Full source passage**')
                source_text(passage)
            elif not passage and not ref.get('supporting_quote'):
                st.caption('Supporting passage was not returned with this citation.')
            source_view(service,ref.get('document_id'),filename,f'{key}_{i}',page,ref.get('xml_hash'))
