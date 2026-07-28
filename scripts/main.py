import base64
import binascii
import json
import os
import socket
import sys
import time
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit, urlunsplit, quote, unquote

import requests

HASH = chr(35)
BASE_NAME = "Dr-Anv"
SCHEMES = ("vmess://", "vless://", "trojan://", "ss://", "hysteria2://", "hy2://", "tuic://")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
SOURCES_FILE = os.environ.get("SOURCES_FILE", "sources.txt")
INPUT_FILE = os.environ.get("INPUT_FILE", "configs.txt")
TCP_TIMEOUT = float(os.environ.get("TCP_TIMEOUT", "4"))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "64"))
GEO_WORKERS = int(os.environ.get("GEO_WORKERS", "8"))
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ConfigCollector/2.0)"}

def pad_b64(data):
    return data + "=" * ((4 - len(data) % 4) % 4)

def try_b64_decode(data):
    cleaned = "".join(data.split())
    cleaned = cleaned.replace("-", "+").replace("_", "/")
    try:
        raw = base64.b64decode(pad_b64(cleaned), validate=False)
    except (binascii.Error, ValueError):
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None

def fetch_text(url):
    try:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=20)
        if response.status_code != 200:
            return ""
        return response.text
    except requests.RequestException:
        return ""

def read_local_file(path):
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        return handle.read()

def load_sources():
    urls = []
    env_sources = os.environ.get("SOURCES", "")
    for item in env_sources.replace(",", "\n").split("\n"):
        item = item.strip()
        if item.startswith("http"):
            urls.append(item)
    for line in read_local_file(SOURCES_FILE).splitlines():
        line = line.strip()
        if line.startswith("http"):
            urls.append(line)
    for argument in sys.argv[1:]:
        if argument.startswith("http"):
            urls.append(argument)
    return list(dict.fromkeys(urls))

def extract_configs(text):
    if not text:
        return []
    decoded = try_b64_decode(text)
    if decoded and any(scheme in decoded for scheme in SCHEMES):
        text = decoded
    found = []
    for token in text.replace("\r", "\n").replace("\t", "\n").replace(" ", "\n").split("\n"):
        token = token.strip().strip("\'\"<>,;")
        if token.lower().startswith(SCHEMES):
            found.append(token)
    return found

def split_fragment(uri):
    head, separator, tail = uri.partition(HASH)
    if separator:
        return head, tail
    return head, ""

def decode_vmess(uri):
    payload = uri[len("vmess://"):]
    payload, _ = split_fragment(payload)
    decoded = try_b64_decode(payload)
    if not decoded:
        return None
    try:
        data = json.loads(decoded)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data

def encode_vmess(data):
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "vmess://" + base64.b64encode(raw).decode("ascii")

def normalize_ss(uri):
    body, fragment = split_fragment(uri[len("ss://"):])
    if "@" in body:
        return body, fragment
    query = ""
    if "?" in body:
        body, query = body.split("?", 1)
    decoded = try_b64_decode(body)
    if not decoded or "@" not in decoded:
        return None, fragment
    if query:
        decoded = decoded + "?" + query
    return decoded, fragment

def endpoint_of(uri):
    lowered = uri.lower()
    try:
        if lowered.startswith("vmess://"):
            data = decode_vmess(uri)
            if not data:
                return None, None
            host = str(data.get("add") or data.get("host") or "").strip()
            port = str(data.get("port") or "").strip()
            return (host or None), (int(port) if port.isdigit() else None)
        if lowered.startswith("ss://"):
            body, _ = normalize_ss(uri)
            if not body:
                return None, None
            parts = urlsplit("ss://" + body)
            return parts.hostname, parts.port
        parts = urlsplit(uri)
        return parts.hostname, parts.port
    except ValueError:
        return None, None

def default_port(uri):
    lowered = uri.lower()
    if lowered.startswith("trojan://") or lowered.startswith("vless://"):
        return 443
    if lowered.startswith("hysteria2://") or lowered.startswith("hy2://") or lowered.startswith("tuic://"):
        return 443
    return 443

