import streamlit as st
from sqlalchemy import create_engine


@st.cache_resource
def get_engine():

    return create_engine(
        st.secrets["DATABASE_URL"]
    )