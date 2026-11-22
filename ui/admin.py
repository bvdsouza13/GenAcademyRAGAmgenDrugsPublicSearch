"""Routine full-library administration, separate from legacy passage review."""
import streamlit as st
from amgen_explorer.auth import require_admin
from ui.common import hero
from ui import library_admin, chunk_experiments


def render(service,corpus,active,*,settings=None):
    require_admin(settings)
    hero('Manage the medicine library', 'Load all source documents, then test and choose chunk settings.', 'ADMIN')
    st.caption('Authorized library administration workspace.')
    library, experiments = st.tabs(['Library', 'Chunk experiments'])
    with library:
        library_admin.render(service,corpus,active)
    with experiments:
        chunk_experiments.render(service,corpus,active)
