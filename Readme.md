@"
# Financial Portfolio Performance Tracker

End-to-end data analytics project that ingests live stock market data, stores it in MySQL, performs financial analysis, and displays results via an interactive Streamlit dashboard.

## Project Overview
This project demonstrates a complete ETL pipeline combined with financial analytics and data visualization. It tracks an 8-stock portfolio against the S&P 500 benchmark over a 5-year period.

### Key Metrics
- Total & Annualized Return
- Volatility (annualized standard deviation)
- Sharpe Ratio (risk-adjusted return)
- Maximum Drawdown
- Asset Correlation Matrix

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Data Ingestion | yfinance (Yahoo Finance API) |
| Data Cleaning | pandas, numpy |
| Database | MySQL 8.0 |
| SQL Analytics | CTEs, Window Functions |
| Reporting | xlsxwriter (Excel), Streamlit (Web) |

## Setup Instructions
1. Clone this repo
2. pip install -r requirements.txt
3. Copy config.example.py to config.py and add your MySQL password
4. Create database: CREATE DATABASE college;
5. Run: python portfolio_analyzer.py
6. Run: python -m streamlit run app.py

## Sample Results
| Metric | Value |
|--------|-------|
| Total Return | 149.22% |
| Annualized Return | 21.09% |
| Volatility | 23.49% |
| Sharpe Ratio | 0.728 |
| Max Drawdown | -32.22% |
| Final Portfolio Value | Dollar 60565.73 |

## Author
**Simran Gupta**
- M.Tech Student
"@ | Out-File -Encoding utf8 README.md