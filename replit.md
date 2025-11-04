# Overview

This is an IDX (Indonesia Stock Exchange) Stock Screener application built with Streamlit. The application filters Indonesian stocks that meet specific criteria: stocks that have risen at least 2% for 2 consecutive days with a minimum trading volume of 15 billion IDR. The app focuses on major IDX stocks and provides data visualization and filtering capabilities using Yahoo Finance as the data source.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Frontend Architecture

**Technology**: Streamlit web framework
- **Rationale**: Streamlit provides a simple, Python-native way to build data-driven web applications without requiring separate frontend/backend code
- **Design Pattern**: Single-page application with reactive UI updates
- **Layout**: Wide layout configuration for better data table visualization
- **Pros**: Rapid development, Python-only codebase, built-in data visualization
- **Cons**: Limited customization compared to traditional web frameworks

## Data Processing Layer

**Stock Data Management**:
- **Data Source**: Yahoo Finance API via yfinance library
- **Rationale**: Free, reliable access to real-time and historical stock data for Indonesian stocks
- **Caching Strategy**: Not yet implemented but recommended for production use
- **Data Format**: Pandas DataFrames for efficient tabular data manipulation

**Filtering Logic**:
- **Problem**: Need to identify stocks with sustained upward momentum
- **Solution**: Multi-day consecutive gain analysis (2%+ for 2 days) with volume threshold (15B IDR minimum)
- **Implementation**: Time-series analysis on historical price data

## Utility Functions

**Currency Formatting**:
- **format_idr()**: Converts numeric values to Indonesian Rupiah with appropriate scaling (Trillion/T, Billion/M, Million/Jt)
- **Rationale**: Improves readability for Indonesian users familiar with local currency conventions

**Data Fetching**:
- **get_stock_data()**: Wrapper around yfinance API for stock data retrieval
- **Default Period**: 5 days of historical data
- **Returns**: Both historical price data and stock metadata

## Application State

**Stock Universe**: Hardcoded list of 76 major IDX stocks
- **Coverage**: Blue-chip stocks across sectors (banking, telecom, consumer goods, commodities, real estate, etc.)
- **Format**: Yahoo Finance ticker symbols with .JK suffix for Jakarta Stock Exchange
- **Rationale**: Focuses on liquid, high-quality stocks rather than entire exchange

# External Dependencies

## Third-Party Libraries

**streamlit**:
- Purpose: Web application framework and UI components
- Features Used: Page configuration, layout, markdown rendering, data display

**yfinance**:
- Purpose: Yahoo Finance API client
- Usage: Fetch historical stock prices, trading volumes, and stock metadata
- Data Points: OHLCV (Open, High, Low, Close, Volume) data and company information

**pandas**:
- Purpose: Data manipulation and analysis
- Usage: DataFrame operations for filtering, sorting, and transforming stock data

**datetime**:
- Purpose: Date and time manipulation
- Usage: Calculate date ranges for historical data queries

## External APIs

**Yahoo Finance**:
- Service: Real-time and historical market data provider
- Endpoint: Accessed via yfinance library wrapper
- Data Format: JSON responses converted to pandas DataFrames
- Rate Limits: Subject to Yahoo Finance API limitations
- Coverage: Indonesian Stock Exchange (IDX) stocks with .JK suffix

## Data Dependencies

**Stock Ticker Symbols**:
- Source: Hardcoded list of IDX stocks
- Format: Yahoo Finance ticker convention (e.g., BBCA.JK for Bank Central Asia)
- Maintenance: Requires manual updates for new listings or delistings