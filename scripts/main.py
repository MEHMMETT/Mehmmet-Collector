import base64
import json
import logging
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Dict
import urllib.parse
import urllib.request
import pycountry
import requests
from bs4 import BeautifulSoup
import shutil
import telegram_sender
import socket

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TELEGRAM_URLS = [
    "https://t.me/s/prrofile_purple", "https://t.me/s/v2line", "https://t.me/s/v2ray1_ng",
    "https://t.me/s/v2ray_swhil", "https://t.me/s/v2rayng_fast", "https://t.me/s/v2rayng_vpnrog",
    "https://t.me/s/v2raytz", "https://t.me/s/vmessorg", "https://t.me/s/ISVvpn",
    "https://t.me/s/forwardv2ray", "https://t.me/s/PrivateVPNs", "https://t.me/s/VlessConfig",
    "https://t.me/s/V2pedia", "https://t.me/s/v2rayNG_Matsuri", "https://t.me/s/proxystore11",
    "https://t.me/s/DirectVPN", "https://t.me/s/OutlineVpnOfficial", "https://t.me/s/networknim",
    "https://t.me/s/beiten", "https://t.me/s/MsV2ray", "https://t.me/s/foxrayiran",
    "https://t.me/s/DailyV2RY", "https://t.me/s/yaney_01", "https://t.me/s/EliV2ray",
    "https://t.me/s/ServerNett", "https://t.me/s/v2rayng_fa2", "https://t.me/s/v2rayng_org",
    "https://t.me/s/V2rayNGvpni", "https://t.me/s/v2rayNG_VPNN", "https://t.me/s/v2_vmess",
    "https://t.me/s/FreeVlessVpn", "https://t.me/s/vmess_vless_v2rayng", "https://t.me/s/freeland8",
    "https://t.me/s/vmessiran", "https://t.me/s/V2rayNG3", "https://t.me/s/ShadowsocksM",
    "https://t.me/s/ShadowSocks_s", "https://t.me/s/VmessProtocol", "https://t.me/s/Easy_Free_VPN",
    "https://t.me/s/V2Ray_FreedomIran", "https://t.me/s/V2RAY_VMESS_free", "https://t.me/s/v2ray_for_free",
    "https://t.me/s/V2rayN_Free", "https://t.me/s/free4allVPN", "https://t.me/s/configV2rayForFree",
    "https://t.me/s/FreeV2rays", "https://t.me/s/DigiV2ray", "https://t.me/s/v2rayNG_VPN",
    "https://t.me/s/freev2rayssr", "https://t.me/s/v2rayn_server", "https://t.me/s/iranvpnet",
    "https://t.me/s/vmess_iran", "https://t.me/s/configV2rayNG", "https://t.me/s/vpn_proxy_custom",
    "https://t.me/s/vpnmasi", "https://t.me/s/ViPVpn_v2ray", "https://t.me/s/vip_vpn_2022",
    "https://t.me/s/FOX_VPN66", "https://t.me/s/YtTe3la", "https://t.me/s/ultrasurf_12",
    "https://t.me/s/frev2rayng", "https://t.me/s/FreakConfig", "https://t.me/s/Awlix_ir",
    "https://t.me/s/arv2ray", "https://t.me/s/flyv2ray", "https://t.me/s/free_v2rayyy",
    "https://t.me/s/ip_cf", "https://t.me/s/lightning6", "https://t.me/s/mehrosaboran",
    "https://t.me/s/oneclickvpnkeys", "https://t.me/s/outline_vpn", "https://t.me/s/outlinev2rayng",
    "https://t.me/s/outlinevpnofficial", "https://t.me/s/v2rayngvpn", "https://t.me/s/V2raNG_DA",
    "https://t.me/s/V2rayNg_madam", "https://t.me/s/v2boxxv2rayng", "https://t.me/s/configshub2",
    "https://t.me/s/v2ray_configs_pool", "https://t.me/s/hope_net", "https://t.me/s/everydayvpn",
    "https://t.me/s/v2nodes", "https://t.me/s/shadowproxy66", "https://t.me/s/free_nettm"
]

SEND_TO_TELEGRAM = os.getenv('SEND_TO_TELEGRAM', 'false').lower() == 'true'
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
SUB_CHECKER_DIR = Path("sub-checker")

def full_unquote(s: str) -> str:
    if chr(37) not in s:
        return s
    prev_s = ""
    while s != prev_s:
        prev_s = s
        s = urllib.parse.unquote(s)
    return s

def clean_previous_configs(configs: List[str]) -> List[str]:
    cleaned_configs = []
    for config in configs:
        try:
            if chr(35) in config:
                base_uri, tag = config.split(chr(35), 1)
                decoded_tag = full_unquote(tag)
                cleaned_tag = re.sub(r'::[A-Z]{2}$', '', decoded_tag).strip()
                if cleaned_tag:
                    final_config = base_uri + chr(35) + cleaned_tag
                else:
                    final_config = base_uri
                cleaned_configs.append(final_config)
            else:
                cleaned_configs.append(config)
        except Exception as e:
            cleaned_configs.append(config)
    return cleaned_configs

