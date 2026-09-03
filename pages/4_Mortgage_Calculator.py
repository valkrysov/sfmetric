import streamlit as st
from theme import inject_theme, render_page_header, render_section, render_kpi_row

inject_theme(page_title="Mortgage Calculator", page_icon="🧮")
render_page_header("Mortgage Calculator", "Estimate your monthly payment for a San Francisco home")

# =========================
# INPUTS
# =========================
render_section("Loan Details", accent="#2563EB")

col1, col2 = st.columns(2)

with col1:
    home_price = st.number_input(
        "Home Price ($)",
        min_value=50000,
        max_value=20000000,
        value=1200000,
        step=10000,
    )

    down_payment_pct = st.slider(
        "Down Payment (%)",
        min_value=0,
        max_value=100,
        value=20,
    )

    interest_rate = st.number_input(
        "Interest Rate (annual %)",
        min_value=0.1,
        max_value=15.0,
        value=6.5,
        step=0.05,
    )

with col2:
    loan_term_years = st.selectbox(
        "Loan Term (years)",
        [30, 15, 20, 10],
        index=0,
    )

    property_tax_rate = st.number_input(
        "Property Tax Rate (annual %, CA typical ~1.2%)",
        min_value=0.0,
        max_value=5.0,
        value=1.2,
        step=0.05,
    )

    annual_insurance = st.number_input(
        "Annual Homeowners Insurance ($)",
        min_value=0,
        max_value=50000,
        value=1800,
        step=100,
    )

monthly_hoa = st.number_input(
    "Monthly HOA Fee ($, if applicable)",
    min_value=0,
    max_value=10000,
    value=0,
    step=25,
)

# =========================
# CALCULATIONS
# =========================
down_payment_amount = home_price * (down_payment_pct / 100)
loan_amount = home_price - down_payment_amount

monthly_rate = (interest_rate / 100) / 12
num_payments = loan_term_years * 12

if monthly_rate > 0:
    monthly_principal_interest = (
        loan_amount
        * (monthly_rate * (1 + monthly_rate) ** num_payments)
        / ((1 + monthly_rate) ** num_payments - 1)
    )
else:
    monthly_principal_interest = loan_amount / num_payments if num_payments > 0 else 0

monthly_property_tax = (home_price * (property_tax_rate / 100)) / 12
monthly_insurance = annual_insurance / 12

total_monthly_payment = (
    monthly_principal_interest
    + monthly_property_tax
    + monthly_insurance
    + monthly_hoa
)

total_interest_paid = (monthly_principal_interest * num_payments) - loan_amount

# =========================
# RESULTS
# =========================
render_section("Estimated Monthly Payment", accent="#099250")

render_kpi_row([
    ("Total Monthly Payment", f"${total_monthly_payment:,.0f}", "pos"),
    ("Principal & Interest", f"${monthly_principal_interest:,.0f}", ""),
    ("Property Tax", f"${monthly_property_tax:,.0f}", ""),
    ("Insurance + HOA", f"${monthly_insurance + monthly_hoa:,.0f}", ""),
])

render_section("Loan Summary", accent="#2563EB")

render_kpi_row([
    ("Loan Amount", f"${loan_amount:,.0f}", ""),
    ("Down Payment", f"${down_payment_amount:,.0f}", ""),
    ("Total Interest (life of loan)", f"${total_interest_paid:,.0f}", "neg"),
    ("Total Paid (life of loan)", f"${loan_amount + total_interest_paid:,.0f}", ""),
])

st.markdown("---")
st.caption(
    "This calculator provides an estimate only and does not constitute financial or lending advice. "
    "Actual rates, taxes, and insurance costs vary. Consult a licensed lender for a formal quote."
)