Filings analysis running LLM locally with easier SEC interfacing using their API. 

The LLM is supposed to give an overview of the selected filing, I was trying to build a way to load up the historical filings
such that it would be able to explain the most current filing in context. 
This would be useful if you need to quickly make decisions or even just for looking up different companies, for DD essentially.

Challenges: I tried to program this by implementing a RAG solution, but quickly found out that this approach is not the way,
as many companies structure their filings differently and I could not get consistent enough data to generate useful embeddings.
Second approach simply loaded it all into the context window and then the user is able to prompt questions about it. This is limited
by the size of the models context window and VRAM.
All in all for local models I find a simple summary of single filings more useful, being able to ask questions about some terms, be it 
domain specific or even legal formalities which is why this is only present in the last version.

This project is by no means complete, I cannot even guarantee that it works in its current state because of the dependency mayhem. 
It was exploratory for me at the time because this was the first use-case I could think of as I first discovered that these models could be run locally.
I might come back to this in the future (doubt it though because reading these filings manually is actually a lot of fun). 
With new knowledge and better resources this could very well work.

Added quarterly overview of financials trying out Cursor for this.(its ok.. more precise prompts == better results) 

This requires Ollama install and the specific model you want to use.
1. install dependencies: `pip install -r /path/to/requirements.txt`
2. navigate to folder `cli_trader/tr_functions`
3. `python3 any_of_the_tools`
