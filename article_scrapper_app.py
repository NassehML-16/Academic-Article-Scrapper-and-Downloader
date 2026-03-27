# ==========================================
# ROBUST STREAMLIT MULTI-DATABASE SCRAPER
# (FIXED GOOGLE SCHOLAR + STABILITY)
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
st.title("📚 Academic Article Scraper (Robust Version)")

st.sidebar.header("Search Settings")
query = st.sidebar.text_area("Search Query")
year_low = st.sidebar.text_input("Start Year", "2000")
year_high = st.sidebar.text_input("End Year", "2025")
max_results = st.sidebar.number_input("Max Results (≤1000)", 10, 1000, 100, 10)

human_mode = st.sidebar.checkbox("🧠 Human Mode (recommended for Scholar)", True)

start_btn = st.sidebar.button("🚀 Run Search")

# ==========================================
# SAFE REQUEST WITH RETRY
# ==========================================
def safe_request(session, url, headers, retries=3):
    for attempt in range(retries):
        try:
            r = session.get(url, headers=headers, timeout=20)

            if r.status_code == 200:
                if "captcha" in r.text.lower():
                    return None
                return r

        except Exception:
            pass

        time.sleep(random.uniform(5, 10))

    return None

# ==========================================
# GOOGLE SCHOLAR (FIXED)
# ==========================================
def scrape_scholar(query, year_low, year_high, max_results):
    session = requests.Session()

    headers_list = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Mozilla/5.0 (X11; Linux x86_64)"
    ]

    # Warm-up
    session.get("https://scholar.google.com", headers={"User-Agent": random.choice(headers_list)})

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

        r = safe_request(session, url, headers)

        if r is None:
            st.warning("⚠️ Request failed. Retrying next page...")
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        listings = soup.select(".gs_r.gs_or.gs_scl")

        if not listings:
            st.warning("⚠️ No more results or blocked.")
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
                authors = parts[0].strip() if parts else "N/A"

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

        # HUMAN DELAY
        if human_mode:
            delay = random.uniform(35, 60)
        else:
            delay = random.uniform(5, 10)

        time.sleep(delay)

    return results

# ==========================================
# RUN
# ==========================================
if start_btn and query:
    results = scrape_scholar(query, year_low, year_high, max_results)

    df = pd.DataFrame(results)

    st.subheader(f"Results ({len(df)})")
    st.dataframe(df, height=600, use_container_width=True)

    # DOWNLOAD FIX
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

            progress.progress((i + 1) / len(df_upload))

    st.download_button("Download ZIP", zip_buffer.getvalue(), "articles.zip")
