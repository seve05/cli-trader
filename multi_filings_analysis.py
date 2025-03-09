import ollama
import base64
from bs4 import BeautifulSoup
import requests
import re 
import time
from langchain.prompts import PromptTemplate
from langchain.chains import RetrievalQA, MapReduceChain, LLMChain,ReduceDocumentsChain
#from langchain.chains.combine_documents.stuff import StuffDocumentsChain
#from langchain.chains.question_answering import load_qa_chain

from langchain_ollama import OllamaLLM

import json
import pandas as pd
import tqdm  
import os
from functools import partial
# sudo systemctl edit ollama.service, open in vim (preferably)



def cut_string(text, sequence):
    index = text.find(sequence) #read string to find sequence
    
    if index != -1:
        return text[:index + len(sequence)]  
    else:
        return text



def load_filings_csv():
    all_filings = []
    with open('documentstore.txt','r', encoding='utf-8') as file:
        all_filings = file.read().split(',')
        file.close()
    return all_filings



def load_hundred_filingnum(cik):
    """Load filing numbers for specific form types (10-K, 10-Q, 8-K, 13D, 13G)"""
    time.sleep(1/10)
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    print(url)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'}
    response = requests.get(url, headers=headers)
    data = response.json()
    
    target_forms = ['10-K', '10-Q', '8-K', '13D', '13G', 'SC 13D', 'SC 13G']
    
    recent_forms = data['filings']['recent']['form']
    recent_accessions = data['filings']['recent']['accessionNumber']
    recent_dates = data['filings']['recent']['filingDate']
    
    filtered_filings = []
    filtered_forms = []
    filtered_dates = []
    count = 0
    
    # Iterate through the filings and filter by form type
    for form, accession, date in zip(recent_forms, recent_accessions, recent_dates):
        if form in target_forms:
            filtered_filings.append(accession)
            filtered_forms.append(form)
            filtered_dates.append(date)
            count += 1
            if count >= 10:  # Show last 10 filings #############################################################################################################################filingsnum
                break
    
    if not filtered_filings:
        print(f"Warning: No {', '.join(target_forms)} filings found for this CIK")
        return None
    
    print(f"\nFound {len(filtered_filings)} relevant filings:")
    for i, (form, acc, date) in enumerate(zip(filtered_forms, filtered_filings, filtered_dates)):
        print(f"{i+1}. Form {form} ({date}): {acc}")
    
    try:
        selection = int(input("\nSelect a filing to analyze (1-{0}): ".format(len(filtered_filings))))
        if 1 <= selection <= len(filtered_filings):
            return [filtered_filings[selection-1]]  # Return single filing as list
        else:
            print(f"Please enter a number between 1 and {len(filtered_filings)}")
    except ValueError:
        print("Please enter a valid number")



def scrape_hundredfilings(cik):
    file = open('documentstore.txt','w') #clear the file
    file.write(" ")
    file.close()
    filingnumbers = load_hundred_filingnum(cik)
    if not filingnumbers:  # Handle case where no filings were found
        return
        
    for filingnum in filingnumbers:
        nodash = filingnum.replace("-","")
        header = {
            'User-Agent': 'SeverinComp severin.comp@gmail.com', 
            'Accept-Encoding':'gzip, deflate'
        }
        
        # First get the index page to find the main document
        index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/index.json"
        index_response = requests.get(index_url, headers=header)
        index_data = index_response.json()
        
        # Find the main document (usually form 10-K, 10-Q, etc.)
        main_doc = None
        for file in index_data['directory']['item']:
            if file['name'].endswith('.htm') and not file['name'].startswith('R'):
                main_doc = file['name']
                break
                
        if not main_doc:
            print(f"Could not find main document for filing {filingnum}")
            continue
            
        # Get the document content using the document viewer URL
        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{main_doc}"
        print(f"\nFetching filing: {doc_url}")
        doc_response = requests.get(doc_url, headers=header)
        
        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(doc_response.text, 'html.parser')
        
        # Remove unwanted elements
        for tag in soup.find_all(['script', 'style', 'table']):
            tag.decompose()
            
        # Extract text content
        text_content = soup.get_text(separator=' ', strip=True)
        
        # Basic cleaning
        text_content = re.sub(r'\s+', ' ', text_content)  # Remove extra whitespace
        text_content = re.sub(r'^\s*$\n', '', text_content, flags=re.MULTILINE)  # Remove empty lines
        
        # Try to find the main content section (often between ITEM 1 and SIGNATURES)
        start_marker = re.search(r'ITEM\s+1\.?', text_content, re.IGNORECASE)
        end_marker = re.search(r'SIGNATURES?', text_content, re.IGNORECASE)
        
        if start_marker and end_marker:
            text_content = text_content[start_marker.start():end_marker.end()]
        
        print("\nFiling loaded\n")
        file = open('documentstore.txt','a')
        file.write(text_content)
        file.write(',')
    file.close()



