"""Mandatory end-to-end demonstration, driven through the EVAP web UI with Playwright.

Phases (run inside the Playwright container, see scripts/run_ui_demo.sh):
  setup : admin creates users, project "Mini BMS", connects the repository, generates the CI token
  demo  : engineer imports the Excel SRS, creates TC-001 from SW-001, writes/imports the script,
          reviewer approves it, engineer executes it manually (expects PASS),
          reviewer enables automatic Git-triggered validation
  check : signs in and captures screenshots of Overview and Results (after the push demo)
Every action goes through the browser UI — no direct API calls.
"""
import os
import re
import sys

from playwright.sync_api import expect, sync_playwright

URL = os.environ.get("EVAP_URL", "http://127.0.0.1:8300")
OUT = os.environ.get("OUT_DIR", "/out")
EX = os.environ.get("EXAMPLES_DIR", "/examples")
ADMIN = (os.environ["ADMIN_USER"], os.environ["ADMIN_PASSWORD"])
ENG = ("alice", os.environ["ENG_PASSWORD"])
REV = ("rob", os.environ["REV_PASSWORD"])
REPO = os.environ["REPO_URL"]
SHOT = 0
PHASE = sys.argv[1] if len(sys.argv) > 1 else "x"


def shot(page, name):
    global SHOT
    SHOT += 1
    page.screenshot(path=f"{OUT}/{PHASE}_{SHOT:02d}_{name}.png", full_page=True)


def login(page, user):
    page.goto(URL + "/")
    page.evaluate("localStorage.removeItem('evap_token')")
    page.goto(URL + "/")
    page.get_by_label("Username").fill(user[0])
    page.get_by_label("Password").fill(user[1])
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_text(f"{user[0]} ·")).to_be_visible()


def nav(page, label):
    page.locator(".sidebar").get_by_role("link", name=label).click()


def setup(page):
    login(page, ADMIN)
    # 1. Create the Mini BMS validation project
    page.get_by_role("button", name=re.compile("New project|Create your first project")).first.click()
    page.get_by_label("Project name").fill("Mini BMS")
    page.get_by_label("Description").fill("SIL validation of the Mini BMS demonstration software")
    page.get_by_role("button", name="Create project").click()
    expect(page.locator(".toast")).to_contain_text("Mini BMS")
    nav(page, "CI/CD Integration")
    # Users: engineer + reviewer (four-eyes principle)
    for (name, pw), role in ((ENG, "engineer"), (REV, "reviewer")):
        page.get_by_placeholder("username").fill(name)
        page.get_by_placeholder("password (min 10 chars)").fill(pw)
        page.locator(".card", has_text="Users & roles").locator("select").last.select_option(role)
        page.get_by_role("button", name="Add user").click()
        expect(page.locator("td", has_text=name)).to_be_visible()
    # 2. Connect the Mini BMS repository
    page.get_by_label("Git repository URL").fill(REPO)
    page.get_by_label("Branch").fill("main")
    page.get_by_role("button", name="Save Git integration").click()
    expect(page.locator(".toast")).to_contain_text("Git integration saved")
    page.get_by_role("button", name="Generate CI token").click()
    token = page.locator(".ok code").inner_text().strip()
    assert token.startswith("evapci_"), token
    with open("/secrets/ci_token.txt", "w") as f:  # consumed by the operator, then deleted
        f.write(token)
    page.locator(".ok code").evaluate("el => el.textContent = 'evapci_••••••••'")
    shot(page, "cicd_configured")


def demo(page):
    login(page, ENG)
    # 3. Import the Excel SRS
    nav(page, "Requirements")
    page.get_by_test_id("srs-file").set_input_files(f"{EX}/SRS_mini_bms.xlsx")
    expect(page.locator(".ok")).to_contain_text("created: SW-001")
    shot(page, "requirements_imported")
    # 4. Create TC-001 directly from the requirement
    page.locator("tr", has_text="SW-001").click()
    page.get_by_role("button", name="+ Test case").click()
    expect(page.get_by_label("Test case ID")).to_have_value("TC-001")
    page.get_by_label("Title").fill("Charging authorization at the overtemperature threshold")
    page.get_by_label("Preconditions").fill("BMS initialised; all other charging conditions satisfied")
    page.get_by_label("Inputs").fill("Battery temperature: 59.9, 60.0, 60.1 degC")
    page.get_by_label("Expected results").fill("Charging allowed: True, False, False")
    page.get_by_role("button", name="Create test case").click()
    expect(page.locator(".toast")).to_contain_text("TC-001 created")
    # 5. Write the parameterized pytest script (imported into the editor), validate, save
    page.locator('input[type=file][accept=".py,text/x-python"]').set_input_files(f"{EX}/test_tc001_sw001.py")
    expect(page.locator(".cm-content")).to_contain_text("test_sw001_overtemperature_protection")
    page.get_by_role("button", name="Validate").click()
    expect(page.locator(".ok")).to_contain_text("Syntax OK")
    page.get_by_role("button", name="Save as new revision").click()
    expect(page.locator(".toast")).to_contain_text("Saved revision r1")
    shot(page, "script_saved_draft")
    # 6. Reviewer approves (author cannot approve own script)
    login(page, REV)
    nav(page, "Test Design")
    page.locator(".list-item", has_text="TC-001").click()
    page.get_by_placeholder("Review comment").fill("Boundary values 59.9/60.0/60.1 cover SW-001")
    page.get_by_role("button", name="Approve r1").click()
    expect(page.locator(".toast")).to_contain_text("approved")
    # 7. Engineer executes the approved test manually
    login(page, ENG)
    nav(page, "Test Design")
    page.locator(".list-item", has_text="TC-001").click()
    page.get_by_role("button", name="Execute approved r1").click()
    modal = page.locator(".modal")
    expect(modal.locator(".badge", has_text="PASSED")).to_be_visible(timeout=120_000)
    modal.locator("tr.click").first.click()
    expect(modal.locator("pre.log")).to_contain_text("3 passed")
    shot(page, "manual_run_pass")
    page.keyboard.press("Escape")
    # 8. Reviewer enables automatic Git-triggered validation
    login(page, REV)
    nav(page, "CI/CD Integration")
    page.get_by_label(re.compile("Automatic validation on every push")).check()
    page.get_by_role("button", name="Save Git integration").click()
    expect(page.locator(".toast")).to_contain_text("Git integration saved")
    expect(page.get_by_text("automatic validation enabled")).to_be_visible()
    shot(page, "auto_validation_enabled")


def check(page):
    login(page, ENG)
    nav(page, "Overview")
    expect(page.get_by_text("Latest validation status")).to_be_visible()
    page.wait_for_timeout(1500)
    shot(page, "overview")
    nav(page, "Validation Results")
    page.wait_for_timeout(1500)
    shot(page, "results")
    nav(page, "Requirements")
    page.wait_for_timeout(800)
    shot(page, "requirements")


if __name__ == "__main__":
    phase = sys.argv[1]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(20_000)
        try:
            {"setup": setup, "demo": demo, "check": check}[phase](page)
        except Exception:
            page.screenshot(path=f"{OUT}/FAILED_{phase}.png", full_page=True)
            raise
        browser.close()
    print(f"UI phase '{phase}' OK")
