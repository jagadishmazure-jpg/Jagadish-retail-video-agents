# Connecting a real NVR and scheduling the hourly email

## 1. Camera config (one entry per camera)
```python
CameraConfig("cam-backdoor", "back-door", "rtsp", rtsp_env="CAM_BACKDOOR_URL", sample_every_s=5)
CameraConfig("cam-register", "lane-1", "folder", folder="/srv/nvr-export/register")
```
- **RTSP:** the full URL, including any login, goes in an environment variable, never in code or config.
  Most NVRs expose a per-channel RTSP path; enable it in the NVR admin page and create a view-only user.
  `export CAM_BACKDOOR_URL='rtsp://viewer:<password>@192.168.1.20:554/<channel-path>'`
  The reader runs `ffmpeg -rtsp_transport tcp -i $URL -t 3600 -vf fps=1/N -an frame_%05d.jpg` (audio stripped).
- **Export folder:** for NVRs that export clips (ONVIF or the vendor tool), point `folder` at the export path.
  Files must be named `<camera>_<unix_ts>.mp4`; rename in the export job if needed.
- Lane zone names must match the till lane names so till matching works.

## 2. SMTP (only when you choose to go live)
```bash
export DIGEST_SMTP_HOST=smtp.yourprovider.example DIGEST_SMTP_PORT=587
export DIGEST_SMTP_USER=alerts@yourdomain.example DIGEST_SMTP_PASSWORD='<app password>'
export DIGEST_TO='owner@yourdomain.example,manager@yourdomain.example'
```
Default is dry-run: every digest is written to `outbox/digest-<HHMM>.eml` and nothing is sent.
Live sending uses STARTTLS, 3 attempts with 1s then 2s backoff, and every attempt is in the audit log.

## 3. Schedule
Cron (top of every hour):
```cron
0 * * * * cd /opt/retail-video-agents && /usr/bin/python3.12 scripts/hourly_digest.py >> /var/log/digest.log 2>&1
```
systemd timer:
```ini
# /etc/systemd/system/hourly-digest.service
[Unit]
Description=Hourly NVR text digest
[Service]
Type=oneshot
WorkingDirectory=/opt/retail-video-agents
EnvironmentFile=/etc/hourly-digest.env
ExecStart=/usr/bin/python3.12 scripts/hourly_digest.py

# /etc/systemd/system/hourly-digest.timer
[Unit]
Description=Run hourly digest at the top of each hour
[Timer]
OnCalendar=hourly
Persistent=true
[Install]
WantedBy=timers.target
```
`sudo systemctl enable --now hourly-digest.timer`. Keep `/etc/hourly-digest.env` at mode 600.

## 4. Audio
Audio is off by default and ffmpeg strips it (`-an`). For a Georgia site, the guidance followed here is to keep camera
microphones off, because recording conversations people expect to be private carries legal risk. Turn audio on only
after a lawyer's review, with posted notice, by setting `audio_enabled=True` and supplying a local speech-to-text engine.

## 5. Edge box sizing — TO BE MEASURED
Frames per second per camera, describer latency, and how many cameras one box can handle are not measured yet.
