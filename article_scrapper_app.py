# ==========================================
# STREAMLIT MULTI-DATABASE LITERATURE SCRAPER (ROBUST UPDATED)
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

st.set_page_config(page_title="Academic Article Scraper", layout="wide")

# ==========================================
# 🔧 SESSION CACHE & STATE MANAGEMENT
# ==========================================
if "cache_results" not in st.session_state:
    st.session_state.cache_results = {}

# We use this specifically for Google Scholar to resume after CAPTCHAs
if "scholar_temp_results" not in st.session_state:
    st.session_state.scholar_temp_results = []

# ==========================================
# UI HEADER
# ==========================================
st.title("📚 Academic Article Scraper & Downloader")
st.markdown("Search multiple academic databases, deduplicate results, and handle Google Scholar CAPTCHAs.")

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
    ["Google Scholar", "Crossref", "OpenAlex", "Semantic Scholar", "PubMed"],
    default=["Crossref", "OpenAlex"]
)

if st.sidebar.button("🗑️ Clear Search Cache"):
    st.session_state.cache_results = {}
    st.session_state.scholar_temp_results = []
    st.success("Cache cleared!")

start_btn = st.sidebar.button("🚀 Run Search")

# ==========================================
# API SCRAPERS
# ==========================================

def scrape_crossref(query, max_results):
    try:
        url = f"https://api.crossref.org/works?query={urllib.parse.quote(query)}&rows={max_results}"
        r = requests.get(url, timeout=15).json()
        return [{
            "Title": item.get("title", [""])[0],
            "Authors": ", ".join([a.get("family","") for a in item.get("author",[])]),
            "Year": item.get("issued", {}).get("date-parts", [[None]])[0][0],
            "Journal": item.get("container-title", [""])[0],
            "Citations": item.get("is-referenced-by-count", 0) or 0,
            "Link": item.get("URL", ""),
            "Source": "Crossref"
        } for item in r['message']['items']]
    except: return []

def scrape_openalex(query, max_results):
    try:
        url = f"https://api.openalex.org/works?search={urllib.parse.quote(query)}&per-page={max_results}"
        r = requests.get(url, timeout=15).json()
        return [{
            "Title": item.get("title"),
            "Authors": ", ".join([a['author']['display_name'] for a in item.get('authorships',[])]),
            "Year": item.get("publication_year"),
            "Journal": item.get("host_venue", {}).get("display_name"),
            "Citations": item.get("cited_by_count", 0) or 0,
            "Link": item.get("id"),
            "Source": "OpenAlex"
        } for item in r['results']]
    except: return []

def scrape_semantic(query, max_results):
    try:
        url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={urllib.parse.quote(query)}&limit={max_results}&fields=title,authors,year,citationCount,url"
        r = requests.get(url, timeout=15).json()
        return [{
            "Title": item.get("title"),
            "Authors": ", ".join([a.get("name") for a in item.get("authors",[])]),
            "Year": item.get("year"),
            "Journal": "N/A",
            "Citations": item.get("citationCount", 0) or 0,
            "Link": item.get("url"),
            "Source": "Semantic Scholar"
        } for item in r.get("data", [])]
    except: return []

def scrape_pubmed(query, max_results):
    try:
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmax={max_results}&term={urllib.parse.quote(query)}&retmode=json"
        ids = requests.get(url, timeout=15).json()["esearchresult"]["idlist"]
        return [{
            "Title": f"PubMed ID {pid}",
            "Authors": "N/A", "Year": "N/A", "Journal": "N/A", "Citations": 0,
            "Link": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/",
            "Source": "PubMed"
        } for pid in ids]
    except: return []

# ==========================================
# GOOGLE SCHOLAR SCRAPER (WITH RECOVERY)
# ==========================================

