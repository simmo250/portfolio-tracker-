"""
Financial Portfolio Performance Tracker (MySQL Version)
========================================================
End-to-end ETL + Analysis + Reporting pipeline.
"""

import os
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import create_engine, text
import xlsxwriter

from config import (
    PORTFOLIO, BENCHMARK, START_DATE, END_DATE,
    RISK_FREE_RATE, EXCEL_PATH,
    DB_USER, DB_PASSWORD, DB_HOST, DB_NAME
)

warnings.filterwarnings("ignore")

# ============================================================
# STEP 1: EXTRACT — Download data from Yahoo Finance
# ============================================================
def fetch_market_data():
    """Download adjusted close prices for portfolio + benchmark."""
    tickers = list(PORTFOLIO.keys()) + [BENCHMARK]
    print(f"📥 Downloading data for: {', '.join(tickers)}")

    data = yf.download(
        tickers,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=False,
        progress=False,
        group_by="ticker",
    )

    frames = []
    for ticker in tickers:
        df = data[ticker].copy()
        df["Symbol"] = ticker
        df = df.reset_index().rename(columns={
            "Date": "trade_date",
            "Open": "open_price",
            "High": "high_price",
            "Low": "low_price",
            "Close": "close_price",
            "Adj Close": "adj_close",
            "Volume": "volume",
        })
        frames.append(df)

    long_df = pd.concat(frames, ignore_index=True)
    long_df["trade_date"] = pd.to_datetime(long_df["trade_date"]).dt.date
    long_df = long_df.dropna(subset=["adj_close"])
    print(f"✅ Downloaded {len(long_df):,} rows across {len(tickers)} tickers.")
    return long_df


# ============================================================
# STEP 2: LOAD — Store data into MySQL
# ============================================================
def load_to_mysql(df):
    """Create schema and load data into MySQL."""
    os.makedirs("output", exist_ok=True)
    
    # MySQL Connection String
    connection_string = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
    print(f"🔌 Connecting to MySQL database '{DB_NAME}'...")
    
    try:
        engine = create_engine(connection_string)
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        print(f"\n❌ MySQL Connection Error: {e}")
        print("Please check your username, password, and database name in config.py")
        return None

    # Read and Execute Schema
    with open("database_setup.sql", "r") as f:
        schema_sql = f.read()

    with engine.begin() as conn:
        for stmt in schema_sql.split(";"):
            if stmt.strip():
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    # Ignore drop table errors if tables don't exist yet
                    if "Unknown table" not in str(e) and "1051" not in str(e):
                        print(f"SQL Warning: {e}")

    # Insert stocks
    stocks_df = pd.DataFrame({
        "symbol": list(PORTFOLIO.keys()) + [BENCHMARK],
        "company_name": [
            "Apple Inc.", "Microsoft Corp.", "Alphabet Inc.",
            "Amazon.com Inc.", "JPMorgan Chase & Co.",
            "Johnson & Johnson", "Exxon Mobil Corp.", "Tesla Inc.",
            "SPDR S&P 500 ETF Trust"
        ],
        "sector": [
            "Technology", "Technology", "Technology", "Consumer Discretionary",
            "Financials", "Healthcare", "Energy", "Consumer Discretionary",
            "Benchmark"
        ],
        "is_benchmark": [0]*len(PORTFOLIO) + [1],
    })
    stocks_df.to_sql("stocks", engine, if_exists="append", index=False)

    # Map ticker symbols -> ticker_id
    with engine.connect() as conn:
        ticker_map = pd.read_sql("SELECT ticker_id, symbol FROM stocks", conn)
    df = df.merge(ticker_map, left_on="Symbol", right_on="symbol", how="left")

    # Insert daily prices
    prices_df = df[[
        "ticker_id", "trade_date", "open_price", "high_price",
        "low_price", "close_price", "adj_close", "volume"
    ]].copy()
    prices_df.to_sql("daily_prices", engine, if_exists="append", index=False)

    # Insert holdings
    holdings_df = pd.DataFrame({
        "ticker_id": [ticker_map.loc[ticker_map.symbol == t, "ticker_id"].iloc[0]
                      for t in PORTFOLIO.keys()],
        "shares": list(PORTFOLIO.values()),
    })
    holdings_df.to_sql("holdings", engine, if_exists="append", index=False)

    print(f"✅ Loaded {len(prices_df):,} price rows into MySQL.")
    return engine


