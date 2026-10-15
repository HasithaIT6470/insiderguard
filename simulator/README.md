# Activity Lab

A separate synthetic employee activity simulator connected to InsiderGuard's authenticated REST API. It runs on **http://localhost:5175**; the detector remains on **http://localhost:5173**.

Run the backend and frontend first, then start the simulator in a third PowerShell terminal:

```powershell
cd simulator
npm.cmd start
```

Keep the terminal open and visit **http://localhost:5175**. The simulator needs Node.js and uses built-in modules; no `npm install` is needed in this directory. It proxies API requests to **http://127.0.0.1:8000**. See the main [README](../README.md#quick-start) for backend and frontend setup.

## Supervisor demonstration

1. Open the simulator and InsiderGuard in separate windows, side by side.
2. In the simulator connect as `admin` / `Guard#12345` (current development default; use the credentials for your database). This is the authorized platform operator; simulated employees do not have real credentials.
3. Click **Prepare new employee**. The simulator creates a unique employee in **Simulator Lab** and submits normal learning history through `/api/events`. Show the established baseline and initial Low/0 risk.
4. Click **Normal work**. The transmitted login/read/download should remain normal for the fresh employee.
5. Click **Unusual download**. With default settings, the 120 MB event is below the fixed bulk-download threshold but triggers a personal download anomaly. Open the response details to show the stored-event count and read the baseline evidence in InsiderGuard.
6. Click **Register demo decoy**, then **Correlated threat**. The detector combines night login, unfamiliar device, restricted access, a 900 MB download and decoy access; default settings produce a Critical/100 score and an alert.
7. Show the automatically updated InsiderGuard dashboard/Alerts page. Both refresh every five seconds while visible and when returning to the tab. Use **Open employee evidence** or **Open highest-risk alert** from the simulator to inspect the detector's actual evidence.
8. Try **Invalid event**. It must be rejected, remain absent from stored event counts and appear in InsiderGuard's administrator parsing-error notification/history.
9. Click **Prepare new employee** to demonstrate another clean run. Previous employees, events and cases remain stored. **Clear display** clears only the simulator's transmission display.

Additional buttons exercise failed login bursts, repeated denial, off-hours login, large downloads, unknown devices, restricted resources and honeytoken access individually. A single indicator can remain below the alert threshold. Current risk represents the recent peak, so normal activity does not erase historical findings.

## Connection behavior

- The browser sends requests through this simulator's Node server to the fixed loopback InsiderGuard API. Backend authentication, ingestion validation, role checks, deterministic scoring and auditing remain authoritative.
- Connection requires an administrator role because event ingestion and decoy creation are administrator-only. Analysts can inspect the resulting cases in InsiderGuard.
- The simulator stores the JWT and its current demo state in tab session storage; the operator password is not stored. Disconnect clears the JWT. Reload restores a valid session.
- Every transmission displays its actual payload and API response. Scores, event counts, registry state and alerts are queried from InsiderGuard, not invented locally.
- The simulation date is based on the newest dataset event. Learning events precede that date; scenarios intentionally use fixed normal/night timestamps on that date. These are replayed synthetic events, not observations of the real machine.
- The demo supports configured learning windows of 1–60 days and at most 5,000 required learning events. Detection thresholds are taken from the API; changed rules can change demonstration scores.

## Verification

`npm test` checks scenario structures and learning history. 

The server supports `SIMULATOR_PORT` and `INSIDERGUARD_API_PORT` for local test instances. Both servers bind to loopback. No endpoint agent, file scanner, real employee monitoring or real credential collection is installed.
