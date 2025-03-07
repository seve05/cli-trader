import requests
import pandas as pd
from tabulate import tabulate
import json
from datetime import datetime
import time
import yfinance as yf

def get_company_info(input_text):
    """Get company CIK from either ticker or company name"""
    try:
        df = pd.read_json('company_tickers.json').T
    except FileNotFoundError:
        url = "https://www.sec.gov/files/company_tickers.json"
        headers = {
            'User-Agent': 'Pizza Destroyer definitelyreal@gmail.com',
            'Accept-Encoding': 'gzip, deflate'
        }
        response = requests.get(url, headers=headers)
        df = pd.read_json(response.text).T
        df.to_json('company_tickers.json')
    
    input_text = input_text.upper()
    # Try ticker match first
    ticker_match = df[df['ticker'] == input_text]
    if not ticker_match.empty:
        company_info = ticker_match.iloc[0]
    else:
        # Try company name match
        name_matches = df[df['title'].str.upper().str.contains(input_text)]
        if name_matches.empty:
            raise ValueError(f"No company found matching '{input_text}'")
        elif len(name_matches) > 1:
            print("\nMultiple matches found:")
            for _, row in name_matches.iterrows():
                print(f"- {row['title']} ({row['ticker']})")
            raise ValueError("Please specify using ticker symbol")
        company_info = name_matches.iloc[0]
    
    return {
        'name': company_info['title'],
        'cik': str(company_info['cik_str']).zfill(10),
        'ticker': company_info['ticker']
    }