def scrape_scholar(query, year_low, year_high, max_results):
    session = requests.Session()
    
    # 1. ENHANCED HEADERS: To match a real Chrome browser more closely
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://scholar.google.com/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    # Resume from session state if available
    results = st.session_state.scholar_temp_results
    start_index = (len(results) // 10) * 10 
    
    progress_bar = st.progress(len(results) / max_results if max_results > 0 else 0)
    status_text = st.empty()

    while len(results) < max_results:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://scholar.google.com/scholar?q={encoded}&as_ylo={year_low}&as_yhi={year_high}&start={start_index}"

        try:
            r = session.get(url, headers=headers, timeout=15)
            html_check = r.text.lower()

            # 🚨 IMPROVED BLOCK DETECTION
            # Google sometimes returns a 403 or 429 without "captcha" in the text
            if "captcha" in html_check or "unusual traffic" in html_check or r.status_code in [403, 429]:
                st.warning(f"⚠️ Google is throttling requests at result {len(results)}.")
                
                # 2. THE FIX: Instructions to force a cookie refresh
                st.markdown(f"### [Step 1: Click here to verify you are human]({url})")
                st.info("""
                **If you don't see a CAPTCHA:** Just refresh the Google page twice, 
                perform a manual search for anything, then come back here.
                """)
                
                # We use a unique key for the button to avoid Streamlit Duplicate ID errors
                if st.button(f"✅ I've verified/refreshed! Resume", key=f"scholar_res_{start_index}"):
                    # Give it one more long sleep to let the IP 'cool down'
                    time.sleep(5)
                    st.rerun()
                else:
                    st.stop() 

            soup = BeautifulSoup(r.text, "html.parser")
            listings = soup.select(".gs_r.gs_or.gs_scl")

            # 3. HANDLING EMPTY LISTS
            if not listings:
                if "gs_res_ccl_mid" not in r.text: # If the main results container is missing
                    st.error("Google Scholar blocked the page structure. Try again in a few minutes.")
                    break
                break

            for item in listings:
                if len(results) >= max_results: break
                
                title_tag = item.select_one(".gs_rt")
                authors_tag = item.select_one(".gs_a")
                snippet_tag = item.select_one(".gs_rs")
                
                authors, year, journal, citations = "N/A", "N/A", "N/A", 0
                if authors_tag:
                    parts = authors_tag.text.split("-")
                    authors = parts[0].strip()
                    year_match = re.search(r"\b(19|20)\d{2}\b", authors_tag.text)
                    if year_match: year = year_match.group()

                cite_tag = item.find("a", string=re.compile(r"Cited by"))
                if cite_tag:
                    citations = int(re.sub(r"[^\d]", "", cite_tag.text))

                results.append({
                    "Title": title_tag.text if title_tag else "N/A",
                    "Authors": authors,
                    "Year": year,
                    "Journal": journal,
                    "Citations": citations,
                    "Link": title_tag.find("a")["href"] if (title_tag and title_tag.find("a")) else "N/A",
                    "Source": "Google Scholar"
                })
            
            st.session_state.scholar_temp_results = results
            start_index += 10
            
            progress_bar.progress(min(len(results) / max_results, 1.0))
            status_text.write(f"✅ Scholar: Collected {len(results)} articles...")
            
            # 4. RANDOMIZED HUMAN DELAY
            # Short delays are the #1 reason for blocks. 
            time.sleep(random.uniform(20, 35))

        except Exception as e:
            st.error(f"❌ Scholar Error: {e}")
            break

    return results

# ==========================================
# MAIN EXECUTION
# ==========================================
if start_btn and query:
    try:
        key = f"{query}_{year_low}_{year_high}_{max_results}_{'_'.join(databases)}"
        
        # We start with an empty list and populate based on selection
        all_results = []

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

        st.session_state.cache_results[key] = all_results

        df = pd.DataFrame(all_results)

        if not df.empty:
            # Data Formatting
            if "Citations" not in df.columns: df["Citations"] = 0
            df["Citations"] = pd.to_numeric(df["Citations"], errors="coerce").fillna(0).astype(int)

            min_cite = st.slider("Minimum Citations Filter", 0, 500, 0)
            df = df[df["Citations"] >= min_cite]

            st.subheader(f"📊 Results ({len(df)})")
            st.dataframe(df, use_container_width=True)

            # Export Buttons
            col1, col2 = st.columns(2)
            with col1:
                st.download_button("📥 Download CSV", df.to_csv(index=False), "results.csv", "text/csv")
            with col2:
                buffer = BytesIO()
                with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                    df.to_excel(writer, index=False)
                st.download_button("📥 Download Excel", buffer.getvalue(), "results.xlsx")
        else:
            st.warning("No results found across selected databases.")

    except Exception as e:
        st.error(f"❌ Application Error: {e}")

# ==========================================
# BULK DOWNLOADER
# ==========================================
st.divider()
st.subheader("📥 Bulk PDF Downloader")
st.info("Upload the Excel file you just downloaded to attempt a bulk PDF fetch.")
uploaded_file = st.file_uploader("Upload Excel", type=["xlsx"])

if uploaded_file:
    df_upload = pd.read_excel(uploaded_file)
    if "Title" in df_upload.columns and "Link" in df_upload.columns:
        if st.button("🚀 Start Bulk Download"):
            zip_buffer = BytesIO()
            dl_progress = st.progress(0)
            
            with zipfile.ZipFile(zip_buffer, "w") as zip_file:
                for i, row in df_upload.iterrows():
                    try:
                        # Note: This is a simple GET; many journals block direct automated PDF downloads
                        r = requests.get(row["Link"], timeout=20)
                        clean_title = re.sub(r'[^\w\s-]', '', row['Title'])[:50]
                        zip_file.writestr(f"{clean_title}.html", r.content)
                    except:
                        pass
                    dl_progress.progress((i + 1) / len(df_upload))
            
            st.download_button("📦 Download Results ZIP", zip_buffer.getvalue(), "articles_bundle.zip")
    else:
        st.error("Excel must have 'Title' and 'Link' columns.")
