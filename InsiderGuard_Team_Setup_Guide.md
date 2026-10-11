# InsiderGuard --- Local Setup Guide for Team Members

This guide explains how to clone the InsiderGuard repository from
GitHub, configure the development tools, and run the frontend and
backend locally on Windows.

InsiderGuard is an AI-assisted insider-threat detection and
data-exfiltration prevention prototype. It uses synthetic data for
development and testing.

## 1. Applications to install

Install these applications before starting:

1.  **GitHub Desktop** --- to clone the repository and share code
    changes: <https://desktop.github.com/>
2.  **Visual Studio Code** --- to edit the project:
    <https://code.visualstudio.com/>
3.  **Python 3.11** --- for the FastAPI backend:
    <https://www.python.org/downloads/>
    -   During installation, enable **Add Python to PATH** if that
        option is shown.
4.  **Node.js 18 or newer** --- for the React/Vite frontend:
    <https://nodejs.org/en/download/>
    -   The Node.js installer includes npm.
5.  **Git** --- GitHub Desktop may install or manage Git for you; if
    needed, install it from <https://git-scm.com/downloads/>.

Recommended VS Code extensions: - Python (Microsoft) - Pylance
(Microsoft) - ESLint (recommended for frontend work)

You do not need to install XAMPP or a separate web server based on the
standard startup instructions in this project's README. If the current
backend configuration requires a separate database service or
environment variables, follow the project maintainer's instructions for
that configuration.

## 2. Check the installations

Open PowerShell or a VS Code terminal and run:

``` powershell
py --version
node --version
npm --version
git --version
```

Use Python 3.11 for the commands below. If `py -3.11` is not available,
install Python 3.11 or ask the project maintainer which Python version
is supported by the current dependencies.

## 3. Clone the repository

1.  Open GitHub Desktop and sign in with your GitHub account.

2.  Accept the invitation to the private InsiderGuard repository if the
    project owner invited you.

3.  In GitHub Desktop, select **File → Clone Repository**.

4.  Select the InsiderGuard repository under GitHub.com.

5.  Choose a local location, for example:

    `C:\Users\<your-Windows-username>\source\InsiderGuard`

6.  Click **Clone**.

7.  In GitHub Desktop, select **Open in Visual Studio Code**, or open
    the cloned folder manually in VS Code.

The project root should contain folders similar to:

``` text
InsiderGuard/
├── README.md
├── backend/
└── frontend/
```

Use the cloned repository. Do not create a second repository inside it.

## 4. Set up the backend (first-time setup)

In VS Code, select **Terminal → New Terminal**. The following commands
assume the terminal starts in the project root.

### 4.1 Open the backend folder

``` powershell
cd backend
```

### 4.2 Create a Python virtual environment

Run this once for this local clone:

``` powershell
py -3.11 -m venv .venv
```

If `backend\.venv` already exists, do not create it again.

### 4.3 Activate the virtual environment

Run this each time you open a new backend terminal:

``` powershell
.\.venv\Scripts\Activate.ps1
```

The terminal prompt should start with `(.venv)`.

If PowerShell blocks activation, you can use Command Prompt instead:

``` cmd
.venv\Scripts\activate.bat
```

Alternatively, select the Python interpreter at
`backend\.venv\Scripts\python.exe` in VS Code. Do not change your
computer's global execution policy just for this project.

### 4.4 Install backend dependencies

Run this once for the environment, and repeat it if the project's
backend dependencies change:

``` powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Wait until installation completes. If this step fails, do not continue
to the seed or server commands; save the full error message and ask the
team for help.

### 4.5 Generate the synthetic development data

The project README specifies:

``` powershell
python -m app.seed --reset
```

This command generates labelled synthetic data, scores it, and runs the
evaluation. The `--reset` option may reset or replace local seed data,
so run it only when setting up or intentionally regenerating your local
development data. Do not run it against data you need to preserve.

If the project maintainer has supplied additional `.env` or database
setup instructions, follow those before seeding.

## 5. Start the backend

In the backend terminal, with `(.venv)` active and the current directory
set to `backend`, run:

``` powershell
python -m uvicorn app.main:app --reload
```

Keep this terminal open while using the website.

Expected local addresses:

-   API server: <http://localhost:8000>
-   Interactive API documentation: <http://localhost:8000/docs>

You can open `/docs` in a browser to confirm that the FastAPI
application is responding. A working API does not by itself guarantee
that the frontend is configured correctly.

## 6. Set up the frontend (first-time setup)

Keep the backend running. In VS Code, open a **second terminal** using
**Terminal → New Terminal**.

If the new terminal starts in the project root, run:

``` powershell
cd frontend
npm install
```

This installs the frontend dependencies. You normally do not need to run
`npm install` every time; run it during initial setup and again when the
frontend dependencies or lockfile change.

When installation completes, start the frontend:

``` powershell
npm run dev
```

Keep this terminal open too. Vite should show a local URL, usually:

<http://localhost:5173/>

Open that URL in your browser. The README says Vite proxies `/api`
requests to the backend at `http://localhost:8000`, so both servers must
be running for the complete application to work.

