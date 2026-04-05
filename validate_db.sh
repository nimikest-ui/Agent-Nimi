#!/bin/bash

echo "======================================================"
echo "PENTEST DATABASE VALIDATION"
echo "======================================================"

DB="pentest.db"

if [ ! -f "$DB" ]; then
    echo "[!] Database not found: $DB"
    exit 1
fi

echo "[+] Database found: $DB"
echo ""

# Table count
echo "=== TABLE COUNT ==="
sqlite3 $DB "SELECT COUNT(*) || ' tables' FROM sqlite_master WHERE type='table';"
echo ""

# Tool statistics
echo "=== TOOL STATISTICS ==="
sqlite3 $DB "SELECT COUNT(*) || ' total tools' FROM tools;"
sqlite3 $DB "SELECT COUNT(*) || ' Kali-installed tools' FROM tools WHERE kali_installed=1;"
sqlite3 $DB "SELECT COUNT(*) || ' beginner-friendly tools' FROM tools WHERE difficulty='beginner';"
sqlite3 $DB "SELECT COUNT(*) || ' advanced tools' FROM tools WHERE difficulty='advanced';"
echo ""

# Categories
echo "=== TOP 5 CATEGORIES ==="
sqlite3 $DB "SELECT category, COUNT(*) as cnt FROM tools GROUP BY category ORDER BY cnt DESC LIMIT 5;" | column -t -s '|'
echo ""

# Tags
echo "=== TAG SUMMARY ==="
sqlite3 $DB "SELECT COUNT(*) || ' total tags' FROM tags;"
sqlite3 $DB "SELECT COUNT(*) || ' tool-tag relationships' FROM tool_tags;"
echo ""

# Examples
echo "=== USAGE EXAMPLES ==="
sqlite3 $DB "SELECT COUNT(*) || ' total examples' FROM tool_examples;"
sqlite3 $DB "SELECT t.name, COUNT(te.id) as examples FROM tools t LEFT JOIN tool_examples te ON t.id=te.tool_id GROUP BY t.id HAVING examples > 0 ORDER BY examples DESC LIMIT 3;" | column -t -s '|'
echo ""

# Sample queries
echo "=== SAMPLE TOOL: nmap ==="
sqlite3 -header -column $DB "SELECT name, category, difficulty, stealth_level, kali_installed FROM tools WHERE name='nmap';"
echo ""

# Views
echo "=== AVAILABLE VIEWS ==="
sqlite3 $DB "SELECT name FROM sqlite_master WHERE type='view';" | nl
echo ""

# Database size
echo "=== DATABASE SIZE ==="
du -h $DB

echo ""
echo "======================================================"
echo "[+] Validation complete!"
echo "======================================================"
