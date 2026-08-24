# ============================================================
# SFMETRIC SHARED THEME — Clean Light
# Single source of truth for styling across all pages.
# Import and call inject_theme() at the top of every page.
# ============================================================

import streamlit as st


def inject_theme(page_title, page_icon="🏙️"):
    """Call once, first thing, on every page."""

    st.set_page_config(
        page_title=f"{page_title} · SFMETRIC",
        page_icon=page_icon,
        layout="wide",
    )

    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    /* ---------- BASE ---------- */
    .stApp { background-color: #FAFBFC; }
    [data-testid="stSidebar"] {
        background-color: #FFFFFF;
        border-right: 1px solid #E4E7EC;
    }
    h1, h2, h3, .stMarkdown p {
        font-family: 'Inter', sans-serif;
        color: #101828;
    }

    /* ---------- SIDEBAR BRAND ---------- */
    .sfm-brand {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 4px 0 16px 0;
        margin-bottom: 12px;
        border-bottom: 1px solid #E4E7EC;
    }
    .sfm-brand-mark { font-size: 20px; }
    .sfm-brand-text {
        font-family: 'Inter', sans-serif;
        font-weight: 700;
        font-size: 14px;
        color: #101828;
        letter-spacing: 0.01em;
    }
    .sfm-brand-sub {
        font-family: 'Inter', sans-serif;
        font-size: 10px;
        color: #667085;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    /* ---------- PAGE TITLE ---------- */
    .sfm-title {
        font-family: 'Inter', sans-serif;
        font-weight: 700;
        font-size: 26px;
        color: #101828;
        letter-spacing: -0.02em;
        margin-bottom: 2px;
    }
    .sfm-subtitle {
        font-family: 'Inter', sans-serif;
        font-size: 13px;
        font-weight: 500;
        color: #667085;
        margin-bottom: 24px;
    }

    /* ---------- SECTION HEADER ---------- */
    .sfm-section {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-top: 32px;
        margin-bottom: 12px;
        padding-left: 10px;
        border-left: 3px solid var(--accent, #2563EB);
    }
    .sfm-section-title {
        font-family: 'Inter', sans-serif;
        font-size: 13px;
        font-weight: 700;
        color: #101828;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .sfm-section-caption {
        font-family: 'Inter', sans-serif;
        font-size: 12px;
        color: #667085;
        margin-left: 13px;
        margin-bottom: 14px;
    }

    /* ---------- KPI CARD GRID ---------- */
    .sfm-kpi-row {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
        gap: 12px;
        margin-bottom: 8px;
    }
    .sfm-kpi {
        background-color: #FFFFFF;
        border: 1px solid #E4E7EC;
        border-radius: 8px;
        padding: 14px 16px;
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    }
    .sfm-kpi-label {
        font-family: 'Inter', sans-serif;
        font-size: 11px;
        font-weight: 600;
        color: #667085;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 6px;
    }
    .sfm-kpi-value {
        font-family: 'Inter', sans-serif;
        font-size: 21px;
        font-weight: 700;
        color: #101828;
        font-variant-numeric: tabular-nums;
    }
    .sfm-kpi-value.pos { color: #099250; }
    .sfm-kpi-value.neg { color: #D92D20; }

    /* ---------- SIGNAL / STATUS BANNER ---------- */
    .sfm-signal {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 14px 18px;
        border-radius: 8px;
        margin-bottom: 16px;
        font-family: 'Inter', sans-serif;
        border: 1px solid transparent;
    }
    .sfm-signal-label { font-size: 13px; font-weight: 700; letter-spacing: 0.01em; }
    .sfm-signal-score {
        font-family: 'Inter', sans-serif;
        font-size: 13px;
        font-weight: 600;
        font-variant-numeric: tabular-nums;
        opacity: 0.85;
    }
    .sfm-signal.seller   { background-color: #ECFDF3; border-color: #ABEFC6; color: #067647; }
    .sfm-signal.balanced { background-color: #FFFAEB; border-color: #FEDF89; color: #B54708; }
    .sfm-signal.buyer    { background-color: #FEF3F2; border-color: #FECDCA; color: #B42318; }
    .sfm-signal.info     { background-color: #EFF4FF; border-color: #B2CCFF; color: #1849A9; }

    /* ---------- BUTTONS ---------- */
    div.stButton > button {
        background-color: #2563EB;
        color: #FFFFFF;
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        font-size: 13px;
        padding: 0.5em 1.6em;
        border-radius: 6px;
        border: none;
        transition: all 0.15s ease;
        box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
    }
    div.stButton > button:hover { background-color: #1D4ED8; }

/* ---------- TIGHTEN STREAMLIT DEFAULTS ---------- */
[data-testid="stVerticalBlock"] { gap: 0.5rem; }
.block-container { padding-top: 4rem; padding-bottom: 2rem; }
[data-testid="stDataFrame"] {
    border: 1px solid #E4E7EC;
    border-radius: 8px;
}

    </style>
    """, unsafe_allow_html=True)

    st.sidebar.markdown("""
        <div class="sfm-brand">
            <span class="sfm-brand-mark">🏙️</span>
            <div>
                <div class="sfm-brand-text">SFMETRIC</div>
                <div class="sfm-brand-sub">SF Housing Intelligence</div>
            </div>
        </div>
    """, unsafe_allow_html=True)


def render_page_header(title, subtitle):
    st.markdown(f'<div class="sfm-title">{title}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sfm-subtitle">{subtitle}</div>', unsafe_allow_html=True)


def render_section(title, caption=None, accent="#2563EB"):
    st.markdown(f"""
        <div class="sfm-section" style="--accent: {accent};">
            <div class="sfm-section-title">{title}</div>
        </div>
    """, unsafe_allow_html=True)
    if caption:
        st.markdown(f'<div class="sfm-section-caption">{caption}</div>', unsafe_allow_html=True)


def render_kpi_row(items):
    """items: list of (label, value, css_class) tuples. css_class: '', 'pos', or 'neg'."""
    cards = "".join(
        f"""<div class="sfm-kpi">
                <div class="sfm-kpi-label">{label}</div>
                <div class="sfm-kpi-value {cls}">{value}</div>
            </div>"""
        for label, value, cls in items
    )
    st.markdown(f'<div class="sfm-kpi-row">{cards}</div>', unsafe_allow_html=True)


def render_status_banner(label, score_text, kind="info"):
    """kind: 'seller', 'balanced', 'buyer', or 'info'"""
    st.markdown(f"""
        <div class="sfm-signal {kind}">
            <div class="sfm-signal-label">{label}</div>
            <div class="sfm-signal-score">{score_text}</div>
        </div>
    """, unsafe_allow_html=True)