def get_quarterly_data(cik):
    """Fetch and process quarterly financial data from SEC XBRL API"""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    headers = {
        'User-Agent': 'Pizza Destroyer definitelyreal@gmail.com',
        'Accept-Encoding': 'gzip, deflate'
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # Extract shares outstanding data from dei namespace
        shares_outstanding_data = {}
        if 'dei' in data.get('facts', {}) and 'EntityCommonStockSharesOutstanding' in data['facts']['dei']:
            shares_data = data["facts"]["dei"]["EntityCommonStockSharesOutstanding"]["units"]["shares"]
            for entry in shares_data:
                if 'frame' in entry:
                    # For instant frames (like CY2023Q1I), remove the I
                    frame = entry['frame'].rstrip('I')
                    # Only process quarterly frames
                    if len(frame) > 6 and frame.startswith('CY'):
                        shares_outstanding_data[frame] = entry['val']
        
        # Define the metrics we want to extract with expanded concept mappings
        metrics = {
            'Revenue': [
                'Revenues', 'Revenue', 'SalesRevenueNet', 
                'RevenueFromContractWithCustomerExcludingAssessedTax',
                'RevenueFromContractWithCustomer'
            ],
            'Gross Profit': [
                'GrossProfit', 'GrossMargin'
            ],
            'Net Profit': [
                'NetIncomeLoss', 'ProfitLoss', 'NetIncome',
                'NetIncomeLossAvailableToCommonStockholdersBasic'
            ],
            'Total Debt': [
                # Direct total debt concepts
                'Debt', 'DebtInstrumentCarryingAmount', 'LongTermDebtAndCapitalLeaseObligations',
                'DebtAndCapitalLeaseObligations', 'DebtAndLeaseObligations',
                # Long-term debt
                'LongTermDebt', 'LongTermDebtNoncurrent', 'LongTermNotesPayable',
                'LongTermBorrowings', 'LongTermLoansPayable',
                # Short-term debt
                'ShortTermDebt', 'ShortTermBorrowings', 'NotesPayableCurrent',
                'LongTermDebtCurrent', 'CurrentPortionOfLongTermDebt',
                'DebtCurrent', 'ShortTermNotesPayable',
                # Combined calculations will be handled in processing
                'CurrentDebtAndCapitalLeaseObligation',
                'LongTermDebtAndCapitalLeaseObligationsNoncurrent'
            ],
            'Cash': [
                'CashAndCashEquivalentsAtCarryingValue', 'Cash',
                'CashAndCashEquivalents', 'CashAndDueFromBanks'
            ]
        }
        
        quarterly_data = {}
        annual_data = {}
        
        # Track debt components separately
        debt_components = {
            'short_term': [
                'ShortTermDebt', 'ShortTermBorrowings', 'NotesPayableCurrent',
                'LongTermDebtCurrent', 'CurrentPortionOfLongTermDebt',
                'DebtCurrent', 'ShortTermNotesPayable',
                'CurrentDebtAndCapitalLeaseObligation'
            ],
            'long_term': [
                'LongTermDebt', 'LongTermDebtNoncurrent', 'LongTermNotesPayable',
                'LongTermBorrowings', 'LongTermLoansPayable',
                'LongTermDebtAndCapitalLeaseObligationsNoncurrent'
            ]
        }
        
        # Process each metric
        for metric, concepts in metrics.items():
            for concept in concepts:
                if concept in data.get('facts', {}).get('us-gaap', {}):
                    concept_data = data['facts']['us-gaap'][concept]
                    units = concept_data.get('units', {})
                    
                    # Try both USD and shares units
                    for unit_type in ['USD', 'shares']:
                        if unit_type in units:
                            values = units[unit_type]
                            
                            # Filter for quarterly reports
                            quarterly_values = []
                            for v in values:
                                if ('form' in v and v['form'] in ['10-Q', '10-K'] and
                                    'frame' in v and 'end' in v):
                                    quarterly_values.append(v)
                            
                            # Sort by date and take most recent value for each quarter
                            for value in quarterly_values:
                                quarter = value['frame']
                                end_date = value['end']
                                
                                # Store annual data separately
                                if (metric in ['Revenue', 'Net Profit', 'Gross Profit']) and len(quarter) == 6:  # CY20XX format
                                    year = quarter
                                    if year not in annual_data:
                                        annual_data[year] = {}
                                    if metric not in annual_data[year] or value.get('filed', '0') > annual_data[year].get(f"{metric}_filed", '0'):
                                        annual_data[year][metric] = value['val']
                                        annual_data[year][f"{metric}_filed"] = value.get('filed', '0')
                                        annual_data[year]['end_date'] = end_date
                                    continue
                                
                                # Remove the 'I' suffix for instant measurements to merge with period measurements
                                base_quarter = quarter.rstrip('I')
                                if base_quarter not in quarterly_data:
                                    quarterly_data[base_quarter] = {'end_date': end_date}
                                
                                # Store debt components separately
                                if metric == 'Total Debt':
                                    component_type = None
                                    if concept in debt_components['short_term']:
                                        component_type = 'short_term_debt'
                                    elif concept in debt_components['long_term']:
                                        component_type = 'long_term_debt'
                                    
                                    if component_type:
                                        if component_type not in quarterly_data[base_quarter] or value.get('filed', '0') > quarterly_data[base_quarter].get(f"{component_type}_filed", '0'):
                                            quarterly_data[base_quarter][component_type] = value['val']
                                            quarterly_data[base_quarter][f"{component_type}_filed"] = value.get('filed', '0')
                                
                                # Only update if we don't have this metric yet or if this is a more recent filing
                                if (metric not in quarterly_data[base_quarter] or 
                                    value.get('filed', '0') > quarterly_data[base_quarter].get(f"{metric}_filed", '0')):
                                    quarterly_data[base_quarter][metric] = value['val']
                                    quarterly_data[base_quarter][f"{metric}_filed"] = value.get('filed', '0')
        
        # Add shares outstanding data to quarterly data
        for quarter, shares in shares_outstanding_data.items():
            if quarter in quarterly_data:
                quarterly_data[quarter]['Shares Outstanding'] = shares
            else:
                quarterly_data[quarter] = {'Shares Outstanding': shares}
        
        # Calculate missing quarters from annual data
        for year, year_data in annual_data.items():
            # Get all quarters for this year
            year_quarters = {q: quarterly_data[q] for q in quarterly_data if q.startswith(year)}
            
            # For each metric in annual data, check if we can calculate missing quarters
            for metric in ['Revenue', 'Net Profit', 'Gross Profit']:
                if metric in year_data:
                    annual_value = year_data[metric]
                    
                    # Get quarters that have this metric
                    quarters_with_metric = {q: year_quarters[q][metric] 
                                          for q in year_quarters 
                                          if metric in year_quarters[q]}
                    
                    # If we have 3 quarters, we can calculate the 4th
                    if len(quarters_with_metric) == 3:
                        # Calculate which quarter is missing
                        all_quarters = [f"{year}Q1", f"{year}Q2", f"{year}Q3", f"{year}Q4"]
                        missing_quarter = next(q for q in all_quarters if q not in quarters_with_metric)
                        
                        # Calculate the missing value
                        sum_of_known = sum(quarters_with_metric.values())
                        missing_value = annual_value - sum_of_known
                        
                        # Add the missing quarter if it's not already in the data
                        if missing_quarter not in quarterly_data:
                            quarterly_data[missing_quarter] = {}
                        
                        # Add the calculated value
                        quarterly_data[missing_quarter][metric] = missing_value
                        quarterly_data[missing_quarter][f"{metric}_calculated"] = True
        
        # Calculate total debt from components if needed
        for quarter in quarterly_data:
            if 'Total Debt' not in quarterly_data[quarter]:
                short_term = quarterly_data[quarter].get('short_term_debt', 0)
                long_term = quarterly_data[quarter].get('long_term_debt', 0)
                if short_term or long_term:
                    quarterly_data[quarter]['Total Debt'] = short_term + long_term
        
        # Fill in missing shares outstanding by propagating known values
        # First, convert to DataFrame for easier manipulation
        df = pd.DataFrame.from_dict(quarterly_data, orient='index')
        
        # If we have shares outstanding data, fill missing values
        if 'Shares Outstanding' in df.columns:
            # Sort by index to ensure chronological order
            df = df.sort_index()
            
            # Forward fill (use previous quarter's value if missing)
            df['Shares Outstanding'] = df['Shares Outstanding'].ffill()
            
            # Backward fill (use next quarter's value if still missing)
            df['Shares Outstanding'] = df['Shares Outstanding'].bfill()
            
            # Convert back to dictionary
            quarterly_data = df.to_dict('index')
        
        # Remove the filing date tracking columns and temporary columns
        for quarter in quarterly_data:
            quarterly_data[quarter] = {k: v for k, v in quarterly_data[quarter].items() 
                                     if not k.endswith('_filed') and not k.endswith('_calculated') 
                                     and k not in ['short_term_debt', 'long_term_debt']}
        
        # Filter out annual rows (CY format)
        quarterly_data = {k: v for k, v in quarterly_data.items() if len(k) > 6}
        
        # Convert to DataFrame
        df = pd.DataFrame.from_dict(quarterly_data, orient='index')
        if not df.empty:
            # Convert end_date to datetime for sorting if it exists
            if 'end_date' in df.columns:
                df['end_date'] = pd.to_datetime(df['end_date'])
                df = df.sort_values('end_date', ascending=False)
                df = df.drop('end_date', axis=1)  # Remove after sorting
            else:
                df = df.sort_index(ascending=False)
                
            df.index.name = 'Quarter'
            df = df.head(20)
        
        return df
    
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        return None
    except Exception as e:
        print(f"Error processing data: {e}")
        return None

def format_value(value):
    """Format numeric values with appropriate scaling"""
    if pd.isna(value) or value is None:
        return 'N/A'
    try:
        value = float(value)
        if abs(value) >= 1e9:
            return f'${value/1e9:.2f}B'
        elif abs(value) >= 1e6:
            return f'${value/1e6:.2f}M'
        elif abs(value) >= 1e3:
            return f'${value/1e3:.2f}K'
        else:
            return f'${value:.2f}'
    except (ValueError, TypeError):
        return str(value)

def display_metrics(df, company_info):
    """Display formatted metrics table"""
    # Format all numeric columns
    formatted_df = df.copy()
    
    for column in formatted_df.columns:
        formatted_df[column] = formatted_df[column].apply(format_value)
    
    # Calculate revenue growth and highlight with different shades of green based on growth percentage
    if 'Revenue' in df.columns:
        revenue_series = pd.to_numeric(df['Revenue'], errors='coerce')
        
        # Create a growth series with the same index as the dataframe
        pct_growth_dict = {}
        
        # Calculate growth for each row except the last one
        for i in range(len(revenue_series) - 1):
            current_idx = revenue_series.index[i]
            next_idx = revenue_series.index[i + 1]
            
            current = revenue_series.loc[current_idx]
            previous = revenue_series.loc[next_idx]
            
            # Handle negative to positive transition
            if previous <= 0 and current > 0:
                # Consider this as significant growth
                pct_growth_dict[current_idx] = 100  # Assign 100% growth for highlighting purposes
            elif previous <= 0 and current <= 0:
                # Less negative is still growth
                if previous < current:
                    # Calculate percentage improvement
                    improvement = ((previous - current) / abs(previous)) * -100
                    pct_growth_dict[current_idx] = improvement
                else:
                    pct_growth_dict[current_idx] = 0  # No growth
            elif previous > 0:
                # Normal percentage calculation
                pct_growth_dict[current_idx] = ((current - previous) / previous) * 100
        
        # The last row has no previous to compare
        if len(revenue_series) > 0:
            pct_growth_dict[revenue_series.index[-1]] = None
        
        # Apply different colors based on growth percentage
        for idx in formatted_df.index:
            if idx in pct_growth_dict:
                g = pct_growth_dict[idx]
                val = formatted_df.at[idx, 'Revenue']
                
                if not pd.isna(g) and g >= 15:
                    formatted_df.at[idx, 'Revenue'] = f'\033[38;5;34m{val}\033[0m'  # Dark green for 15%+
                elif not pd.isna(g) and g >= 10:
                    formatted_df.at[idx, 'Revenue'] = f'\033[38;5;114m{val}\033[0m'  # Medium green for 10-15%
                elif not pd.isna(g) and g >= 5:
                    formatted_df.at[idx, 'Revenue'] = f'\033[38;5;120m{val}\033[0m'  # Light green for 5-10%
    
    print(f"\nQuarterly Financial Metrics for {company_info['name']} ({company_info['ticker']})")
    print("(Green highlights indicate revenue growth: dark=15%+, medium=10%+, light=5%+)")
    print("(Negative to positive transitions are considered significant growth)")
    print("(Missing quarters are calculated from annual data when possible)")
    print(tabulate(formatted_df, headers='keys', tablefmt='grid', showindex=True))

def add_share_prices(df, ticker, cik):
    """Add share prices and market cap to quarterly data using yfinance"""
    try:
        # Get historical stock data
        stock = yf.Ticker(ticker)
        stock_history = stock.history(period="max")
        
        # Create a new column for share prices
        df['Share Price'] = None
        
        # For each quarter, determine the end date and get the stock price
        for idx, row in df.iterrows():
            # Extract year and quarter from the index (e.g., CY2024Q1)
            if not idx.startswith('CY'):
                continue
                
            year = int(idx[2:6])
            quarter = int(idx[7])
            
            # Determine the end date of the quarter
            if quarter == 1:
                end_month, end_day = 3, 31  # March 31
            elif quarter == 2:
                end_month, end_day = 6, 30  # June 30
            elif quarter == 3:
                end_month, end_day = 9, 30  # September 30
            else:  # quarter == 4
                end_month, end_day = 12, 31  # December 31
                
            # Create the date string
            end_date_str = f"{year}-{end_month:02d}-{end_day:02d}"
            
            # Try to get the stock price on that date or the nearest available date
            try:
                # Try exact date match
                if end_date_str in stock_history.index:
                    df.at[idx, 'Share Price'] = stock_history.loc[end_date_str]['Close']
                else:
                    # Find the nearest trading day before the end date
                    nearest_dates = stock_history.index[stock_history.index <= end_date_str]
                    if not nearest_dates.empty:
                        nearest_date = nearest_dates[-1]  # Last date before or on end_date
                        df.at[idx, 'Share Price'] = stock_history.loc[nearest_date]['Close']
            except Exception as e:
                print(f"Could not get stock price for {end_date_str}: {e}")
        
        # Try to get public float data from SEC API
        try:
            url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
            headers = {
                'User-Agent': 'Pizza Destroyer definitelyreal@gmail.com',
                'Accept-Encoding': 'gzip, deflate'
            }
            
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            public_float_data = {}
            
            # Extract public float data
            if 'dei' in data.get('facts', {}) and 'EntityPublicFloat' in data['facts']['dei']:
                if 'USD' in data['facts']['dei']['EntityPublicFloat']['units']:
                    float_data = data["facts"]["dei"]["EntityPublicFloat"]["units"]["USD"]
                    for entry in float_data:
                        if 'frame' in entry and 'val' in entry:
                            # For instant frames (like CY2023Q1I), remove the I
                            frame = entry['frame'].rstrip('I')
                            # Only process quarterly frames
                            if len(frame) > 6 and frame.startswith('CY'):
                                public_float_data[frame] = entry['val']
            
            # Calculate shares outstanding from public float where needed
            if public_float_data and ('Shares Outstanding' not in df.columns or df['Shares Outstanding'].isna().any()):
                # Create the column if it doesn't exist
                if 'Shares Outstanding' not in df.columns:
                    df['Shares Outstanding'] = None
                    
                for idx, row in df.iterrows():
                    if idx in public_float_data and pd.notnull(df.at[idx, 'Share Price']):
                        public_float = public_float_data[idx]
                        share_price = df.at[idx, 'Share Price']
                        
                        # Only calculate if we don't already have shares outstanding
                        if pd.isna(df.at[idx, 'Shares Outstanding']):
                            # Calculate shares outstanding = public float / share price
                            if share_price > 0:  # Avoid division by zero
                                calculated_shares = public_float / share_price
                                df.at[idx, 'Shares Outstanding'] = calculated_shares
                                print(f"Calculated shares for {idx}: {calculated_shares:,.0f} shares")
        
        except Exception as e:
            print(f"Error processing public float data: {e}")
        
        # Fill in missing shares outstanding by propagating known values
        if 'Shares Outstanding' in df.columns:
            # Sort by index to ensure chronological order
            temp_df = df.sort_index().copy()
            
            # Convert to numeric to avoid warnings
            temp_df['Shares Outstanding'] = pd.to_numeric(temp_df['Shares Outstanding'], errors='coerce')
            
            # Forward fill (use previous quarter's value if missing)
            temp_df['Shares Outstanding'] = temp_df['Shares Outstanding'].ffill()
            
            # Backward fill (use next quarter's value if still missing)
            temp_df['Shares Outstanding'] = temp_df['Shares Outstanding'].bfill()
            
            # Update the original dataframe
            for idx in df.index:
                if idx in temp_df.index:
                    df.at[idx, 'Shares Outstanding'] = temp_df.at[idx, 'Shares Outstanding']
        
        # Calculate Market Cap if we have both Share Price and Shares Outstanding
        if 'Share Price' in df.columns and 'Shares Outstanding' in df.columns:
            df['Market Cap'] = df.apply(
                lambda row: row['Share Price'] * row['Shares Outstanding'] 
                if pd.notnull(row['Share Price']) and pd.notnull(row['Shares Outstanding']) 
                else None, 
                axis=1
            )
        
        # Move Share Price and Market Cap to the beginning of the DataFrame
        priority_cols = ['Share Price', 'Market Cap']
        existing_priority = [col for col in priority_cols if col in df.columns]
        other_cols = [col for col in df.columns if col not in existing_priority]
        df = df[existing_priority + other_cols]
        
        return df
    
    except Exception as e:
        print(f"Error fetching stock data for {ticker}: {e}")
        return df

def main():
    print("Enter company name or ticker symbol (e.g., 'Apple' or 'AAPL'):")
    user_input = input("> ")
    
    try:
        company_info = get_company_info(user_input)
        print(f"\nFetching data for {company_info['name']} (CIK: {company_info['cik']})...")
        
        df = get_quarterly_data(company_info['cik'])
        if df is not None and not df.empty:
            # Add share prices and calculate market cap
            df = add_share_prices(df, company_info['ticker'], company_info['cik'])
            display_metrics(df, company_info)
        else:
            print("No quarterly data found for this company")
            
    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    main()


#
#
#
#   add top stocks by country, by market cap
#
#
#
#