# Deploying ClaudeMarket to Google Cloud (Always Free)

Runs the bot 24/7 on a free `e2-micro` VM, independent of your Mac.

## 0. What "always free" requires

- Region must be **`us-west1`, `us-central1`, or `us-east1`** (only these qualify).
- Machine type **`e2-micro`**, **1 per account**, standard persistent disk **≤ 30 GB**.
- A Discord bot uses tiny CPU/bandwidth, so it fits comfortably.
- Signup needs a credit card for identity, but the always-free VM is not billed.

## 1. Create the VM

**Console:** Compute Engine → VM instances → Create instance
- Name: `claudemarket`
- Region: `us-central1`, Zone: `us-central1-a`
- Machine type: `e2-micro`
- Boot disk: **Debian 12**, size **30 GB**, type **Standard persistent disk**
- Leave firewall unchecked (the bot only makes outbound connections)
- Create

**Or with the `gcloud` CLI:**
```bash
gcloud compute instances create claudemarket \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-standard
```

### If you get `ZONE_RESOURCE_POOL_EXHAUSTED`

That zone is temporarily out of `e2-micro` capacity — not an account issue.
Retry in another zone within a free-tier region (us-west1 / us-central1 /
us-east1). Keep the machine type `e2-micro` so it stays free:

```bash
for Z in us-central1-a us-central1-b us-central1-c us-central1-f \
         us-east1-b us-east1-c us-east1-d \
         us-west1-a us-west1-b us-west1-c; do
  echo "Trying $Z ..."
  gcloud compute instances create claudemarket \
    --zone=$Z --machine-type=e2-micro \
    --image-family=debian-12 --image-project=debian-cloud \
    --boot-disk-size=30GB --boot-disk-type=pd-standard && { echo "Created in $Z"; break; }
done
```

## 2. SSH in

Console: click **SSH** next to the instance. Or:
```bash
gcloud compute ssh claudemarket --zone=us-central1-a
```

## 3. Get the code onto the VM

The repo is public, so no auth is needed — just clone it:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/alxhil/claudemarket.git
cd claudemarket
```

## 4. Create the .env (with your rotated secrets)

```bash
cp .env.example .env
nano .env
```
Fill in `DISCORD_BOT_TOKEN`, `DISCORD_WEBHOOK_URL`, and `ODDS_API_KEY`.
Save (Ctrl+O, Enter) and exit (Ctrl+X).

## 5. Run the setup script

```bash
bash deploy/setup.sh
```
This creates a virtualenv, installs dependencies, and installs a systemd
service that auto-starts on boot and restarts on crash.

## 6. Verify

```bash
sudo systemctl status claudemarket     # should say "active (running)"
journalctl -u claudemarket -f          # live logs; look for "connected to Gateway"
```
Then run `!help` in Discord.

## Managing it later

```bash
journalctl -u claudemarket -f          # live logs
sudo systemctl restart claudemarket    # after editing .env
sudo systemctl stop claudemarket       # stop
```

## Updating to new code

```bash
cd ~/claudemarket
git pull
sudo systemctl restart claudemarket
```

## Turn off the Mac service (avoid two bots)

Once the VM bot is confirmed running, stop the Mac copy so they don't both
reply:
```bash
# on your Mac:
launchctl bootout gui/$(id -u)/com.claudemarket.bot
```
