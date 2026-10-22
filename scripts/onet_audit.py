"""Internal review only: python3 -m streamlit run scripts/onet_audit.py."""
import sys
from pathlib import Path

# Streamlit also supports launching this script directly from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st
from app import render_audit
from src.i18n import LANGUAGE_OPTIONS, initialize_language, language_name

initialize_language(st.session_state)
st.set_page_config(page_title='O*NET data audit', layout='wide')
st.selectbox('🌐', LANGUAGE_OPTIONS, key='ui_language', format_func=language_name)
render_audit(st)
