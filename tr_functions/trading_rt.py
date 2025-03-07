import yfinance as yf
import time
from tabulate import tabulate
import os
import sys
import threading
import queue

def get_stock_data(ticker):
    stock = yf.Ticker(ticker)
    info = stock.info
    
    return {
        'symbol': ticker.upper(),
        'price': info.get('regularMarketPrice', 'N/A'),
        'volume': info.get('volume', 0),
        'market_open': info.get('regularMarketOpen', 'N/A'),
        'market_close': info.get('previousClose', 'N/A'),
        'change_%': round(((info.get('regularMarketPrice', 0) - info.get('previousClose', 0)) / 
                          info.get('previousClose', 1)) * 100, 2) if info.get('previousClose') else 'N/A'
    }

def input_listener(command_queue):
    """Listen for user input in a separate thread"""
    while True:
        command = input("\nEnter additional tickers (space separated) or commands:\n"
                        "- 'remove TICKER' to remove a ticker\n"
                        "- 'clear' to clear all tickers\n"
                        "- 'exit' to quit\n> ")
        command_queue.put(command)
        # Don't sleep here - it causes the cursor to move back

def clear_screen():
    """Clear the terminal screen"""
    # Check if we're on Windows or Unix-like
    if os.name == 'nt':  # Windows
        os.system('cls')
    else:  # Unix-like (Linux, macOS)
        os.system('clear')

def main():
    # Get user input for initial tickers
    tickers_input = input("Enter stock tickers separated by space (e.g., AAPL MSFT GOOGL): ")
    valid_tickers = validate_tickers(tickers_input.split())
    
    if not valid_tickers:
        print("No valid tickers provided. Exiting...")
        return

    refresh_rate = 1  # Refresh every second
    command_queue = queue.Queue()
    
    # Start input listener thread
    input_thread = threading.Thread(target=input_listener, args=(command_queue,), daemon=True)
    input_thread.start()
    
    # Clear screen and print header
    clear_screen()
    print("\nReal-Time Stock Data (sorted by volume)")
    print(f"Refreshing every {refresh_rate} seconds. You can add more tickers below.\n")
    
    try:
        first_run = True
        lines_printed = 0
        screen_needs_refresh = False
        
        while True:
            # Check for new commands
            processing_command = False
            while not command_queue.empty():
                processing_command = True
                command = command_queue.get().strip()
                
                if command.lower() == 'exit':
                    print("\nExiting program...")
                    return
                
                elif command.lower() == 'clear':
                    valid_tickers = []
                    print("Cleared all tickers.")
                    screen_needs_refresh = True
                
                elif command.lower().startswith('remove '):
                    ticker_to_remove = command[7:].strip().upper()
                    if ticker_to_remove in valid_tickers:
                        valid_tickers.remove(ticker_to_remove)
                        print(f"Removed {ticker_to_remove}")
                        screen_needs_refresh = True
                    else:
                        print(f"{ticker_to_remove} not in current list")
                
                else:
                    # Assume it's a list of tickers to add
                    new_tickers = validate_tickers(command.split())
                    if new_tickers:  # Only mark for refresh if we actually added tickers
                        for ticker in new_tickers:
                            if ticker not in valid_tickers:
                                valid_tickers.append(ticker)
                                print(f"Added {ticker}")
                        screen_needs_refresh = True
            
            # If we processed a command, give the input thread time to reset
            if processing_command:
                time.sleep(0.1)
                
            # Skip data fetching if no tickers
            if not valid_tickers:
                time.sleep(refresh_rate)
                continue
                
            # Get data for all stocks
            stocks_data = []
            for ticker in valid_tickers:
                try:
                    stock_data = get_stock_data(ticker)
                    stocks_data.append(stock_data)
                except Exception as e:
                    print(f"Error fetching data for {ticker}: {e}")
            
            # Sort by volume
            stocks_data.sort(key=lambda x: x['volume'], reverse=True)
            
            # Prepare table
            headers = ['Symbol', 'Price', 'Volume', 'Open', 'Prev Close', 'Change %']
            table_data = [[
                stock['symbol'],
                stock['price'],
                f"{stock['volume']:,}",
                stock['market_open'],
                stock['market_close'],
                f"{stock['change_%']}%"
            ] for stock in stocks_data]
            
            # Clear screen if needed (after user commands)
            if screen_needs_refresh:
                clear_screen()
                print("\nReal-Time Stock Data (sorted by volume)")
                print(f"Refreshing every {refresh_rate} seconds. You can add more tickers below.\n")
                first_run = True  # Force a full redraw
                screen_needs_refresh = False
            
            # For the first iteration or after screen clear, just print the table
            if first_run:
                first_run = False
                table_output = tabulate(table_data, headers=headers, tablefmt='grid')
                print(table_output)
                lines_printed = table_output.count('\n') + 1
                
                # Print the input prompt once after the table
                print("\nEnter additional tickers (space separated) or commands:")
                print("- 'remove TICKER' to remove a ticker")
                print("- 'clear' to clear all tickers")
                print("- 'exit' to quit")
                print("> ", end='', flush=True)  # No newline, just the prompt
            else:
                # Only update the table, not the input area
                if os.environ.get('ANSI_SUPPORT', '1') == '1':
                    # Save cursor position
                    sys.stdout.write("\033[s")
                    # Move cursor to the top of the table area
                    sys.stdout.write(f"\033[{lines_printed + 6}A")
                    sys.stdout.flush()
                    
                    # Print the updated table
                    table_output = tabulate(table_data, headers=headers, tablefmt='grid')
                    print(table_output)
                    lines_printed = table_output.count('\n') + 1
                    
                    # Restore cursor position
                    sys.stdout.write("\033[u")
                    sys.stdout.flush()
                else:
                    # For terminals without ANSI support, just print a new table
                    print("\nUpdated data:")
                    table_output = tabulate(table_data, headers=headers, tablefmt='grid')
                    print(table_output)
                    print("> ", end='', flush=True)
            
            time.sleep(refresh_rate)
            
    except KeyboardInterrupt:
        print("\nExiting program...")

def validate_tickers(tickers):
    """Validate a list of tickers and return only valid ones"""
    valid_tickers = []
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            stock.info
            valid_tickers.append(ticker.upper())
        except:
            print(f"Invalid ticker: {ticker}")
    return valid_tickers

if __name__ == "__main__":
    main()
