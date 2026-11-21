# Putting MHGC on the internet (Render)

This puts Mega Hyper Galactic Conquest on a public web address so friends can play from their own
computers. It uses a GitHub repository for the code and a Render web service to run it. Allow about
20 minutes the first time. Everything here uses **personal** accounts, not company ones.

## What you need
- A GitHub account (github.com) and, ideally, Git for Windows (git-scm.com). GitHub's web upload
  works too.
- A Render account (render.com). Sign up with your GitHub account; that makes step 3 easier.
- A payment card for Render. The blueprint uses the **Starter** plan, so the server stays awake, plus
  a **1 GB disk**, so saved games survive restarts. At the time of writing that's roughly $7 a month
  plus a few cents for the disk. Check render.com/pricing.

## 1. Unzip
Unzip `mhgc-web.zip` somewhere outside OneDrive, for example `C:\Temp\mhgc-web`.

## 2. Put the code on GitHub
Create a new repository on github.com, for example `mhgc`. **Private** is fine, since Render can
deploy private repositories. Don't add a README or .gitignore there; the project has its own.

**With Git (PowerShell):**
```
cd C:\Temp\mhgc-web
git init
git add .
git commit -m "MHGC"
git branch -M main
git remote add origin https://github.com/<your-name>/mhgc.git
git push -u origin main
```
The `.gitignore` keeps out virtual environments, local saves and zips.

**Without Git:** on the new repository's page choose **uploading an existing file**, drag in
everything inside `mhgc-web` (not the folder itself), and commit. Make sure `render.yaml`,
`requirements.txt` and the `app` and `mhgc` folders are at the top level of the repository.

## 3. Create the service on Render
1. In the Render dashboard choose **New → Blueprint**.
2. Connect your GitHub account if asked, and pick the `mhgc` repository.
3. Render reads `render.yaml` and shows one web service, **mhgc**, on the Starter plan with a disk
   called **mhgc-saves**. Choose **Apply** (or **Deploy Blueprint**) and add your card if asked.
4. The first build takes a few minutes. When the service shows **Live**, its address is at the top
   of the service page, for example `https://mhgc-xxxx.onrender.com`.

## 4. Check it
Open `https://<your-address>/api/health`; it should say `{"ok":true,...}`. The API's own
documentation is at `https://<your-address>/docs`.

## 5. Play with friends
1. Open `https://<your-address>/`. You see the game list. Choose **New game** and fill in a game
   name (optional), your name, the **Game size** (8 empires on 75x75 is the default; 9, 12 or 16),
   the number of **Human seats** (up to the size) and how chatty the computer empires are. Then
   either **I'll play a race**: a race name (one word, such as `Terrans`) and a **password** for it
   (at least 4 characters), or **Host only, no race**. Either way the game needs a **host
   password**: "Use my race password" (ticked) makes it the same as your race password, or type
   another. You can use the same host password for all the games you host; the browser can
   remember it for your next game. Choose **Create**.
   Seats you don't give to humans are computer empires. You are now in the game, and you are its
   host.
2. Send your friends the address. Each one opens it, clicks your game in the list (**Open / join**)
   and, under **Take an open seat**, picks a seat, types their name (and, before the first turn, a
   race name) and chooses a password for their race. From then on they can play from any browser
   or phone: open the game and, under **Play an existing race**, pick their race and enter the
   password. One person may take several seats. The game list shows every seat, who has
   submitted (✓), and who the turn is waiting for.
3. Everyone gives orders. Click a square on the map to see what is there, with buttons for the
   orders that make sense (**Build ship**, **Profile** and so on for a system; **Move (click map)**,
   **Intercept** and so on for a fleet or ship). With a fleet or ship selected you can also
   right-click any square to move it there. The **Orders** tab lists the draft: reorder, edit or
   delete orders there, add any order with **New order…**, or type classic order codes under
   **Classic order text**.
