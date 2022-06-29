import configparser
import json
import logging
import os
import sys
import time
import typing
from datetime import datetime as dt
from json.decoder import JSONDecodeError

import bs4
import requests
from discordlogger.discordhandler import DiscordHandler

last_changes_file = "last_changes.json"


# Load config
def load_config():
    config = configparser.ConfigParser()
    with open("config.ini", encoding="utf-8") as f:
        config.read_file(f)
    return config


config = load_config()


# Logging setup
def setup_logging():
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
                            config["LOGGING"]["webhook_url"])
        dh.setFormatter(formatter)
        dh.setLevel(logging.WARNING)
    logger.addHandler(ch)
    logger.addHandler(fh)
    logger.addHandler(dh)
    return logger


logger = setup_logging()


#  Retrieve arcdps website content
def download_website_content() -> requests.Response:
    arcdps_url = "https://www.deltaconnected.com/arcdps/"
    try:
        response = requests.get(arcdps_url, timeout=5)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        logger.critical("Request to arcdps website timed out")
        sys.exit(1)
    except requests.exceptions.HTTPError:
        logger.critical("Request return code was not OK "
                        + f"({response.status_code})")
        sys.exit(1)
    return response


def parse_html(response: requests.Response) -> typing.List[str]:
    soup = bs4.BeautifulSoup(response.content, features="html.parser")
    soup = soup.find("b", string="changes")
    changelog = []
    for element in soup.next_elements:
        element_string = element.string
        if element_string is not None:
            changelog.append(element.string.strip())
        if element.name == "b" and element.string == "download":
            break
    # remove "changes", "downloads" and a newline from list
    changelog = changelog[1:-2]
    return changelog


def write_last_changes(changelog: typing.List[str]):
    try:
        with open(last_changes_file, "w", encoding="utf-8") as f:
            json.dump({"changes": changelog,
                       "timestamp": dt.now().isoformat()}, f)
    except Exception:
        logger.exception(
            f"A problem occured while writing {last_changes_file}")
        sys.exit(1)


# Reading last changes file
def load_last_changes(changelog: typing.List[str]):
    try:
        with open(last_changes_file, encoding="utf-8") as f:
            last_changes_data = json.load(f)
        # <= tests for subset
        if not {"timestamp", "changes"} <= last_changes_data.keys():
            raise FileNotFoundError
    except FileNotFoundError:
        logger.warning(f"File {last_changes_file} not found, "
                       + "creating a new file. ")
        write_last_changes(changelog)
        sys.exit(1)
    except JSONDecodeError:
        logger.warning(f"File {last_changes_file} "
                       + "empty or corrupt, creating a new file. "
                       + "You can find the old file under "
                       + f"{last_changes_file}.old")
        try:
            os.rename(last_changes_file, last_changes_file + ".old")
        except FileExistsError:
            pass
        write_last_changes(changelog)
        sys.exit(1)
    return last_changes_data


# Check if there was an arcdps update
def test_for_update(last_changes_data: typing.Dict) -> bool:
    last_test_timestamp = dt.fromisoformat(
        last_changes_data["timestamp"])
    hours_since_last_test = (
        dt.now() - last_test_timestamp).total_seconds() / 3600
    if hours_since_last_test > 1:
        logger.warning(f"Time since last update check more than "
                       + f"{hours_since_last_test} hours! Last Update: "
                       + f"{str(last_test_timestamp)}")

    return False if changelog[0] == last_changes_data["changes"][0] \
        else True


def get_checksum() -> str:
    url = "https://www.deltaconnected.com/arcdps/x64/d3d11.dll.md5sum"
    try:
        response = requests.get(url)
        response.raise_for_status()
    except Exception:
        logger.exception("An exception occured while trying to download"
                         + "the md5 checksum")
        sys.exit(1)
    return response.content.decode().split()[0]


def load_webhooks() -> str:
    try:
        with open("webhooks.json", "r", encoding="utf-8") as f:
            webhooks = json.load(f)
    except Exception:
        logger.exception("An exception occured while trying to read "
                         + "the webhooks.json file.")
        sys.exit(1)
    return webhooks


# Send message(s) via Discord webhook(s)
def send_update_message(changelog: typing.List[str],
                        old_changelog: typing.List[str]):
    webhooks = load_webhooks()
    checksum = get_checksum()
    changes = ""
    for change in changelog:
        if change in old_changelog:
            break
        else:
            changes += change + "\n"

    download_url = "https://www.deltaconnected.com/arcdps/x64/"
    body = {
        "content": "Ein neues ArcDPS Update ist verfügbar! "
        + ":partying_face:",
        "embeds": [{
            "color": 296359,
            "title": "changes",
            "description": f"{changes}\n"
            + f"[Link zum Download]({download_url})\n"
            + f"md5sum: `{checksum}`",
            "footer": {"text": "Webhook von Joma#5663"}
        }]
    }

    for webhook in webhooks:
        body["username"] = webhook["username"] if webhook["username"] \
            else config["WEBHOOK"]["default_username"]
        body["avatar_url"] = webhook["avatar_url"] if \
            webhook["avatar_url"] else ""

        try:
            response = requests.post(webhook["url"], json=body,
                                     timeout=5)
            response.raise_for_status()
        except requests.exceptions.Timeout:
            logger.error("Request to discord webhook url timed out"
                         + f"\nID: {webhook['url']}")
        except requests.exceptions.HTTPError:
            logger.exception(
                f"Request to discord webhook url failed\n"
                + f"\nID: {webhook['url']}")


if __name__ == "__main__":
    try:
        logger.info("Starting script...")
        response = download_website_content()
        logger.debug("Downloaded website content")
        changelog = parse_html(response)
        logger.debug("Parsed website content")
        last_changes_data = load_last_changes(changelog)
        logger.debug("Loaded last changelog")
        update_available = test_for_update(last_changes_data)
        if not update_available:
            logger.info("No changes detected, exiting...")
        else:
            logger.info("New changes detected")
            send_update_message(changelog, last_changes_data["changes"])
            logger.info("Sent discord webhook messages")
        write_last_changes(changelog)
        logger.debug("Wrote latest changes data to disk")
    except Exception:
        logger.exception("Unexpected error!")
