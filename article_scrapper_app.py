# ==========================================
# STREAMLIT MULTI-DATABASE LITERATURE SCRAPER (FULL UPDATED)
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
# 🔧 SESSION CACHE
# ==========================================
if "cache_results" not in st.session_state:
    st.session_state.cache_results = {}

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
# SCRAPERS
# ==========================================
def scrape_crossref(query, max_results):
    url = f"https://api.crossref.org/works?query={urllib.parse.quote(query)}&rows={max_results}"
    r = requests.get(url).json()
    results = []
    for item in r['message']['items']:
        results.append({
            "Title": item.get("title", [""])[0],
            "Authors": ", ".join([a.get("family",""
) for a in item.get("author",[])]),
            "Year": item.get("issued", {}).get("date-parts", [[None]])[0][0],
            "Journal": item.get("container-title", [""])[0],
            "Citations": item.get("is-referenced-by-count", 0) or 0,
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
            "Citations": item.get("cited_by_count", 0) or 0,
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
            "Citations": item.get("citationCount", 0) or 0,
            "Link": item.get("url")
        })
    return results

def scrape_pubmed(query, max_results):
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmax={max_results}&term={urllib.parse.quote(query)}&retmode=json"
    ids = requests.get(url).json()["esearchresult"]["idlist"]
    return [{"Title": f"PubMed ID {pid}", "Authors": "", "Year": "", "Journal": "", "Citations": 0, "Link": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/"} for pid in ids]

def scrape_scholar(query, year_low, year_high, max_results):
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0"}
    session.get("https://scholar.google.com", headers=headers)
    time.sleep(random.uniform(20, 35))

    results = []
    progress = st.progress(0)
    for start in range(0, max_results, 10):
        encoded = urllib.parse.quote_plus(query)
        url = f"https://scholar.google.com/scholar?q={encoded}&as_ylo={year_low}&as_yhi={year_high}&start={start}"
        r = session.get(url, headers=headers)
        soup = BeautifulSoup(r.text, "html.parser")
        listings = soup.select(".gs_r.gs_or.gs_scl")

        for item in listings:
            title_tag = item.select_one(".gs_rt")
            authors_tag = item.select_one(".gs_a")
            snippet_tag = item.select_one(".gs_rs")
            footer_links = item.select(".gs_fl a")

            authors, year, journal, citations = "N/A", "N/A", "N/A", 0
            if authors_tag:
                parts = authors_tag.text.split("-")
                authors = parts[0].strip() if len(parts)>0 else "N/A"
                if len(parts)>1:
                    year_match = re.search(r"\b(19|20)\d{2}\b", parts[1])
                    if year_match: year = year_match.group()
                    journal = parts[1].strip()
            for a in footer_links:
                if "Cited by" in a.text:
                    try: citations = int(a.text.replace("Cited by",""))
                    except: citations = 0

            results.append({
                "Title": title_tag.text if title_tag else "",
                "Authors": authors,
                "Year": year,
                "Journal": journal,
                "Citations": citations,
                "Link": title_tag.find("a")["href"] if title_tag and title_tag.find("a") else "",
                "Abstract": snippet_tag.text if snippet_tag else ""
            })

        st.write(f"Scraped {len(results)} / {max_results} articles...")
        progress.progress(min(len(results)/max_results,1.0))
        time.sleep(random.uniform(35,60))

    return results

# ==========================================
# RUN SEARCH
# ==========================================
if start_btn and query:
    try:
        key = f"{query}_{year_low}_{year_high}_{max_results}_{'_'.join(databases)}"
        all_results = st.session_state.cache_results.get(key, [])

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

        if "Citations" not in df.columns:
            df["Citations"] = 0
        df["Citations"] = pd.to_numeric(df["Citations"], errors="coerce").fillna(0).astype(int)

        min_cite = st.slider("Minimum Citations", 0, 500, 0)
        df = df[df["Citations"] >= min_cite]

        st.subheader(f"📊 Results ({len(df)})")
        st.dataframe(df, use_container_width=True)

        st.download_button("Download CSV", df.to_csv(index=False), "results.csv", mime="text/csv")

        buffer = BytesIO()
        df.to_excel(buffer, index=False, engine="xlsxwriter")
        buffer.seek(0)
        st.download_button("Download Excel", buffer, "results.xlsx")

    except Exception as e:
        st.error(f"Error: {e}")

# ==========================================
# BULK DOWNLOAD
# ==========================================
st.subheader("📥 Bulk Download from Excel")
uploaded_file = st.file_uploader("Upload Excel with columns: Title, Link", type=["xlsx","xls"])
if uploaded_file:
    df_upload = pd.read_excel(uploaded_file)
    if "Title" not in df_upload.columns or "Link" not in df_upload.columns:
        st.error("Excel must contain 'Title' and 'Link' columns.")
    else:
        zip_buffer = BytesIO()
        progress = st.progress(0)
        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            for i, row in df_upload.iterrows():
                try:
                    r = requests.get(row["Link"], timeout=30)
                    filename = f"{row['Title'][:50]}.pdf".replace("/","_")
                    zip_file.writestr(filename, r.content)
                except Exception as e:
                    st.warning(f"Failed: {e}")
                progress.progress((i+1)/len(df_upload))

        st.download_button("Download ZIP", zip_buffer.getvalue(), "articles.zip")