def resolve_ip(host):
    if not host:
        return None
    try:
        socket.inet_aton(host)
        return host
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        return host
    except OSError:
        pass
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            infos = socket.getaddrinfo(host, None, family, socket.SOCK_STREAM)
        except (socket.gaierror, UnicodeError, OSError):
            continue
        for info in infos:
            address = info[4][0]
            if address:
                return address
    return None

def tcp_alive(ip, port):
    if not ip or not port:
        return False, None
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(TCP_TIMEOUT)
    started = time.time()
    try:
        sock.connect((ip, int(port)))
        return True, round((time.time() - started) * 1000)
    except (socket.timeout, OSError):
        return False, None
    finally:
        try:
            sock.close()
        except OSError:
            pass

def valid_country_code(code):
    if not code or not isinstance(code, str):
        return None
    code = code.strip().upper()
    if len(code) != 2 or not code.isalpha():
        return None
    return code

def geo_ip_api_batch(ips):
    result = {}
    endpoint = "http://ip-api.com/batch?fields=status,countryCode,query"
    for index in range(0, len(ips), 100):
        chunk = ips[index:index + 100]
        payload = [{"query": ip} for ip in chunk]
        try:
            response = requests.post(endpoint, json=payload, headers=HTTP_HEADERS, timeout=25)
            if response.status_code == 429:
                time.sleep(10)
                response = requests.post(endpoint, json=payload, headers=HTTP_HEADERS, timeout=25)
            entries = response.json()
        except (requests.RequestException, ValueError):
            entries = []
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if entry.get("status") != "success":
                    continue
                code = valid_country_code(entry.get("countryCode"))
                query = entry.get("query")
                if code and query:
                    result[query] = code
        if index + 100 < len(ips):
            time.sleep(4.5)
    return result

def geo_ipwho(ip):
    try:
        response = requests.get("https://ipwho.is/" + ip, headers=HTTP_HEADERS, timeout=15)
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(data, dict) or data.get("success") is False:
        return None
    return valid_country_code(data.get("country_code"))

def geo_ipinfo(ip):
    token = os.environ.get("IPINFO_TOKEN", "")
    url = "https://ipinfo.io/" + ip + "/json"
    if token:
        url = url + "?token=" + token
    try:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=15)
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return valid_country_code(data.get("country"))

def geo_cloudflare_fallback(ip):
    try:
        response = requests.get("https://api.country.is/" + ip, headers=HTTP_HEADERS, timeout=15)
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return valid_country_code(data.get("country"))

def verified_country(ip, primary):
    votes = []
    if primary:
        votes.append(primary)
    second = geo_ipwho(ip)
    if second:
        votes.append(second)
    if len(set(votes)) == 1 and len(votes) == 2:
        return votes[0]
    third = geo_ipinfo(ip)
    if third:
        votes.append(third)
    if not votes:
        fourth = geo_cloudflare_fallback(ip)
        if fourth:
            votes.append(fourth)
    if not votes:
        return None
    counter = Counter(votes)
    best, count = counter.most_common(1)[0]
    if count >= 2:
        return best
    return votes[0]

def resolve_countries(ips):
    primary_map = geo_ip_api_batch(ips)
    final = {}
    with ThreadPoolExecutor(max_workers=GEO_WORKERS) as pool:
        futures = {pool.submit(verified_country, ip, primary_map.get(ip)): ip for ip in ips}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                code = future.result()
            except Exception:
                code = None
            if code:
                final[ip] = code
    return final

def country_flag(code):
    code = valid_country_code(code)
    if not code:
        return ""
    return chr(0x1F1E6 + ord(code[0]) - 65) + chr(0x1F1E6 + ord(code[1]) - 65)

