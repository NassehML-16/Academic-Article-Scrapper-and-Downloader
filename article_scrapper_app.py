# ==========================================
# STREAMLIT MULTI-DATABASE LITERATURE SCRAPER
# ==========================================

import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
import urllib.parse
import re
from io import BytesIO
import zipfile
import os

st.set_page_config(page_title="Academic Article Scraper", layout="wide")

# ==========================================
# UI HEADER
# ==========================================
st.title("📚 Academic Article Scraper & Downloader")
st.markdown("Search multiple academic databases, deduplicate results, filter, and export or bulk download articles.")

# ==========================================
# SIDEBAR INPUTS
# ==========================================
st.sidebar.header("Search Settings")
query = st.sidebar.text_area("Search Query")
year_low = st.sidebar.text_input("Start Year", "2000")
year_high = st.sidebar.text_input("End Year", "2025")
max_results = st.sidebar.number_input("Max Results (≤1000)", min_value=10, max_value=1000, value=50, step=10)

databases = st.sidebar.multiselect(
    "Select Databases",
    ["Google Scholar", "Crossref", "OpenAlex", "Semantic Scholar", "PubMed", "Scopus (API Key required)"],
    default=["Crossref", "OpenAlex"]
)

scopus_key = ""
if "Scopus (API Key required)" in databases:
    scopus_key = st.sidebar.text_input("Enter Scopus API Key", type="password")
    if not scopus_key:
        st.warning("Scopus selected: Please enter your API key.")

start_btn = st.sidebar.button("🚀 Run Search")

# ==========================================
# SCRAPING FUNCTIONS
# ==========================================
def scrape_crossref(query, max_results):
    url = f"https://api.crossref.org/works?query={urllib.parse.quote(query)}&rows={max_results}"
    r = requests.get(url).json()
    results = []
    for item in r['message']['items']:
        results.append({
            "Title": item.get("title", [""])[0],
            "Authors": ", ".join([a.get("family","") for a in item.get("author",[])]),
            "Year": item.get("issued", {}).get("date-parts", [[None]])[0][0],
            "Journal": item.get("container-title", [""])[0],
            "Citations": item.get("is-referenced-by-count", 0),
            "Link": item.get("URL", "")
        })
    return results

def scrape_openalex(query, max_results):
    url = f"https://api.openalex.org/works?search={urllib.parse.quote(query)}&per-page={max_results}"
    r = requests.get(url).json()
    results = []
    for item in r['results']:
        results.append({
            "Title": item.get("title"),
            "Authors": ", ".join([a['author']['display_name'] for a in item.get('authorships',[])]),
            "Year": item.get("publication_year"),
            "Journal": item.get("host_venue", {}).get("display_name"),
            "Citations": item.get("cited_by_count", 0) if item.get("cited_by_count") is not None else 0,
            "Link": item.get("id")
        })
    return results

def scrape_semantic(query, max_results):
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={urllib.parse.quote(query)}&limit={max_results}&fields=title,authors,year,citationCount,url"
    r = requests.get(url).json()
    results = []
    for item in r.get("data", []):
        results.append({
            "Title": item.get("title"),
            "Authors": ", ".join([a.get("name") for a in item.get("authors",[])]),
            "Year": item.get("year"),
            "Journal": "",
            "Citations": item.get("citationCount", 0) if item.get("citationCount") is not None else 0,
            "Link": item.get("url")
        })
    return results