# ============================================================
# STEP 3A: SQL ANALYSIS — Business queries (MySQL Syntax)
# ============================================================
# NOTE: DATE_FORMAT is used instead of SQLite's strftime()
SQL_MONTHLY_RETURNS = """
WITH monthly_prices AS (
    SELECT
        s.symbol,
        DATE_FORMAT(p.trade_date, '%%Y-%%m') AS month,
        p.adj_close,
        ROW_NUMBER() OVER (
            PARTITION BY s.symbol, DATE_FORMAT(p.trade_date, '%%Y-%%m')
            ORDER BY p.trade_date DESC
        ) AS rn
    FROM daily_prices p
    JOIN stocks s ON s.ticker_id = p.ticker_id
)
SELECT
    symbol,
    month,
    adj_close AS month_end_price,
    LAG(adj_close) OVER (PARTITION BY symbol ORDER BY month) AS prev_month_price,
    ROUND(
        (adj_close - LAG(adj_close) OVER (PARTITION BY symbol ORDER BY month))
        / LAG(adj_close) OVER (PARTITION BY symbol ORDER BY month) * 100, 2
    ) AS monthly_return_pct
FROM monthly_prices
WHERE rn = 1
ORDER BY symbol, month;
"""

SQL_MOVING_AVERAGES = """
SELECT
    s.symbol,
    p.trade_date,
    p.adj_close,
    ROUND(AVG(p.adj_close) OVER (
        PARTITION BY s.symbol ORDER BY p.trade_date
        ROWS BETWEEN 49 PRECEDING AND CURRENT ROW
    ), 2) AS ma_50,
    ROUND(AVG(p.adj_close) OVER (
        PARTITION BY s.symbol ORDER BY p.trade_date
        ROWS BETWEEN 199 PRECEDING AND CURRENT ROW
    ), 2) AS ma_200
FROM daily_prices p
JOIN stocks s ON s.ticker_id = p.ticker_id
WHERE s.symbol = 'AAPL'
ORDER BY p.trade_date DESC
LIMIT 10;
"""

SQL_PORTFOLIO_VALUE = """
SELECT
    p.trade_date,
    ROUND(SUM(p.adj_close * h.shares), 2) AS portfolio_value
FROM daily_prices p
JOIN holdings h ON h.ticker_id = p.ticker_id
GROUP BY p.trade_date
ORDER BY p.trade_date;
"""

def run_sql_analysis(engine):
    """Execute business SQL queries and return DataFrames."""
    print("🔍 Running SQL analysis...")
    results = {}
    with engine.connect() as conn:
        results["monthly_returns"]   = pd.read_sql(SQL_MONTHLY_RETURNS, conn)
        results["moving_averages"]   = pd.read_sql(SQL_MOVING_AVERAGES, conn)
        results["portfolio_value"]   = pd.read_sql(SQL_PORTFOLIO_VALUE, conn)
    print(f"✅ SQL analysis complete: {len(results)} result sets.")
    return results


# ============================================================
# STEP 3B: PYTHON ANALYSIS — Financial metrics
# ============================================================
def compute_metrics(engine):
    """Calculate returns, volatility, Sharpe, drawdown per ticker."""
    print("📊 Computing financial metrics...")
    with engine.connect() as conn:
        prices = pd.read_sql(
            """SELECT s.symbol, p.trade_date, p.adj_close
               FROM daily_prices p
               JOIN stocks s ON s.ticker_id = p.ticker_id
               ORDER BY s.symbol, p.trade_date""",
            conn, parse_dates=["trade_date"]
        )

    pivot = prices.pivot(index="trade_date", columns="symbol", values="adj_close")
    daily_returns = pivot.pct_change().dropna()

    shares = pd.Series(PORTFOLIO)
    portfolio_value = (pivot[list(PORTFOLIO.keys())] * shares).sum(axis=1)
    portfolio_returns = portfolio_value.pct_change().dropna()

    metrics = []
    for symbol in pivot.columns:
        rets = daily_returns[symbol]
        total_ret = (pivot[symbol].iloc[-1] / pivot[symbol].iloc[0]) - 1
        ann_vol = rets.std() * np.sqrt(252)
        ann_ret = rets.mean() * 252
        sharpe = (ann_ret - RISK_FREE_RATE) / ann_vol if ann_vol > 0 else 0
        cum = (1 + rets).cumprod()
        drawdown = (cum / cum.cummax()) - 1
        max_dd = drawdown.min()
        metrics.append({
            "Symbol": symbol,
            "Total Return (%)": round(total_ret * 100, 2),
            "Annualized Return (%)": round(ann_ret * 100, 2),
            "Annualized Volatility (%)": round(ann_vol * 100, 2),
            "Sharpe Ratio": round(sharpe, 3),
            "Max Drawdown (%)": round(max_dd * 100, 2),
        })

    metrics_df = pd.DataFrame(metrics).sort_values("Sharpe Ratio", ascending=False)

    port_total = (portfolio_value.iloc[-1] / portfolio_value.iloc[0]) - 1
    port_vol = portfolio_returns.std() * np.sqrt(252)
    port_ret = portfolio_returns.mean() * 252
    port_sharpe = (port_ret - RISK_FREE_RATE) / port_vol
    port_cum = (1 + portfolio_returns).cumprod()
    port_dd = (port_cum / port_cum.cummax()) - 1

    summary = {
        "Total Return (%)": round(port_total * 100, 2),
        "Annualized Return (%)": round(port_ret * 100, 2),
        "Annualized Volatility (%)": round(port_vol * 100, 2),
        "Sharpe Ratio": round(port_sharpe, 3),
        "Max Drawdown (%)": round(port_dd.min() * 100, 2),
        "Final Portfolio Value ($)": round(portfolio_value.iloc[-1], 2),
    }

    corr = daily_returns.corr().round(3)

    print(f"✅ Metrics computed for {len(metrics_df)} securities.")
    return {
        "asset_metrics": metrics_df,
        "summary": summary,
        "portfolio_value": portfolio_value,
        "daily_returns": daily_returns,
        "correlation": corr,
    }


