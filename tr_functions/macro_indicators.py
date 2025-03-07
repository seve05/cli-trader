import requests
import pandas as pd
import matplotlib.pyplot as plt
from tabulate import tabulate
from datetime import datetime, timedelta
import time
from bs4 import BeautifulSoup
import yfinance as yf
import os

def get_fred_data(series_id, api_key, start_date=None, end_date=None):
    """Fetch data from FRED (Federal Reserve Economic Data)"""
    base_url = "https://api.stlouisfed.org/fred/series/observations"
    
    # Set default dates if not provided
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        # Default to 5 years of data
        start_date = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
    
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": end_date,
        "frequency": "m",  # Monthly data
        "sort_order": "desc"  # Most recent first
    }
    
    response = requests.get(base_url, params=params)
    if response.status_code == 200:
        data = response.json()
        observations = data.get("observations", [])
        
        # Convert to DataFrame
        df = pd.DataFrame(observations)
        if not df.empty:
            df['value'] = pd.to_numeric(df['value'], errors='coerce')
            df['date'] = pd.to_datetime(df['date'])
            return df[['date', 'value']]
    
    return pd.DataFrame()

def get_bls_data(series_id, api_key=None, start_year=None, end_year=None):
    """Fetch data from BLS (Bureau of Labor Statistics) using API v1.0 (no key required)"""
    # Set default years if not provided
    if not end_year:
        end_year = datetime.now().year
    if not start_year:
        start_year = end_year - 5
    
    # BLS API v1.0 (no key required)
    url = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
    
    headers = {
        "Content-Type": "application/json"
    }
    
    data = {
        "seriesid": [series_id],
        "startyear": str(start_year),
        "endyear": str(end_year)
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            result = response.json()
            
            if result.get("status") == "REQUEST_SUCCEEDED":
                series_data = result.get("Results", {}).get("series", [])
                
                if series_data:
                    data_points = series_data[0].get("data", [])
                    
                    # Convert to DataFrame
                    df = pd.DataFrame(data_points)
                    if not df.empty:
                        # Create date column
                        df['date'] = df.apply(lambda row: f"{row['year']}-{row['period'].replace('M', '')}-01", axis=1)
                        df['date'] = pd.to_datetime(df['date'])
                        df['value'] = pd.to_numeric(df['value'], errors='coerce')
                        
                        # Sort by date (most recent first)
                        df = df.sort_values('date', ascending=False)
                        
                        return df[['date', 'value']]
        
        # If API fails, try the fallback method
        print(f"BLS API v1.0 failed for {series_id}, trying fallback method...")
        return get_bls_public_data(series_id, start_year, end_year)
    
    except Exception as e:
        print(f"Error with BLS API: {e}, trying fallback method...")
        return get_bls_public_data(series_id, start_year, end_year)

def get_bls_public_data(series_id, start_year=None, end_year=None):
    """Fallback method to get BLS data from their public website"""
    # This is a simplified approach - for production use, consider using the API with a key
    
    # For unemployment rate (LNS14000000)
    if series_id == "LNS14000000":
        url = "https://data.bls.gov/timeseries/LNS14000000"
        
        try:
            response = requests.get(url)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find the data table
            tables = soup.find_all('table', class_='regular-data')
            
            if tables:
                data = []
                years = []
                
                # Get years from the first row
                year_row = tables[0].find('tr', class_='HeaderDataRow')
                if year_row:
                    for cell in year_row.find_all('th'):
                        if cell.text.strip().isdigit():
                            years.append(int(cell.text.strip()))
                
                # Get monthly data
                for row in tables[0].find_all('tr', class_='DataRow'):
                    cells = row.find_all('td')
                    if cells and len(cells) > 1:
                        month = cells[0].text.strip()
                        if month in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']:
                            month_num = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                                        'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}[month]
                            
                            for i, year in enumerate(years):
                                if i+1 < len(cells):
                                    value = cells[i+1].text.strip()
                                    if value and value != '-':
                                        date = f"{year}-{month_num:02d}-01"
                                        data.append({'date': date, 'value': float(value)})
                
                if data:
                    df = pd.DataFrame(data)
                    df['date'] = pd.to_datetime(df['date'])
                    df = df.sort_values('date', ascending=False)
                    return df
        except Exception as e:
            print(f"Error fetching BLS public data: {e}")
    
    return pd.DataFrame()

def get_treasury_yields():
    """Get current Treasury yield curve data"""
    try:
        # Use a more reliable source for Treasury yields
        import pandas_datareader.data as web
        
        # Get the most recent Treasury yield curve data
        today = datetime.now()
        start_date = today - timedelta(days=7)  # Look back a week to ensure we get data
        
        # Use Treasury constant maturity data from FRED
        maturities = {
            '3-Month': 'DGS3MO',
            '6-Month': 'DGS6MO',
            '1-Year': 'DGS1',
            '2-Year': 'DGS2',
            '5-Year': 'DGS5',
            '10-Year': 'DGS10',
            '30-Year': 'DGS30'
        }
        
        yields = {}
        latest_date = None
        
        for label, series in maturities.items():
            try:
                df = web.DataReader(series, 'fred', start_date, today)
                if not df.empty:
                    # Get the most recent non-NaN value
                    latest = df.dropna().iloc[-1]
                    yields[label] = latest[0]
                    if latest_date is None or latest.name > latest_date:
                        latest_date = latest.name
            except Exception as e:
                print(f"Could not fetch {label} Treasury yield: {e}")
        
        return yields, latest_date
    
    except Exception as e:
        print(f"Error fetching Treasury yields: {e}")
        return {}, None

def get_market_indices():
    """Get current values for major market indices"""
    indices = {
        '^GSPC': 'S&P 500',
        '^DJI': 'Dow Jones',
        '^IXIC': 'NASDAQ',
        '^RUT': 'Russell 2000',
        '^VIX': 'VIX (Volatility Index)'
    }
    
    results = {}
    
    for ticker, name in indices.items():
        try:
            # Use a simpler approach to get current data
            index = yf.Ticker(ticker)
            history = index.history(period="1y")
            
            if not history.empty:
                # Get the most recent close price
                current_price = history['Close'].iloc[-1]
                
                # Calculate YTD change
                # Find the first trading day of the year
                current_year = datetime.now().year
                start_of_year_data = history[history.index.year == current_year]
                if not start_of_year_data.empty:
                    start_price = start_of_year_data['Close'].iloc[0]
                    ytd_change = ((current_price - start_price) / start_price) * 100
                else:
                    ytd_change = None
                
                results[name] = {
                    'Current': current_price,
                    'YTD Change %': ytd_change
                }
            
            # Avoid hitting rate limits
            time.sleep(0.5)
            
        except Exception as e:
            print(f"Error fetching data for {name}: {e}")
    
    return results

def format_date(date):
    """Format date as Month Year"""
    if isinstance(date, str):
        date = pd.to_datetime(date)
    return date.strftime('%b %Y')

def format_percent(value):
    """Format value as percentage with 1 decimal place"""
    if pd.isna(value):
        return "N/A"
    return f"{value:.1f}%"

def format_value(value, is_percent=False):
    """Format numeric value with appropriate precision"""
    if pd.isna(value):
        return "N/A"
    if is_percent:
        return f"{value:.1f}%"
    if value >= 1000000000:
        return f"${value/1000000000:.2f}B"
    if value >= 1000000:
        return f"${value/1000000:.2f}M"
    if value >= 1000:
        return f"${value/1000:.1f}K"
    return f"{value:.2f}"

def clear_screen():
    """Clear the terminal screen"""
    os.system('cls' if os.name == 'nt' else 'clear')

def get_fred_data_no_key(series_id, start_date=None, end_date=None):
    """Fallback method to get FRED data without an API key"""
    try:
        # Use pandas-datareader as a fallback
        import pandas_datareader.data as web
        
        # Set default dates if not provided
        if not end_date:
            end_date = datetime.now()
        else:
            end_date = pd.to_datetime(end_date)
            
        if not start_date:
            start_date = end_date - timedelta(days=5*365)
        else:
            start_date = pd.to_datetime(start_date)
        
        # Fetch data from FRED using pandas-datareader
        df = web.DataReader(series_id, 'fred', start_date, end_date)
        
        # Rename column and reset index to match our format
        df = df.reset_index()
        df.columns = ['date', 'value']
        
        # Sort by date (most recent first)
        df = df.sort_values('date', ascending=False)
        
        return df
    
    except Exception as e:
        print(f"Error fetching FRED data without API key: {e}")
        return pd.DataFrame()

def check_dependencies():
    """Check and install required dependencies"""
    required_packages = {
        'pandas': 'pandas',
        'requests': 'requests',
        'tabulate': 'tabulate',
        'beautifulsoup4': 'bs4',
        'yfinance': 'yfinance',
        'pandas-datareader': 'pandas_datareader'
    }
    
    missing_packages = []
    
    for package, import_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"Missing required packages: {', '.join(missing_packages)}")
        install = input("Would you like to install them now? (y/n): ").lower()
        
        if install == 'y':
            import subprocess
            import sys
            
            for package in missing_packages:
                print(f"Installing {package}...")
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            
            print("All required packages installed. Restarting script...")
            # Re-import the modules
            for package_name in required_packages.values():
                if package_name in sys.modules:
                    del sys.modules[package_name]
            
            return True
        else:
            print("Cannot continue without required packages.")
            return False
    
    return True

