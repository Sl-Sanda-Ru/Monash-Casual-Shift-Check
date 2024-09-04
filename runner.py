import requests
from datetime import datetime, timedelta
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

nrml_msg = "You Have Done {} Hours, and You Got Future Bookings For {} Hours, You Can Do {:.2f} More Hours"
exceed_msg = "You Have Done {} Hours, and You Got Future Bookings For {} Hours, **Hours Exceeded By {:.2f}**"


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


def process_roster_data(roster_data, fortnight_end):
    shifts = ([], [])  # shifts within the fortnight, shifts outside fortnight
    total_hours = 0
    global current_date, current_time
    current_date = datetime.now().date()
    current_time = datetime.now().time()

    for shortfall in roster_data.get("roster", {}).get("shortfalls", []):
        # global shift_date, shift_start, shift_end
        shift_date = datetime.strptime(shortfall["day"], "%Y-%m-%d").date()
        shift_day = shift_date.strftime('%A')
        shift_start = shortfall["shiftStart"]
        shift_end = shortfall["shiftEnd"]
        location = f'{shortfall["location4"]["description"]} {shortfall["location2"]["description"]}'
        try:
            assigner = shortfall["notes"][0]["text"]
        except:
            pass
        else:
            location += f" {assigner}"
        # print(shift_date, shift_start, shift_end, location)
        if (
            shift_date <= fortnight_end
            and shift_date > current_date
            or (
                shift_date == current_date
                and datetime.strptime(shift_end, "%H:%M").time() > current_time
            )
        ):
            shifts[0].append(f"{shift_date} **{shift_day}** {location} {shift_start} {shift_end}")
            total_hours += calculate_shift_hours(shift_start, shift_end)
        elif shift_date > fortnight_end:
            shifts[1].append(f"{shift_date} **{shift_day}** {location} {shift_start} {shift_end}")

    return shifts, total_hours


def get_completed_hours():
    if getenv("CHRMDRIVR"):
        cService = webdriver.ChromeService(executable_path=getenv("CHRMDRIVR"))
        driver = webdriver.Chrome(service=cService, options=options)
    else:
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
    sleep(5)
    hours = (
        WebDriverWait(driver, 15)
        .until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="13_cumulativetotal"]'))
        )
        .text
    )
    if not hours:
        hours = 0
    fortnight_end = driver.find_element(
        By.XPATH, '//*[@id="0_date"]/span[3]/span/span'
    ).text
    fortnight_end = (
        datetime.strptime(fortnight_end, "%a %d/%m").replace(year=datetime.now().year)
        + timedelta(days=13)
    ).date()
    driver.quit()
    logging.info(f"get_completed_hours: {hours} fortnight end:{fortnight_end}")
    return float(hours), fortnight_end


def generate_report():
    while True:
        try:
            donehours, fortnight_end = get_completed_hours()
        except ValueError:
            sleep(15)
        else:
            break
    rosterdata = process_roster_data(fetch_roster_data(), fortnight_end)
    total = rosterdata[1] + donehours
    if total > 48:
        msg = exceed_msg.format(donehours, rosterdata[1], total - 48)
    else:
        msg = nrml_msg.format(donehours, rosterdata[1], 48 - total)
    return (
        f"{msg}\n\nHere's Your Schedule:\n"
        + "\n".join(rosterdata[0][0])
        + "\n\nShifts booked for upcoming fortnights:\n"
        + "\n".join(rosterdata[0][1])
    )


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

try:
    scheduler_thread.start()
    handlerclient.run()
except KeyboardInterrupt:
    logging.info("Script terminated by user")
    exit()
