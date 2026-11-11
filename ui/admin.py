"""Routine full-library administration, separate from legacy passage review."""
import streamlit as st
from ui.common import hero
from ui import library_admin, chunk_experiments


def render(service,corpus,active):
    hero('Manage the medicine library', 'Load all source documents, then test and choose chunk settings.', 'ADMIN')
    st.caption('Local administration workspace · Shared-host authentication is outside this prototype.')
    library, experiments = st.tabs(['Library', 'Chunk experiments'])
    with library:
        library_admin.render(service,corpus,active)
    with experiments:
        chunk_experiments.render(service,corpus,active)