def main():
    # Make API keys optional
    print("FRED and BLS API keys are optional. Press Enter to use methods that don't require keys.")
    fred_api_key = input("Enter your FRED API key (optional): ").strip()
    
    # Define the indicators to fetch - using the most reliable series IDs
    indicators = [
        {
            "name": "CPI (YoY Change)",
            "source": "FRED",
            "series_id": "CPIAUCSL",
            "is_percent": True,
            "transform": lambda df: df.assign(
                value=100 * (df['value'] / df['value'].shift(-12) - 1)
            ) if len(df) > 12 else df
        },
        {
            "name": "Core CPI (YoY Change)",
            "source": "FRED",
            "series_id": "CPILFESL",
            "is_percent": True,
            "transform": lambda df: df.assign(
                value=100 * (df['value'] / df['value'].shift(-12) - 1)
            ) if len(df) > 12 else df
        },
        {
            "name": "Unemployment Rate",
            "source": "BLS",
            "series_id": "LNS14000000",
            "is_percent": True
        },
        {
            "name": "GDP Growth (QoQ)",
            "source": "FRED",
            "series_id": "GDPC1",
            "is_percent": True,
            "transform": lambda df: df.assign(
                value=100 * (df['value'] / df['value'].shift(-1) - 1)
            ) if len(df) > 1 else df
        },
        {
            "name": "Federal Funds Rate",
            "source": "FRED",
            "series_id": "FEDFUNDS",
            "is_percent": True
        },
        {
            "name": "10-Year Treasury Yield",
            "source": "FRED",
            "series_id": "GS10",
            "is_percent": True
        },
        {
            "name": "2-Year Treasury Yield",
            "source": "FRED",
            "series_id": "GS2",
            "is_percent": True
        },
        {
            "name": "Housing Starts",
            "source": "FRED",
            "series_id": "HOUST",
            "is_percent": False,
            "transform": lambda df: df.assign(
                value=df['value'] * 1000  # Convert from thousands to actual number
            ) if not df.empty else df
        },
        {
            "name": "Retail Sales (MoM Change)",
            "source": "FRED",
            "series_id": "RSXFS",
            "is_percent": True,
            "transform": lambda df: df.assign(
                value=100 * (df['value'] / df['value'].shift(-1) - 1)
            ) if len(df) > 1 else df
        },
        {
            "name": "Industrial Production",
            "source": "FRED",
            "series_id": "INDPRO",
            "is_percent": False
        }
    ]
    
    print("\nFetching US macroeconomic indicators...\n")
    
    # Fetch data for each indicator
    results = []
    
    for indicator in indicators:
        print(f"Fetching {indicator['name']}...")
        
        if indicator['source'] == 'FRED':
            if fred_api_key:
                df = get_fred_data(indicator['series_id'], fred_api_key)
            else:
                df = get_fred_data_no_key(indicator['series_id'])
        elif indicator['source'] == 'BLS':
            df = get_bls_data(indicator['series_id'])  # No API key needed
        else:
            # Fallback to empty DataFrame
            df = pd.DataFrame()
        
        # Apply any transformations
        if 'transform' in indicator and not df.empty:
            try:
                df = indicator['transform'](df)
            except Exception as e:
                print(f"Error transforming data for {indicator['name']}: {e}")
        
        # Get the most recent values
        if not df.empty:
            try:
                latest = df.iloc[0]
                previous = df.iloc[1] if len(df) > 1 else None
                
                # Find data from a year ago (approximately 12 months)
                year_ago = None
                if len(df) > 12:
                    year_ago_date = latest['date'] - pd.DateOffset(months=12)
                    year_ago_candidates = df[df['date'] <= year_ago_date]
                    if not year_ago_candidates.empty:
                        year_ago = year_ago_candidates.iloc[0]
                
                results.append({
                    'Indicator': indicator['name'],
                    'Latest': latest['value'],
                    'Latest Date': latest['date'],
                    'Previous': previous['value'] if previous is not None else None,
                    'Previous Date': previous['date'] if previous is not None else None,
                    'Year Ago': year_ago['value'] if year_ago is not None else None,
                    'Year Ago Date': year_ago['date'] if year_ago is not None else None,
                    'Is Percent': indicator.get('is_percent', False)
                })
            except Exception as e:
                print(f"Error processing results for {indicator['name']}: {e}")
    
    # Get Treasury yield curve
    print("Fetching Treasury yield curve...")
    treasury_yields, yield_date = get_treasury_yields()
    
    # Get market indices
    print("Fetching market indices...")
    market_indices = get_market_indices()
    
    # Display results
    #clear_screen()
    
    # Format the data for display
    table_data = []
    for result in results:
        is_percent = result['Is Percent']
        
        # Calculate changes
        prev_change = None
        if result['Previous'] is not None and not pd.isna(result['Previous']):
            prev_change = result['Latest'] - result['Previous']
            
        year_change = None
        if result['Year Ago'] is not None and not pd.isna(result['Year Ago']):
            year_change = result['Latest'] - result['Year Ago']
        
        table_data.append([
            result['Indicator'],
            format_value(result['Latest'], is_percent),
            format_date(result['Latest Date']),
            format_value(prev_change, is_percent) if prev_change is not None else "N/A",
            format_value(year_change, is_percent) if year_change is not None else "N/A"
        ])
    
    # Print the main economic indicators table
    print("\n---- US MACROECONOMIC INDICATORS ----\n")
    print(tabulate(
        table_data,
        headers=['Indicator', 'Latest Value', 'Date', 'Change (MoM)', 'Change (YoY)'],
        tablefmt='grid'
    ))
    
    # Print Treasury yields
    if treasury_yields:
        print("\n---- US TREASURY YIELDS ----\n")
        yield_data = [[k, f"{v:.2f}%" if v is not None else "N/A"] for k, v in treasury_yields.items()]
        print(tabulate(
            yield_data,
            headers=['Maturity', 'Yield'],
            tablefmt='grid'
        ))
        if yield_date:
            print(f"As of: {format_date(yield_date)}")
    
    # Print market indices
    if market_indices:
        print("\n---- MARKET INDICES ----\n")
        indices_data = []
        for name, data in market_indices.items():
            indices_data.append([
                name,
                format_value(data['Current'], False),
                format_percent(data['YTD Change %']) if data['YTD Change %'] is not None else "N/A"
            ])
        
        print(tabulate(
            indices_data,
            headers=['Index', 'Current Value', 'YTD Change'],
            tablefmt='grid'
        ))
        print(f"As of: {datetime.now().strftime('%b %d, %Y')}")

if __name__ == "__main__":
    if check_dependencies():
        main() 