## 7. Development login accounts

The README documents these development accounts, created by the seed
process when the app is not running in production mode:

  Role      Username    Development password
  --------- ----------- ----------------------
  Admin     `admin`     `Admin#12345`
  Analyst   `analyst`   `Analyst#12345`

If login fails, confirm that the seed process completed and check the
backend terminal for errors. These are disposable local development
credentials only. Do not reuse them outside local development or expose
the development server publicly. Follow the maintainer's instructions if
`INSIDERGUARD_ADMIN_PASSWORD`, `INSIDERGUARD_ANALYST_PASSWORD`, or other
environment variables are configured.

## 8. Daily startup after the initial setup

You do not need to reinstall everything each time.

### Terminal 1 --- Backend

Open a terminal in VS Code:

``` powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload
```

### Terminal 2 --- Frontend

Open a second terminal:

``` powershell
cd frontend
npm run dev
```

Then open <http://localhost:5173/>.

Keep both terminals running while using the website. To stop a server,
focus its terminal and press `Ctrl+C`.

## 9. When to install dependencies again

  ---------------------------------------------------------------------------------
  Command                                       When to run it
  --------------------------------------------- -----------------------------------
  `py -3.11 -m venv .venv`                      Once per local clone/environment

  Activate `.venv`                              Every time you open a new backend
                                                terminal

  `python -m pip install -r requirements.txt`   Initial setup and when backend
                                                dependencies change

  `python -m app.seed --reset`                  Initial data setup or when
                                                intentionally
                                                resetting/regenerating synthetic
                                                data

  `npm install`                                 Initial setup and when frontend
                                                dependencies/lockfile change

  `python -m uvicorn app.main:app --reload`     Every time you want to run the
                                                backend

  `npm run dev`                                 Every time you want to run the
                                                frontend
  ---------------------------------------------------------------------------------

## 10. Common issues

### `ModuleNotFoundError: No module named 'sqlalchemy'` or `No module named 'uvicorn'`

Make sure you are in the `backend` folder and the virtual environment is
activated. Then run:

``` powershell
python -m pip install -r requirements.txt
```

### `uvicorn` is not found

With the virtual environment activated, run:

``` powershell
python -m uvicorn app.main:app --reload
```

### `npm` is not recognized

Confirm Node.js is installed, then close and reopen VS Code and check:

``` powershell
node --version
npm --version
```

### Port 8000 or 5173 is already in use

Another process may already be using the port. Stop the other
development server with `Ctrl+C` in its terminal, or ask the team before
changing project port settings.

### Frontend loads but API requests fail

1.  Confirm the backend is running and <http://localhost:8000/docs>
    opens.
2.  Confirm the frontend is running at <http://localhost:5173/>.
3.  Check the browser's Developer Tools (**F12 → Console** and
    **Network**) for the failing request.
4.  Check the backend terminal for errors.
5.  Confirm the Vite proxy configuration and backend environment
    settings have not been changed.

### Seed or login fails

Read the full backend error. Check whether the local environment needs a
`.env` file, database configuration, or other settings. Never commit
real `.env` files, passwords, API keys, or personal data to GitHub.

### `npm install` reports vulnerabilities or an install-script warning

Do not automatically run `npm audit fix --force`; it can install
breaking dependency versions. Share the output with the project team and
review the dependencies before making changes.

## 11. Working with GitHub as a team

To avoid overwriting each other's work, use a feature branch for each
task.

1.  In GitHub Desktop, select `main` and use **Fetch origin**. Pull any
    available changes before starting work.
2.  Create a branch for your task, for example
    `feature/alert-dashboard`.
3.  Edit and test the code in VS Code.
4.  Review the changes in GitHub Desktop and commit them with a clear
    message.
5.  Push the branch to GitHub.
6.  Open a Pull Request and have the team review it before merging into
    `main`.

If `requirements.txt`, `package.json`, or `package-lock.json` changes
after pulling updates, install the updated dependencies as described
above.

Never commit `.venv`, `node_modules`, `.env` files containing secrets,
or private datasets. Keep the root README and dependency files committed
so teammates can reproduce the setup.

## 12. Optional: Run tests

Backend tests:

``` powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest -q
```

Frontend tests:

``` powershell
cd frontend
npm test
```

The frontend test command depends on the scripts defined in
`frontend/package.json`.

## Quick reference

  --------------------------------------------------------------------------------------------------
  Component               Command                                     Local address
  ----------------------- ------------------------------------------- ------------------------------
  Backend API             `python -m uvicorn app.main:app --reload`   <http://localhost:8000>

  API docs                Open in browser                             <http://localhost:8000/docs>

  Frontend                `npm run dev`                               <http://localhost:5173/>
  --------------------------------------------------------------------------------------------------

**Remember:** run the backend and frontend in separate terminals. Both
must remain running while you use the complete InsiderGuard website.
