---
name: webapp-testing
description: Toolkit for interacting with and testing local web applications using Playwright or headless browsers. Supports verifying frontend functionality, debugging UI behavior, capturing browser screenshots, and viewing browser logs.
---

# Web Application Testing

To test local web applications, write native Python Playwright or browser automation scripts.

## Guidelines
1. Ensure the web application server is running or start it in a background process.
2. Navigate to the local URL (e.g., http://localhost:8501 for Streamlit).
3. Wait for network idle or DOM elements to appear.
4. Interact with widgets, verify states, take screenshots of significant steps, and verify results.
