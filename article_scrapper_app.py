# ==========================================
# STREAMLIT MULTI-DATABASE LITERATURE SCRAPER (IMPROVED STABILITY + 1000 ROW SUPPORT)
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
max_results = st.sidebar.number_input("Max Results (≤1000)", min_value=10, max_value=1000, value=100, step=10)

# HUMAN MODE TO REDUCE BLOCKING
human_mode = st.sidebar.checkbox("🧠 Human Mode (Slower, less blocking)", value=True)

# DATABASES
databases = st.sidebar.multiselect(
    "Select Databases",
    ["Google Scholar", "Crossref", "OpenAlex", "Semantic Scholar", "PubMed"],
    default=["Crossref", "OpenAlex"]
)

start_btn = st.sidebar.button("🚀 Run Search")

# ==========================================
# SAFE REQUEST FUNCTION
# ==========================================
def safe_request(url, headers=None, retries=3):
    for _ in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 200:
                return r
        except:
            time.sleep(random.uniform(3, 8))
    return None

# ==========================================
# SCRAPERS (API BASED = FAST & SAFE)
# ==========================================
def scrape_crossref(query, max_results):
    url = f"https://api.crossref.org/works?query={urllib.parse.quote(query)}&rows={max_results}"
    r = safe_request(url)
    if not r:
        return []
    data = r.json()
    results = []
    for item in data['message']['items']:
        results.append({
            "Title": item.get("title", [""])[0],
            "Authors": ", ".join([a.get("family","") for a in item.get("author",[])]),
            "Year": item.get("issued", {}).get("date-parts", [[None]])[0][0],
            "Journal": item.get("container-title", [""])[0],
            "Citations": item.get("is-referenced-by-count", 0),
            "Link": item.get("URL", "")
        })
    return results

# ==========================================
# GOOGLE SCHOLAR (HUMAN MODE IMPROVED)
# ==========================================
def scrape_scholar(query, year_low, year_high, max_results):
    session = requests.Session()

    headers_list = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Mozilla/5.0 (X11; Linux x86_64)"
    ]

    # Warmup request
    session.get("https://scholar.google.com", headers={"User-Agent": random.choice(headers_list)})
    time.sleep(random.uniform(10, 20))

    results = []
    progress = st.progress(0)

    for start in range(0, max_results, 10):
        headers = {
            "User-Agent": random.choice(headers_list),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://scholar.google.com/"
        }

        encoded = urllib.parse.quote_plus(query)
        url = f"https://scholar.google.com/scholar?q={encoded}&as_ylo={year_low}&as_yhi={year_high}&start={start}"

        r = safe_request(url, headers=headers)
        if not r:
            st.warning("⚠️ Request failed, stopping Scholar scraping.")
            break

        if "captcha" in r.text.lower():
            st.error("🚨 CAPTCHA detected. Stopping Scholar scraping.")
            break

        soup = BeautifulSoup(r.text, "html.parser")
        listings = soup.select(".gs_r.gs_or.gs_scl")

        if not listings:
            break

        for item in listings:
            title_tag = item.select_one(".gs_rt")
            meta_tag = item.select_one(".gs_a")
            footer_links = item.select(".gs_fl a")

            authors, year, journal, citations = "N/A", "N/A", "N/A", 0

            if meta_tag:
                parts = meta_tag.text.split("-")
                authors = parts[0].strip()
                if len(parts) > 1:
                    year_match = re.search(r"\b(19|20)\d{2}\b", parts[1])
                    if year_match:
                        year = year_match.group()
                    journal = parts[1].strip()

            for a in footer_links:
                if "Cited by" in a.text:
                    try:
                        citations = int(a.text.replace("Cited by", "").strip())
                    except:
                        pass

            results.append({
                "Title": title_tag.text if title_tag else "",
                "Authors": authors,
                "Year": year,
                "Journal": journal,
                "Citations": citations,
                "Link": title_tag.find("a")["href"] if title_tag and title_tag.find("a") else ""
            })

        progress.progress(min((start + 10) / max_results, 1.0))

        # KEEP YOUR 35–60s DELAY
        delay = random.uniform(35, 60) if human_mode else random.uniform(5, 10)
        time.sleep(delay)

    return results

# ==========================================
# RUN SEARCH
# ==========================================
if start_btn and query:
    all_results = []

    if "Crossref" in databases:
        all_results += scrape_crossref(query, max_results)

    if "Google Scholar" in databases:
        all_results += scrape_scholar(query, year_low, year_high, max_results)

    df = pd.DataFrame(all_results)

    # ENSURE LARGE TABLE SUPPORT
    st.write(f"Total rows loaded: {len(df)}")

    # ==========================================
    # DEDUPLICATION
    # ==========================================
    dedup = st.checkbox("Remove duplicate articles")
    if dedup:
        before = len(df)
        df = df.drop_duplicates(subset=["Title"])
        st.success(f"Removed {before - len(df)} duplicates")

    # ==========================================
    # DISPLAY LARGE TABLE (1000 ROW SAFE)
    # ==========================================
    st.dataframe(df, use_container_width=True, height=600)

    # ==========================================
    # DOWNLOADS
    # ==========================================
    st.download_button("Download CSV", df.to_csv(index=False), "results.csv")

    excel_buffer = BytesIO()
    df.to_excel(excel_buffer, index=False, engine="xlsxwriter")
    excel_buffer.seek(0)
    st.download_button("Download Excel", excel_buffer, "results.xlsx")

# ==========================================
# BULK DOWNLOAD ZIP
# ==========================================
st.subheader("📥 Bulk Download from Excel")
file = st.file_uploader("Upload Excel (Title, Link)")

if file:
    df_upload = pd.read_excel(file)
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        for _, row in df_upload.iterrows():
            try:
                r = requests.get(row["Link"], timeout=30)
                zip_file.writestr(f"{row['Title'][:40]}.pdf", r.content)
            except:
                pass

    st.download_button("Download ZIP", zip_buffer.getvalue(), "articles.zip")