def rename_config(uri, name):
    lowered = uri.lower()
    if lowered.startswith("vmess://"):
        data = decode_vmess(uri)
        if not data:
            return None
        data["ps"] = name
        return encode_vmess(data)
    if lowered.startswith("ss://"):
        body, _ = normalize_ss(uri)
        if not body:
            return None
        return "ss://" + body + HASH + quote(name, safe="")
    base, _ = split_fragment(uri)
    parts = urlsplit(base)
    if not parts.hostname:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, "")) + HASH + quote(name, safe="")

def collect_all():
    raw = []
    raw.extend(extract_configs(read_local_file(INPUT_FILE)))
    for url in load_sources():
        raw.extend(extract_configs(fetch_text(url)))
    unique = []
    seen = set()
    for uri in raw:
        base, _ = split_fragment(uri)
        key = base.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(uri)
    return unique

def build_records(configs):
    records = []
    for uri in configs:
        host, port = endpoint_of(uri)
        if not host:
            continue
        if not port:
            port = default_port(uri)
        records.append({"uri": uri, "host": host, "port": int(port)})
    deduped = {}
    for record in records:
        key = (record["host"].lower(), record["port"])
        deduped.setdefault(key, record)
    return list(deduped.values())

def test_records(records):
    alive = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {}
        for record in records:
            futures[pool.submit(probe, record)] = record
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception:
                result = None
            if result:
                alive.append(result)
    return alive

def probe(record):
    ip = resolve_ip(record["host"])
    if not ip:
        return None
    ok, latency = tcp_alive(ip, record["port"])
    if not ok:
        return None
    record["ip"] = ip
    record["latency"] = latency if latency is not None else 9999
    return record

def assign_names(records, country_map):
    grouped = defaultdict(list)
    for record in records:
        code = country_map.get(record["ip"])
        if not code:
            continue
        record["country"] = code
        grouped[code].append(record)
    named = []
    for code in sorted(grouped.keys()):
        group = sorted(grouped[code], key=lambda item: item["latency"])
        flag = country_flag(code)
        base = BASE_NAME + " " + flag if flag else BASE_NAME + " " + code
        total = len(group)
        for index, record in enumerate(group, start=1):
            name = base if total == 1 else base + " " + str(index)
            renamed = rename_config(record["uri"], name)
            if not renamed:
                continue
            record["name"] = name
            record["final"] = renamed
            named.append(record)
    return named

def write_outputs(records):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    lines = [record["final"] for record in records]
    plain_path = os.path.join(OUTPUT_DIR, "sub.txt")
    encoded_path = os.path.join(OUTPUT_DIR, "sub_base64.txt")
    report_path = os.path.join(OUTPUT_DIR, "report.json")
    with open(plain_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + ("\n" if lines else ""))
    with open(encoded_path, "w", encoding="utf-8") as handle:
        handle.write(base64.b64encode("\n".join(lines).encode("utf-8")).decode("ascii"))
    grouped = defaultdict(list)
    for record in records:
        grouped[record["country"]].append(record["name"])
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "total": len(records),
                "countries": {key: len(value) for key, value in sorted(grouped.items())},
                "names": [record["name"] for record in records],
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
    for country in sorted(grouped.keys()):
        country_lines = [record["final"] for record in records if record["country"] == country]
        with open(os.path.join(OUTPUT_DIR, "sub_" + country + ".txt"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(country_lines) + "\n")
    return plain_path, encoded_path

def main():
    configs = collect_all()
    if not configs:
        print("no configurations found")
        return 1
    records = build_records(configs)
    alive = test_records(records)
    if not alive:
        print("no reachable configurations")
        return 1
    ips = sorted({record["ip"] for record in alive})
    country_map = resolve_countries(ips)
    named = assign_names(alive, country_map)
    if not named:
        print("no configurations with verified location")
        return 1
    named.sort(key=lambda item: (item["country"], item["latency"]))
    plain_path, encoded_path = write_outputs(named)
    print("configs parsed: " + str(len(configs)))
    print("configs reachable: " + str(len(alive)))
    print("configs published: " + str(len(named)))
    print("plain output: " + plain_path)
    print("base64 output: " + encoded_path)
    return 0

if __name__ == "__main__":
    sys.exit(main())