4. **Check orders** (top bar) tries the draft against the current position and marks each order
   ✓ or ✗ with the reason. **Submit turn** sends it. The turn runs as soon as every human seat is
   taken and submitted. Until then you can choose **Withdraw**, and any change to your orders
   withdraws the submission automatically, so submit again when you're done.
5. When a turn runs, every open browser updates within a few seconds and shows the **Report** tab:
   order results, messages, events, battles (also marked on the map), the maintenance ledger,
   scans and statistics. The **Stats** tab graphs your figures over every turn, and the turn
   picker at the top shows the map and results of any earlier turn.
6. **Chat** has a game-wide channel, plus private threads with each human race you have made
   contact with (the rules' contact requirement). Computer empires don't read chat; use a MESSAGE
   order for them.
7. You created the game, so you are the host. The host can **Force turn** (top bar): it runs the
   turn now, without waiting, after asking you to confirm; seats that haven't submitted give no
   orders that turn. The ☰ menu has **Host controls**: reset a player's forgotten password (you
   give them a temporary one), hand a race to the computer, open a computer empire for a new
   player, and **Export for analysis** at any time. With the host password ("I'm the host" in the
   game dialog) you can also log in as the host without a race and **View as** any race,
   read-only. Everyone sees a notice in the chat when the host changes the game, and every host
   action (and every View as) goes into a host audit log that the export includes. In a game of
   computer empires only, the host runs each turn with **Run turn** or **Run 5 turns**.
8. The **?** button (or the `?` key) opens the rules, with a contents list and search. Order forms
   show the matching rulebook section under **More from the rulebook**.

**Good to know:**
- **Passwords.** Each race has its own password, and the host has a host password. On Render the
  game is served over HTTPS, so passwords travel encrypted. The server stores only a salted scrypt
  hash of each password (and a hash of each browser's login key), never the password itself, and
  no page, API answer, export or log contains them. There is no limit on wrong password tries
  (it's a game for a few friends). `render.yaml` sets `MHGC_TRUST_PROXY=1` so the server reads
  the visitor address Render's proxy reports (the last `X-Forwarded-For` entry); nothing uses the
  address at the moment. Leave it unset anywhere else.
- Anyone with the address can still see the game list, take an open seat, read the game-wide
  chat or drop a game nobody is seated in. Only share the address with people you trust.
- **Forgotten password:** the host resets it from **Host controls** and tells the player the
  temporary password; the player chooses a new one at the next login.
- **Games from before passwords** carry on: a browser that held a seat keeps it, and on its next
  visit it is asked to choose a password before it can play. If that browser is lost, the host
  resets the race's password. An old game without a host password asks its host to set one on
  the next visit, before the host's powers work again.
- There are no deadlines. A game waits for its players as long as it takes (or for the host).
- Games are saved after every change and survive restarts and redeploys. Old turns are kept, so
  players can look back through earlier turns.
- The game is designed for a laptop or desktop screen (1366x768 or larger).

## 6. Updating the game later
Unzip the new version over your folder, then push it:
```
cd C:\Temp\mhgc-web
git add .
git commit -m "Rule changes"
git push
```
Render rebuilds and redeploys by itself in a few minutes. Games in progress carry on. If a change
makes an old save unreadable, that game is skipped rather than crashing the server, and it won't
appear in the game list.

## Stopping it
On the service's page in Render, **Suspend** stops the server, and **Resume** starts it again;
**Delete** removes it for good. Check Render's billing page for what a suspended service and its disk
still cost.

## If something goes wrong
- **The build fails:** open the service's **Logs** in Render. It should install `fastapi` and
  `uvicorn` from `requirements.txt` and then start with
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- **"Not healthy":** Render checks `/api/health`. Open `https://<your-address>/api/health`.
- **Games vanish after a redeploy:** the disk isn't attached. On the service's **Disks** page there
  should be a disk mounted at `/var/data`, and under **Environment**, `SAVE_DIR` should be
  `/var/data/saves`.
