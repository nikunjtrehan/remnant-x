# Remnant X workbench

Desktop-first React + TypeScript application. FastAPI owns perception, order
interpretation, placement and final verification; the browser renders results.

## Local development

From the project root, start the API using `scripts/start.ps1 -Demo` in one terminal.
Demo stock is still seeded explicitly in the UI, never at startup.

In a second PowerShell terminal:

```powershell
Set-Location 'D:\remnant-X\Front End'
npm ci
npm run dev
```

Open the printed address, normally `http://127.0.0.1:5173`. Vite proxies `/api`
to `http://127.0.0.1:8000`. No provider credentials belong in this folder or the
browser. The backend reads its existing environment configuration.

```powershell
npm run check
```

This runs interaction/unit checks and a production TypeScript/Vite build.
`npm run preview` previews that build. Development proxying is not included in
the production build: deployment needs a same-origin `/api` reverse proxy to
FastAPI. Hosting and GitHub publication are separate future steps.

See [MILESTONES.md](MILESTONES.md) for scope and validation checkpoints.
