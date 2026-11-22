"""Reachable recovery controls even when the active pointer is unreadable."""
import streamlit as st
from ui.common import action


def render(service=None, startup_error=None):
    if startup_error:
        st.error('The persistent library could not be restored: ' + startup_error)
    else:
        st.error('The local library could not be opened. Your saved source versions have not been changed.')
    st.subheader('Library recovery')
    if service is None:
        st.info('Check config/app.toml and .streamlit/secrets.toml locally, then reload. Keep credentials out of shared reports.')
        st.caption('The Demo tour remains available from the sidebar.')
        return
    if hasattr(service, 'list_recoverable_versions'):
        ok, result = action('Inspect saved library versions', service.list_recoverable_versions)
        if ok:
            for warning in result.get('warnings', []):
                st.warning(warning)
            versions = result.get('versions', [])
            if versions:
                choices = {r['run_id']: r for r in versions}
                selected = st.selectbox('Verified local source version', list(choices),
                    format_func=lambda rid: f"{rid[:12]} · {choices[rid].get('record_count', 0):,} expected records")
                st.caption('Restore checks stored records and search visibility before changing the active version.')
                if st.button('Restore selected library', key='recovery_restore'):
                    ok, _ = action('Restore library', lambda: service.restore_library_version(selected))
                    if ok:
                        st.rerun()
            else:
                st.info('No intact saved version is available. Restore the registered PDFs and registry backup before rebuilding.')
    if hasattr(service, 'recover_working_xml') and st.button('Regenerate working XML', key='recovery_xml'):
        ok, _ = action('Regenerate working XML', service.recover_working_xml)
        if ok:
            st.success('Working XML regenerated from registered source PDFs. Saved published snapshots remain intact.')
