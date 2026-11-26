# Telegram Vault Bot (Kurigram + MongoDB + Hugging Face Spaces)

A modular MTProto Telegram File & Text Vault bot built with **Kurigram** and **MongoDB (Motor)**, ready for deployment on **Hugging Face Docker Spaces**.

## Features
- Single file & media storage with permanent share links
- Text note storage (`/text Title | Content`)
- Multi-file & text bundler (`/wizard` and `/batch`)
- Inline (`@bot query`) and command (`/search`) search
- Force-Subscribe channel gatekeeper (`/fsub`)
- Auto-delete delivery timer (`/autodel`)
- Content protection (`PROTECT_CONTENT`)
- Optional URL shortener integration
- User content requests (`/request`)
- Admin controls (`/stats`, `/broadcast`, `/ban`, `/unban`)
- Built-in HTTP health endpoint on port `7860`

## Quick Start
1. Copy `.env.example` to `.env` (or add the keys as Secrets in Hugging Face Spaces).
2. Add your bot as an Administrator in your private `DB_CHANNEL_ID` (and any `FSUB_CHANNELS`).
3. Run locally with `python -m bot` or push to GitHub to sync with Hugging Face Docker Spaces.
