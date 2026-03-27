# ==========================================
# FINAL FIXED STREAMLIT SCRAPER (NO ERRORS)
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

st.title("📚 Academic Article Scraper & Downloader")

# ==========================================
# SIDEBAR
# ==========================================
st.sidebar.header("Search Settings")
query = st.sidebar.text_area("Search Query")
year_low = st.sidebar.text_input("Start Year", "2000")
year_high = st.sidebar.text_input("End Year", "2025")
max_results = st.sidebar.number_input("Max Results (≤1000)", 10, 1000, 100, 10)

start_btn = st.sidebar.button("🚀 Run Search")

# ==========================================
# SAFE HELPER
# ==========================================
def safe_int(val):
    try:
        return int(val)
    except:
        return 0

# ==========================================
# SCHOLAR (SAFE)
# ==========================================
def scrape_scholar(query, year_low, year_high, max_results):
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0"}

    session.get("https://scholar.google.com", headers=headers)
    time.sleep(random.uniform(30, 45))

    results = []
    progress = st.progress(0)

    for start in range(0, max_results, 10):
        try:
            url = f"https://scholar.google.com/scholar?q={urllib.parse.quote_plus(query)}&as_ylo={year_low}&as_yhi={year_high}&start={start}"
            r = session.get(url, headers=headers, timeout=15)

            if "captcha" in r.text.lower():
                st.warning("⚠️ CAPTCHA detected. Stopping.")
                break

            soup = BeautifulSoup(r.text, "html.parser")
            listings = soup.select(".gs_r.gs_or.gs_scl")

            if not listings:
                break

            for item in listings:
                title_tag = item.select_one(".gs_rt")
                authors_tag = item.select_one(".gs_a")
                snippet_tag = item.select_one(".gs_rs")
                footer_links = item.select(".gs_fl a")

                authors, year, journal = "N/A", "N/A", "N/A"
                citations = 0

                if authors_tag:
                    meta = authors_tag.text
                    parts = meta.split("-")
                    authors = parts[0].strip() if parts else "N/A"

                    if len(parts) > 1:
                        journal = parts[1]
                        y = re.search(r"\b(19|20)\d{2}\b", journal)
                        if y:
                            year = y.group()

                for a in footer_links:
                    if "Cited by" in a.text:
                        citations = safe_int(a.text.replace("Cited by", ""))

                results.append({
                    "Title": title_tag.text if title_tag else "",
                    "Authors": authors,
                    "Year": year,
                    "Journal": journal,
                    "Citations": citations if citations else 0,
                    "Link": title_tag.find("a")["href"] if title_tag and title_tag.find("a") else "",
                    "Abstract": snippet_tag.text if snippet_tag else ""
                })

            progress.progress(min((start+10)/max_results,1.0))
            time.sleep(random.uniform(35,60))

        except Exception:
            continue

    return results

# ==========================================
# RUN
# ==========================================
if start_btn and query:
    results = scrape_scholar(query, year_low, year_high, max_results)

    # FIX: ensure dataframe always has columns
    if len(results) == 0:
        df = pd.DataFrame(columns=["Title","Authors","Year","Journal","Citations","Link","Abstract"])
    else:
        df = pd.DataFrame(results)

    # FIX: ensure Citations column exists
    if "Citations" not in df.columns:
        df["Citations"] = 0

    df["Citations"] = pd.to_numeric(df["Citations"], errors="coerce").fillna(0)

    # ==========================================
    # FILTER
    # ==========================================
    min_cite = st.slider("Minimum Citations", 0, 500, 0)
    df = df[df["Citations"] >= min_cite]

    st.subheader(f"Results ({len(df)})")
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

    zip_buffer = BytesIO()
    progress = st.progress(0)

    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        for i, row in df_upload.iterrows():
            try:
                r = requests.get(row["Link"], timeout=30)
                zip_file.writestr(f"file_{i}.pdf", r.content)
            except:
                pass

            progress.progress((i+1)/len(df_upload))

    st.download_button("Download ZIP", zip_buffer.getvalue(), "articles.zip")
