# Third-Party Notices and Licenses

LocalLeads Kit incorporates, bundles, or downloads upon first execution the following open-source software, datasets, and typography. This document provides attribution and notices as required by their respective licenses.

---

## 1. Geographic Gazetteer Data (GeoNames)

* **Project:** GeoNames Geographic Database (`cities5000.txt`, `admin1CodesASCII.txt`, `countryInfo.txt`)
* **Source:** [GeoNames.org](https://www.geonames.org/)
* **Attribution:** "Contains data from GeoNames (https://www.geonames.org), used under the Creative Commons Attribution license (CC BY). See https://www.geonames.org/export/ for terms."

<!--
NOTE ON UPSTREAM LICENSING:
Previous project documentation mistakenly framed generic Creative Commons CC BY 4.0 summary deed text ("You are free to: Share... Adapt... Under the following terms: Attribution...") as a verbatim quote from geonames.org/export. It is not.
On GeoNames' own web export terms page (https://www.geonames.org/export/), the license is described without a version number: "cc-by licence (creative commons attribution license)".
In GeoNames' gazetteer dump directory documentation (https://download.geonames.org/export/dump/readme.txt), the work is explicitly stated as: "licensed under a Creative Commons Attribution 4.0 License, see https://creativecommons.org/licenses/by/4.0/".
The individual downloaded dump archive (cities5000.zip) contains only the raw tab-delimited data file cities5000.txt without an embedded header or nested readme.
-->

### Upstream Terms (Verbatim Quotes):

**From GeoNames Export Page (https://www.geonames.org/export/):**
> - **free:** GeoNames data is free, the data is available without costs.
> - **cc-by licence** (creative commons attribution license). You should give credit to GeoNames when using data or web services with a link or another reference to GeoNames.
> - commercial usage is allowed
> - **'as is':** The data is provided "as is" without warranty or any representation of accuracy, timeliness or completeness.

**From GeoNames Dump Readme (https://download.geonames.org/export/dump/readme.txt):**
> "This work is licensed under a Creative Commons Attribution 4.0 License,  
> see https://creativecommons.org/licenses/by/4.0/  
> The Data is provided 'as is' without warranty or any representation of accuracy, timeliness or completeness."

---

## 2. Bundled Typography (Local Offline Web Fonts)

Both fonts are bundled locally as `.woff2` files in `static/fonts/` and served directly by Streamlit without any external CDN dependencies.

### Manrope
* **Copyright:** Copyright 2018 The Manrope Project Authors (https://github.com/sharanda/manrope)
* **Upstream Repository:** [https://github.com/sharanda/manrope](https://github.com/sharanda/manrope)
* **Upstream License Source:** [https://raw.githubusercontent.com/sharanda/manrope/master/OFL.txt](https://raw.githubusercontent.com/sharanda/manrope/master/OFL.txt)
* **Version / Commit:** Version 4.69 (Commit c5be1b5)
* **License:** SIL Open Font License, Version 1.1 (full text bundled in `static/fonts/OFL-Manrope.txt`)

### JetBrains Mono
* **Copyright:** Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)
* **Upstream Repository:** [https://github.com/JetBrains/JetBrainsMono](https://github.com/JetBrains/JetBrainsMono)
* **Upstream License Source:** [https://raw.githubusercontent.com/JetBrains/JetBrainsMono/master/OFL.txt](https://raw.githubusercontent.com/JetBrains/JetBrainsMono/master/OFL.txt)
* **Version / Commit:** Version v2.304 (Commit a4ca5ef)
* **License:** SIL Open Font License, Version 1.1 (full text bundled in `static/fonts/OFL-JetBrainsMono.txt`)

---

## 3. Automated First-Run Runtime Downloads

The 1-click launcher scripts (`run.bat` and `run.sh`) automatically download and provision the following isolated components into `%LOCALAPPDATA%\LocalLeadsKit` (Windows) or `~/.localleadskit` (macOS/Linux):

### uv (Astral Software)
* **Description:** Fast Python package and runtime manager
* **Upstream Repository:** [https://github.com/astral-sh/uv](https://github.com/astral-sh/uv)
* **Pinned Release:** v0.6.5 (Verified via official SHA256 integrity checksums)
* **License:** MIT License / Apache License 2.0

### Standalone Python (python-build-standalone)
* **Description:** Portable, isolated standalone Python 3.11 build
* **Upstream Repository:** [https://github.com/indygreg/python-build-standalone](https://github.com/indygreg/python-build-standalone)
* **License:** Python Software Foundation License Version 2.0 (GPL-compatible)

---

## 4. Pinned Python Runtime Dependencies

The following packages are installed into the isolated runtime virtual environment:

| Package | Version | License | Upstream Project / Repository |
| :--- | :--- | :--- | :--- |
| **streamlit** | 1.58.0 | Apache-2.0 | [https://streamlit.io](https://streamlit.io) |
| **pandas** | >=2.2.0, <3.0.0 | BSD 3-Clause | [https://pandas.pydata.org](https://pandas.pydata.org) |
| **requests** | 2.32.5 | Apache-2.0 | [https://requests.readthedocs.io](https://requests.readthedocs.io) |
| **beautifulsoup4** | 4.14.3 | MIT | [https://www.crummy.com/software/BeautifulSoup/](https://www.crummy.com/software/BeautifulSoup/) |
| **phonenumbers** | 9.0.39 | Apache-2.0 | [https://github.com/daviddrysdale/python-phonenumbers](https://github.com/daviddrysdale/python-phonenumbers) |
| **pyarrow** | 25.0.1 | Apache-2.0 | [https://arrow.apache.org](https://arrow.apache.org) |
| **altair** | 6.3.0 | BSD 3-Clause | [https://altair-viz.github.io](https://altair-viz.github.io) |

---

## 5. Contact & Inquiries

For legal or licensing inquiries regarding LocalLeads Kit:  
Contact: `supportlocalleadskit@gmail.com`
