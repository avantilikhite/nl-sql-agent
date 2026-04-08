"""
Take 6 demo screenshots for the README GIF.
Each screenshot shows the user question + agent response in the chat area.
"""

import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ASSETS = Path(__file__).parent / "assets"
ASSETS.mkdir(exist_ok=True)
URL = "http://localhost:8501"

QUESTIONS = [
    None,  # Frame 0: landing page (no question)
    "What are the top 5 products by total revenue?",
    "Now break that down by month",
    "Which customers placed the most orders but have the lowest average order value? Show the top 10.",
    "Delete all cancelled orders",
    "What interesting patterns do you see in the order data? Any seasonality or trends?",
]


def wait_for_response(page, timeout=60):
    """Wait until the spinner disappears, meaning the agent has responded."""
    # Wait for spinner to appear then disappear
    time.sleep(2)  # Give spinner time to appear
    for _ in range(timeout):
        spinners = page.locator("text=Querying the database").count()
        if spinners == 0:
            time.sleep(1)  # Extra settle time
            return True
        time.sleep(1)
    return False


def take_screenshots():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Use a wide viewport for clean screenshots
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        page.goto(URL, wait_until="networkidle")
        time.sleep(3)  # Let Streamlit fully render

        # Frame 0: Landing page
        page.screenshot(path=str(ASSETS / "frame_0.png"), full_page=False)
        print("✓ Frame 0: Landing page")

        for i, question in enumerate(QUESTIONS[1:], start=1):
            # Type the question into the chat input
            chat_input = page.locator('textarea[data-testid="stChatInputTextArea"]')
            chat_input.click()
            chat_input.fill(question)

            # Press Enter to submit
            chat_input.press("Enter")

            # Wait for the agent to respond
            print(f"  Waiting for Q{i} response...")
            wait_for_response(page, timeout=90)
            time.sleep(2)  # Let markdown render

            # Scroll to the latest user message so the question is visible
            page.evaluate("""
                const msgs = document.querySelectorAll('[data-testid="stChatMessage"]');
                if (msgs.length >= 2) {
                    msgs[msgs.length - 2].scrollIntoView({block: 'start'});
                }
            """)
            time.sleep(1)

            page.screenshot(path=str(ASSETS / f"frame_{i}.png"), full_page=False)
            print(f"✓ Frame {i}: {question[:50]}...")

        browser.close()
        print(f"\nAll {len(QUESTIONS)} screenshots saved to {ASSETS}/")


if __name__ == "__main__":
    take_screenshots()