def clean_filings(inp):
    text = inp[0]
    
    # Basic cleaning
    text = re.sub(r'\s+', ' ', text)  # normalize whitespace
    text = re.sub(r'[\r\n]+', '\n', text)  # normalize newlines
    text = re.sub(r'[^\x00-\x7F]+', '', text)  # ASCII Alphabet 8bits is all you need)
    
    # Remove common SEC filing artifacts
    text = re.sub(r'Table of Contents', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^\s*\[\d+\]\s*$', '', text, flags=re.MULTILINE)  # remove page numbers
    
    # Remove any remaining HTML entities
    text = re.sub(r'&[a-zA-Z]+;', ' ', text)
    text = re.sub(r'&#\d+;', ' ', text)
    
    return [text.strip()]



def load_documents(filename):
    documents = []
    with open(filename, 'r') as file:
        documents.append(file.read())
    return documents



def get_company_cik(company_name):

    try:
        df = pd.read_json('company_tickers.json').T
    except FileNotFoundError:
        url = "https://www.sec.gov/files/company_tickers.json"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        df = pd.read_json(response.text).T
        df.to_json('company_tickers.json')
    
    df['title'] = df['title'].str.lower()
    company_name = company_name.lower()
    
    # Try to find an exact match first
    matches = df[df['title'] == company_name]
    if len(matches) == 0:
        # If no exact match, try partial matching
        matches = df[df['title'].str.contains(company_name, case=False, na=False)]
    
    if len(matches) == 0:
        raise ValueError(f"No company found matching '{company_name}'")
    elif len(matches) > 1:
        print("Multiple matches found:")
        for _, row in matches.iterrows():
            print(f"- {row['title']} (CIK: {row['cik_str']})")
        raise ValueError("Please provide a more specific company name")
    
    # Pad CIK with leading zeros to 10 digits
    cik = str(matches.iloc[0]['cik_str']).zfill(10)
    return cik



def getlatestfiling(cik):
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'}
    response = requests.get(url, headers=headers)
    recent = response.json()['filings']['recent']['accessionNumber'][0]
    return recent



def get_company_info_from_ticker(ticker):
    #Get company name and CIK from ticker symbol from json
    try:
        df = pd.read_json('company_tickers.json').T
    except FileNotFoundError:
        # Fetch and save the data if not cached
        url = "https://www.sec.gov/files/company_tickers.json"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        df = pd.read_json(response.text).T
        df.to_json('company_tickers.json')
    
    # Convert ticker to uppercase for matching
    ticker = ticker.upper()
    
    # Try to find an exact match for the ticker
    matches = df[df['ticker'] == ticker]
    
    if len(matches) == 0:
        raise ValueError(f"No company found with ticker symbol '{ticker}'")
    
    # Get the company info
    company_info = matches.iloc[0]
    return {
        'name': company_info['title'],
        'cik': str(company_info['cik_str']).zfill(10),
        'ticker': company_info['ticker']
    }



def clean_llm_output(text):
    # Use regex to remove anything between <think> and </think> tags (including the tags)
    cleaned_text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    return cleaned_text.strip()






                            #main code filings
##########################################################################################
def Multi_pipeline(company_name):
    """Process a single SEC filing and enable interactive Q&A directly with the full document"""
    try:
        cik = get_company_cik(company_name)
        print(f"Found CIK: {cik} for company: {company_name}")
        scrape_hundredfilings(cik)
        documentsaslist = load_documents('documentstore.txt')
        finaldocuments = documentsaslist
        print(f"Length of document: {len(finaldocuments[0])}")
        print("----------------------------Loading data done-----------------------------------")
        
        # Initialize LLM
        qa_llm = OllamaLLM(
            model='deepseek-r1:7b',
            temperature=0,  # Lower temperature for more factual responses, 0 for no hallucination
        ) ##############################################################################################################################llmmodel
        
        # Get the full document text
        full_document = finaldocuments[0]
        # Create a summary prompt template
        summary_prompt_template = """You are an expert financial analyst assistant analyzing SEC filings.
        
        Below is the full text of an SEC filing. First, summarize this filing in a structured format with the following information:
        1. Company Name: [Extract the exact legal name of the company]
        2. Filing Type: [Identify the exact SEC form type (10-K, 10-Q, 8-K, etc.)]
        3. Reporting Period: [Identify the exact reporting period or date]
        4. Key Financial Metrics: [List 3-5 key financial metrics with exact figures]
        5. Main Business Activities: [Briefly describe the company's main business]
        6. Key Highlights: [List 3-5 main highlights or important disclosures]
        
        Keep your summary concise, factual, and well-structured.
        
        SEC Filing:
        {document}
        
        Summary:"""
        
        SUMMARY_PROMPT = PromptTemplate.from_template(full_document)
        
        # Create a QA prompt template that uses the entire document
        qa_prompt_template = """You are an expert financial analyst assistant analyzing SEC filings.
        
        Below is the full text of an SEC filing. Use this document to answer the question at the end.
        If you don't know the answer, just say that you don't know, don't try to make up an answer.
        Always maintain a professional tone and be precise with financial information.
        
        SEC Filing:
        {document}
        
        Question: {question}
        
        Answer:"""
        
        QA_PROMPT = PromptTemplate.from_template(qa_prompt_template)
        
        # Generate an overview of the filing
        print("\nGenerating an overview of the filing...")
        
        try:
            # Create a chain for the summary
            summary_chain = LLMChain(llm=qa_llm, prompt=SUMMARY_PROMPT)
            
            # Generate the summary and clean it
            raw_summary = summary_chain.run(document=full_document)
            summary = clean_llm_output(raw_summary)
            
            print("\n=== FILING OVERVIEW ===")
            print(summary)
            print("=======================\n")
            
        except Exception as e:
            print(f"Error generating overview: {str(e)}")

        print("\nEntering Q&A mode. Type 'exit' to quit.")
        while True:
            question = input("\nAsk a question about the filing (or 'exit' to quit): ")
            if question.lower() == 'exit':
                break
            
            try:
                # Create a chain for Q&A
                qa_chain = LLMChain(llm=qa_llm, prompt=QA_PROMPT)
                
                # Generate the answer using the full document and clean it
                raw_answer = qa_chain.run(document=full_document, question=question)
                answer = clean_llm_output(raw_answer)
                
                print("\nAnswer:", answer)
                
            except Exception as e:
                print(f"Error generating answer: {str(e)}")

        return "Q&A session completed"

    except ValueError as e:
        print(f"Error: {e}")
        return




if __name__ == "__main__"   #if run as main python program:
    user_input = input("Enter company name or ticker symbol: ").upper()
    
    try:
        if user_input:
            company_info = get_company_info_from_ticker(user_input)
            print(f"Found company: {company_info['name']} (CIK: {company_info['cik']})")
            company_name = company_info['name']
        else:
            company_name = user_input
        
        Multi_pipeline(company_name)

    except ValueError as e:
        print(f"Error: {e}")
        print("Please try again with a valid company name or ticker symbol.")
    except KeyboardInterrupt:
        print("\nExiting Q&A mode...")

#
#        -   add in stocks and shareprice, revenue  as context for more robust answer
#
#   good so far except for the 10K which is too large (approx 100k tokens)
#
#       batch processing for enything above 50k length, split into parts 
#       then during q and a LL M needs to be able to access documents to answer questions, no vectordb o embeddings 
#       - create hash map for every documents contents such that llm can select which document to open 
#       (dont have to search every document)
#               - this happens during the splitting process (creates hashmap/dict)
