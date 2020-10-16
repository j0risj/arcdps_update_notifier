import requests
import bs4
import time
import configparser
import logging
import sys
import json
from datetime import datetime as dt

from discordlogger.discordhandler import DiscordHandler

# Load config
config = configparser.ConfigParser()
with open("config.ini", encoding="utf-8") as f:
    config.read_file(f)

# Logging setup
logger = logging.getLogger("arcdps_updater")
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    "[%(asctime)s][%(name)s][%(levelname)s]: %(message)s",
    "%Y-%m-%d %H:%M:%S")
ch = logging.StreamHandler()
ch.setFormatter(formatter)
fh = logging.FileHandler("arcdps_updater.log", encoding="utf-8")
fh.setFormatter(formatter)
fh.setLevel(logging.INFO)
if config.getboolean("LOGGING", "enable_discord_logging"):
    dh = DiscordHandler(logger.name + "Log",
                        config["LOGGING"]["webhhok_url"])
    dh.setFormatter(formatter)
    dh.setLevel(logging.WARNING)
logger.addHandler(ch)
logger.addHandler(fh)
logger.addHandler(dh)

logger.debug("Starting script...")

arcdps_url = "https://www.deltaconnected.com/arcdps/"
webhook_url = f"https://discordapp.com/api/webhooks/"
download_url = "https://www.deltaconnected.com/arcdps/x64/"
last_update_data_filename = "last_update_data.json"

#  Retrieving and parsing arcdps website content
logger.debug("Downloading website content...")

try:
    response = requests.get(arcdps_url, timeout=5)
    response.raise_for_status()
except requests.exceptions.Timeout:
    logger.critical("Request to arcdps website timed out")
    sys.exit(1)
except requests.exceptions.HTTPError:
    logger.critical(f"Request return code was not 200")
    sys.exit(1)

logger.debug("Downloaded website content")

soup = bs4.BeautifulSoup(response.content, features="html.parser")

soup = soup.find_all("b", string="changes")
if len(soup) != 1:
    logger.critical(f"Error while parsing soup, found {len(soup)} "
                    + "matches for tag: 'b'")
    sys.exit(1)

changelog = []

for element in soup[0].next_elements:
    if type(element) is bs4.element.NavigableString:
        changelog.append(str(element).strip())
    elif type(element) is bs4.element.Tag and (element.name == "b" and element.string == "download"):
        break

changelog = changelog[1:]  # remove "changes" string from list

logger.debug("Parsed website content")

# Reading last update message file
try:
    with open(last_update_data_filename, encoding="utf-8") as f:
        last_update_data = json.load(f)
    if "message" not in last_update_data or "time" not in last_update_data:
        raise FileNotFoundError
    last_update_data["time"] = dt.strptime(last_update_data["time"], "%Y-%m-%d %H:%M:%S.%f")
except FileNotFoundError:
    logger.warning(
        "File 'last_update_data.txt' not found or empty, creating file...")
    try:
        with open(last_update_data_filename, "w", encoding="utf-8") as f:
            json.dump({"message": changelog[0], "time": str(
                dt.now())}, f)
    except Exception as e:
        logger.exception(
            f"There was an error writing the last update message file to disk")
    sys.exit(1)

logger.debug("Loaded latest update message from disk")

time_since_last_update = dt.now() - last_update_data["time"]
if time_since_last_update.days > 0:
    logger.warning(
        f"Time since last update check more than {time_since_last_update.days} days! Last Update: {str(last_update_data['time'])}")
elif time_since_last_update.seconds / 3600 > 1:
    logger.warning(
        f"Time since last update check more than {time_since_last_update.seconds // 3600} hours! Last Update: {str(last_update_data['time'])}")

if changelog[0] == last_update_data["message"]:
    try:
        with open(last_update_data_filename, "w", encoding="utf-8") as f:
            json.dump({"message": changelog[0], "time": str(
                dt.now())}, f)
    except Exception as e:
        logger.exception(
            f"There was an error writing the last update message file to disk")
        sys.exit(1)
    logger.info("No changes detected, exiting...")
    sys.exit(0)

#  New change detected handling
logger.info("New changes detected")

change_date = changelog[0].split(":")[0]
changes = "\n".join(
    [change for change in changelog if change.startswith(change_date)])

body = {
    "username": config["WEBHOOK"]["username"],
    "content": "Ein neues ArcDPS Update ist verfügbar! :partying_face:",
    "embeds": [{
        "color": 14434878,
        "title": "changes",
        "description": f"{changes}\n\n[Link zum Download]({download_url})",
        "footer": {"text": "Webhook von Joma#5663"}
    }]
}
if "avatar_url" in config["WEBHOOK"]:
    body["avatar_url"] = config["WEBHOOK"]["avatar_url"]

for webhook_id in config["WEBHOOK"]["webhook_ids"].split(","):
    try:
        response = requests.post(
            webhook_url + webhook_id, json=body, timeout=5)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        logger.exception(
            f"Request to discord webhook url timed out\nID: {webhook_id}")
        sys.exit(1)
    except requests.exceptions.HTTPError:
        logger.exception(
            f"Request to discord webhook url failed\nID: {webhook_id}")
        sys.exit(1)

logger.info("Successfully sent discord webhook messages")

try:
    with open(last_update_data_filename, "w", encoding="utf-8") as f:
        json.dump({"message": changelog[0], "time": str(
            dt.now())}, f)
except Exception as e:
    logger.exception(
        f"There was an error writing the last update message file to disk")
    sys.exit(1)

logger.info("Wrote latest update data to disk")
