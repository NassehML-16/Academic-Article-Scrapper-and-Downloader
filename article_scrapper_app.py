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

def get_stealth_headers():
    """Returns a randomized set of headers to mimic a real browser."""
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0"
    ]
    return {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Referer": "https://scholar.google.com/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }

def scrape_crossref(query, max_results):
    url = f"https://api.crossref.org/works?query={urllib.parse.quote(query)}&rows={max_results}"
    try:
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
    except: return []

def scrape_openalex(query, max_results):
    url = f"https://api.openalex.org/works?search={urllib.parse.quote(query)}&per-page={max_results}"
    try:
        r = requests.get(url).json()
        results = []
        for item in r['results']:
            results.append({
                "Title": item.get("title"),
                "Authors": ", ".join([a['author']['display_name'] for a in item.get('authorships',[])]),
                "Year": item.get("publication_year"),
                "Journal": item.get("host_venue", {}).get("display_name"),
                "Citations": item.get("cited_by_count", 0) if item.get("cited_by_count") else 0,
                "Link": item.get("id")
            })
        return results
    except: return []

def scrape_semantic(query, max_results):
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={urllib.parse.quote(query)}&limit={max_results}&fields=title,authors,year,citationCount,url"
    try:
        r = requests.get(url).json()
        results = []
        for item in r.get("data", []):
            results.append({
                "Title": item.get("title"),
                "Authors": ", ".join([a.get("name") for a in item.get("authors",[])]),
                "Year": item.get("year"),
                "Journal": "",
                "Citations": item.get("citationCount", 0) if item.get("citationCount") else 0,
                "Link": item.get("url")
            })
        return results
    except: return []

def scrape_pubmed(query, max_results):
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmax={max_results}&term={urllib.parse.quote(query)}&retmode=json"
    try:
        ids = requests.get(url).json()["esearchresult"]["idlist"]
        results = []
        for pid in ids:
            results.append({"Title": f"PubMed ID {pid}", "Authors": "", "Year": "", "Journal": "", "Citations": 0, "Link": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/"})
        return results
    except: return []

def scrape_scholar(query, year_low, year_high, max_results):
    session = requests.Session()
    results = []
    progress_bar = st.progress(0)
    
    for start in range(0, max_results, 10):
        # Update headers every page to rotate User-Agent
        current_headers = get_stealth_headers()
        
        encoded = urllib.parse.quote_plus(query)
        url = f"https://scholar.google.com/scholar?q={encoded}&as_ylo={year_low}&as_yhi={year_high}&start={start}"

        try:
            r = session.get(url, headers=current_headers, timeout=15)
            if r.status_code == 429:
                st.error("Google Scholar has blocked the request (Too Many Requests). Try again later or reduce Max Results.")
                break
                
            soup = BeautifulSoup(r.text, "html.parser")
            listings = soup.select(".gs_r.gs_or.gs_scl")
            
            if not listings:
                if "detected unusual traffic" in r.text:
                    st.error("CAPTCHA Triggered. Google Scholar blocked this session.")
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

                # Robust Citation Extraction
                for a in footer_links:
                    if "Cited by" in a.text:
                        cite_val = re.sub(r"\D", "", a.text)
                        citations = int(cite_val) if cite_val else 0

                results.append({
                    "Title": title_tag.text if title_tag else "Unknown Title",
                    "Authors": authors,
                    "Year": year,
                    "Journal": journal,
                    "Citations": citations,
                    "Link": title_tag.find("a")["href"] if title_tag and title_tag.find("a") else "",
                    "Abstract": snippet_tag.text if snippet_tag else ""
                })
            
            progress_bar.progress(min((start + 10) / max_results, 1.0))
            
            # STEALTH DELAYS
            # 1. Normal delay between pages
            time.sleep(random.uniform(20, 35)) 
            
            # 2. Long "Human Break" every 3 pages
            if (start // 10) % 3 == 0 and start != 0:
                st.write("Simulating human review break...")
                time.sleep(random.uniform(45, 70))

        except Exception as e:
            st.warning(f"Error on Scholar page {start}: {e}")
            break
            
    return results

def scrape_scopus(query, max_results, api_key):
    headers = {"X-ELS-APIKey": api_key}
    url = f"https://api.elsevier.com/content/search/scopus?query={urllib.parse.quote(query)}&count={max_results}"
    try:
        r = requests.get(url, headers=headers)
        data = r.json().get("search-results", {}).get("entry", [])
        results = []
        for item in data:
            results.append({
                "Title": item.get("dc:title"),
                "Authors": item.get("dc:creator",""),
                "Year": item.get("prism:coverDate","")[:4],
                "Journal": item.get("prism:publicationName",""),
                "Citations": int(item.get("citedby-count", 0)),
                "Link": item.get("prism:url","")
            })
        return results
    except:
        st.warning("Error fetching Scopus data.")
        return []

# ==========================================
# RUN SEARCH
# ==========================================
if start_btn and query:
    all_results = []

    with st.spinner("Accessing Academic Databases..."):
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
        st.error("No results found. Please try a different query or fewer databases.")
    else:
        df = pd.DataFrame(all_results)
        
        # Ensure Citations is numeric and handle NaNs/Missing
        df["Citations"] = pd.to_numeric(df["Citations"], errors='coerce').fillna(0).astype(int)

        # ==========================================
        # DEDUPLICATION
        # ==========================================
        dedup = st.checkbox("Remove duplicate articles (by Title)", value=True)
        if dedup:
            total_before = len(df)
            df = df.drop_duplicates(subset=["Title"], keep="first")
            st.info(f"Articles Scraped: {total_before} | Unique Articles: {len(df)}")

        # ==========================================
        # FILTERS
        # ==========================================
        min_cite = st.slider("Filter by Minimum Citations", 0, 500, 0)
        df = df[df["Citations"] >= min_cite]

        # ==========================================
        # DISPLAY
        # ==========================================
        st.subheader(f"📊 Results ({len(df)})")
        st.dataframe(df, use_container_width=True)

        # ==========================================
        # EXPORT
        # ==========================================
        col1, col2 = st.columns(2)
        with col1:
            st.download_button("💾 Download CSV", df.to_csv(index=False), "academic_results.csv", "text/csv")
        with col2:
            excel_buffer = BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False)
            excel_buffer.seek(0)
            st.download_button("💾 Download Excel", excel_buffer, "academic_results.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ==========================================
# BULK DOWNLOADER
# ==========================================
st.divider()
st.subheader("📥 Bulk Download PDF/HTML from Excel")
uploaded_file = st.file_uploader("Upload previously exported Excel", type=["xlsx", "xls"])

if uploaded_file:
    df_upload = pd.read_excel(uploaded_file)
    if "Title" in df_upload.columns and "Link" in df_upload.columns:
        if st.button("Start Bulk Download"):
            zip_buffer = BytesIO()
            progress_dl = st.progress(0)
            with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                for i, row in df_upload.iterrows():
                    title = str(row["Title"]).strip()[:50]
                    link = row["Link"]
                    try:
                        if pd.notna(link) and str(link).startswith("http"):
                            r = requests.get(link, timeout=15)
                            ext = "pdf" if "application/pdf" in r.headers.get("Content-Type","") else "html"
                            clean_name = re.sub(r'[\\/*?:"<>|]', "", title)
                            zip_file.writestr(f"{clean_name}.{ext}", r.content)
                    except:
                        st.warning(f"Could not download: {title}")
                    progress_dl.progress((i+1)/len(df_upload))
            
            st.download_button("📦 Download ZIP of Articles", zip_buffer.getvalue(), "articles_bundle.zip")
    else:
        st.error("Uploaded file must contain 'Title' and 'Link' columns.")