def scrape_configs_from_url(url: str) -> List[str]:
    configs = []
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        all_text_content = "\n".join(tag.get_text('\n') for tag in soup.find_all(['div', 'code', 'blockquote', 'pre']))
        pattern = r'((?:vmess|vless|ss|hy2|trojan|hysteria2)://[^\s<>"\'`]+)'
        found_configs = re.findall(pattern, all_text_content)
        for config in found_configs:
            if config.startswith("vmess://"):
                try:
                    base_part = config.split(chr(35), 1)[0]
                    encoded_json = base_part.replace("vmess://", "")
                    encoded_json += '=' * (-len(encoded_json) % 4)
                    decoded_bytes = base64.b64decode(encoded_json)
                    try:
                        decoded_json = decoded_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        decoded_json = decoded_bytes.decode("latin-1")
                    vmess_data = json.loads(decoded_json)
                    updated_json = json.dumps(vmess_data, separators=(',', ':'))
                    updated_b64 = base64.b64encode(updated_json.encode('utf-8')).decode('utf-8').rstrip('=')
                    configs.append("vmess://" + updated_b64)
                except Exception as e:
                    pass
            else:
                base_uri = config.split(chr(35), 1)[0]
                configs.append(base_uri)
        return configs
    except Exception as e:
        return []

def run_sub_checker(input_configs: List[str]) -> List[str]:
    if not SUB_CHECKER_DIR.is_dir():
        return []
    normal_txt_path = SUB_CHECKER_DIR / "normal.txt"
    final_txt_path = SUB_CHECKER_DIR / "final.txt"
    cl_py_path = SUB_CHECKER_DIR / "cl.py"
    normal_txt_path.write_text("\n".join(input_configs), encoding="utf-8")
    try:
        process = subprocess.run(
            ["python", cl_py_path.name],
            cwd=SUB_CHECKER_DIR,
            capture_output=True,
            text=True,
            timeout=7200
        )
        if process.returncode != 0:
            return []
        if final_txt_path.exists():
            checked_configs = final_txt_path.read_text(encoding="utf-8").splitlines()
            return [line for line in checked_configs if line.strip()]
        else:
            return []
    except Exception as e:
        return []

def get_accurate_ip(host: str) -> str:
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for info in infos:
            address = info[4][0]
            if address:
                return address
    except Exception:
        pass
    return ""

def extract_host(config: str) -> str:
    try:
        if config.startswith("vmess://"):
            base_part = config.split(chr(35), 1)[0]
            encoded_json = base_part.replace("vmess://", "")
            encoded_json += '=' * (-len(encoded_json) % 4)
            decoded_bytes = base64.b64decode(encoded_json)
            try:
                decoded_json = decoded_bytes.decode("utf-8")
            except UnicodeDecodeError:
                decoded_json = decoded_bytes.decode("latin-1")
            data = json.loads(decoded_json)
            return str(data.get("add") or data.get("host") or "")
        else:
            base_uri = config.split(chr(35), 1)[0]
            parts = urllib.parse.urlsplit(base_uri)
            return parts.hostname or ""
    except Exception:
        return ""

def get_geo_batch(ips: List[str]) -> Dict[str, str]:
    results = {}
    valid_ips = [ip for ip in ips if ip]
    if not valid_ips:
        return results
    endpoint = "http://ip-api.com/batch?fields=countryCode,query"
    for index in range(0, len(valid_ips), 100):
        chunk = valid_ips[index:index + 100]
        payload = [{"query": ip} for ip in chunk]
        try:
            response = requests.post(endpoint, json=payload, timeout=20)
            if response.status_code == 200:
                entries = response.json()
                for entry in entries:
                    query = entry.get("query")
                    code = entry.get("countryCode")
                    if query and code:
                        results[query] = code.upper()
        except Exception:
            pass
    return results

def get_country_flag(code: str) -> str:
    if not code or len(code) != 2 or not code.isalpha():
        return chr(10067)
    return chr(0x1F1E6 + ord(code[0]) - 65) + chr(0x1F1E6 + ord(code[1]) - 65)

