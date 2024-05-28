import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
import schedule
from pyrogram import Client, filters
from os import getenv
from dotenv import load_dotenv
from time import sleep
from threading import Thread
import logging


load_dotenv(dotenv_path="config.env")

logging.basicConfig(level=logging.INFO)

options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_experimental_option("excludeSwitches", ["enable-logging"])

nrml_msg = "You Have Done {} Hours, and You Got Future Bookings For {} Hours, You Can Do {} More Hours"
exceed_msg = "You Have Done {} Hours, and You Got Future Bookings For {} Hours, **Hours Exceeded By {}**"


handlerclient = Client(
    "HandlerClient",
    bot_token=getenv("BTTKN"),
    api_id=getenv("APIID"),
    api_hash=getenv("APIHASH"),
)
senderclient = Client(
    "SenderClient",
    bot_token=getenv("BTTKN"),
    api_id=getenv("APIID"),
    api_hash=getenv("APIHASH"),
)
senderclient.start()
logging.info("Telegram Bot Clients Created")


def fetch_roster_data():
    headers = {
        "authorization": getenv("AUTHKEY"),
        "content-type": "application/json",
        "accept-encoding": "gzip",
        "user-agent": "okhttp/4.10.0",
    }
    try:
        response = requests.get(
            "https://monash.shiftmatch.com.au/cascom/json.my.roster.do", headers=headers
        )
        response.raise_for_status()
    except Exception:
        return None
    return response.json()


def calculate_shift_hours(shift_start, shift_end):
    start_time = datetime.strptime(shift_start, "%H:%M")
    end_time = datetime.strptime(shift_end, "%H:%M")
    return (end_time - start_time).total_seconds() / 3600  # to get in hours


def process_roster_data(roster_data):
    shifts = []
    total_hours = 0
    current_date = datetime.now().date()
    current_time = datetime.now().time()

    for shortfall in roster_data.get("roster", {}).get("shortfalls", []):
        shift_date = datetime.strptime(shortfall["day"], "%Y-%m-%d").date()
        shift_start = shortfall["shiftStart"]
        shift_end = shortfall["shiftEnd"]
        location = f'{shortfall["location4"]["description"]} {shortfall["location2"]["description"]}'
        try:
            assigner = shortfall["notes"][0]["text"]
        except:
            pass
        else:
            location += f" {assigner}"

        if shift_date > current_date or (
            shift_date == current_date
            and not datetime.strptime(shift_end, "%H:%M").time() < current_time
        ):
            shifts.append(f"{shift_date} {location} {shift_start} {shift_end}")
            total_hours += calculate_shift_hours(shift_start, shift_end)

    return shifts, total_hours


def get_completed_hours():
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )
    driver.get(
        "https://cust03-prd01-ath01.prd.mykronos.com/authn/XUI/?realm=monashhealth_prd_01&service=1850CustomerIDPChain&goto=https%3A%2F%2Fmonashhealth-sso.prd.mykronos.com%3A443%2F"
    )
    uname = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.XPATH, '//*[@id="userNameInput"]'))
    )
    passw = driver.find_element(By.XPATH, '//*[@id="passwordInput"]')
    uname.send_keys(getenv("UNAME"))
    passw.send_keys(getenv("PWORD"))
    passw.send_keys(Keys.ENTER)
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located(
            (By.XPATH, '//*[@id="emptimecard-btn-204"]/div/div[2]/i')
        )
    )
    driver.get(
        "https://monashhealth-sso.prd.mykronos.com/timekeeping#/myTimecard?ctxt=myTimecard"
    )
    hours = (
        WebDriverWait(driver, 15)
        .until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="13_cumulativetotal"]/span[3]/span/span')
            )
        )
        .text
    )
    driver.quit()
    logging.info(f"get_completed_hours: {hours}")
    return float(hours)


def generate_report():
    rosterdata = process_roster_data(fetch_roster_data())
    while True:
        try:
            donehours = get_completed_hours()
        except ValueError:
            sleep(15)
        else:
            break

    total = rosterdata[1] + donehours
    if total > 48:
        msg = exceed_msg.format(donehours, rosterdata[1], total - 48)
    else:
        msg = nrml_msg.format(donehours, rosterdata[1], 48 - total)
    return f"{msg}\nHere's Your Schedule:\n" + "\n".join(rosterdata[0])


def sender():
    report = generate_report()
    senderclient.send_message(chat_id=getenv("CHTID"), text=report)


schedule.every().day.at(getenv("TIME")).do(sender)


def run_scheduler():
    while True:
        schedule.run_pending()
        sleep(58)


@handlerclient.on_message(filters.command("check"))
def check(client, message):
    report = generate_report()
    client.send_message(chat_id=getenv("CHTID"), text=report)


scheduler_thread = Thread(target=run_scheduler)
scheduler_thread.start()
try:
    handlerclient.run()
except KeyboardInterrupt:
    logging.info("Script terminated by user")
finally:
    senderclient.stop()
