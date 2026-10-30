#!/usr/bin/env bash
# Read-only capacity / security / backup audit for a Linux server. Changes nothing, prints no secrets and no file contents.
# Usage:  ssh your-hetzner 'bash -s' < hetzner-audit.sh | tee hetzner-audit.txt
# Parts that need root say so; run with sudo for a fuller picture (still read-only).
set -u
hr() { printf '\n== %s ==\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

hr "HOST"
hostname; (. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME"); uname -r; uptime
hr "CPU / LOAD (load per core should stay well under 1.0 to leave headroom)"
cores=$(nproc); echo "cores=$cores"; read -r l1 l5 l15 _ < /proc/loadavg
awk -v l="$l5" -v c="$cores" 'BEGIN{printf "load5=%s per_core=%.2f\n", l, l/c}'
hr "MEMORY"
free -m; echo; vmstat 1 3 2>/dev/null | tail -2
hr "DISK (filesystems, free space, inodes)"
df -hT -x tmpfs -x devtmpfs -x squashfs -x overlay 2>/dev/null; echo; df -ih / 2>/dev/null
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT 2>/dev/null
hr "LARGEST TOP-LEVEL DIRECTORIES (sizes only)"
for d in /var/lib/docker /var/lib /home /opt /srv /var/log /root; do [ -d "$d" ] && du -xsh "$d" 2>/dev/null; done
hr "DOCKER (names, images, status only — no environment, no volumes' contents)"
if have docker; then docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' 2>&1 | head -40; echo; docker system df 2>&1 | head -8; else echo "docker not installed or not accessible"; fi
hr "RUNNING SYSTEMD SERVICES (names)"
systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null | awk '{print $1}' | head -60
hr "TIMERS (look for backup jobs)"
systemctl list-timers --all --no-legend --no-pager 2>/dev/null | awk '{print $(NF-1), $NF}' | head -30
ls /etc/cron.d /etc/cron.daily 2>/dev/null
hr "LISTENING PORTS (anything on 0.0.0.0 / :: is reachable from outside unless firewalled)"
ss -tlnH 2>/dev/null | awk '{print $4}' | sort -u
hr "FIREWALL"
if have ufw; then ufw status verbose 2>&1 | head -25; else echo "ufw not installed"; fi
have nft && nft list tables 2>&1 | head -5
hr "SSH HARDENING (effective keys only)"
if have sshd; then sshd -T 2>/dev/null | grep -Ei '^(permitrootlogin|passwordauthentication|pubkeyauthentication|port|kbdinteractiveauthentication|allowusers|maxauthtries) ' || echo "run with sudo to read the effective sshd config"; fi
hr "BRUTE-FORCE PROTECTION / UPDATES"
have fail2ban-client && (fail2ban-client status 2>&1 | head -5) || echo "fail2ban: not found"
systemctl is-enabled unattended-upgrades 2>/dev/null || echo "unattended-upgrades: not enabled/found"
have apt && echo "upgradable packages: $(apt list --upgradable 2>/dev/null | grep -c upgradable)"
[ -f /var/run/reboot-required ] && echo "REBOOT REQUIRED" || echo "no reboot pending"
hr "BACKUP INDICATORS (tools present; this cannot see Hetzner-side backups/snapshots — check the Hetzner console)"
for t in restic borg rclone rsync pg_dump; do have "$t" && echo "found: $t"; done
hr "SUMMARY (heuristics, not verdicts)"
free_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9'); total_gb=$(df -BG --output=size / | tail -1 | tr -dc '0-9')
avail_mb=$(free -m | awk '/Mem:/{print $7}')
echo "root free: ${free_gb}G of ${total_gb}G  | mem available: ${avail_mb}M | load5 per core: $(awk -v l="$l5" -v c="$cores" 'BEGIN{printf "%.2f", l/c}')"
echo "usable for an archive if you keep a 25% free-space reserve: $(( free_gb - total_gb/4 ))G (negative = no room)"
