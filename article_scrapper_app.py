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
    ["Google Scholar", "Crossref", "OpenAlex", "Semantic Scholar", "PubMed"],
    default=["Crossref", "OpenAlex"]
)

start_btn = st.sidebar.button("🚀 Run Search")

# ==========================================
# SCRAPERS
# ==========================================
def scrape_crossref(query, max_results):
    url = f"https://api.crossref.org/works?query={urllib.parse.quote(query)}&rows={max_results}"
    r = requests.get(url).json()
    return [{
        "Title": item.get("title", [""])[0],
        "Authors": ", ".join([a.get("family","") for a in item.get("author",[])]),
        "Year": item.get("issued", {}).get("date-parts", [[None]])[0][0],
        "Journal": item.get("container-title", [""])[0],
        "Citations": item.get("is-referenced-by-count", 0) or 0,
        "Link": item.get("URL", "")
    } for item in r['message']['items']]


def scrape_openalex(query, max_results):
    url = f"https://api.openalex.org/works?search={urllib.parse.quote(query)}&per-page={max_results}"
    r = requests.get(url).json()
    return [{
        "Title": item.get("title"),
        "Authors": ", ".join([a['author']['display_name'] for a in item.get('authorships',[])]),
        "Year": item.get("publication_year"),
        "Journal": item.get("host_venue", {}).get("display_name"),
        "Citations": item.get("cited_by_count", 0) or 0,
        "Link": item.get("id")
    } for item in r['results']]


def scrape_semantic(query, max_results):
    url = f"https://api.semanticscholar.org/graph/v1/paper/search?query={urllib.parse.quote(query)}&limit={max_results}&fields=title,authors,year,citationCount,url"
    r = requests.get(url).json()
    return [{
        "Title": item.get("title"),
        "Authors": ", ".join([a.get("name") for a in item.get("authors",[])]),
        "Year": item.get("year"),
        "Journal": "",
        "Citations": item.get("citationCount", 0) or 0,
        "Link": item.get("url")
    } for item in r.get("data", [])]


def scrape_pubmed(query, max_results):
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&retmax={max_results}&term={urllib.parse.quote(query)}&retmode=json"
    ids = requests.get(url).json()["esearchresult"]["idlist"]
    return [{
        "Title": f"PubMed ID {pid}",
        "Authors": "",
        "Year": "",
        "Journal": "",
        "Citations": 0,
        "Link": f"https://pubmed.ncbi.nlm.nih.gov/{pid}/"
    } for pid in ids]


def scrape_scholar(query, year_low, year_high, max_results):
    session = requests.Session()
    # Using a slightly more specific User-Agent helps a bit
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    }

    # Initial warm-up
    try:
        session.get("https://scholar.google.com", headers=headers, timeout=10)
    except:
        pass
        
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    start = 0
    while len(results) < max_results:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://scholar.google.com/scholar?q={encoded}&as_ylo={year_low}&as_yhi={year_high}&start={start}"

        try:
            r = session.get(url, headers=headers, timeout=15)
            html_check = r.text.lower()

            # 🚨 BLOCK DETECTION
            if "captcha" in html_check or "unusual traffic" in html_check:
                st.warning("⚠️ Google Scholar CAPTCHA detected!")
                st.markdown(f"**[Step 1: Click here to solve the CAPTCHA in your browser]({url})**")
                st.info("Step 2: After solving it and seeing results in your browser, come back and click the button below.")
                
                # This button stops the code execution until clicked
                if st.button(f"I've solved it! Resume scraping page {start//10 + 1}", key=f"retry_{start}"):
                    st.rerun() # Refresh to try the same 'start' index again
                else:
                    st.stop() # Pause everything until the button is pressed

            soup = BeautifulSoup(r.text, "html.parser")
            listings = soup.select(".gs_r.gs_or.gs_scl")

            if not listings:
                if "gs_rt" not in r.text: # Double check if it's an empty page or a hidden block
                    st.error("Empty response. Google might be throttling you. Try solving CAPTCHA manually.")
                    break
                break

            for item in listings:
                if len(results) >= max_results:
                    break
                    
                title_tag = item.select_one(".gs_rt")
                authors_tag = item.select_one(".gs_a")
                snippet_tag = item.select_one(".gs_rs")
                footer_links = item.select(".gs_fl a")

                authors, year, journal, citations = "N/A", "N/A", "N/A", 0

                if authors_tag:
                    parts = authors_tag.text.split("-")
                    authors = parts[0].strip() if len(parts) > 0 else "N/A"
                    if len(parts) > 1:
                        year_match = re.search(r"\b(19|20)\d{2}\b", parts[1])
                        if year_match:
                            year = year_match.group()
                        journal = parts[1].strip()

                for a in footer_links:
                    if "Cited by" in a.text:
                        try:
                            citations = int(re.sub(r"[^\d]", "", a.text))
                        except:
                            citations = 0

                results.append({
                    "Title": title_tag.text if title_tag else "N/A",
                    "Authors": authors,
                    "Year": year,
                    "Journal": journal,
                    "Citations": citations,
                    "Link": title_tag.find("a")["href"] if title_tag and title_tag.find("a") else "N/A",
                    "Abstract": snippet_tag.text if snippet_tag else ""
                })

            # Update UI
            current_progress = min(len(results) / max_results, 1.0)
            progress_bar.progress(current_progress)
            status_text.write(f"✅ Scraped {len(results)} / {max_results} articles...")

            # Increment page and sleep
            start += 10
            time.sleep(random.uniform(15, 25)) # Slightly faster but still randomized

        except Exception as e:
            st.error(f"❌ Error: {e}")
            break

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

        # ✅ ENSURE CITATIONS EXISTS
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
        st.error(f"❌ App Error: {e}")

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
                    filename = f"{row['Title'][:50]}.pdf".replace("/", "_")
                    zip_file.writestr(filename, r.content)
                except Exception as e:
                    st.warning(f"Failed: {e}")

                progress.progress((i + 1) / len(df_upload))

        st.download_button("Download ZIP", zip_buffer.getvalue(), "articles.zip")