def process_and_save_results(checked_configs: List[str]) -> Dict[str, int]:
    if not checked_configs:
        return {}, []
    loc_dir = Path("loc")
    mix_dir = Path("mix")
    if loc_dir.is_dir():
        try:
            shutil.rmtree(loc_dir)
        except Exception:
            pass
    loc_dir.mkdir(exist_ok=True)
    mix_dir.mkdir(exist_ok=True)
    
    hosts_to_ips = {}
    for config in checked_configs:
        host = extract_host(config)
        if host and host not in hosts_to_ips:
            ip = get_accurate_ip(host)
            if ip:
                hosts_to_ips[host] = ip

    ip_to_country = get_geo_batch(list(hosts_to_ips.values()))
    
    configs_by_protocol = {"vless": [], "vmess": [], "ss": [], "trojan": [], "hy2": []}
    configs_by_location = {}
    country_counters = {}
    final_configs = []

    for config in checked_configs:
        host = extract_host(config)
        ip = hosts_to_ips.get(host, "")
        location_code = ip_to_country.get(ip, "")
        if not location_code:
            try:
                decoded_config = urllib.parse.unquote(config)
                match = re.search(r'::([A-Za-z]{2})$', decoded_config)
                if match:
                    location_code = match.group(1).upper()
            except Exception:
                pass
        if not location_code:
            location_code = "XX"
            
        if location_code not in country_counters:
            country_counters[location_code] = 1
        else:
            country_counters[location_code] += 1
            
        flag = get_country_flag(location_code)
        new_name = "Dr-Anv " + flag + " " + str(country_counters[location_code])
        
        renamed_config = ""
        try:
            if config.startswith("vmess://"):
                base_part = config.split(chr(35), 1)[0]
                encoded_json = base_part.replace("vmess://", "")
                encoded_json += '=' * (-len(encoded_json) % 4)
                decoded_bytes = base64.b64decode(encoded_json)
                try:
                    decoded_json = decoded_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    decoded_json = decoded_bytes.decode("latin-1")
                vmess_data = json.loads(decoded_json)
                vmess_data["ps"] = new_name
                updated_json = json.dumps(vmess_data, separators=(',', ':'))
                updated_b64 = base64.b64encode(updated_json.encode('utf-8')).decode('utf-8').rstrip('=')
                renamed_config = "vmess://" + updated_b64
            else:
                base_uri = config.split(chr(35), 1)[0]
                renamed_config = base_uri + chr(35) + urllib.parse.quote(new_name)
        except Exception:
            renamed_config = config

        if renamed_config.startswith(("hysteria://", "hysteria2://", "hy2://")):
            configs_by_protocol["hy2"].append(renamed_config)
        elif renamed_config.startswith("vless://"):
            configs_by_protocol["vless"].append(renamed_config)
        elif renamed_config.startswith("vmess://"):
            configs_by_protocol["vmess"].append(renamed_config)
        elif renamed_config.startswith("ss://"):
            configs_by_protocol["ss"].append(renamed_config)
        elif renamed_config.startswith("trojan://"):
            configs_by_protocol["trojan"].append(renamed_config)

        if location_code not in configs_by_location:
            configs_by_location[location_code] = []
        configs_by_location[location_code].append(renamed_config)
        final_configs.append(renamed_config)

    for proto, configs in configs_by_protocol.items():
        if configs:
            file_path = Path(proto + ".html")
            file_path.write_text("\n".join(configs), encoding="utf-8")

    Path("mix/sub.html").write_text("\n".join(final_configs), encoding="utf-8")

    for loc_code, configs in configs_by_location.items():
        country_flag_emoji = get_country_flag(loc_code)
        file_path = Path("loc") / (loc_code + " " + country_flag_emoji + ".txt")
        file_path.write_text("\n".join(configs), encoding="utf-8")

    return {proto: len(configs) for proto, configs in configs_by_protocol.items()}, final_configs

def main():
    all_raw_configs = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        future_to_url = {executor.submit(scrape_configs_from_url, url): url for url in TELEGRAM_URLS}
        for future in future_to_url:
            all_raw_configs.extend(future.result())

    unique_new_configs = sorted(list(set(all_raw_configs)))
    previous_configs = []
    previous_mix_file = Path("mix/sub.html")
    if previous_mix_file.is_file():
        try:
            previous_configs = previous_mix_file.read_text(encoding="utf-8").splitlines()
            previous_configs = [line.strip() for line in previous_configs if '://' in line]
            previous_configs = clean_previous_configs(previous_configs)
        except Exception:
            pass

    combined_configs = unique_new_configs + previous_configs
    unique_combined_configs = sorted(list(set(combined_configs)))
    if not unique_combined_configs:
        return

    checked_configs = run_sub_checker(unique_combined_configs)
    
    protocol_counts, renamed_checked_configs = process_and_save_results(checked_configs)
    
    if SEND_TO_TELEGRAM:
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and TELEGRAM_CHANNEL_ID:
            if protocol_counts:
                try:
                    bot = telegram_sender.init_bot(TELEGRAM_BOT_TOKEN)
                    if bot:
                        telegram_sender.send_summary_message(bot, TELEGRAM_CHANNEL_ID, protocol_counts)
                        grouped_configs = telegram_sender.regroup_configs_by_source(renamed_checked_configs)
                        telegram_sender.send_all_grouped_configs(bot, TELEGRAM_CHANNEL_ID, grouped_configs)
                except Exception:
                    pass

if __name__ == "__main__":
    main()
