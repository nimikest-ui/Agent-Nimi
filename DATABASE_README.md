# PENTEST DATABASE - QUICK REFERENCE

## Database Files
- **Schema**: `pentest_db_schema.sql` - Full table definitions
- **Init Script**: `init_pentest_db.py` - Python initialization utility
- **Database**: `pentest.db` - SQLite3 database file

## Initialization
```bash
# Create/reset database
python3 init_pentest_db.py

# With sample data
python3 init_pentest_db.py --sample

# Manual via sqlite3
sqlite3 pentest.db < pentest_db_schema.sql
```

## Core Tables

### Targets (14 tables total)
1. **targets** - Host inventory (IP, hostname, OS, status)
2. **services** - Open ports/services per target
3. **vulnerabilities** - CVE database
4. **target_vulns** - Links vulns to targets/services
5. **exploits** - Exploit code/PoCs (EDB, custom)
6. **credentials** - Harvested creds/hashes
7. **osint** - OSINT findings (emails, subdomains, leaks)
8. **attack_surface** - Enumerated attack vectors
9. **exploit_attempts** - Exploitation log
10. **sessions** - Active shells/sessions
11. **loot** - Exfiltrated files/data
12. **network_map** - Network topology/trust relationships
13. **timeline** - Mission event log

### Pre-built Views
- **compromised_targets** - Targets with active sessions
- **high_value_vulns** - Critical/High CVEs with exploits
- **attack_summary** - Per-target stats (services, vulns, creds, sessions)

## Quick Queries

### Add target
```sql
INSERT INTO targets (ip_address, hostname, domain, os_type, priority) 
VALUES ('192.168.1.50', 'dc01', 'corp.local', 'Windows', 10);
```

### Add service
```sql
INSERT INTO services (target_id, port, service_name, service_version) 
VALUES (1, 445, 'smb', 'SMBv2');
```

### Add vulnerability
```sql
INSERT INTO vulnerabilities (cve_id, title, severity, cvss_score, exploitable)
VALUES ('CVE-2024-1234', 'RCE in SMB', 'critical', 9.8, 1);

-- Link to target
INSERT INTO target_vulns (target_id, service_id, vuln_id, verified)
VALUES (1, 1, 1, 1);
```

### Add credential
```sql
INSERT INTO credentials (target_id, username, password, privilege_level, source)
VALUES (1, 'administrator', 'P@ssw0rd123', 'admin', 'bruteforce');
```

### Add OSINT finding
```sql
INSERT INTO osint (category, source, value, confidence)
VALUES ('email', 'hunter.io', 'admin@target.com', 'high');
```

### Log timeline event
```sql
INSERT INTO timeline (event_type, target_id, severity, title, description, operator)
VALUES ('exploit', 1, 'critical', 'SMB RCE Success', 'Gained SYSTEM shell', 'agent-nimi');
```

### Track session
```sql
INSERT INTO sessions (target_id, session_type, user_context, privilege_level)
VALUES (1, 'meterpreter', 'SYSTEM', 'root');
```

## Useful Queries

### Show all compromised targets
```sql
SELECT * FROM compromised_targets;
```

### High-value targets (multiple vulns)
```sql
SELECT * FROM attack_summary WHERE vulns_count >= 3 ORDER BY priority DESC;
```

### Find exploitable vulns
```sql
SELECT * FROM high_value_vulns;
```

### Active sessions
```sql
SELECT t.ip_address, t.hostname, s.session_type, s.privilege_level, s.established_at
FROM sessions s
JOIN targets t ON s.target_id = t.id
WHERE s.status = 'active';
```

### Credential dump
```sql
SELECT t.ip_address, c.username, c.password, c.hash, c.privilege_level
FROM credentials c
JOIN targets t ON c.target_id = t.id
WHERE c.working = 1
ORDER BY c.privilege_level DESC;
```

### Attack timeline
```sql
SELECT timestamp, event_type, severity, title, description 
FROM timeline 
ORDER BY timestamp DESC 
LIMIT 20;
```

## Field Values

### Target Status
- `active` - Live target
- `compromised` - Shell/access obtained
- `failed` - Exploitation failed
- `ignored` - Out of scope

### Severity Levels
- `critical` - CVSS 9.0-10.0
- `high` - CVSS 7.0-8.9
- `medium` - CVSS 4.0-6.9
- `low` - CVSS 0.1-3.9

### Session Types
- `meterpreter`, `shell`, `webshell`, `ssh`, `rdp`, `vnc`, `sql`

### OSINT Categories
- `email`, `subdomain`, `employee`, `technology`, `leak`, `credential`, `phone`

### Attack Surface Categories
- `web`, `api`, `network`, `wireless`, `physical`, `social`

## Database Access
```bash
# CLI access
sqlite3 pentest.db

# Python access
import sqlite3
conn = sqlite3.connect('pentest.db')
cursor = conn.cursor()
cursor.execute("SELECT * FROM targets")
print(cursor.fetchall())
```

## Backup/Export
```bash
# Backup
cp pentest.db pentest.db.backup

# Export to SQL
sqlite3 pentest.db .dump > pentest_backup.sql

# Export table to CSV
sqlite3 pentest.db "SELECT * FROM targets;" -csv > targets.csv
```
