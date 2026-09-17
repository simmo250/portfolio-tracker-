"""
Streamlit Web Dashboard for the Financial Portfolio Tracker
Run with: python -m streamlit run app.py
"""

import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
from config import DB_USER, DB_PASSWORD, DB_HOST, DB_NAME, PORTFOLIO, START_DATE, END_DATE

# ============================================================
# PAGE CONFIGURATION
# ============================================================
st.set_page_config(
    page_title="Portfolio Tracker",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("📈 Financial Portfolio Performance Tracker")
st.markdown(f"**Analysis Period:** `{START_DATE}` to `{END_DATE}`")
st.markdown("---")

# ============================================================
# DATA LOADING (Cached for speed)
# ============================================================
@st.cache_data
def load_data():
    engine = create_engine(f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}")
    
    # Load prices
    prices = pd.read_sql(
        """SELECT s.symbol, p.trade_date, p.adj_close 
           FROM daily_prices p 
           JOIN stocks s ON s.ticker_id = p.ticker_id""",
        engine, parse_dates=["trade_date"]
    )
    pivot = prices.pivot(index="trade_date", columns="symbol", values="adj_close")
    
    # Load holdings
    holdings = pd.read_sql(
        """SELECT s.symbol, h.shares 
           FROM holdings h 
           JOIN stocks s ON s.ticker_id = h.ticker_id""",
        engine
    )
    return pivot, holdings

try:
    pivot, holdings = load_data()
except Exception as e:
    st.error(f"❌ Could not connect to MySQL: {e}")
    st.stop()

# ============================================================
# CALCULATIONS
# ============================================================
shares = pd.Series(PORTFOLIO)
portfolio_value = (pivot[list(PORTFOLIO.keys())] * shares).sum(axis=1)
daily_returns = pivot.pct_change().dropna()
port_returns = portfolio_value.pct_change().dropna()

total_return = (portfolio_value.iloc[-1] / portfolio_value.iloc[0]) - 1
ann_vol = port_returns.std() * (252 ** 0.5)
ann_ret = port_returns.mean() * 252
sharpe = (ann_ret - 0.04) / ann_vol
max_dd = ((portfolio_value / portfolio_value.cummax()) - 1).min()

# ============================================================
# KPI ROW (Top of dashboard)
# ============================================================
st.subheader("📊 Key Performance Indicators")
col1, col2, col3, col4, col5 = st.columns(5)

col1.metric("Total Return", f"{total_return*100:.2f}%")
col2.metric("Annualized Return", f"{ann_ret*100:.2f}%")
col3.metric("Volatility (Ann.)", f"{ann_vol*100:.2f}%")
col4.metric("Sharpe Ratio", f"{sharpe:.3f}")
col5.metric("Max Drawdown", f"{max_dd*100:.2f}%")

st.markdown("---")

# ============================================================
# CHARTS ROW
# ============================================================
left_col, right_col = st.columns([2, 1])

with left_col:
    st.subheader("💹 Portfolio Value Over Time")
    st.line_chart(portfolio_value, height=400, color="#1F4E78")

with right_col:
    st.subheader("🥧 Portfolio Allocation")
    allocation = pd.Series(PORTFOLIO) * pivot.iloc[-1][list(PORTFOLIO.keys())]
    allocation = allocation.sort_values(ascending=False)
    st.bar_chart(allocation, height=400, color="#1F4E78")

st.markdown("---")

# ============================================================
# ASSET PERFORMANCE TABLE
# ============================================================
st.subheader("📋 Individual Asset Performance")

asset_metrics = []
for symbol in PORTFOLIO.keys():
    rets = daily_returns[symbol]
    total_r = (pivot[symbol].iloc[-1] / pivot[symbol].iloc[0]) - 1
    vol = rets.std() * (252 ** 0.5)
    ret = rets.mean() * 252
    shp = (ret - 0.04) / vol if vol > 0 else 0
    dd = (( (1+rets).cumprod() / (1+rets).cumprod().cummax() ) - 1).min()
    asset_metrics.append({
        "Symbol": symbol,
        "Total Return (%)": round(total_r * 100, 2),
        "Annualized Return (%)": round(ret * 100, 2),
        "Volatility (%)": round(vol * 100, 2),
        "Sharpe Ratio": round(shp, 3),
        "Max Drawdown (%)": round(dd * 100, 2),
    })

asset_df = pd.DataFrame(asset_metrics).sort_values("Sharpe Ratio", ascending=False)
st.dataframe(asset_df, use_container_width=True, hide_index=True)

st.markdown("---")

# ============================================================
# CORRELATION HEATMAP
# ============================================================
st.subheader("🔥 Asset Correlation Matrix")
corr = daily_returns.corr().round(3)
st.dataframe(
    corr.style.background_gradient(cmap="RdYlGn", vmin=-1, vmax=1).format("{:.3f}"),
    use_container_width=True
)

st.caption("Built with Python, MySQL, Pandas, and Streamlit")