# Run the bot on a free Linux VM

The bot is a continuously running Python worker. It needs outbound internet
access and persistent storage for `data/listings.db`. A domain and public web
endpoint are unnecessary.

Oracle Always Free provides eligible Ubuntu compute instances. An AMD
`VM.Standard.E2.1.Micro` is a starting point for the current configuration, which
does not launch a browser. Free capacity can be unavailable, and Oracle can
reclaim idle instances. Use resources within the Always Free allocation rather
than relying on temporary trial credits. [Oracle resource limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Signup requires card verification, and the free tier has no uptime SLA.
[Oracle Free Tier FAQ](https://www.oracle.com/cloud/free/faq/).

## 1. Create the VM

Create an Oracle Free Tier account and an Always Free-eligible Ubuntu VM in
your home region. Save its SSH key and public IP address. The commands below
assume the Ubuntu login is `ubuntu`; replace `SERVER_IP` with the VM's IP.
Use your SSH key with `ssh` and `rsync` if it is not already loaded in your SSH agent.

Keep `immoscout24.enabled: false` initially. Its browser and verification flow
need additional setup; the other current adapters run without a browser.

## 2. Transfer the code, settings and delivery cache

On your Mac, stop the foreground bot with Ctrl+C. If you installed macOS
autostart, stop that agent too so it does not resume sending from the Mac:

```bash
launchctl unload ~/Library/LaunchAgents/com.wohnungsbot.goettingen.plist
```

Run these transfer commands from the project directory on your Mac. They copy
the current working code, including changes that have not been committed.
Your `.env` travels privately over SSH; it should stay out of Git.

```bash
ssh ubuntu@SERVER_IP 'mkdir -p ~/germany-wohnungsbot/data'
rsync -av --exclude='__pycache__/' bot deploy config.yaml requirements.txt .env ubuntu@SERVER_IP:~/germany-wohnungsbot/
rsync -av data/listings.db ubuntu@SERVER_IP:~/germany-wohnungsbot/data/
```

Omit the last command only if the bot has never created a database. Keeping the
existing database preserves seen IDs and Telegram delivery history. Transfer it
after stopping the Mac bot so the copy is consistent. Run one active bot using
that history; separate Mac and VM database copies will diverge.

## 3. Install and check on Ubuntu

SSH into the VM, then run:

```bash
sudo apt update
sudo apt install -y python3 python3-venv
cd ~/germany-wohnungsbot
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
chmod 600 .env
.venv/bin/python -m bot.doctor
```

The doctor sends a Telegram test message and checks the enabled portals and
filters. Review its results before starting the service. A zero matching count
can also mean that publication dates or warm rents could not be verified.
Portal verification pages and rate limits still apply from a VM.

For a foreground check, use `.venv/bin/python -m bot.main`, then stop with Ctrl+C.
The existing `run.sh` uses macOS `caffeinate`; use the Python command on Linux.

## 4. Start automatically and recover from crashes

The included service example assumes the project is at
`/home/ubuntu/germany-wohnungsbot`. Adjust its `User`, `WorkingDirectory`
and `ExecStart` before enabling it if your username or project path differs.

```bash
sudo cp deploy/wohnungsbot.service.example /etc/systemd/system/wohnungsbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now wohnungsbot
sudo systemctl status wohnungsbot
```

The bot now starts on boot and restarts after a failure. It loads `.env` itself,
and writes its SQLite cache and file logs into the project's persistent `data/`
directory. This example runs the bot as `ubuntu`, rather than root.

```bash
sudo journalctl -u wohnungsbot -f
sudo systemctl restart wohnungsbot
sudo systemctl stop wohnungsbot
```

Use the restart command after editing `.env` or `config.yaml`. Keep private
backups of the delivery database; use SQLite's backup API if backing it up while
the bot is running.

## Timing and other free options

Current polling targets are roughly 5 seconds for Kleinanzeigen and 5 minutes
for other enabled platforms. Network requests, warm-rent checks and backoff can
extend those times. Hosting does not make every platform instantaneous.

An existing always-on home PC is another option with no hosting bill, although
it uses electricity and depends on your home connection.

Render free web services sleep after 15 minutes without inbound traffic and
lose local SQLite files on restart or redeploy; free persistent disks are not
available. This worker only makes outbound requests, so that plan does not fit
its current design. [Render free-service limitations](https://render.com/docs/free).

GitHub Actions scheduled workflows run at intervals of at least 5 minutes and
can be delayed or dropped. They do not fit a continuous five-second polling
loop. [GitHub schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
