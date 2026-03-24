# la-scanner-radio

A lightweight web-based scanner radio player for the Los Angeles metro area. Streams live audio feeds from Broadcastify directly in your browser — no app, no account needed.

## What it does

- Pulls all live audio feeds from the LA metro area (Broadcastify)
- Serves a dark-themed web UI at `localhost:8765`
- Filter channels by category: Public Safety, Amateur Radio, Rail, Other
- Search channels by name
- Shows online/offline status for each feed with a color dot
- Auto-refreshes the channel list every 5 minutes

## Requirements

- Python 3.7+
- `requests` and `beautifulsoup4` (recommended, falls back to stdlib if missing)

## Setup

**Windows**

```bat
install.bat
```

Then run:

```bat
run.bat
```

**Mac / Linux**

```bash
pip install -r requirements.txt
python radio.py
```

A browser tab will open automatically at `http://localhost:8765`.

## Project structure

```
la-scanner-radio/
├── radio.py          # main application
├── requirements.txt
├── install.bat       # Windows install script
├── run.bat           # Windows run script
└── README.md
```

## Notes

- Audio streams require no login for standard quality feeds
- Some feeds may be offline or region-restricted
- This project is for personal/educational use only. Audio content belongs to Broadcastify and respective feed providers.
