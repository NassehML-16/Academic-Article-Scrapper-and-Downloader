# ==========================================
# FINAL FIXED STREAMLIT MULTI-DATABASE SCRAPER
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
# UI
# ==========================================
st.title("📚 Academic Article Scraper & Downloader")

st.sidebar.header("Search Settings")
query = st.sidebar.text_area("Search Query")
year_low = st.sidebar.text_input("Start Year", "2000")
year_high = st.sidebar.text_input("End Year", "2025")
max_results = st.sidebar.number_input("Max Results (≤1000)", 10, 1000, 100, 10)

start_btn = st.sidebar.button("🚀 Run Search")

# ==========================================
# SAFE DATAFRAME STRUCTURE (CRITICAL FIX)
# ==========================================
def ensure_columns(df):
    required_cols = ["Title", "Authors", "Year", "Journal", "Citations", "Link", "Abstract"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = "" if col != "Citations" else 0
    return df

# ==========================================
# GOOGLE SCHOLAR
# ==========================================
def scrape_scholar(query, year_low, year_high, max_results):
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0"}
    session.get("https://scholar.google.com", headers=headers)
    time.sleep(random.uniform(10, 20))

    results = []
    progress = st.progress(0)

    for start in range(0, max_results, 10):
        try:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://scholar.google.com/scholar?q={encoded}&as_ylo={year_low}&as_yhi={year_high}&start={start}"

            r = session.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            listings = soup.select(".gs_r.gs_or.gs_scl")

            if not listings:
                break

            for item in listings:
                title_tag = item.select_one(".gs_rt")
                authors_tag = item.select_one(".gs_a")
                snippet_tag = item.select_one(".gs_rs")
                footer_links = item.select(".gs_fl a")

                authors, year, journal, citations = "", "", "", 0

                if authors_tag:
                    meta_text = authors_tag.text
                    parts = meta_text.split("-")
                    authors = parts[0].strip() if parts else ""

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

            progress.progress(min((start + 10) / max_results, 1.0))
            time.sleep(random.uniform(35, 60))

        except Exception:
            continue

    return results

# ==========================================
# RUN SEARCH
# ==========================================
if start_btn and query:
    results = scrape_scholar(query, year_low, year_high, max_results)

    if not results:
        st.warning("No results found.")
        st.stop()

    df = pd.DataFrame(results)

    # 🔥 CRITICAL FIX HERE
    df = ensure_columns(df)

    # ==========================================
    # DEDUPLICATION
    # ==========================================
    dedup = st.checkbox("Remove duplicate articles")
    total_articles = len(df)
    duplicates_count = df.duplicated(subset=["Title"], keep=False).sum()

    if dedup:
        df = df.drop_duplicates(subset=["Title"], keep="first")
        st.info(f"Total extracted: {total_articles}")
        st.info(f"Duplicates removed: {duplicates_count}")
        st.info(f"Final count: {len(df)}")

    # ==========================================
    # FILTERS (FIXED ERROR)
    # ==========================================
    min_cite = st.slider("Minimum Citations", 0, 500, 0)

    df["Citations"] = pd.to_numeric(df["Citations"], errors="coerce").fillna(0)
    df = df[df["Citations"] >= min_cite]

    # ==========================================
    # DISPLAY
    # ==========================================
    st.subheader(f"📊 Results ({len(df)})")
    st.dataframe(df, height=600, use_container_width=True)

    # ==========================================
    # DOWNLOAD
    # ==========================================
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", csv, "results.csv", "text/csv")

    buffer = BytesIO()
    df.to_excel(buffer, index=False, engine="xlsxwriter")
    buffer.seek(0)

    st.download_button(
        "Download Excel",
        buffer,
        file_name="results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ==========================================
# BULK DOWNLOAD
# ==========================================
st.subheader("📥 Bulk Download from Excel")
file = st.file_uploader("Upload Excel with Title & Link", type=["xlsx"])

if file:
    df_upload = pd.read_excel(file)

    if "Link" not in df_upload.columns:
        st.error("Excel must contain a 'Link' column")
    else:
        zip_buffer = BytesIO()
        progress = st.progress(0)

        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            for i, row in df_upload.iterrows():
                try:
                    r = requests.get(row["Link"], timeout=30)
                    zip_file.writestr(f"file_{i}.pdf", r.content)
                except:
                    pass

                progress.progress((i + 1) / len(df_upload))

        st.download_button("Download ZIP", zip_buffer.getvalue(), "articles.zip")
