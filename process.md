1. Run a BigQuery in GDELTS Database for newspaper articles for 10 major English and Hindi newspapers in India between 2023 and 2024 election cycle - extracted arounf 1 million articles.
2. Clean and refine - removed horoscope, sports, crime etc.
4. Filter the relevant topics 
5. Extract full text for those specific articles (~500K) - running Trafilatura for comprehensive scraping
6. Before running the pipeline, ensure the following:
  - Create embeddings using transformers - preferably BAAI/bge-m3
  - After that, ensure that you save those embedding as .npy files, and thenm merge with the extraction from last step - this gives a topic label (eg. crime, LPG, war etc, to each article)
  - Then, run BERTopic script to put them into large topic buckets - can run into the thousands.
  - To simplify, we create three levels of topics - totaling 15.
  - 
8. Run the pipeline (already built)
