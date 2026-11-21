# Running Mega Hyper Galactic Conquest on your laptop

## What you need
**Python 3.10 or newer.**
- **Windows:** get it from python.org/downloads, and tick **"Add python.exe to PATH"** in the installer.
- **Mac:** use python.org, or `brew install python`.

On Windows nothing is downloaded: the packages the game needs are bundled in the `wheels` folder, so it works behind a company network too. On a Mac the first start downloads them.

## Start it
1. Unzip `mhgc-web.zip` somewhere outside OneDrive, for example `C:\Games\mhgc-web`.
2. Run the start script:
   - **Windows:** double-click **`start-windows.bat`**.
   - **Mac or Linux:** open Terminal in the folder and run `bash start-mac-linux.sh`.
3. The first time, it spends a minute setting up. Then your browser opens
   **http://127.0.0.1:8790/**. If it doesn't, open that address yourself.
4. To stop, close the black window, or press Ctrl+C in it.

Your games are saved in the `saves` folder, so they survive a restart. Delete that folder to start fresh.

## Starting it from VS Code
1. **Open the folder:** choose File → Open Folder… and pick the unzipped `mhgc-web` folder.
2. **Install the extension:** if VS Code offers the **Python** extension, install it.
3. **Run the start script once** so it creates the `.venv` environment: double-click `start-windows.bat`, or run `bash start-mac-linux.sh` on a Mac. Then close that window.
4. **Pick the interpreter:** press Ctrl+Shift+P (Cmd+Shift+P on a Mac), run **Python: Select Interpreter**, and choose the one in `.venv`.
5. **Start the game:** press **F5**, or open Run and Debug and choose **MHGC server**. The server starts and your browser opens the game.

The server restarts by itself when you edit the code. Press Shift+F5 to stop it.

You can also just type the start command in VS Code's terminal (Terminal → New Terminal):
- **Windows:** `.\start-windows.bat`
- **Mac:** `bash start-mac-linux.sh`

## Playing
- **New game:** name it, choose how many human seats you want, pick your race name and a password for it (at least 4 characters), and a host password (tick "Use my race password" to use the same one; you can use one host password for all your games), and Create. Every other empire is played by the computer. You can also host without a race ("Host only").
- **Taking a seat:** click the game in the list, then under **Take an open seat** pick a seat, your name and a password. Anyone can then play that race from any browser: open the game and log in under **Play an existing race** with the password. One person can hold several races and switch between them in the top bar.
- **Running a turn:** enter orders and **Submit turn**. The turn runs when every human seat has submitted. As the host you can **Force turn**; the ☰ menu has the other host controls (reset a forgotten password, hand a race to the computer, export).
- **Help:** the **?** button opens the rulebook.

## Playing with others on your home network
The game only listens on your own computer. To let someone on the same Wi-Fi join, change `127.0.0.1` to `0.0.0.0` on the last line of the start script. They then open `http://<your laptop's IP address>:8790/`. Windows may ask to allow it through the firewall. Playing with others now uses passwords; note that on your home network the game is plain `http`, so passwords cross your Wi-Fi unencrypted. Use passwords you don't use anywhere else (it's a hobby game: four letters will do). On Render (`DEPLOY.md`) everything is HTTPS.

To put it on the internet instead, see `DEPLOY.md` (Render).
