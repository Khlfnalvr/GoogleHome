# Google Home Widget for Windows 11

Control your Google Home **lamp** and **AC** from the Windows 11 taskbar.

- Click the house icon in the taskbar tray (next to the clock): a flyout opens with **Lamp On/Off**, **AC On/Off** and **AC temperature − / +**.
- Sign in with your Google account. Commands go through Google Assistant, so any device in your Google Home app works.

## One-time Google setup (about 5 minutes)

Google only lets an app use your Google Home if it has its own OAuth client, so you create one (free):

1. Open <https://console.cloud.google.com/> and create a project.
2. **APIs & Services → Library** → search **Google Assistant API** → **Enable**.
3. **Google Auth Platform** (or **OAuth consent screen**):
   - App name: anything, e.g. `Google Home Widget`, plus your email.
   - Audience: **External**, add your Google account as a **test user**.
   - Then **Publish app** (set to *In production*). Otherwise you'd have to sign in again every 7 days.
4. **Clients** (or **Credentials → Create credentials → OAuth client ID**) → type **Desktop app** → **Download JSON**.

## Use it

1. Run `GoogleHomeWidget.exe`.
2. Click **Sign in with Google**. The first time, pick the JSON file from step 4. Your browser opens for Google login.
   If Google says *"Google hasn't verified this app"*, click **Advanced → Go to …**. It's your own app.
3. Click **⚙** and type your lamp and AC names **exactly as they appear in the Google Home app**. Turn on **Start with Windows** if you like.

To keep the icon visible on the taskbar (not hidden under **^**): **Settings → Personalization → Taskbar → Other system tray icons** → turn on **GoogleHomeWidget**.

## Get the .exe

- **Download:** GitHub → **Actions** → latest **Build Windows app** run → **Artifacts → GoogleHomeWidget**.
- **Or build it:** install Python 3.11+, then run `build.bat`. The exe is in `dist\`.
  If you put `client_secret.json` next to `build.bat`, it gets bundled into the exe, so you (or family) only need to click **Sign in with Google**.

## Troubleshooting

| Message | Fix |
| --- | --- |
| "Sorry, I couldn't find …" / device not found | Device name in ⚙ doesn't match the Google Home app. |
| "Google Assistant API has not been used in project …" | Step 2 not done, or done in a different project. |
| Sign-in expired every week | Step 3: publish the app (*In production*), then sign in again. |

Settings and sign-in are stored in `%APPDATA%\GoogleHomeWidget`.