def scrape_pubmed(query, max_results):
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmax={max_results}&term={urllib.parse.quote(query)}&retmode=json"
    ids = requests.get(url).json()["esearchresult"]["idlist"]
    results = []
    for pid in ids:
        results.append({"Title": f"PubMed ID {pid}", "Authors": "", "Year": "", "Journal": "", "Citations": 0, "Link": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/"})
    return results

def scrape_scholar(query, year_low, year_high, max_results):
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    session.get("https://scholar.google.com", headers=headers)
    time.sleep(random.uniform(2, 5))

    results = []
    progress_bar = st.progress(0)
    
    for start in range(0, max_results, 10):
        encoded = urllib.parse.quote_plus(query)
        url = f"https://scholar.google.com/scholar?q={encoded}&as_ylo={year_low}&as_yhi={year_high}&start={start}"

        r = session.get(url, headers=headers)
        soup = BeautifulSoup(r.text, "html.parser")
        listings = soup.select(".gs_r.gs_or.gs_scl")
        
        if not listings:
            break

        for item in listings:
            title_tag = item.select_one(".gs_rt")
            authors_tag = item.select_one(".gs_a")
            snippet_tag = item.select_one(".gs_rs")
            footer_links = item.select(".gs_fl a")
            
            authors, year, journal, citations = "N/A", "N/A", "N/A", 0
            
            if authors_tag:
                meta_text = authors_tag.text
                parts = meta_text.split("-")
                authors = parts[0].strip() if len(parts) > 0 else "N/A"
                if len(parts) > 1:
                    year_match = re.search(r"\b(19|20)\d{2}\b", parts[1])
                    if year_match: year = year_match.group()
                    journal = parts[1].strip()

            # Fix for Citations
            for a in footer_links:
                if "Cited by" in a.text:
                    try:
                        # Extract only digits from "Cited by 123"
                        cite_val = re.sub(r"\D", "", a.text)
                        citations = int(cite_val) if cite_val else 0
                    except:
                        citations = 0
            
            results.append({
                "Title": title_tag.text if title_tag else "",
                "Authors": authors,
                "Year": year,
                "Journal": journal,
                "Citations": citations,
                "Link": title_tag.find("a")["href"] if title_tag and title_tag.find("a") else "",
                "Abstract": snippet_tag.text if snippet_tag else ""
            })
        
        progress_bar.progress(min((start + 10) / max_results, 1.0))
        # Large delay to avoid Google bot detection
        time.sleep(random.uniform(5, 10)) 
        
    return results

def scrape_scopus(query, max_results, api_key):
    headers = {"X-ELS-APIKey": api_key}
    url = f"https://api.elsevier.com/content/search/scopus?query={urllib.parse.quote(query)}&count={max_results}"
    r = requests.get(url, headers=headers)
    results = []
    try:
        data = r.json().get("search-results", {}).get("entry", [])
        for item in data:
            results.append({
                "Title": item.get("dc:title"),
                "Authors": item.get("dc:creator",""),
                "Year": item.get("prism:coverDate","")[:4],
                "Journal": item.get("prism:publicationName",""),
                "Citations": int(item.get("citedby-count", 0)),
                "Link": item.get("prism:url","")
            })
    except:
        st.warning("Error fetching Scopus data. Check API key.")
    return results

# ==========================================
# RUN SEARCH
# ==========================================
if start_btn and query:
    all_results = []

    with st.spinner("Searching databases..."):
        if "Crossref" in databases:
            all_results += scrape_crossref(query, max_results)
        if "OpenAlex" in databases:
            all_results += scrape_openalex(query, max_results)
        if "Semantic Scholar" in databases:
            all_results += scrape_semantic(query, max_results)
        if "PubMed" in databases:
            all_results += scrape_pubmed(query, max_results)
        if "Google Scholar" in databases:
            all_results += scrape_scholar(query, year_low, year_high, max_results)
        if "Scopus (API Key required)" in databases and scopus_key:
            all_results += scrape_scopus(query, max_results, scopus_key)

    if not all_results:
        st.error("No results found.")
    else:
        df = pd.DataFrame(all_results)
        
        # Ensure Citations is numeric and handle NaNs
        df["Citations"] = pd.to_numeric(df["Citations"], errors='coerce').fillna(0).astype(int)

        # ==========================================
        # DEDUPLICATION
        # ==========================================
        dedup = st.checkbox("Remove duplicate articles (by Title)")
        total_articles = len(df)
        if dedup:
            df = df.drop_duplicates(subset=["Title"], keep="first")
            st.info(f"Total extracted: {total_articles} | After deduplication: {len(df)}")

        # ==========================================
        # FILTERS
        # ==========================================
        min_cite = st.slider("Minimum Citations", 0, 500, 0)
        df = df[df["Citations"] >= min_cite]

        # ==========================================
        # DISPLAY
        # ==========================================
        st.subheader(f"📊 Results ({len(df)})")
        st.dataframe(df, use_container_width=True)

        # ==========================================
        # DOWNLOAD SCRAPED DATA
        # ==========================================
        col1, col2 = st.columns(2)
        with col1:
            st.download_button("Download CSV", df.to_csv(index=False), "results.csv", mime="text/csv")

        with col2:
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False)
            excel_buffer.seek(0)
            st.download_button(
                "Download Excel",
                data=excel_buffer,
                file_name="results.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

# ==========================================
# BULK DOWNLOAD FROM EXCEL
# ==========================================
st.divider()
st.subheader("📥 Bulk Download from Excel")
uploaded_file = st.file_uploader(
    "Upload Excel with columns: Title, Link",
    type=["xlsx", "xls"]
)
if uploaded_file:
    df_upload = pd.read_excel(uploaded_file)
    if "Title" not in df_upload.columns or "Link" not in df_upload.columns:
        st.error("Excel must contain 'Title' and 'Link' columns.")
    else:
        st.info(f"Preparing to download {len(df_upload)} files...")
        zip_buffer = BytesIO()
        progress_dl = st.progress(0)
        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            for i, row in df_upload.iterrows():
                title = str(row["Title"]).strip()
                link = row["Link"]
                try:
                    if pd.isna(link) or str(link).strip() == "":
                        continue
                    r = requests.get(link, timeout=20)
                    ext = "pdf" if "application/pdf" in r.headers.get("Content-Type","") else "html"
                    filename = f"{title[:50]}.{ext}".replace("/", "_").replace("\\", "_")
                    zip_file.writestr(filename, r.content)
                except Exception as e:
                    st.warning(f"Failed to download '{title}': {e}")
                progress_dl.progress((i+1)/len(df_upload))
        
        st.download_button(
            "Download All Articles as ZIP",
            zip_buffer.getvalue(),
            file_name="articles.zip"
        )
