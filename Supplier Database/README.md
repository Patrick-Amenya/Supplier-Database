# Assent Supplier Master Database

A Streamlit supplier/company master database with:
- Assent-style UI colors
- CSV upload
- Column mapping
- Duplicate analysis before import
- Exact matching by Tax ID, Registration Number, DUNS, LEI, domain, and normalized company name
- Fuzzy company-name duplicate detection
- Duplicate Review Center
- Supplier search
- Import history
- SQLite database created automatically

## Deploy on Streamlit Community Cloud

Main file path:

app.py

## Run locally

pip install -r requirements.txt
streamlit run app.py

The app creates supplier_master.db automatically on first run.