# ============================================================
# STEP 4: EXCEL DASHBOARD
# ============================================================
def build_excel_dashboard(sql_results, metrics, engine):
    os.makedirs("output", exist_ok=True)
    print("📤 Building Excel dashboard...")

    with pd.ExcelWriter(EXCEL_PATH, engine="xlsxwriter") as writer:
        workbook = writer.book

        title_fmt  = workbook.add_format({"bold": True, "font_size": 18, "font_color": "#1F4E78"})
        header_fmt = workbook.add_format({"bold": True, "bg_color": "#1F4E78", "font_color": "white", "border": 1, "align": "center"})
        num_fmt    = workbook.add_format({"num_format": "#,##0.00"})
        pct_fmt    = workbook.add_format({"num_format": "0.00%"})
        ratio_fmt  = workbook.add_format({"num_format": "0.000"})

        ws = workbook.add_worksheet("Dashboard")
        ws.write("A1", "📈 Portfolio Performance Dashboard", title_fmt)
        ws.write("A2", f"Period: {START_DATE} to {END_DATE}")

        summary = metrics["summary"]
        ws.write("A4", "Key Performance Indicators", header_fmt)
        row = 5
        for k, v in summary.items():
            ws.write(row, 0, k)
            if "(%)" in k:
                ws.write_number(row, 1, v / 100, pct_fmt)
            else:
                ws.write_number(row, 1, v, num_fmt)
            row += 1

        pv = metrics["portfolio_value"].reset_index()
        pv.columns = ["Date", "Portfolio Value"]
        pv.to_excel(writer, sheet_name="Data_PortfolioValue", index=False)

        chart = workbook.add_chart({"type": "line"})
        chart.add_series({
            "name": "Portfolio Value",
            "categories": ["Data_PortfolioValue", 1, 0, len(pv), 0],
            "values":     ["Data_PortfolioValue", 1, 1, len(pv), 1],
            "line": {"color": "#1F4E78", "width": 2.5},
        })
        chart.set_title({"name": "Portfolio Value Over Time"})
        chart.set_size({"width": 900, "height": 400})
        ws.insert_chart("D5", chart)

        metrics["asset_metrics"].to_excel(writer, sheet_name="Asset_Metrics", index=False)
        ws2 = writer.sheets["Asset_Metrics"]
        for i, col in enumerate(metrics["asset_metrics"].columns):
            ws2.set_column(i, i, max(15, len(col) + 2))
            ws2.write(0, i, col, header_fmt)

        metrics["correlation"].to_excel(writer, sheet_name="Correlation")
        ws3 = writer.sheets["Correlation"]
        ws3.conditional_format(1, 1, len(metrics["correlation"]), len(metrics["correlation"]),
            {"type": "3_color_scale", "min_color": "#F8696B", "mid_color": "#FFEB84", "max_color": "#63BE7B"})

        sql_results["monthly_returns"].to_excel(writer, sheet_name="Monthly_Returns", index=False)
        sql_results["moving_averages"].to_excel(writer, sheet_name="Moving_Averages_AAPL", index=False)
        sql_results["portfolio_value"].to_excel(writer, sheet_name="SQL_Portfolio_Value", index=False)

    print(f"✅ Excel dashboard saved to {EXCEL_PATH}")


# ============================================================
# MAIN PIPELINE
# ============================================================
def main():
    print("=" * 60)
    print("  FINANCIAL PORTFOLIO PERFORMANCE TRACKER (MySQL)")
    print("=" * 60)

    raw_df = fetch_market_data()
    engine = load_to_mysql(raw_df)
    
    if engine is None:
        print("❌ Pipeline stopped due to database connection error.")
        return

    sql_results = run_sql_analysis(engine)
    metrics     = compute_metrics(engine)
    build_excel_dashboard(sql_results, metrics, engine)

    print("\n" + "=" * 60)
    print("  PORTFOLIO SUMMARY")
    print("=" * 60)
    for k, v in metrics["summary"].items():
        print(f"  {k:<35} {v}")
    print("=" * 60)
    print("\n✅ Project complete! Open the Excel file to view the dashboard.")


if __name__ == "__main__":
    main()